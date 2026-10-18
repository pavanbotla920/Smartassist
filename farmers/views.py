from django.shortcuts import render, redirect, get_object_or_404
from django.db.models import Count, Q
from django.db.models.functions import TruncMonth
from django.contrib.auth.decorators import login_required
from django.contrib.auth import logout as auth_logout
from django.core.cache import cache
from django.http import HttpResponse, JsonResponse, Http404, StreamingHttpResponse
from django.views.decorators.http import require_GET, require_POST
from django.contrib import messages
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth.models import User
from django.utils.translation import gettext as _, check_for_language
from django.urls import reverse, translate_url
from django.conf import settings as conf_settings
from django.utils.http import url_has_allowed_host_and_scheme
from django.utils import timezone
from datetime import timedelta
from dateutil.relativedelta import relativedelta
from urllib.parse import urlencode, urlparse
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from .models import ApplicationRequest, Scheme, Notification, UserProfile
from .forms import UserRegisterForm, UserUpdateForm, UserProfileForm, CitizenApplicationForm, SchemeForm
from .emails import notify, notify_application_status
import csv
import asyncio
import json
import re
import os
import tempfile
import subprocess
import hashlib
import html
import logging
from aiohttp import ClientError, ClientResponseError
from edge_tts import Communicate
from edge_tts.exceptions import EdgeTTSException

# IMPORT THE LOCATION DATA HELPER
from .location_data import get_location_json

logger = logging.getLogger(__name__)


# -----------------------------
# AUTHENTICATION VIEWS
# -----------------------------
def register(request):
    if request.method == 'POST':
        form = UserRegisterForm(request.POST)
        if form.is_valid():
            form.save()
            username = form.cleaned_data.get('username')
            messages.success(
                request,
                _('Account created for %(username)s! You can now log in.') % {
                    'username': username,
                },
            )
            return redirect('login')
    else:
        form = UserRegisterForm()
    return render(request, 'register.html', {'form': form})


def logout_user(request):
    """Log out current user and redirect to home."""
    auth_logout(request)
    messages.success(request, _('You have been logged out successfully.'))
    return redirect('home')


@login_required
def profile(request):
    user_profile, created = UserProfile.objects.get_or_create(user=request.user)

    if request.method == 'POST':
        user_form = UserUpdateForm(request.POST, instance=request.user)
        # Include request.FILES to handle the Profile Photo upload
        profile_form = UserProfileForm(request.POST, request.FILES, instance=user_profile)
        
        if user_form.is_valid() and profile_form.is_valid():
            user_form.save()
            profile_form.save()
            messages.success(request, _('Your profile has been updated!'))
            return redirect('profile')
    else:
        user_form = UserUpdateForm(instance=request.user)
        profile_form = UserProfileForm(instance=user_profile)

    # Fetch the JSON map of States -> Districts for the dynamic dropdown
    location_json = get_location_json()

    context = {
        'user_form': user_form,
        'profile_form': profile_form,
        'location_json': location_json,
    }
    return render(request, 'profile.html', context)


# -----------------------------
# CITIZEN VIEWS
# -----------------------------
def home(request):
    """Home page with project overview"""
    return render(request, 'home.html')


def scheme_awareness(request):
    """Public scheme listing with filters, stats, and search."""
    all_schemes = Scheme.objects.all()
    schemes = all_schemes

    search_query = (request.GET.get('q') or '').strip()
    state_filter = (request.GET.get('state') or '').strip()
    category_filter = (request.GET.get('category') or '').strip()
    type_filter = (request.GET.get('type') or '').strip()
    if type_filter:
        type_filter = {'central': 'Central', 'state': 'State'}.get(type_filter.lower(), type_filter)

    if search_query:
        schemes = schemes.filter(
            Q(scheme_name__icontains=search_query)
            | Q(description__icontains=search_query)
            | Q(category__icontains=search_query)
            | Q(department__icontains=search_query)
        )

    if state_filter:
        schemes = schemes.filter(state__iexact=state_filter)

    if category_filter:
        schemes = schemes.filter(category__iexact=category_filter)

    if type_filter in ['Central', 'State']:
        schemes = schemes.filter(scheme_type=type_filter)

    states = list(
        all_schemes.exclude(state__isnull=True)
        .exclude(state__exact='')
        .values_list('state', flat=True)
        .distinct()
        .order_by('state')
    )

    categories = list(
        all_schemes.exclude(category__isnull=True)
        .exclude(category__exact='')
        .values_list('category', flat=True)
        .distinct()
        .order_by('category')
    )

    context = {
        'schemes': schemes.order_by('scheme_name'),
        'total_schemes': all_schemes.count(),
        'central_schemes': all_schemes.filter(scheme_type='Central').count(),
        'state_schemes': all_schemes.filter(scheme_type='State').count(),
        'states': states,
        'categories': categories,
        'search_query': search_query,
        'state_filter': state_filter,
        'category_filter': category_filter,
        'type_filter': type_filter,
    }
    return render(request, 'scheme_awareness.html', context)


def scheme_detail(request, scheme_id):
    """Public scheme detail page. Apply action remains login-protected."""
    scheme = get_object_or_404(Scheme, id=scheme_id)
    return render(request, 'scheme_detail.html', {'scheme': scheme})


class VoiceServiceError(Exception):
    """Raised when an external translation or speech provider cannot respond."""


VOICE_LANGUAGES = {
    'english': ('en', 'English', 'en-IN-NeerjaNeural'),
    'en': ('en', 'English', 'en-IN-NeerjaNeural'),
    'hindi': ('hi', 'Hindi', 'hi-IN-SwaraNeural'),
    'hi': ('hi', 'Hindi', 'hi-IN-SwaraNeural'),
    'marathi': ('mr', 'Marathi', 'mr-IN-AarohiNeural'),
    'mr': ('mr', 'Marathi', 'mr-IN-AarohiNeural'),
    'telugu': ('te', 'Telugu', 'te-IN-ShrutiNeural'),
    'te': ('te', 'Telugu', 'te-IN-ShrutiNeural'),
}


def _scheme_voice_text(scheme):
    fields = (
        ('Scheme name', f'Government scheme called {scheme.scheme_name}'),
        ('About this scheme', scheme.description),
        ('Eligibility', scheme.eligibility),
        ('Required documents', scheme.documents_required),
    )
    return '\n'.join(
        f'{label}: {value.strip()}'
        for label, value in fields
        if value and value.strip()
    )


def _split_voice_text(text, limit):
    remaining = text.strip()
    chunks = []
    while remaining:
        if len(remaining) <= limit:
            chunks.append(remaining)
            break
        split_at = remaining.rfind(' ', 0, limit + 1)
        if split_at <= 0:
            split_at = limit
        chunks.append(remaining[:split_at].strip())
        remaining = remaining[split_at:].strip()
    return chunks


def _provider_response(url, service_name):
    request = Request(
        url,
        headers={'User-Agent': 'SmartAssist multilingual scheme assistance/1.0'},
    )
    try:
        with urlopen(request, timeout=12) as response:
            return response.read()
    except HTTPError as exc:
        logger.warning('%s returned HTTP %s', service_name, exc.code)
        raise VoiceServiceError(
            f'{service_name} is temporarily unavailable (HTTP {exc.code}). Please try again later.'
        ) from exc
    except (URLError, TimeoutError) as exc:
        logger.warning('%s could not be reached: %s', service_name, exc)
        raise VoiceServiceError(
            f'{service_name} could not be reached. Check your internet connection and try again.'
        ) from exc


def _translate_scheme_voice_text(text, language_code):
    return _translate_text(text, language_code)


def _translate_text(text, language_code):
    if len(text) > 4500:
        raise VoiceServiceError(
            'This scheme has too much text for the free translation quota. Please check its details on the official website.'
        )

    translated_chunks = []
    for chunk in _split_voice_text(text, 450):
        query = urlencode({
            'q': chunk,
            'langpair': f'en|{language_code}',
        })
        payload = _provider_response(
            f'https://api.mymemory.translated.net/get?{query}',
            'Free translation service',
        )
        try:
            result = json.loads(payload)
        except (TypeError, ValueError) as exc:
            raise VoiceServiceError(
                'The translation service returned an unreadable response. Please try again later.'
            ) from exc

        if result.get('responseStatus') != 200 or result.get('quotaFinished'):
            logger.warning(
                'Translation service rejected the request: status=%s details=%s',
                result.get('responseStatus'),
                result.get('responseDetails', ''),
            )
            raise VoiceServiceError(
                'The free translation service is unavailable or its daily quota has been reached. Please try again later.'
            )

        translated = result.get('responseData', {}).get('translatedText', '').strip()
        if not translated:
            raise VoiceServiceError(
                'The translation service did not return translated scheme information.'
            )
        translated_chunks.append(html.unescape(translated))
    return ' '.join(translated_chunks)


@require_GET
def scheme_translation_api(request):
    """Translate only public scheme fields; never accept user/application data."""
    try:
        scheme_id = int(request.GET.get('scheme_id', ''))
    except (TypeError, ValueError):
        return JsonResponse({'error': 'A valid scheme_id is required.'}, status=400)

    language = (request.GET.get('lang') or '').strip().lower()
    if language not in {'en', 'hi', 'mr', 'te'}:
        return JsonResponse(
            {'error': 'Choose English, Hindi, Marathi, or Telugu.'},
            status=400,
        )

    scheme = get_object_or_404(Scheme, id=scheme_id)
    all_fields = {
        'scheme_name': scheme.scheme_name or '',
        'description': scheme.description or '',
        'eligibility': scheme.eligibility or '',
        'documents_required': scheme.documents_required or '',
    }
    requested_fields = request.GET.get('fields')
    if requested_fields:
        field_names = tuple(dict.fromkeys(requested_fields.split(',')))
        if not field_names or any(field not in all_fields for field in field_names):
            return JsonResponse({'error': 'One or more scheme fields are invalid.'}, status=400)
        fields = {field: all_fields[field] for field in field_names}
    else:
        fields = all_fields

    if language == 'en':
        return JsonResponse({'language': language, 'fields': fields})

    cache_fingerprint = hashlib.sha256(
        json.dumps(fields, ensure_ascii=False, sort_keys=True).encode('utf-8')
    ).hexdigest()
    cache_key = f'scheme_translation:{scheme.pk}:{language}:{cache_fingerprint}'
    cached_translation = cache.get(cache_key)
    if cached_translation is not None:
        return JsonResponse(cached_translation)

    try:
        translated_fields = {
            field: _translate_text(value, language) if value.strip() else ''
            for field, value in fields.items()
        }
    except VoiceServiceError as exc:
        logger.warning(
            'Scheme translation failed for scheme_id=%s language=%s: %s',
            scheme.pk,
            language,
            exc,
        )
        return JsonResponse(
            {
                'error': str(exc),
                'language': language,
                'original_language': 'en',
            },
            status=503,
        )

    response_data = {
        'language': language,
        'original_language': 'en',
        'fields': translated_fields,
    }
    cache.set(cache_key, response_data, timeout=24 * 60 * 60)
    return JsonResponse(response_data)


async def _stream_edge_speech(text, voice_name):
    audio = bytearray()
    async for item in Communicate(text, voice_name).stream():
        if item['type'] == 'audio':
            audio.extend(item['data'])
    return bytes(audio)


def _synthesize_scheme_voice(text, voice_name):
    try:
        audio = asyncio.run(asyncio.wait_for(
            _stream_edge_speech(text, voice_name),
            timeout=30,
        ))
    except asyncio.TimeoutError as exc:
        raise VoiceServiceError(
            'The free speech service took too long to respond. Please try again.'
        ) from exc
    except ClientResponseError as exc:
        logger.warning('Free speech service returned HTTP %s', exc.status)
        if exc.status == 429:
            message = 'The free speech service is rate-limited right now. Please wait and try again.'
        else:
            message = 'The free speech service is temporarily unavailable. Please try again later.'
        raise VoiceServiceError(message) from exc
    except (ClientError, EdgeTTSException, OSError) as exc:
        logger.warning('Free speech service request failed: %s', exc)
        raise VoiceServiceError(
            'The free speech service could not be reached. Check your internet connection and try again.'
        ) from exc
    except Exception as exc:
        logger.exception('Unexpected failure while generating speech')
        raise VoiceServiceError(
            'Speech could not be generated right now. Please try again later.'
        ) from exc

    if not audio:
        raise VoiceServiceError('The speech service returned empty audio.')
    return audio


@require_GET
def scheme_voice_audio(request, scheme_id):
    """Translate only this stored scheme's information and return its speech audio."""
    requested_language = (request.GET.get('lang') or '').strip().lower()
    language = VOICE_LANGUAGES.get(requested_language)
    if language is None:
        return JsonResponse(
            {'error': 'Choose English, Hindi, Marathi, or Telugu.'},
            status=400,
        )

    scheme = get_object_or_404(Scheme, id=scheme_id)
    source_text = _scheme_voice_text(scheme)
    if not source_text:
        return JsonResponse(
            {'error': 'This scheme does not have any information available to read aloud.'},
            status=422,
        )

    remote_address = request.META.get('REMOTE_ADDR', 'unknown')
    rate_key = f'scheme-voice-rate:{hashlib.sha256(remote_address.encode()).hexdigest()}'
    if cache.add(rate_key, 1, timeout=60):
        request_count = 1
    else:
        try:
            request_count = cache.incr(rate_key)
        except ValueError:
            request_count = 1
            cache.set(rate_key, request_count, timeout=60)
    if request_count > 20:
        return JsonResponse(
            {'error': 'Voice requests are temporarily limited. Please wait a minute and try again.'},
            status=429,
        )

    language_code, language_name, voice_name = language
    audio_cache_key = 'scheme-voice-audio:' + hashlib.sha256(
        f'{scheme.pk}:{language_code}:{source_text}'.encode()
    ).hexdigest()
    cached_audio = cache.get(audio_cache_key)
    if cached_audio is not None:
        return HttpResponse(cached_audio, content_type='audio/mpeg')

    spoken_text = source_text
    if language_code != 'en':
        try:
            spoken_text = _translate_scheme_voice_text(source_text, language_code)
        except VoiceServiceError as exc:
            return JsonResponse({'error': str(exc)}, status=503)

    try:
        audio = _synthesize_scheme_voice(spoken_text, voice_name)
    except VoiceServiceError as exc:
        return JsonResponse({
            'error': str(exc),
            'translated_text': spoken_text,
            'language': language_code,
            'language_name': language_name,
        }, status=503)

    cache.set(audio_cache_key, audio, timeout=60 * 60 * 12)
    response = HttpResponse(audio, content_type='audio/mpeg')
    response['Cache-Control'] = 'private, max-age=3600'
    return response

@login_required
def settings_view(request):
    """User settings page"""
    return render(request, 'settings.html')

@login_required
def apply_for_assistance(request):
    """Citizen application form"""
    user_profile, created = UserProfile.objects.get_or_create(user=request.user)
    scheme_id = request.POST.get('scheme_id') or request.GET.get('scheme_id')
    scheme = get_object_or_404(Scheme, id=scheme_id) if scheme_id else None

    if request.method == 'POST':
        form = CitizenApplicationForm(request.POST)
        if form.is_valid():
            application = form.save(commit=False)
            application.user = request.user
            application.scheme = scheme
            application.status = 'Pending'
            application.save()

            scheme_name = scheme.scheme_name if scheme else _('government scheme assistance')
            notify(
                request.user,
                _('Application Submitted'),
                _('Your application for %(scheme)s has been submitted successfully.') % {
                    'scheme': scheme_name,
                },
                email_to=application.email,
            )

            if scheme:
                messages.success(
                    request,
                    _('Your request for %(scheme)s has been submitted. Our volunteers will help you with the application.') % {
                        'scheme': scheme.scheme_name,
                    },
                )
            else:
                messages.success(request, _('Application submitted for assistance. Our volunteers will help you apply for suitable schemes.'))
            return redirect('application_status')
    else:
        # Pre-fill form with EVERYTHING from profile data
        initial_data = {
            'name': user_profile.full_name or request.user.get_full_name() or request.user.username,
            'email': request.user.email,
            'mobile': user_profile.phone,
            'age': user_profile.age,
            'gender': user_profile.gender,
            'education': user_profile.education,
            'category': user_profile.category,
            'state': user_profile.state,
            'district': user_profile.district,
            'income': None, # Profile saves income as a range (e.g., '1l_3l'), not a raw integer, so we leave this blank unless you add a specific income field to the profile.
        }
        
        # If the user hasn't saved a state in their profile, but the scheme is state-specific, use the scheme's state
        if scheme and not initial_data['state']:
            initial_data['state'] = scheme.state
            
        form = CitizenApplicationForm(initial=initial_data)

        # Fetch the JSON map of States -> Districts for the dynamic dropdown
    location_json = get_location_json()

    return render(request, 'apply.html', {
        'form': form, 
        'scheme': scheme,
        'location_json': location_json
    })

@login_required
def application_status(request):
    """Track application status"""
    applications = ApplicationRequest.objects.filter(user=request.user)
    return render(request, 'application_status.html', {'applications': applications})


# -----------------------------
# ADMIN/VOLUNTEER VIEWS
# -----------------------------
@login_required
def admin_dashboard(request):
    user_profile = get_object_or_404(UserProfile, user=request.user)
    if user_profile.role not in ['volunteer', 'admin']:
        return redirect('dashboard')

    # --- Application Stats (Keep Existing) ---
    applications = ApplicationRequest.objects.all().order_by('-created_at')
    total_applications = applications.count()
    pending = applications.filter(status='Submitted').count()
    under_review = applications.filter(status='Under Review').count()
    applied = applications.filter(status='Applied').count()
    approved = applications.filter(status='Approved').count()
    rejected = applications.filter(status='Rejected').count()

    # ==========================================
    # NEW ANALYTICS LOGIC
    # ==========================================
    now = timezone.now()
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    
    # 1. Farmer Registration Trends
    total_farmers = UserProfile.objects.filter(role='citizen').count()
    
    # Calculate for the dynamic tags (default to month)
    week_start = today_start - timedelta(days=today_start.weekday())
    month_start = today_start.replace(day=1)
    six_months_ago = month_start - relativedelta(months=6)
    year_start = month_start - relativedelta(years=1)

    farmers_week = UserProfile.objects.filter(role='citizen', user__date_joined__gte=week_start).count()
    farmers_month = UserProfile.objects.filter(role='citizen', user__date_joined__gte=month_start).count()
    farmers_six_months = UserProfile.objects.filter(role='citizen', user__date_joined__gte=six_months_ago).count()
    farmers_year = UserProfile.objects.filter(role='citizen', user__date_joined__gte=year_start).count()

    # Chart Data (Last 6 months for a neat graph)
    trend_months = []
    trend_counts = []
    for i in range(5, -1, -1): # 5 months ago to current month
        start_date = (month_start - relativedelta(months=i))
        end_date = start_date + relativedelta(months=1)
        count = UserProfile.objects.filter(role='citizen', user__date_joined__gte=start_date, user__date_joined__lt=end_date).count()
        trend_months.append(start_date.strftime('%b'))
        trend_counts.append(count)

    # 2. Scheme Trends
    active_schemes = Scheme.objects.all().count()
    central_schemes = Scheme.objects.filter(scheme_type='Central').count()
    state_schemes = Scheme.objects.filter(scheme_type='State').count()
    new_schemes_month = Scheme.objects.filter(created_at__gte=month_start).count() if hasattr(Scheme, 'created_at') else 0
    
    # Get some schemes to display in the Engagement/Expiring boxes
    # (Since we don't have real engagement tracking yet, we just grab the first few)
    recent_schemes = Scheme.objects.all().order_by('-id')[:3]
    expiring_schemes = Scheme.objects.all().order_by('id')[:3] # Placeholder if no closing_date

    # 3. Geographic Distribution
    # Top 5 Districts
    district_data = (
        UserProfile.objects.filter(role='citizen')
        .exclude(district__isnull=True).exclude(district='')
        .values('district', 'state')
        .annotate(count=Count('id'))
        .order_by('-count')[:5]
    )

    # State Bar Chart Data
    state_distribution = (
        UserProfile.objects.filter(role='citizen')
        .exclude(state__isnull=True).exclude(state='')
        .values('state')
        .annotate(count=Count('id'))
        .order_by('-count')[:8] # Top 8 states
    )
    state_labels = [item['state'] for item in state_distribution]
    state_data = [item['count'] for item in state_distribution]

    context = {
        'applications': applications[:10],
        'total_applications': total_applications,
        'pending': pending,
        'under_review': under_review,
        'applied': applied,
        'approved': approved,
        'rejected': rejected,
        
        # Farmer Trends
        'total_farmers': total_farmers,
        'farmers_week': farmers_week,
        'farmers_month': farmers_month,
        'farmers_six_months': farmers_six_months,
        'farmers_year': farmers_year,
        'trend_months': trend_months,
        'trend_counts': trend_counts,
        
        # Scheme Trends
        'active_schemes': active_schemes,
        'central_schemes': central_schemes,
        'state_schemes': state_schemes,
        'new_schemes_month': new_schemes_month,
        'recent_schemes': recent_schemes,
        'expiring_schemes': expiring_schemes,
        
        # Geo Distribution
        'district_data': district_data,
        'state_labels': state_labels,
        'state_data': state_data,
    }
    return render(request, 'admin_dashboard.html', context)

@login_required 
def manage_schemes(request):
    """Manage government schemes (List, Create, Delete)"""
    user_profile = UserProfile.objects.get(user=request.user)
    if user_profile.role not in ['volunteer', 'admin']:
        return redirect('dashboard')

    if request.method == 'POST':
        form = SchemeForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, _('Scheme added successfully!'))
            return redirect('manage_schemes')
    else:
        form = SchemeForm()

    # Fetch all schemes, newest first
    schemes = Scheme.objects.all().order_by('-id') 
    
    return render(request, 'manage_schemes.html', {'form': form, 'schemes': schemes})
@login_required
def add_scheme(request):
    """Create a new scheme"""
    user_profile = UserProfile.objects.get(user=request.user)
    if user_profile.role not in ['volunteer', 'admin']:
        return redirect('dashboard')

    if request.method == 'POST':
        form = SchemeForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, _('Scheme added successfully!'))
            return redirect('manage_schemes')
    else:
        form = SchemeForm()

    return render(request, 'scheme_form.html', {'form': form})

@login_required
def edit_scheme(request, scheme_id):
    """Edit an existing scheme"""
    scheme = get_object_or_404(Scheme, id=scheme_id)
    user_profile = UserProfile.objects.get(user=request.user)
    
    if user_profile.role not in ['volunteer', 'admin']:
        return redirect('dashboard')

    if request.method == 'POST':
        form = SchemeForm(request.POST, instance=scheme)
        if form.is_valid():
            form.save()
            messages.success(request, _('Scheme updated successfully!'))
            return redirect('manage_schemes')
    else:
        form = SchemeForm(instance=scheme)

    return render(request, 'scheme_form.html', {'form': form, 'scheme': scheme})
@login_required
def delete_scheme(request, scheme_id):
    """Delete a scheme"""
    scheme = get_object_or_404(Scheme, id=scheme_id)
    user_profile = UserProfile.objects.get(user=request.user)
    
    if user_profile.role in ['volunteer', 'admin']:
        scheme.delete()
        messages.success(request, _('Scheme deleted successfully!'))
    return redirect('manage_schemes')

@login_required
def update_application_status(request, app_id):
    user_profile = get_object_or_404(UserProfile, user=request.user)
    if user_profile.role not in ['volunteer', 'admin']:
        return redirect('dashboard')

    application = get_object_or_404(ApplicationRequest, id=app_id)
    
    if request.method == 'POST':
        new_status = request.POST.get('status')
        notes = request.POST.get('notes')
        application.status = new_status
        application.notes = notes
        application.applied_by = request.user
        application.save()

        notification = notify_application_status(application, new_status, notes)

        messages.success(request, 'Application status updated!')
        if not getattr(notification, 'email_sent', False):
            messages.warning(
                request,
                _('The status was saved, but the email could not be sent: %(error)s')
                % {'error': getattr(notification, 'email_error', '') or 'unknown error'},
            )
        return redirect('admin_dashboard')

    return render(request, 'update_status.html', {'application': application})

@login_required
def apply_scheme_admin(request, app_id, scheme_id):
    """Apply for scheme on behalf of citizen"""
    user_profile = get_object_or_404(UserProfile, user=request.user)
    if user_profile.role not in ['volunteer', 'admin']:
        return redirect('dashboard')

    application = get_object_or_404(ApplicationRequest, id=app_id)
    scheme = get_object_or_404(Scheme, id=scheme_id)

    # Update application
    application.scheme = scheme
    application.status = 'Applied'
    application.applied_by = request.user
    application.application_number = f"APP-{application.id}-{scheme.id}"
    application.save()

    # Send notification
    notify(
        application.user,
        _('Scheme Applied'),
        _('We have applied for %(scheme)s on your behalf.') % {'scheme': scheme.scheme_name},
        email_to=application.email,
    )

    messages.success(request, _('Scheme applied successfully!'))
    return redirect('admin_dashboard')




# -----------------------------
# LANGUAGE SWITCHER
# -----------------------------
def set_language(request):
    """Set user language preference and redirect to language-prefixed URL."""
    lang_code = request.GET.get('lang') or request.POST.get('lang') or 'en'
    valid_codes = {code for code, _ in conf_settings.LANGUAGES}
    if lang_code not in valid_codes:
        lang_code = 'en'

    # Prefer explicit next target, otherwise fall back to referrer.
    next_url = request.GET.get('next') or request.POST.get('next') or request.META.get('HTTP_REFERER', '/')

    # Prevent open redirects.
    if not url_has_allowed_host_and_scheme(
        url=next_url,
        allowed_hosts={request.get_host()},
        require_https=request.is_secure(),
    ):
        next_url = '/'

    parsed = urlparse(next_url)
    path_only = parsed.path or '/'
    query = f'?{parsed.query}' if parsed.query else ''
    fragment = f'#{parsed.fragment}' if parsed.fragment else ''

    # Strip any existing language prefix so we never double-prefix.
    all_lang_codes = [code for code, _ in conf_settings.LANGUAGES if code != 'en']
    for code in all_lang_codes:
        if path_only.startswith(f'/{code}/'):
            path_only = path_only[len(code) + 1:]  # strip /code, keep leading /
            break
        if path_only == f'/{code}':
            path_only = '/'
            break

    # Build language-prefixed path directly.
    # English uses no prefix (prefix_default_language=False in i18n_patterns).
    if lang_code == 'en':
        next_path = path_only + query + fragment
    else:
        next_path = f'/{lang_code}{path_only}' + query + fragment

    response = redirect(next_path)
    
    # Store language in session so LocaleMiddleware can find it immediately
    if hasattr(request, 'session'):
        request.session['_language'] = lang_code
        request.session.modified = True
    
    # Also set language cookie for persistence
    response.set_cookie(
        conf_settings.LANGUAGE_COOKIE_NAME,
        lang_code,
        max_age=getattr(conf_settings, 'LANGUAGE_COOKIE_AGE', 365 * 24 * 60 * 60),
        path=getattr(conf_settings, 'LANGUAGE_COOKIE_PATH', '/'),
        secure=getattr(conf_settings, 'LANGUAGE_COOKIE_SECURE', False),
        httponly=getattr(conf_settings, 'LANGUAGE_COOKIE_HTTPONLY', False),
        samesite=getattr(conf_settings, 'LANGUAGE_COOKIE_SAMESITE', 'Lax'),
    )
    return response


# -----------------------------
# DASHBOARD
# -----------------------------
@login_required
def dashboard(request):
    # ✅ Automatically redirect Admins/Volunteers to their proper dashboard
    if hasattr(request.user, 'userprofile') and request.user.userprofile.role in ['admin', 'volunteer']:
        return redirect('admin_dashboard')

    # Fetch the user's profile safely, just in case it doesn't exist yet
    user_profile, created = UserProfile.objects.get_or_create(user=request.user)

    # 📊 APPLICATION STATISTICS (USER SPECIFIC)
    total_applications = ApplicationRequest.objects.filter(user=request.user).count()
    approved_apps = ApplicationRequest.objects.filter(user=request.user, status='Approved').count()
    pending_apps = ApplicationRequest.objects.filter(user=request.user, status='Pending').count()
    rejected_apps = ApplicationRequest.objects.filter(user=request.user, status='Rejected').count()

    # 📊 SCHEME STATISTICS (GLOBAL, since schemes are public)
    total_schemes = Scheme.objects.count()

    # 📊 RECENT APPLICATIONS (USER SPECIFIC)
    recent_applications = ApplicationRequest.objects.filter(user=request.user).order_by('-created_at')[:5]

    # 📊 USER STATS (ALREADY USER SPECIFIC)
    user_applications = total_applications
    user_approved = approved_apps

    context = {
        'total_applications': total_applications,
        'approved_apps': approved_apps,
        'pending_apps': pending_apps,
        'rejected_apps': rejected_apps,
        'total_schemes': total_schemes,
        'user_applications': user_applications,
        'user_approved': user_approved,
        'recent_applications': recent_applications,
        'user_profile': user_profile, # Passed for the farm profile widget
    }

    return render(request, 'dashboard.html', context)


def _format_link(url):
    if not url or not isinstance(url, str):
        return None
    clean_url = url.strip()
    if not clean_url:
        return None
    clean_url = clean_url.rstrip(' .,;\n\r\t')
    if clean_url.startswith('//'):
        clean_url = 'https:' + clean_url
    elif urlparse(clean_url).scheme and not clean_url.lower().startswith(('http://', 'https://')):
        return None
    elif '://' in clean_url and not clean_url.lower().startswith(('http://', 'https://')):
        return None
    elif not clean_url.lower().startswith(('http://', 'https://')):
        clean_url = 'https://' + clean_url
    parsed_url = urlparse(clean_url)
    if parsed_url.scheme.lower() not in {'http', 'https'} or not parsed_url.hostname:
        return None
    return clean_url


def _normalize_state_name(name):
    if not name:
        return ''
    return name.replace('-', ' ').strip().lower()


def _bucket_scheme_category(row):
    category_text = (row.get('department') or row.get('scheme_type') or '').strip().lower()
    if not category_text:
        return 'Other'
    if 'agri' in category_text or 'farm' in category_text:
        return 'Agriculture'
    if 'health' in category_text or 'medical' in category_text or 'care' in category_text:
        return 'Healthcare'
    if 'educ' in category_text or 'skill' in category_text or 'school' in category_text:
        return 'Education'
    if 'women' in category_text:
        return 'Women Empowerment'
    if 'social' in category_text or 'welfare' in category_text or 'poverty' in category_text:
        return 'Social Welfare'
    if 'econom' in category_text or 'loan' in category_text or 'finance' in category_text or 'credit' in category_text:
        return 'Economic Support'
    return category_text.title()


def india_map_overview_api(request):
    csv_path = os.path.join(conf_settings.BASE_DIR, 'schemes_data.csv')
    if not os.path.exists(csv_path):
        csv_path = os.path.join(conf_settings.BASE_DIR, 'schemes.csv')

    all_schemes = _load_schemes_from_csv(csv_path)
    total_schemes = len(all_schemes)
    central_schemes = sum(1 for scheme in all_schemes if (scheme.get('scheme_type') or '').strip().lower() == 'central')
    state_schemes = total_schemes - central_schemes

    category_counts = {}
    state_counts = {}
    for scheme in all_schemes:
        bucket = _bucket_scheme_category(scheme)
        category_counts[bucket] = category_counts.get(bucket, 0) + 1
        state_name = (scheme.get('state') or '').strip()
        if state_name and state_name.lower() != 'india':
            state_counts[state_name] = state_counts.get(state_name, 0) + 1

    top_states = sorted(state_counts.items(), key=lambda item: item[1], reverse=True)[:8]
    top_category = max(category_counts.items(), key=lambda item: item[1])[0] if category_counts else 'General'

    return JsonResponse({
        'total_schemes': total_schemes,
        'central_schemes': central_schemes,
        'state_schemes': state_schemes,
        'active_states': len(state_counts),
        'top_state': top_states[0][0] if top_states else '—',
        'category_counts': category_counts,
        'top_states': [{'state': name, 'count': count} for name, count in top_states],
        'top_category': top_category,
    })


def india_map_state_analytics_api(request, state_name):
    requested_state = _normalize_state_name(state_name)
    csv_path = os.path.join(conf_settings.BASE_DIR, 'schemes_data.csv')
    if not os.path.exists(csv_path):
        csv_path = os.path.join(conf_settings.BASE_DIR, 'schemes.csv')

    all_schemes = _load_schemes_from_csv(csv_path)
    matching_schemes = []
    for scheme in all_schemes:
        scheme_state = _normalize_state_name(scheme.get('state'))
        is_central = (scheme.get('scheme_type') or '').strip().lower() == 'central'
        if is_central or scheme_state == requested_state:
            matching_schemes.append(scheme)

    total_schemes = len(matching_schemes)
    central_schemes = sum(1 for scheme in matching_schemes if (scheme.get('scheme_type') or '').strip().lower() == 'central')
    state_schemes = total_schemes - central_schemes
    category_counts = {}
    for scheme in matching_schemes:
        bucket = _bucket_scheme_category(scheme)
        category_counts[bucket] = category_counts.get(bucket, 0) + 1

    top_category = max(category_counts.items(), key=lambda item: item[1])[0] if category_counts else 'General'
    top_categories = sorted(category_counts.items(), key=lambda item: item[1], reverse=True)

    return JsonResponse({
        'state_name': state_name,
        'total_schemes': total_schemes,
        'central_schemes': central_schemes,
        'state_schemes': state_schemes,
        'category_counts': category_counts,
        'top_category': top_category,
        'top_categories': [{ 'category': key, 'count': value } for key, value in top_categories],
    })


def _load_schemes_from_csv(csv_path):
    schemes = []
    if not os.path.exists(csv_path):
        return schemes

    with open(csv_path, newline='', encoding='utf-8') as csvfile:
        reader = csv.DictReader(csvfile)
        for row in reader:
            schemes.append({
                'id': (row.get('id') or '').strip(),
                'scheme_name': (row.get('scheme_name') or '').strip(),
                'description': (row.get('description') or '').strip(),
                'eligibility': (row.get('eligibility') or '').strip(),
                'documents_required': (row.get('documents_required') or '').strip(),
                'official_website': (row.get('official_website') or '').strip(),
                'state': (row.get('state') or '').strip(),
                'scheme_type': (row.get('scheme_type') or '').strip(),
                'department': (row.get('department') or '').strip(),
            })
    return schemes


def schemes_by_state_api(request, state_name):
    requested_state = state_name.replace('-', ' ').strip()
    csv_path = os.path.join(conf_settings.BASE_DIR, 'schemes_data.csv')
    if not os.path.exists(csv_path):
        csv_path = os.path.join(conf_settings.BASE_DIR, 'schemes.csv')

    all_schemes = _load_schemes_from_csv(csv_path)
    matching = []
    for scheme in all_schemes:
        row_state = scheme.get('state', '').strip()
        is_central = scheme.get('scheme_type', '').lower() == 'central'
        if is_central or row_state.lower() == requested_state.lower():
            matching.append({
                'id': scheme.get('id'),
                'name': scheme.get('scheme_name'),
                'description': scheme.get('description'),
                'eligibility': scheme.get('eligibility'),
                'documents_required': scheme.get('documents_required'),
                'category': scheme.get('scheme_type') or 'General',
                'scheme_type': scheme.get('scheme_type') or '',
                'apply_link': scheme.get('official_website'),
                'official_website': scheme.get('official_website'),
                'department': scheme.get('department'),
                'state': row_state,
            })

    return JsonResponse(matching, safe=False)


def state_schemes_public_api(request, state_name):
    """Public API endpoint returning a JSON array of schemes for a selected state."""
    state_name_unescaped = state_name.replace('-', ' ')
    # Get both state-specific schemes and central schemes
    matching_schemes = Scheme.objects.filter(
        Q(state__iexact=state_name_unescaped) | Q(scheme_type='Central')
    ).order_by('scheme_name')

    scheme_data = []
    for scheme in matching_schemes:
        apply_link = _format_link(scheme.apply_link) or _format_link(scheme.official_website)
        scheme_data.append({
            'name': scheme.scheme_name,
            'description': scheme.description or scheme.benefits or 'No description available.',
            'eligibility': scheme.eligibility or '',
            'documents_required': scheme.documents_required or '',
            'benefits': scheme.benefits or '',
            'category': scheme.category or scheme.scheme_type or 'General',
            'scheme_type': scheme.scheme_type or '',
            'state': scheme.state or '',
            'department': scheme.department or '',
            'apply_link': apply_link,
            'official_website': _format_link(scheme.official_website),
            'id': scheme.id,
        })

    return JsonResponse(scheme_data, safe=False)


# -----------------------------
# AI RECOMMENDATION
# -----------------------------
@login_required
def recommend_schemes(request):

    schemes = []
    form_data = {}

    if request.method == 'POST':
        # Use .get() with defaults so it doesn't crash if a user skips steps
        age = int(request.POST.get('age') or 0)
        income = int(request.POST.get('income') or 0) # 0 means no income limit enforced if skipped
        category = request.POST.get('category') or 'General'
        state = request.POST.get('state') or ''
        
        form_data = {
            'age': age,
            'income': income,
            'category': category,
            'state': state
        }

        all_schemes = Scheme.objects.all()
        results = []

        for scheme in all_schemes:
            score = 0
            reasons = []

            # AGE CHECK (Always required, so we always check)
            if scheme.min_age <= age <= scheme.max_age:
                score += 30
                reasons.append("Age eligible")
            else:
                # If they fail the age check, it's a bad match. 
                # We don't add points, but we still keep it in the list to sort later.
                pass 

            # INCOME CHECK (If income is 0, it means they skipped it, so we give them the points)
            if income == 0 or income <= scheme.income_limit:
                score += 30
                if income > 0:
                    reasons.append("Income eligible")

            # CATEGORY CHECK (If they skip, it defaults to General)
            if scheme.category == "All" or scheme.category.lower() == category.lower():
                score += 20
                reasons.append("Category match")

            # STATE CHECK (If they skip, state is empty, so we give them the points)
            if not state or not scheme.state or state.lower() in scheme.state.lower():
                score += 20
                if state:
                    reasons.append("Location match")

            scheme_official = _format_link(scheme.official_website)
            scheme_apply = _format_link(scheme.apply_link) or scheme_official

            results.append({
                'scheme': scheme,
                'score': score,
                'reasons': reasons,
                'official_url': scheme_official,
                'apply_url': scheme_apply
            })

        # SORT BY SCORE
        results = sorted(results, key=lambda x: x['score'], reverse=True)

        # FILTER: Only keep schemes with a score of 40 or higher
        schemes = [r for r in results if r['score'] >= 40][:5]

    return render(request, 'recommend.html', {
        'schemes': schemes,
        'form_data': form_data
    })


# -----------------------------
# APPLY SCHEME
# -----------------------------
@login_required
def apply_scheme(request, scheme_id):
    scheme = get_object_or_404(Scheme, id=scheme_id)
    return redirect(f"{reverse('apply_assistance')}?scheme_id={scheme.pk}")


# -----------------------------
# MY APPLICATIONS
# -----------------------------
@login_required
def my_applications(request):

    applications = ApplicationRequest.objects.filter(
        user=request.user
    ).order_by('-created_at')

    return render(request, 'my_applications.html', {
        'applications': applications
    })


from django.conf import settings

try:
    import openai
except ModuleNotFoundError:
    openai = None

if openai is not None:
    openai.api_key = getattr(settings, 'OPENAI_API_KEY', None)


def _get_openai_client():
    api_key = getattr(settings, 'OPENAI_API_KEY', None)
    if not api_key or openai is None:
        return None

    try:
        from openai import OpenAI
        return OpenAI(api_key=api_key)
    except Exception:
        return None


def _normalize_lang_code(raw_lang):
    lang = (raw_lang or 'auto').lower().strip()
    if lang in ['hi', 'hi-in', 'hindi']:
        return 'hi'
    if lang in ['mr', 'mr-in', 'marathi']:
        return 'mr'
    if lang in ['en', 'en-in', 'english']:
        return 'en'
    return 'auto'


def _detect_reply_language(message, requested_lang='auto'):
    lang = _normalize_lang_code(requested_lang)
    if lang != 'auto':
        return lang

    text = (message or '').strip()
    if not text:
        return 'en'

    if re.search(r'[\u0900-\u097F]', text):
        marathi_markers = ['मला', 'आहे', 'योजना', 'शेतकरी', 'काय', 'माझ्या', 'साठी']
        text_low = text.lower()
        if any(marker in text_low for marker in marathi_markers):
            return 'mr'
        return 'hi'

    return 'en'


def _localize_text(key, lang='en'):
    messages = {
        'ask_question': {
            'en': 'Please ask a question about schemes, such as age, income, and state.',
            'hi': 'कृपया योजना के बारे में प्रश्न पूछें, जैसे उम्र, आय और राज्य।',
            'mr': 'कृपया योजनांबद्दल प्रश्न विचारा, जसे वय, उत्पन्न आणि राज्य.'
        },
        'hello': {
            'en': 'Hi! Share your age, income, and state to get better scheme recommendations.',
            'hi': 'नमस्ते! बेहतर योजना सुझाव पाने के लिए अपनी उम्र, आय और राज्य बताएं।',
            'mr': 'नमस्कार! चांगल्या योजना शिफारसींसाठी तुमचे वय, उत्पन्न आणि राज्य सांगा.'
        },
        'no_match': {
            'en': 'I could not find an exact scheme match yet. Please share age, annual income, category, and state.',
            'hi': 'मुझे अभी सटीक योजना मिलान नहीं मिला। कृपया उम्र, वार्षिक आय, श्रेणी और राज्य बताएं।',
            'mr': 'मला अजून अचूक योजना जुळणी मिळाली नाही. कृपया वय, वार्षिक उत्पन्न, प्रवर्ग आणि राज्य सांगा.'
        },
        'top_options': {
            'en': 'Here are the best options for your query:',
            'hi': 'आपके प्रश्न के लिए सबसे उपयुक्त विकल्प:',
            'mr': 'तुमच्या प्रश्नासाठी सर्वोत्तम पर्याय:'
        },
        'kisan': {
            'en': 'PM Kisan provides Rs. 6000 per year to eligible small and marginal farmers.',
            'hi': 'पीएम किसान योजना पात्र छोटे और सीमांत किसानों को प्रति वर्ष ₹6000 देती है।',
            'mr': 'पीएम किसान योजनेत पात्र लघु आणि सीमांत शेतकऱ्यांना दरवर्षी ₹6000 मिळतात.'
        },
        'insurance': {
            'en': 'Crop insurance support is available under Pradhan Mantri Fasal Bima Yojana.',
            'hi': 'फसल बीमा सहायता प्रधानमंत्री फसल बीमा योजना के तहत उपलब्ध है।',
            'mr': 'प्रधानमंत्री फसल विमा योजनेअंतर्गत पीक विमा मदत उपलब्ध आहे.'
        },
    }
    return messages.get(key, {}).get(lang, messages.get(key, {}).get('en', ''))


def _transcribe_audio_with_openai(audio_file):
    """Return transcript text using Whisper when API key is configured."""
    api_key = getattr(settings, 'OPENAI_API_KEY', None)
    if not api_key or openai is None:
        return ''

    # New SDK path
    client = _get_openai_client()
    if client:
        try:
            content_type = getattr(audio_file, 'content_type', None) or 'audio/webm'
            transcript = client.audio.transcriptions.create(
                model='whisper-1',
                file=(getattr(audio_file, 'name', 'voice.webm'), audio_file, content_type),
            )
            text = getattr(transcript, 'text', '') or ''
            if text:
                return text.strip()
        except Exception:
            try:
                audio_file.seek(0)
            except Exception:
                pass

    # Legacy SDK path
    try:
        transcript = openai.Audio.transcribe('whisper-1', audio_file)
        text = transcript.get('text', '') if isinstance(transcript, dict) else ''
        return (text or '').strip()
    except Exception:
        return ''


def _transcribe_audio_without_openai(audio_file, language='auto'):
    """Fallback STT using SpeechRecognition + ffmpeg conversion when needed."""
    try:
        import speech_recognition as sr
    except Exception:
        return '', 'SpeechRecognition library not installed on server.'

    try:
        import imageio_ffmpeg
        ffmpeg_bin = imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        ffmpeg_bin = 'ffmpeg'

    requested_lang = _normalize_lang_code(language)
    locale = {
        'hi': 'hi-IN',
        'mr': 'mr-IN',
        'en': 'en-IN',
        'auto': 'hi-IN',
    }[requested_lang]

    recognizer = sr.Recognizer()
    suffix = os.path.splitext(getattr(audio_file, 'name', 'voice.webm'))[1] or '.webm'

    tmp_in = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
    tmp_in.write(audio_file.read())
    tmp_in.flush()
    tmp_in_path = tmp_in.name
    tmp_in.close()

    tmp_wav_path = tempfile.NamedTemporaryFile(delete=False, suffix='.wav').name

    try:
        input_ext = suffix.lower()
        source_path = tmp_in_path

        # WAV/AIFF/FLAC can be parsed directly by SpeechRecognition.
        if input_ext not in ['.wav', '.aiff', '.aif', '.flac']:
            cmd = [
                ffmpeg_bin, '-y', '-i', tmp_in_path,
                '-ac', '1', '-ar', '16000', '-f', 'wav', tmp_wav_path
            ]
            proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
            if proc.returncode != 0:
                return '', 'Audio conversion failed on server. Please try again with a clear 5-6 second recording.'
            source_path = tmp_wav_path

        with sr.AudioFile(source_path) as source:
            audio_data = recognizer.record(source)

        text = recognizer.recognize_google(audio_data, language=locale)
        return (text or '').strip(), ''
    except sr.UnknownValueError:
        return '', 'Could not understand the recorded audio. Please speak clearly and retry.'
    except sr.RequestError:
        return '', 'Speech service is unavailable from server right now. Please try again in a minute.'
    except Exception:
        return '', 'Server fallback transcription failed due to an internal error.'
    finally:
        for path in [tmp_in_path, tmp_wav_path]:
            try:
                if path and os.path.exists(path):
                    os.remove(path)
            except Exception:
                pass


def _extract_profile_from_message(message):
    message_low = (message or '').lower()
    age = None
    income = None
    state = ''

    numbers = re.findall(r'\d+', message_low)
    if len(numbers) >= 1:
        age = int(numbers[0])
    if len(numbers) >= 2:
        income = int(numbers[1])

    states = [
        'maharashtra', 'tamil nadu', 'kerala', 'karnataka', 'delhi', 'telangana',
        'rajasthan', 'uttar pradesh', 'madhya pradesh', 'west bengal', 'gujarat',
        'punjab', 'haryana', 'bihar', 'odisha', 'andhra pradesh', 'assam'
    ]
    for s in states:
        if s in message_low:
            state = s
            break

    return age, income, state


def _find_matching_schemes(age=None, income=None, state='', category='All', query=''):
    schemes = Scheme.objects.all()
    matched = []
    query_low = (query or '').lower().strip()

    for scheme in schemes:
        score = 0
        reasons = []

        if age is not None and scheme.min_age <= age <= scheme.max_age:
            score += 35
            reasons.append('age eligibility')

        if income is not None and income <= scheme.income_limit:
            score += 30
            reasons.append('income eligibility')

        if state and state in (scheme.state or '').lower():
            score += 20
            reasons.append('state match')

        if category and category != 'All' and (scheme.category == 'All' or scheme.category == category):
            score += 10
            reasons.append('category match')

        if query_low:
            haystack = ' '.join([
                scheme.scheme_name or '',
                scheme.description or '',
                scheme.eligibility or '',
                scheme.department or '',
                scheme.state or '',
            ]).lower()
            if any(token in haystack for token in query_low.split() if len(token) > 2):
                score += 25
                reasons.append('query relevance')

        if score > 0:
            matched.append((scheme, score, reasons))

    matched.sort(key=lambda item: item[1], reverse=True)
    return matched[:5]


def default_chatbot_response(message):
    lang = _detect_reply_language(message)
    message_low = (message or '').lower()

    if not message_low.strip():
        return _localize_text('ask_question', lang)

    # Friendly quick replies
    if 'kisan' in message_low:
        return _localize_text('kisan', lang)
    if 'insurance' in message_low or 'bima' in message_low:
        return _localize_text('insurance', lang)
    if 'hello' in message_low or 'hi' in message_low:
        return _localize_text('hello', lang)

    age, income, state = _extract_profile_from_message(message)
    matched = _find_matching_schemes(age=age, income=income, state=state, query=message)

    if matched:
        lines = []
        for scheme, score, reasons in matched[:3]:
            reason_text = ', '.join(reasons[:2]) if reasons else 'general relevance'
            if lang == 'hi':
                lines.append(f"- {scheme.scheme_name} ({scheme.state}) - स्कोर {score} ({reason_text})")
            elif lang == 'mr':
                lines.append(f"- {scheme.scheme_name} ({scheme.state}) - गुण {score} ({reason_text})")
            else:
                lines.append(f"- {scheme.scheme_name} ({scheme.state}) - match score {score} ({reason_text})")
        return _localize_text('top_options', lang) + "\n" + "\n".join(lines)

    return _localize_text('no_match', lang)


@login_required
@require_POST
def transcribe_voice(request):
    audio_file = request.FILES.get('audio')
    language = request.POST.get('language', 'auto')
    if not audio_file:
        return JsonResponse({'error': 'Audio file is required.'}, status=400)

    if audio_file.size > 10 * 1024 * 1024:
        return JsonResponse({'error': 'Audio file too large. Please keep it under 10MB.'}, status=400)

    transcript = _transcribe_audio_with_openai(audio_file)
    if not transcript:
        try:
            audio_file.seek(0)
        except Exception:
            pass
        transcript, fallback_error = _transcribe_audio_without_openai(audio_file, language=language)

    if not transcript:
        return JsonResponse({
            'error': fallback_error or 'Unable to transcribe audio. Configure OPENAI_API_KEY or install fallback STT dependencies.'
        }, status=502)

    return JsonResponse({'transcript': transcript})


def _stream_text_chunks(text):
    if not text:
        return
    for token in text.split():
        payload = json.dumps({'token': token + ' '})
        yield f"data: {payload}\n\n"
    yield "data: {\"done\": true}\n\n"


def _build_openai_messages(message, response_lang):
    language_hint = {
        'hi': 'Reply in Hindi.',
        'mr': 'Reply in Marathi.',
        'en': 'Reply in English.',
        'auto': 'Reply in the user language.',
    }.get(response_lang, 'Reply in the user language.')

    top_matches = _find_matching_schemes(query=message)
    context_lines = []
    for scheme, score, _ in top_matches[:3]:
        context_lines.append(
            f"{scheme.scheme_name} | {scheme.state} | {scheme.category} | income_limit={scheme.income_limit}"
        )

    return [
        {
            'role': 'system',
            'content': 'You are SmartAssist, an assistant for Indian farmer welfare schemes. Give concise, practical answers.'
        },
        {
            'role': 'system',
            'content': language_hint
        },
        {
            'role': 'system',
            'content': 'Relevant scheme context:\n' + '\n'.join(context_lines) if context_lines else 'No specific context found.'
        },
        {
            'role': 'user',
            'content': message
        }
    ]


def chatbot(request):
    message = request.GET.get('message', '').strip()
    mode = request.GET.get('mode', 'auto').lower()
    requested_lang = request.GET.get('lang', 'auto')
    response_lang = _detect_reply_language(message, requested_lang)

    if not message:
        return JsonResponse({'reply': _localize_text('ask_question', response_lang)})

    def get_local_response():
        return default_chatbot_response(message)

    if mode == 'local':
        reply = get_local_response()
    elif mode == 'openai':
        client = _get_openai_client()
        if client:
            try:
                response = client.chat.completions.create(
                    model="gpt-4o-mini",
                    messages=_build_openai_messages(message, response_lang),
                    temperature=0.7,
                    max_tokens=220
                )
                reply = (response.choices[0].message.content or '').strip()
                if not reply:
                    reply = get_local_response()
            except Exception:
                reply = get_local_response()
        else:
            reply = "OpenAI API key is not configured. Please switch to Local mode." 
    else:
        # auto mode: prefer OpenAI if available
        client = _get_openai_client()
        if client:
            try:
                response = client.chat.completions.create(
                    model="gpt-4o-mini",
                    messages=_build_openai_messages(message, response_lang),
                    temperature=0.7,
                    max_tokens=220
                )
                reply = (response.choices[0].message.content or '').strip()
                if not reply:
                    reply = get_local_response()
            except Exception:
                reply = get_local_response()
        else:
            reply = get_local_response()

    return JsonResponse({'reply': reply})


def chatbot_stream(request):
    message = request.GET.get('message', '').strip()
    mode = request.GET.get('mode', 'auto').lower()
    requested_lang = request.GET.get('lang', 'auto')
    response_lang = _detect_reply_language(message, requested_lang)

    if not message:
        def empty_stream():
            for chunk in _stream_text_chunks(_localize_text('ask_question', response_lang)):
                yield chunk
        return StreamingHttpResponse(empty_stream(), content_type='text/event-stream')

    def event_stream():
        local_reply = default_chatbot_response(message)

        if mode in ['openai', 'auto']:
            client = _get_openai_client()
            if client:
                try:
                    stream = client.chat.completions.create(
                        model='gpt-4o-mini',
                        messages=_build_openai_messages(message, response_lang),
                        temperature=0.7,
                        max_tokens=220,
                        stream=True,
                    )

                    sent_any = False
                    for part in stream:
                        delta = ''
                        try:
                            delta = part.choices[0].delta.content or ''
                        except Exception:
                            delta = ''

                        if delta:
                            sent_any = True
                            yield f"data: {json.dumps({'token': delta})}\n\n"

                    if not sent_any:
                        for chunk in _stream_text_chunks(local_reply):
                            yield chunk
                    else:
                        yield "data: {\"done\": true}\n\n"
                    return
                except Exception:
                    pass

        for chunk in _stream_text_chunks(local_reply):
            yield chunk

    response = StreamingHttpResponse(event_stream(), content_type='text/event-stream')
    response['Cache-Control'] = 'no-cache'
    response['X-Accel-Buffering'] = 'no'
    return response