from django.contrib.auth.models import User
from django.core import mail
from django.core.exceptions import ImproperlyConfigured
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.test import Client, RequestFactory, TestCase, override_settings
from django.template.loader import get_template
from django.urls import reverse, translate_url
from django.utils import timezone
from django.utils.translation import deactivate_all
from unittest.mock import patch
from importlib import import_module
import os
import json
import sys
from types import SimpleNamespace

from aiohttp import ClientResponseError
from farmers.admin import NotificationAdmin
from farmers.models import ApplicationRequest, Notification, Scheme, UserProfile
from farmers.forms import CitizenApplicationForm, SchemeForm, UserProfileForm
from farmers.views import (
    VoiceServiceError,
    _scheme_voice_text,
    _synthesize_scheme_voice,
    _transcribe_audio_without_openai,
    _validate_audio_content,
)
from farmers.notification_queue import process_notification, process_pending_notifications
from farmers.offline_translation import lookup_local_translation
from farmers.transcription import (
    InvalidAudioError,
    ModelUnavailableError,
    UnsupportedLanguageError,
    _load_model,
    get_model_path,
    transcribe_audio,
)
from smartassist.settings import (
    _get_allowed_hosts,
    _get_bool_setting,
    _get_csrf_trusted_origins,
    _get_cache_config,
    _get_debug_setting,
    _get_nonnegative_int_setting,
    _get_secret_key,
)

normalize_legacy_pending_status = import_module(
    'farmers.migrations.0009_normalize_legacy_pending_status'
).normalize_legacy_pending_status
reconcile_legacy_notifications = import_module(
    'farmers.migrations.0015_reconcile_legacy_notifications'
).reconcile_legacy_notifications


class NotificationAdminTests(TestCase):
    def test_error_columns_preserve_both_values_and_detail_editability(self):
        admin_instance = NotificationAdmin(Notification, None)
        notification = SimpleNamespace(
            email_error='historical delivery error',
            last_error='current queue error',
        )

        self.assertEqual(
            admin_instance.email_error_preview(notification),
            'historical delivery error',
        )
        self.assertEqual(
            admin_instance.last_error_preview(notification),
            'current queue error',
        )
        self.assertNotIn('email_error', admin_instance.readonly_fields)
        self.assertNotIn('last_error', admin_instance.readonly_fields)

    def test_error_columns_truncate_long_values(self):
        admin_instance = NotificationAdmin(Notification, None)
        long_error = 'x' * 100

        self.assertEqual(len(admin_instance.email_error_preview(
            SimpleNamespace(email_error=long_error)
        )), 80)
        self.assertTrue(
            admin_instance.last_error_preview(
                SimpleNamespace(last_error=long_error)
            ).endswith('...')
        )


class SmartAssistVerificationTests(TestCase):
    def setUp(self):
        self.central_scheme = Scheme.objects.create(
            scheme_name='Central Test Scheme',
            scheme_type='Central',
            state='India',
            department='Ministry of Test',
            description='Central scheme description.',
            eligibility='Eligible citizens.',
            documents_required='Identity proof.',
            official_website='https://example.gov.in/central',
            apply_link='https://example.gov.in/apply',
            category='General',
        )
        self.state_scheme = Scheme.objects.create(
            scheme_name='State Test Scheme',
            scheme_type='State',
            state='Test State',
            department='State Department',
            description='State scheme description.',
            eligibility='State residents.',
            documents_required='Residency proof.',
            official_website='https://example.gov.in/state',
            category='General',
        )
        self.user = User.objects.create_user(username='citizen', password='secret123')

    def tearDown(self):
        self.client.cookies.pop('django_language', None)
        deactivate_all()
        super().tearDown()


    def test_central_scheme_filter_uses_scheme_type_not_state(self):
        response = self.client.get(reverse('scheme_awareness'), {'type': 'Central'})

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Central Test Scheme')
        self.assertNotContains(response, 'State Test Scheme')
        self.assertEqual(len(response.context['schemes']), 1)

    def test_central_schemes_remain_available_when_state_is_selected(self):
        response = self.client.get(
            reverse('scheme_awareness'),
            {'type': 'Central', 'state': 'Assam'},
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Central Test Scheme')
        self.assertNotContains(response, 'State Test Scheme')
        self.assertEqual(list(response.context['schemes']), [self.central_scheme])
        self.assertContains(response, 'option value="Central" selected', html=False)
        self.assertEqual(response.context['state_filter'], 'Assam')

    def test_state_filter_includes_central_and_matching_state_schemes(self):
        response = self.client.get(
            reverse('scheme_awareness'),
            {'state': 'Test State'},
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Central Test Scheme')
        self.assertContains(response, 'State Test Scheme')

    def test_recommendation_page_renders_for_authenticated_user(self):
        self.client.force_login(self.user)

        response = self.client.get(reverse('recommend'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'eligibilityForm')
        self.assertContains(response, 'id="step-4"', html=False)
        self.assertContains(response, 'Transgender')
        self.assertContains(response, 'rural_urban')
        self.assertContains(response, 'Skip to Results')
        self.assertContains(
            response,
            '>Eligibility</a>',
            html=False,
        )
        for category in ('General', 'Other Backward Class (OBC)', 'Scheduled Caste (SC)', 'Scheduled Tribe (ST)', 'Economically Weaker Section (EWS)'):
            self.assertContains(response, category)

    def test_shared_dev_stylesheet_is_loaded_except_on_recommendation(self):
        home_response = self.client.get(reverse('home'))
        self.assertContains(home_response, '/static/css/smartassist-dev.css')

        self.client.force_login(self.user)
        recommendation_response = self.client.get(reverse('recommend'))
        self.assertNotContains(recommendation_response, '/static/css/smartassist-dev.css')
        ai_response = self.client.get(reverse('ai_recommendation'))
        self.assertNotContains(ai_response, '/static/css/smartassist-dev.css')

    def test_ai_recommendation_is_separate_from_eligibility(self):
        self.client.force_login(self.user)

        response = self.client.get(reverse('ai_recommendation'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'AI-Driven Scheme Discovery')
        self.assertContains(response, 'recommendForm')
        self.assertContains(response, 'Top Recommendation Results')
        self.assertContains(response, 'href="/recommend/"', html=False)
        self.assertNotContains(response, 'eligibilityForm')

    def test_navigation_exposes_separate_eligibility_and_ai_links(self):
        self.client.force_login(self.user)

        response = self.client.get(reverse('home'))

        self.assertContains(response, 'href="/recommend/"', html=False)
        self.assertContains(response, 'Eligibility')
        self.assertNotContains(response, 'href="/ai-recommendation/"', html=False)

        dashboard_response = self.client.get(reverse('dashboard'))
        self.assertContains(dashboard_response, 'href="/ai-recommendation/"', html=False)

    def test_ai_recommendation_uses_real_scheme_records(self):
        self.client.force_login(self.user)

        response = self.client.post(
            reverse('ai_recommendation'),
            {
                'age': '30',
                'income': '100000',
                'category': 'General',
                'state': 'Test State',
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'State Test Scheme')
        self.assertEqual(response.context['schemes'][0]['scheme'], self.state_scheme)

    def test_recommendation_handles_optional_fields_and_returns_matches(self):
        self.client.force_login(self.user)

        response = self.client.post(
            reverse('recommend'),
            {'age': '', 'income': '', 'category': '', 'state': ''},
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'valid non-negative age')
        self.assertEqual(response.context['schemes'], [])

    def test_recommendation_does_not_score_missing_or_invalid_income(self):
        self.client.force_login(self.user)

        response = self.client.post(
            reverse('ai_recommendation'),
            {'age': '30', 'income': 'not-a-number', 'category': 'General'},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['schemes'], [])
        self.assertContains(response, 'valid non-negative annual income')

    def test_recommendation_rejects_missing_age(self):
        self.client.force_login(self.user)

        response = self.client.post(
            reverse('recommend'),
            {'age': '', 'income': '100000', 'category': 'General', 'state': 'Test State'},
        )

        self.assertEqual(response.context['schemes'], [])
        self.assertContains(response, 'valid non-negative age')

    def test_recommendation_enforces_age_income_state_and_category(self):
        eligible = Scheme.objects.create(
            scheme_name='Eligible State Scheme',
            scheme_type='State',
            state='Test State',
            department='Test Department',
            min_age=25,
            max_age=40,
            income_limit=200000,
            category='General',
        )
        too_young = Scheme.objects.create(
            scheme_name='Too Young Scheme',
            scheme_type='State',
            state='Test State',
            department='Test Department',
            min_age=35,
            max_age=60,
            income_limit=200000,
            category='General',
        )
        too_old = Scheme.objects.create(
            scheme_name='Too Old Scheme',
            scheme_type='State',
            state='Test State',
            department='Test Department',
            min_age=10,
            max_age=20,
            income_limit=200000,
            category='General',
        )
        too_rich = Scheme.objects.create(
            scheme_name='Too Rich Scheme',
            scheme_type='State',
            state='Test State',
            department='Test Department',
            min_age=25,
            max_age=40,
            income_limit=50000,
            category='General',
        )
        wrong_state = Scheme.objects.create(
            scheme_name='Other State Scheme',
            scheme_type='State',
            state='Other State',
            department='Test Department',
            min_age=25,
            max_age=40,
            income_limit=200000,
            category='General',
        )
        wrong_category = Scheme.objects.create(
            scheme_name='Category Restricted Scheme',
            scheme_type='State',
            state='Test State',
            department='Test Department',
            min_age=25,
            max_age=40,
            income_limit=200000,
            category='SC',
        )

        self.client.force_login(self.user)
        response = self.client.post(
            reverse('recommend'),
            {'age': '30', 'income': '100000', 'category': 'General', 'state': 'Test State'},
        )

        recommended = [item['scheme'] for item in response.context['schemes']]
        self.assertIn(eligible, recommended)
        self.assertNotIn(too_young, recommended)
        self.assertNotIn(too_old, recommended)
        self.assertNotIn(too_rich, recommended)
        self.assertNotIn(wrong_state, recommended)
        self.assertNotIn(wrong_category, recommended)

    def test_recommendation_allows_missing_optional_state_and_category(self):
        self.client.force_login(self.user)

        response = self.client.post(
            reverse('recommend'),
            {'age': '30', 'income': '100000', 'category': '', 'state': ''},
        )

        self.assertTrue(response.context['schemes'])
        self.assertIsNone(response.context['validation_error'])

    def test_recommendation_excludes_scheme_with_missing_state(self):
        malformed_scheme = Scheme.objects.create(
            scheme_name='Malformed State Scheme',
            scheme_type='State',
            state='',
            department='Test Department',
            min_age=25,
            max_age=40,
            income_limit=200000,
            category='General',
        )

        self.client.force_login(self.user)
        response = self.client.post(
            reverse('recommend'),
            {'age': '30', 'income': '100000', 'category': 'General', 'state': 'Gujarat'},
        )

        self.assertNotIn(
            malformed_scheme,
            [item['scheme'] for item in response.context['schemes']],
        )

    def test_ai_and_regular_recommendations_apply_same_state_and_category_filters(self):
        self.client.force_login(self.user)
        response = self.client.post(
            reverse('ai_recommendation'),
            {
                'age': '30',
                'income': '100000',
                'category': 'General',
                'state': 'Test State',
            },
        )
        ai_names = {item['scheme'].scheme_name for item in response.context['schemes']}

        response = self.client.post(
            reverse('recommend'),
            {
                'age': '30',
                'income': '100000',
                'category': 'General',
                'state': 'Test State',
            },
        )
        regular_names = {item['scheme'].scheme_name for item in response.context['schemes']}

        self.assertEqual(ai_names, regular_names)

    def test_recommendations_accept_age_minimum_and_maximum_boundaries(self):
        minimum_scheme = Scheme.objects.create(
            scheme_name='Minimum Age Boundary Scheme',
            scheme_type='State',
            state='Test State',
            department='Test Department',
            min_age=25,
            max_age=40,
            income_limit=200000,
            category='General',
        )
        maximum_scheme = Scheme.objects.create(
            scheme_name='Maximum Age Boundary Scheme',
            scheme_type='State',
            state='Test State',
            department='Test Department',
            min_age=20,
            max_age=30,
            income_limit=200000,
            category='General',
        )
        self.client.force_login(self.user)

        for endpoint in ('recommend', 'ai_recommendation'):
            with self.subTest(endpoint=endpoint, boundary='minimum'):
                response = self.client.post(
                    reverse(endpoint),
                    {
                        'age': '25',
                        'income': '100000',
                        'category': 'General',
                        'state': 'Test State',
                    },
                )
                recommended = [item['scheme'] for item in response.context['schemes']]
                self.assertIn(minimum_scheme, recommended)

            with self.subTest(endpoint=endpoint, boundary='maximum'):
                response = self.client.post(
                    reverse(endpoint),
                    {
                        'age': '30',
                        'income': '100000',
                        'category': 'General',
                        'state': 'Test State',
                    },
                )
                recommended = [item['scheme'] for item in response.context['schemes']]
                self.assertIn(maximum_scheme, recommended)

    def test_recommendations_accept_income_limit_boundary(self):
        boundary_scheme = Scheme.objects.create(
            scheme_name='Income Boundary Scheme',
            scheme_type='State',
            state='Test State',
            department='Test Department',
            min_age=25,
            max_age=40,
            income_limit=150000,
            category='General',
        )
        self.client.force_login(self.user)

        for endpoint in ('recommend', 'ai_recommendation'):
            response = self.client.post(
                reverse(endpoint),
                {
                    'age': '30',
                    'income': '150000',
                    'category': 'General',
                    'state': 'Test State',
                },
            )
            with self.subTest(endpoint=endpoint):
                recommended = [item['scheme'] for item in response.context['schemes']]
                self.assertIn(boundary_scheme, recommended)

    def test_recommendations_isolate_state_specific_schemes_by_state(self):
        maharashtra_scheme = Scheme.objects.create(
            scheme_name='Maharashtra Boundary Scheme',
            scheme_type='State',
            state='Maharashtra',
            department='Test Department',
            min_age=25,
            max_age=40,
            income_limit=200000,
            category='General',
        )
        gujarat_scheme = Scheme.objects.create(
            scheme_name='Gujarat Boundary Scheme',
            scheme_type='State',
            state='Gujarat',
            department='Test Department',
            min_age=25,
            max_age=40,
            income_limit=200000,
            category='General',
        )
        self.client.force_login(self.user)

        cases = (
            ('Maharashtra', maharashtra_scheme, gujarat_scheme),
            ('Gujarat', gujarat_scheme, maharashtra_scheme),
        )
        for endpoint in ('recommend', 'ai_recommendation'):
            for state, expected, excluded in cases:
                response = self.client.post(
                    reverse(endpoint),
                    {
                        'age': '30',
                        'income': '100000',
                        'category': 'General',
                        'state': state,
                    },
                )
                with self.subTest(endpoint=endpoint, state=state):
                    recommended = [item['scheme'] for item in response.context['schemes']]
                    self.assertIn(expected, recommended)
                    self.assertNotIn(excluded, recommended)

    def test_recommendations_normalize_state_case_and_whitespace(self):
        scheme = Scheme.objects.create(
            scheme_name='Maharashtra Normalization Scheme',
            scheme_type='State',
            state='Maharashtra',
            department='Test Department',
            min_age=25,
            max_age=40,
            income_limit=200000,
            category='General',
        )
        self.client.force_login(self.user)

        for endpoint in ('recommend', 'ai_recommendation'):
            response = self.client.post(
                reverse(endpoint),
                {
                    'age': '30',
                    'income': '100000',
                    'category': ' General ',
                    'state': '  maHARashtra  ',
                },
            )
            with self.subTest(endpoint=endpoint):
                recommended = [item['scheme'] for item in response.context['schemes']]
                self.assertIn(scheme, recommended)

    def test_recommendations_support_all_category_and_missing_inputs(self):
        all_category_scheme = Scheme.objects.create(
            scheme_name='All Category Boundary Scheme',
            scheme_type='State',
            state='Test State',
            department='Test Department',
            min_age=25,
            max_age=40,
            income_limit=200000,
            category='All',
        )
        self.client.force_login(self.user)

        for endpoint in ('recommend', 'ai_recommendation'):
            response = self.client.post(
                reverse(endpoint),
                {
                    'age': '30',
                    'income': '100000',
                    'category': 'SC',
                    'state': 'Test State',
                },
            )
            with self.subTest(endpoint=endpoint, case='all-category'):
                recommended = [item['scheme'] for item in response.context['schemes']]
                self.assertIn(all_category_scheme, recommended)

            response = self.client.post(
                reverse(endpoint),
                {
                    'age': '30',
                    'income': '100000',
                    'category': '',
                    'state': '',
                },
            )
            with self.subTest(endpoint=endpoint, case='missing-state-category'):
                recommended = [item['scheme'] for item in response.context['schemes']]
                self.assertIn(all_category_scheme, recommended)

    def test_underage_application_uses_scheme_age_criteria(self):
        youth_scheme = Scheme.objects.create(
            scheme_name='Youth Test Scheme',
            scheme_type='State',
            state='Test State',
            department='Youth Department',
            min_age=16,
            max_age=25,
            category='General',
        )
        self.client.force_login(self.user)

        response = self.client.post(
            f"{reverse('apply_assistance')}?scheme_id={youth_scheme.id}",
            {
                'scheme_id': str(youth_scheme.id),
                'name': 'Young Farmer',
                'age': '16',
                'gender': 'Female',
                'mobile': '9876543210',
                'email': 'young@example.com',
                'education': 'Student',
                'income': '10000',
                'category': 'General',
                'state': 'Test State',
                'district': 'Test District',
            },
        )

        self.assertRedirects(response, reverse('application_status'))
        self.assertTrue(ApplicationRequest.objects.filter(
            user=self.user, scheme=youth_scheme, age=16,
        ).exists())

    def test_export_is_csv_and_requires_staff_role(self):
        self.client.force_login(self.user)
        response = self.client.get(reverse('export_applications'))
        self.assertRedirects(response, reverse('dashboard'))

        profile, _ = UserProfile.objects.get_or_create(user=self.user)
        profile.role = 'admin'
        profile.save(update_fields=['role'])
        response = self.client.get(reverse('export_applications'))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'text/csv')
        self.assertIn('applications.csv', response['Content-Disposition'])
        self.assertIn(
            b'Application ID,Applicant,Scheme,Status,State,District,Application Date',
            response.content,
        )

    def test_recommendation_requires_authentication(self):
        response = self.client.get(reverse('recommend'))

        self.assertRedirects(
            response,
            f"{reverse('login')}?next={reverse('recommend')}",
            fetch_redirect_response=False,
        )


    def test_profile_form_allows_incomplete_profile(self):
        form = UserProfileForm(data={})

        self.assertTrue(form.is_valid())

    def test_profile_requires_authentication(self):
        response = self.client.get(reverse('profile'))

        self.assertRedirects(
            response,
            f"{reverse('login')}?next={reverse('profile')}",
            fetch_redirect_response=False,
        )

    def test_profile_view_saves_incomplete_profile(self):
        self.client.force_login(self.user)

        response = self.client.post(
            reverse('profile'),
            {'username': 'citizen', 'email': ''},
        )

        self.assertRedirects(response, reverse('profile'))
        self.assertTrue(UserProfile.objects.filter(user=self.user).exists())

    def test_profile_completion_uses_exact_22_field_denominator(self):
        self.client.force_login(self.user)
        self.user.email = 'citizen@example.com'
        self.user.save(update_fields=['email'])
        profile, _ = UserProfile.objects.get_or_create(user=self.user)
        profile.phone = '9876543210'
        profile.age = 30
        profile.gender = 'male'
        profile.save(update_fields=['phone', 'age', 'gender'])

        response = self.client.get(reverse('profile'))

        self.assertEqual(response.context['profile_completion'], round(5 / 22 * 100))

    def test_profile_page_exposes_location_data_and_dropdowns(self):
        self.client.force_login(self.user)

        response = self.client.get(reverse('profile'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'id="id_state"', html=False)
        self.assertContains(response, 'id="id_district"', html=False)
        self.assertContains(response, 'id="location-data"', html=False)
        self.assertContains(response, 'Profile completeness')

    def test_profile_post_persists_user_and_location_details(self):
        self.client.force_login(self.user)

        response = self.client.post(
            reverse('profile'),
            {
                'username': 'updated-citizen',
                'email': 'updated@example.com',
                'phone': '9876543210',
                'age': ' thirty',
                'gender': 'male',
                'education': 'graduate',
                'income_range': '1l_3l',
                'category': 'General',
                'state': 'Andhra Pradesh',
                'district': 'Alluri Sitharama Raju',
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Please check the highlighted fields')
        self.user.refresh_from_db()
        self.assertEqual(self.user.username, 'citizen')

        response = self.client.post(
            reverse('profile'),
            {
                'username': 'updated-citizen',
                'email': 'updated@example.com',
                'phone': '9876543210',
                'age': '30',
                'gender': 'male',
                'education': 'graduate',
                'income_range': '1l_3l',
                'category': 'General',
                'state': 'Andhra Pradesh',
                'district': 'Alluri Sitharama Raju',
            },
        )

        self.assertRedirects(response, reverse('profile'))
        self.user.refresh_from_db()
        profile = UserProfile.objects.get(user=self.user)
        self.assertEqual(self.user.username, 'updated-citizen')
        self.assertEqual(profile.state, 'Andhra Pradesh')
        self.assertEqual(profile.district, 'Alluri Sitharama Raju')

    def test_profile_post_persists_optional_farmer_details(self):
        self.client.force_login(self.user)

        response = self.client.post(
            reverse('profile'),
            {
                'username': 'citizen',
                'email': 'citizen@example.com',
                'phone': '9876543210',
                'age': '30',
                'gender': 'male',
                'education': 'graduate',
                'income_range': '1l_3l',
                'category': 'General',
                'state': 'Andhra Pradesh',
                'district': 'Alluri Sitharama Raju',
                'taluka': 'Araku',
                'village_panchayat': 'Paderu',
                'rural_urban': 'rural',
                'pin_code': '531001',
                'full_name': 'Citizen Farmer',
                'family_size': '4',
                'occupation': 'Farmer',
                'landholding_size': '2.50',
                'ownership_type': 'owner',
                'crops_grown': 'Rice',
                'livestock_assets': 'Two cows',
                'farmer_type': 'small',
                'ration_card_type': 'Priority',
            },
        )

        self.assertRedirects(response, reverse('profile'))
        profile = UserProfile.objects.get(user=self.user)
        self.assertEqual(profile.taluka, 'Araku')
        self.assertEqual(profile.village_panchayat, 'Paderu')
        self.assertEqual(profile.rural_urban, 'rural')
        self.assertEqual(profile.pin_code, '531001')
        self.assertEqual(profile.family_size, 4)
        self.assertEqual(profile.occupation, 'Farmer')
        self.assertEqual(str(profile.landholding_size), '2.50')
        self.assertEqual(profile.ownership_type, 'owner')
        self.assertEqual(profile.crops_grown, 'Rice')
        self.assertEqual(profile.livestock_assets, 'Two cows')
        self.assertEqual(profile.farmer_type, 'small')
        self.assertEqual(profile.ration_card_type, 'Priority')

    def test_profile_form_contains_approved_fields_only(self):
        approved_fields = {
            'phone', 'state', 'district', 'age', 'gender', 'education',
            'income_range', 'category', 'taluka', 'village_panchayat',
            'rural_urban', 'pin_code', 'family_size', 'occupation',
            'landholding_size', 'ownership_type', 'crops_grown',
            'livestock_assets', 'farmer_type', 'ration_card_type',
        }
        excluded_fields = {
            'full_name', 'survey_no', 'hissa_no', 'marital_status',
            'disability_status', 'email_notifications',
        }

        self.assertEqual(set(UserProfileForm.base_fields), approved_fields)
        self.assertTrue(excluded_fields.isdisjoint(UserProfileForm.base_fields))

    def test_profile_form_accepts_all_approved_optional_fields(self):
        form = UserProfileForm(data={
            'taluka': 'Araku',
            'village_panchayat': 'Paderu',
            'rural_urban': 'rural',
            'pin_code': '012345',
            'family_size': '4',
            'occupation': 'Farmer',
            'landholding_size': '2.50',
            'ownership_type': 'owner',
            'crops_grown': 'Rice',
            'livestock_assets': 'Two cows',
            'farmer_type': 'small',
            'ration_card_type': 'Priority',
        })

        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.cleaned_data['pin_code'], '012345')

    def test_profile_form_validates_age_boundaries(self):
        for value in ('18', '120'):
            with self.subTest(value=value):
                form = UserProfileForm(data={'age': value})
                self.assertTrue(form.is_valid(), form.errors)

        for value in ('17', '121'):
            with self.subTest(value=value):
                form = UserProfileForm(data={'age': value})
                self.assertFalse(form.is_valid())
                self.assertIn('age', form.errors)

        blank_form = UserProfileForm(data={'age': ''})
        self.assertTrue(blank_form.is_valid(), blank_form.errors)

    def test_profile_form_validates_pin_code(self):
        for value in ('', '531001', '012345'):
            with self.subTest(value=value):
                form = UserProfileForm(data={'pin_code': value})
                self.assertTrue(form.is_valid(), form.errors)

        for value in ('12345', '1234567', '12A456'):
            with self.subTest(value=value):
                form = UserProfileForm(data={'pin_code': value})
                self.assertFalse(form.is_valid())
                self.assertIn('pin_code', form.errors)

    def test_profile_form_validates_family_size(self):
        for value in ('', '1', '4'):
            with self.subTest(value=value):
                form = UserProfileForm(data={'family_size': value})
                self.assertTrue(form.is_valid(), form.errors)

        for value in ('0', '-1'):
            with self.subTest(value=value):
                form = UserProfileForm(data={'family_size': value})
                self.assertFalse(form.is_valid())
                self.assertIn('family_size', form.errors)

    def test_profile_form_validates_landholding_size(self):
        for value in ('', '0', '2.50'):
            with self.subTest(value=value):
                form = UserProfileForm(data={'landholding_size': value})
                self.assertTrue(form.is_valid(), form.errors)

        for value in ('-1', 'not-a-decimal'):
            with self.subTest(value=value):
                form = UserProfileForm(data={'landholding_size': value})
                self.assertFalse(form.is_valid())
                self.assertIn('landholding_size', form.errors)

    def test_profile_form_validates_controlled_choices(self):
        choice_fields = {
            'rural_urban': ('rural', 'urban'),
            'ownership_type': ('owner', 'tenant', 'sharecropper', 'oral_lessee'),
            'farmer_type': ('small', 'medium', 'large', 'landless'),
        }

        for field_name, choices in choice_fields.items():
            for value in choices:
                with self.subTest(field=field_name, value=value):
                    form = UserProfileForm(data={field_name: value})
                    self.assertTrue(form.is_valid(), form.errors)
            with self.subTest(field=field_name, value=''):
                form = UserProfileForm(data={field_name: ''})
                self.assertTrue(form.is_valid(), form.errors)
            with self.subTest(field=field_name, value='invalid'):
                form = UserProfileForm(data={field_name: 'invalid'})
                self.assertFalse(form.is_valid())
                self.assertIn(field_name, form.errors)

    def test_profile_form_enforces_landless_consistency(self):
        for landholding_size in ('', '0'):
            with self.subTest(landholding_size=landholding_size):
                form = UserProfileForm(data={
                    'farmer_type': 'landless',
                    'landholding_size': landholding_size,
                })
                self.assertTrue(form.is_valid(), form.errors)

        landless_with_land = UserProfileForm(data={
            'farmer_type': 'landless',
            'landholding_size': '0.01',
        })
        self.assertFalse(landless_with_land.is_valid())
        self.assertIn('landholding_size', landless_with_land.errors)

        non_landless_with_zero = UserProfileForm(data={
            'farmer_type': 'small',
            'landholding_size': '0',
        })
        self.assertTrue(
            non_landless_with_zero.is_valid(),
            non_landless_with_zero.errors,
        )

    def test_profile_completion_counts_zero_and_ignores_excluded_fields(self):
        self.client.force_login(self.user)
        self.user.email = 'citizen@example.com'
        self.user.save(update_fields=['email'])
        profile, _ = UserProfile.objects.get_or_create(user=self.user)
        profile.phone = '9876543210'
        profile.age = 30
        profile.gender = 'male'
        profile.education = 'graduate'
        profile.income_range = '1l_3l'
        profile.category = 'General'
        profile.state = 'Andhra Pradesh'
        profile.district = 'Alluri Sitharama Raju'
        profile.taluka = 'Araku'
        profile.village_panchayat = 'Paderu'
        profile.rural_urban = 'rural'
        profile.pin_code = '012345'
        profile.family_size = 1
        profile.occupation = 'Farmer'
        profile.landholding_size = 0
        profile.ownership_type = 'owner'
        profile.crops_grown = 'Rice'
        profile.livestock_assets = 'Two cows'
        profile.farmer_type = 'landless'
        profile.ration_card_type = 'Priority'
        profile.email_notifications = False
        profile.full_name = 'Excluded Name'
        profile.survey_no = '12A'
        profile.hissa_no = '3'
        profile.marital_status = 'Married'
        profile.disability_status = 'None'
        profile.save()

        response = self.client.get(reverse('profile'))

        self.assertEqual(response.context['profile_completion'], 100)

    def test_profile_page_renders_approved_fields_once_and_excludes_legacy_fields(self):
        self.client.force_login(self.user)

        response = self.client.get(reverse('profile'))

        approved_fields = (
            'taluka',
            'village_panchayat',
            'rural_urban',
            'pin_code',
            'family_size',
            'occupation',
            'landholding_size',
            'ownership_type',
            'crops_grown',
            'livestock_assets',
            'farmer_type',
            'ration_card_type',
        )
        for field_name in approved_fields:
            with self.subTest(field=field_name):
                self.assertContains(
                    response,
                    f'name="{field_name}"',
                    count=1,
                    html=False,
                )

        excluded_fields = (
            'full_name',
            'survey_no',
            'hissa_no',
            'marital_status',
            'disability_status',
            'email_notifications',
        )
        for field_name in excluded_fields:
            with self.subTest(field=field_name):
                self.assertNotContains(
                    response,
                    f'name="{field_name}"',
                    html=False,
                )

        self.assertContains(response, 'id="id_state"', html=False)
        self.assertContains(response, 'id="id_district"', html=False)
        self.assertContains(response, 'location-data', html=False)
        self.assertContains(response, 'profile-error', html=False)

    def test_application_form_validates_mobile_and_age(self):
        form = CitizenApplicationForm(data={
            'name': 'Test Farmer',
            'age': '-1',
            'gender': 'Other',
            'mobile': '123',
            'email': 'farmer@example.com',
            'education': 'Graduate',
            'income': '100000',
            'category': 'General',
            'state': 'Test State',
            'district': 'Test District',
        })

        self.assertFalse(form.is_valid())
        self.assertIn('mobile', form.errors)
        self.assertIn('age', form.errors)

    def test_scheme_form_rejects_duplicate_and_invalid_age_range(self):
        form = SchemeForm(data={
            'scheme_name': self.central_scheme.scheme_name,
            'scheme_type': self.central_scheme.scheme_type,
            'state': self.central_scheme.state,
            'department': self.central_scheme.department,
            'description': 'Duplicate',
            'benefits': '',
            'eligibility': '',
            'documents_required': '',
            'min_age': '50',
            'max_age': '20',
            'income_limit': '100000',
            'category': 'General',
            'education_required': '',
            'official_website': '',
            'apply_link': '',
        })

        self.assertFalse(form.is_valid())
        self.assertIn('scheme_name', form.errors)
        self.assertIn('max_age', form.errors)

    def test_settings_requires_authentication(self):
        response = self.client.get(reverse('settings'))

        self.assertRedirects(
            response,
            f"{reverse('login')}?next={reverse('settings')}",
            fetch_redirect_response=False,
        )

    def test_settings_save_and_reload_isolated_per_session(self):
        self.client.force_login(self.user)
        response = self.client.post(
            reverse('settings'),
            {
                'language': 'mr',
                'appearance': 'dark',
                'font_size': 'large',
                'sms_alerts': 'on',
                'voice_language': 'hi',
            },
        )

        self.assertEqual(response.status_code, 302)
        response = self.client.get(reverse('settings'))
        self.assertContains(response, 'value="dark" selected')
        self.assertContains(response, 'value="large" selected')
        self.assertContains(response, 'value="hi" selected')
        self.assertContains(response, 'name="sms_alerts" checked')
        self.assertNotContains(response, 'name="email_notifications" checked')

        other_client = self.client.__class__()
        other_user = User.objects.create_user(username='settings-other', password='secret123')
        other_client.force_login(other_user)
        response = other_client.get(reverse('settings'))
        self.assertContains(response, 'value="light" selected')
        self.assertContains(response, 'value="normal" selected')
        self.assertContains(response, 'value="auto" selected')

    def test_settings_supports_telugu_voice_language(self):
        self.client.force_login(self.user)
        response = self.client.post(
            reverse('settings'),
            {
                'language': 'en',
                'appearance': 'light',
                'font_size': 'normal',
                'voice_language': 'te',
            },
        )

        self.assertEqual(response.status_code, 302)
        response = self.client.get(reverse('settings'))
        self.assertContains(response, 'option value="te" selected')


    def test_registration_rejects_weak_password_server_side(self):
        response = self.client.post(
            reverse('register'),
            {
                'username': 'newfarmer',
                'email': 'farmer@example.com',
                'password1': 'password123',
                'password2': 'password123',
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Avoid common passwords')
        self.assertFalse(User.objects.filter(username='newfarmer').exists())

    def test_registration_accepts_strong_password_with_confirmation(self):
        response = self.client.post(
            reverse('register'),
            {
                'username': 'newfarmer',
                'email': 'farmer@example.com',
                'password1': 'Mango!River42',
                'password2': 'Mango!River42',
            },
        )

        self.assertRedirects(response, reverse('login'), fetch_redirect_response=False)
        self.assertTrue(User.objects.filter(username='newfarmer').exists())

    def test_management_templates_render_for_staff_roles(self):
        profile = UserProfile.objects.get(user=self.user)
        profile.role = 'admin'
        profile.save(update_fields=['role'])
        profile.refresh_from_db()
        self.assertEqual(profile.role, 'admin')
        self.user.refresh_from_db()
        self.client.force_login(self.user)

        manage_response = self.client.get(reverse('manage_schemes'))
        self.assertEqual(manage_response.status_code, 200)
        self.assertContains(manage_response, 'Add New Scheme')

        form_response = self.client.get(reverse('add_scheme'))
        self.assertEqual(form_response.status_code, 200)
        self.assertContains(form_response, 'Save scheme')

        application = ApplicationRequest.objects.create(
            user=self.user,
            name='Test Applicant',
            age=30,
            gender='Other',
            mobile='9876543210',
            email='applicant@example.com',
            education='Graduate',
            income=100000,
            category='General',
            state='Test State',
            district='Test District',
        )
        status_response = self.client.get(reverse('update_status', args=[application.id]))
        self.assertEqual(status_response.status_code, 200)
        self.assertContains(status_response, 'New status')

    def test_admin_dashboard_authorizes_staff_roles_and_rejects_citizens(self):
        self.client.force_login(self.user)
        citizen_response = self.client.get(reverse('admin_dashboard'))
        self.assertRedirects(
            citizen_response,
            reverse('dashboard'),
            fetch_redirect_response=False,
        )

        profile = UserProfile.objects.get(user=self.user)
        for role in ('admin', 'volunteer'):
            with self.subTest(role=role):
                profile.role = role
                profile.save(update_fields=['role'])
                self.user.refresh_from_db()
                self.client.force_login(self.user)
                response = self.client.get(reverse('admin_dashboard'))
                self.assertEqual(response.status_code, 200)
                self.assertContains(response, 'Admin Dashboard')

    def test_admin_dashboard_uses_database_counts_and_analytics(self):
        profile = UserProfile.objects.get(user=self.user)
        profile.role = 'admin'
        profile.save(update_fields=['role'])
        self.user.refresh_from_db()
        self.client.force_login(self.user)

        ApplicationRequest.objects.create(
            user=self.user,
            scheme=self.central_scheme,
            name='Approved Applicant',
            age=30,
            gender='Other',
            mobile='9876543210',
            email='approved@example.com',
            education='Graduate',
            income=100000,
            category='General',
            state='India',
            district='Pune',
            status='Approved',
        )
        ApplicationRequest.objects.create(
            user=self.user,
            scheme=self.state_scheme,
            name='Submitted Applicant',
            age=31,
            gender='Other',
            mobile='9123456780',
            email='submitted@example.com',
            education='Graduate',
            income=100000,
            category='General',
            state='Test State',
            district='',
            status='Submitted',
        )

        response = self.client.get(reverse('admin_dashboard'))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['total_applications'], 2)
        self.assertEqual(response.context['pending'], 1)
        self.assertEqual(response.context['under_review'], 0)
        self.assertEqual(response.context['applied'], 0)
        self.assertEqual(response.context['approved'], 1)
        self.assertEqual(response.context['rejected'], 0)
        self.assertEqual(response.context['total_schemes'], 2)
        self.assertEqual(response.context['central_schemes'], 1)
        self.assertEqual(response.context['state_schemes'], 1)
        self.assertEqual(response.context['district_data'][0]['district'], 'Pune')
        self.assertContains(response, 'Admin Analytics')
        self.assertContains(response, 'Approved Applicant')
        self.assertContains(response, 'Central Test Scheme')
        self.assertContains(response, 'Submitted')

    def test_admin_dashboard_status_counts_include_zero_statuses(self):
        profile = UserProfile.objects.get(user=self.user)
        profile.role = 'admin'
        profile.save(update_fields=['role'])
        self.user.refresh_from_db()
        self.client.force_login(self.user)

        ApplicationRequest.objects.create(
            user=self.user,
            scheme=self.central_scheme,
            name='Submitted Applicant',
            age=30,
            gender='Other',
            mobile='9876543210',
            email='submitted@example.com',
            education='Graduate',
            income=100000,
            category='General',
            state='India',
            district='Pune',
            status='Submitted',
        )

        response = self.client.get(reverse('admin_dashboard'))

        self.assertEqual(response.context['status_counts'], {
            'Submitted': 1,
            'Under Review': 0,
            'Applied': 0,
            'Approved': 0,
            'Rejected': 0,
        })
        self.assertContains(response, '<p>Applied</p>', html=False)

    def test_admin_dashboard_groups_applications_by_month(self):
        profile = UserProfile.objects.get(user=self.user)
        profile.role = 'admin'
        profile.save(update_fields=['role'])
        self.user.refresh_from_db()
        self.client.force_login(self.user)

        current_application = ApplicationRequest.objects.create(
            user=self.user,
            scheme=self.central_scheme,
            name='Current Applicant',
            age=30,
            gender='Other',
            mobile='9876543210',
            email='current@example.com',
            education='Graduate',
            income=100000,
            category='General',
            state='India',
            district='Pune',
            status='Submitted',
        )
        previous_application = ApplicationRequest.objects.create(
            user=self.user,
            scheme=self.state_scheme,
            name='Previous Applicant',
            age=31,
            gender='Other',
            mobile='9123456780',
            email='previous@example.com',
            education='Graduate',
            income=100000,
            category='General',
            state='Test State',
            district='Nashik',
            status='Submitted',
        )
        current_month = timezone.now().replace(day=15, hour=12, minute=0, second=0, microsecond=0)
        previous_month = current_month.replace(day=1)
        previous_month = previous_month.replace(
            year=previous_month.year - (previous_month.month == 1),
            month=12 if previous_month.month == 1 else previous_month.month - 1,
        )
        ApplicationRequest.objects.filter(pk=current_application.pk).update(
            created_at=current_month,
        )
        ApplicationRequest.objects.filter(pk=previous_application.pk).update(
            created_at=previous_month,
        )

        response = self.client.get(reverse('admin_dashboard'))

        trend_months = json.loads(response.context['application_trend_months'])
        trend_counts = json.loads(response.context['application_trend_counts'])
        self.assertEqual(trend_months[-1:], [current_month.strftime('%b %Y')])
        self.assertEqual(
            trend_counts[-2:],
            [1, 1],
        )
        self.assertContains(response, 'Application Trends (Last 6 Months)')

    def test_admin_dashboard_ranks_most_applied_schemes_and_excludes_unlinked(self):
        profile = UserProfile.objects.get(user=self.user)
        profile.role = 'admin'
        profile.save(update_fields=['role'])
        self.user.refresh_from_db()
        self.client.force_login(self.user)

        for index in range(2):
            ApplicationRequest.objects.create(
                user=self.user,
                scheme=self.central_scheme,
                name=f'Central Applicant {index}',
                age=30,
                gender='Other',
                mobile=f'987654321{index}',
                email=f'central{index}@example.com',
                education='Graduate',
                income=100000,
                category='General',
                state='India',
                district='Pune',
                status='Submitted',
            )
        ApplicationRequest.objects.create(
            user=self.user,
            scheme=self.state_scheme,
            name='State Applicant',
            age=31,
            gender='Other',
            mobile='9123456780',
            email='state@example.com',
            education='Graduate',
            income=100000,
            category='General',
            state='Test State',
            district='Nashik',
            status='Submitted',
        )
        ApplicationRequest.objects.create(
            user=self.user,
            name='General Assistance Applicant',
            age=32,
            gender='Other',
            mobile='9000000000',
            email='general@example.com',
            education='Graduate',
            income=100000,
            category='General',
            state='India',
            district='Pune',
            status='Submitted',
        )

        response = self.client.get(reverse('admin_dashboard'))

        ranked = list(response.context['most_applied_schemes'])
        self.assertEqual(
            [(item['scheme__scheme_name'], item['total']) for item in ranked],
            [
                ('Central Test Scheme', 2),
                ('State Test Scheme', 1),
            ],
        )
        self.assertContains(response, 'Most Applied Schemes')
        self.assertContains(response, '2 applications')
        self.assertContains(response, '1 application')

    def test_admin_dashboard_handles_empty_application_data(self):
        profile = UserProfile.objects.get(user=self.user)
        profile.role = 'admin'
        profile.save(update_fields=['role'])
        self.user.refresh_from_db()
        self.client.force_login(self.user)

        response = self.client.get(reverse('admin_dashboard'))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['total_applications'], 0)
        self.assertContains(response, 'No applications yet.')
        self.assertContains(response, 'No district data available.')

    def test_farmer_dashboard_uses_current_user_data_and_existing_routes(self):
        application = ApplicationRequest.objects.create(
            user=self.user,
            scheme=self.central_scheme,
            name='Dashboard Applicant',
            age=30,
            gender='Other',
            mobile='9876543210',
            email='dashboard@example.com',
            education='Graduate',
            income=100000,
            category='General',
            state='India',
            district='Pune',
            status='Approved',
        )
        other_user = User.objects.create_user(username='dashboard-other', password='secret123')
        ApplicationRequest.objects.create(
            user=other_user,
            scheme=self.state_scheme,
            name='Other Dashboard Applicant',
            age=31,
            gender='Other',
            mobile='9123456780',
            email='other-dashboard@example.com',
            education='Graduate',
            income=100000,
            category='General',
            state='Test State',
            district='Nashik',
            status='Submitted',
        )

        self.client.force_login(self.user)
        response = self.client.get(reverse('farmer_dashboard'))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['total_applications'], 1)
        self.assertEqual(response.context['approved_applications'], 1)
        self.assertEqual(response.context['pending_review'], 0)
        self.assertContains(response, 'Dashboard Applicant')
        self.assertContains(response, self.central_scheme.scheme_name)
        self.assertContains(response, 'Check Eligibility')
        self.assertContains(response, 'Find Schemes')
        self.assertContains(response, 'Update Profile')
        self.assertNotContains(response, 'Other Dashboard Applicant')
        self.assertEqual(application.user_id, self.user.id)

    def test_farmer_dashboard_redirects_staff_to_admin_dashboard(self):
        profile = UserProfile.objects.get(user=self.user)
        profile.role = 'admin'
        profile.save(update_fields=['role'])
        self.user.refresh_from_db()
        self.client.force_login(self.user)

        response = self.client.get(reverse('farmer_dashboard'))

        self.assertRedirects(response, reverse('admin_dashboard'), fetch_redirect_response=False)

    def test_manage_schemes_requires_authorized_role(self):
        self.client.force_login(self.user)

        for url_name, args in (
            ('manage_schemes', ()),
            ('add_scheme', ()),
            ('edit_scheme', (self.central_scheme.id,)),
        ):
            with self.subTest(url_name=url_name):
                response = self.client.get(reverse(url_name, args=args))
                self.assertRedirects(response, reverse('dashboard'), fetch_redirect_response=False)

        response = self.client.post(
            reverse('delete_scheme', args=[self.central_scheme.id]),
            follow=False,
        )
        self.assertRedirects(response, reverse('dashboard'), fetch_redirect_response=False)
        self.assertTrue(Scheme.objects.filter(pk=self.central_scheme.pk).exists())

    def test_admin_can_create_edit_and_delete_scheme(self):
        profile = UserProfile.objects.get(user=self.user)
        profile.role = 'admin'
        profile.save(update_fields=['role'])
        self.user.refresh_from_db()
        self.client.force_login(self.user)
        scheme_data = {
            'scheme_name': 'Managed Test Scheme',
            'scheme_type': 'State',
            'state': 'Test State',
            'department': 'Test Department',
            'description': 'Scheme description.',
            'benefits': 'Scheme benefits.',
            'eligibility': 'Scheme eligibility.',
            'documents_required': 'Identity proof.',
            'official_website': 'https://example.gov.in/managed',
            'apply_link': 'https://example.gov.in/managed/apply',
            'min_age': 18,
            'max_age': 65,
            'income_limit': 500000,
            'category': 'General',
            'education_required': 'Graduate',
        }

        create_response = self.client.post(reverse('add_scheme'), scheme_data)

        self.assertRedirects(create_response, reverse('manage_schemes'))
        scheme = Scheme.objects.get(scheme_name='Managed Test Scheme')
        self.assertContains(self.client.get(reverse('manage_schemes')), scheme.scheme_name)

        updated_data = {**scheme_data, 'scheme_name': 'Updated Managed Scheme', 'department': 'Updated Department'}
        edit_response = self.client.post(
            reverse('edit_scheme', args=[scheme.id]),
            updated_data,
        )

        self.assertRedirects(edit_response, reverse('manage_schemes'))
        scheme.refresh_from_db()
        self.assertEqual(scheme.scheme_name, 'Updated Managed Scheme')
        self.assertEqual(scheme.department, 'Updated Department')

        delete_response = self.client.post(reverse('delete_scheme', args=[scheme.id]))

        self.assertRedirects(delete_response, reverse('manage_schemes'))
        self.assertFalse(Scheme.objects.filter(pk=scheme.id).exists())

    def test_scheme_detail_displays_existing_scheme_details_and_links(self):
        self.central_scheme.benefits = 'Scheme benefits.'
        self.central_scheme.save(update_fields=['benefits'])
        response = self.client.get(reverse('scheme_detail', args=[self.central_scheme.id]))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'vendor/leaflet/leaflet.css')
        self.assertContains(response, 'vendor/leaflet/leaflet.js')
        self.assertNotContains(response, 'https://unpkg.com/leaflet')
        self.assertContains(response, self.central_scheme.scheme_name)
        self.assertContains(response, self.central_scheme.scheme_type)
        self.assertContains(response, self.central_scheme.state)
        self.assertContains(response, self.central_scheme.department)
        self.assertContains(response, self.central_scheme.eligibility)
        self.assertContains(response, self.central_scheme.benefits)
        self.assertContains(response, self.central_scheme.official_website)

        awareness_response = self.client.get(reverse('scheme_awareness'))
        self.assertContains(awareness_response, self.central_scheme.apply_link)

    @patch('farmers.notification_queue.mail.send_mail', side_effect=RuntimeError('SMTP unavailable'))
    def test_status_update_saves_and_creates_one_notification_when_email_fails(self, send_mail):
        profile = UserProfile.objects.get(user=self.user)
        profile.role = 'admin'
        profile.save(update_fields=['role'])
        self.user.refresh_from_db()
        self.client.force_login(self.user)
        application = ApplicationRequest.objects.create(
            user=self.user,
            name='Test Applicant',
            age=30,
            gender='Other',
            mobile='9876543210',
            email='applicant@example.com',
            education='Graduate',
            income=100000,
            category='General',
            state='Test State',
            district='Test District',
        )

        response = self.client.post(
            reverse('update_status', args=[application.id]),
            {'status': 'Approved', 'notes': 'Approved for testing.'},
        )

        self.assertRedirects(response, reverse('admin_dashboard'), fetch_redirect_response=False)
        application.refresh_from_db()
        self.assertEqual(application.status, 'Approved')
        self.assertEqual(application.notes, 'Approved for testing.')
        self.assertEqual(Notification.objects.filter(user=self.user).count(), 1)
        process_pending_notifications()
        send_mail.assert_called_once()

    @patch('farmers.notification_queue.mail.send_mail')
    def test_application_submission_uses_notification_helper(self, send_mail):
        self.client.force_login(self.user)

        response = self.client.post(
            reverse('apply_assistance'),
            {
                'name': 'Citizen User',
                'age': '30',
                'gender': 'Female',
                'mobile': '9876543210',
                'email': 'citizen@example.com',
                'education': 'Graduate',
                'income': '300000',
                'category': 'General',
                'state': 'Test State',
                'district': 'Test District',
            },
        )

        self.assertRedirects(response, reverse('application_status'))
        application = ApplicationRequest.objects.get(user=self.user)
        notification = Notification.objects.get(user=self.user)
        self.assertEqual(notification.subject, 'Application Submitted')
        self.assertEqual(notification.message, (
            'Your application for government scheme assistance has been '
            'submitted successfully.'
        ))
        send_mail.assert_called_once()
        self.assertEqual(
            send_mail.call_args.kwargs['recipient_list'],
            ['citizen@example.com'],
        )
        self.assertEqual(application.status, 'Submitted')

    @patch('farmers.notification_queue.mail.send_mail')
    def test_admin_scheme_application_uses_notification_helper(self, send_mail):
        profile = UserProfile.objects.get(user=self.user)
        profile.role = 'admin'
        profile.save(update_fields=['role'])
        self.user.refresh_from_db()
        self.client.force_login(self.user)
        application = ApplicationRequest.objects.create(
            user=self.user,
            name='Test Applicant',
            age=30,
            gender='Other',
            mobile='9876543210',
            email='applicant@example.com',
            education='Graduate',
            income=100000,
            category='General',
            state='Test State',
            district='Test District',
        )

        response = self.client.post(
            reverse(
                'apply_scheme_admin',
                args=[application.id, self.central_scheme.id],
            ),
        )

        self.assertRedirects(
            response,
            reverse('admin_dashboard'),
            fetch_redirect_response=False,
        )
        application.refresh_from_db()
        self.assertEqual(application.status, 'Applied')
        notification = Notification.objects.get(user=self.user)
        self.assertEqual(notification.subject, 'Scheme Applied')
        self.assertEqual(
            notification.message,
            'We have applied for Central Test Scheme on your behalf.',
        )
        process_pending_notifications()
        send_mail.assert_called_once()

    def test_admin_scheme_application_rejects_get_without_side_effects(self):
        profile = UserProfile.objects.get(user=self.user)
        profile.role = 'admin'
        profile.save(update_fields=['role'])
        self.user.refresh_from_db()
        self.client.force_login(self.user)
        application = ApplicationRequest.objects.create(
            user=self.user,
            name='Test Applicant',
            age=30,
            gender='Other',
            mobile='9876543210',
            email='applicant@example.com',
            education='Graduate',
            income=100000,
            category='General',
            state='Test State',
            district='Test District',
        )

        response = self.client.get(
            reverse('apply_scheme_admin', args=[application.id, self.central_scheme.id]),
        )

        self.assertEqual(response.status_code, 405)
        application.refresh_from_db()
        self.assertIsNone(application.scheme_id)
        self.assertEqual(application.status, 'Submitted')
        self.assertFalse(Notification.objects.filter(user=self.user).exists())

    @patch('farmers.notification_queue.mail.send_mail')
    def test_admin_scheme_application_does_not_reset_processed_statuses(self, send_mail):
        profile = UserProfile.objects.get(user=self.user)
        profile.role = 'admin'
        profile.save(update_fields=['role'])
        self.user.refresh_from_db()
        self.client.force_login(self.user)

        for status in ('Applied', 'Under Review', 'Approved'):
            with self.subTest(status=status):
                application = ApplicationRequest.objects.create(
                    user=self.user,
                    scheme=self.central_scheme,
                    name='Test Applicant',
                    age=30,
                    gender='Other',
                    mobile='9876543210',
                    email='applicant@example.com',
                    education='Graduate',
                    income=100000,
                    category='General',
                    state='Test State',
                    district='Test District',
                    status=status,
                )

                response = self.client.post(
                    reverse(
                        'apply_scheme_admin',
                        args=[application.id, self.central_scheme.id],
                    ),
                )

                self.assertRedirects(
                    response,
                    reverse('admin_dashboard'),
                    fetch_redirect_response=False,
                )
                application.refresh_from_db()
                self.assertEqual(application.status, status)
                self.assertEqual(
                    Notification.objects.filter(
                        user=self.user,
                        application=application,
                    ).count(),
                    0,
                )

        send_mail.assert_not_called()

    @patch('farmers.notification_queue.mail.send_mail')
    def test_rejected_application_can_be_reapplied_to_same_scheme(self, send_mail):
        profile = UserProfile.objects.get(user=self.user)
        profile.role = 'admin'
        profile.save(update_fields=['role'])
        self.user.refresh_from_db()
        self.client.force_login(self.user)
        application = ApplicationRequest.objects.create(
            user=self.user,
            scheme=self.central_scheme,
            name='Test Applicant',
            age=30,
            gender='Other',
            mobile='9876543210',
            email='applicant@example.com',
            education='Graduate',
            income=100000,
            category='General',
            state='Test State',
            district='Test District',
            status='Rejected',
        )

        response = self.client.post(
            reverse(
                'apply_scheme_admin',
                args=[application.id, self.central_scheme.id],
            ),
        )

        self.assertRedirects(
            response,
            reverse('admin_dashboard'),
            fetch_redirect_response=False,
        )
        application.refresh_from_db()
        self.assertEqual(application.status, 'Applied')
        self.assertEqual(Notification.objects.filter(user=self.user).count(), 1)
        process_pending_notifications()
        send_mail.assert_called_once()

    def test_apply_scheme_admin_csrf_protection(self):
        csrf_client = Client(enforce_csrf_checks=True)
        profile = UserProfile.objects.get(user=self.user)
        profile.role = 'admin'
        profile.save(update_fields=['role'])
        self.user.refresh_from_db()
        csrf_client.force_login(self.user)
        application = ApplicationRequest.objects.create(
            user=self.user,
            name='Test Applicant',
            age=30,
            gender='Other',
            mobile='9876543210',
            email='applicant@example.com',
            education='Graduate',
            income=100000,
            category='General',
            state='Test State',
            district='Test District',
        )
        url = reverse(
            'apply_scheme_admin',
            args=[application.id, self.central_scheme.id],
        )

        response = csrf_client.post(url)
        self.assertEqual(response.status_code, 403)
        application.refresh_from_db()
        self.assertEqual(application.status, 'Submitted')
        self.assertFalse(Notification.objects.filter(user=self.user).exists())

        csrf_client.get(reverse('login'))
        csrf_token = csrf_client.cookies['csrftoken'].value
        response = csrf_client.post(
            url,
            HTTP_X_CSRFTOKEN=csrf_token,
        )
        self.assertRedirects(
            response,
            reverse('admin_dashboard'),
            fetch_redirect_response=False,
        )
        application.refresh_from_db()
        self.assertEqual(application.status, 'Applied')

    def test_admin_scheme_application_requires_authorized_post_user(self):
        application = ApplicationRequest.objects.create(
            user=self.user,
            name='Test Applicant',
            age=30,
            gender='Other',
            mobile='9876543210',
            email='applicant@example.com',
            education='Graduate',
            income=100000,
            category='General',
            state='Test State',
            district='Test District',
        )

        response = self.client.post(
            reverse('apply_scheme_admin', args=[application.id, self.central_scheme.id]),
        )
        self.assertRedirects(
            response,
            f"{reverse('login')}?next={reverse('apply_scheme_admin', args=[application.id, self.central_scheme.id])}",
            fetch_redirect_response=False,
        )

        profile = UserProfile.objects.get(user=self.user)
        profile.role = 'citizen'
        profile.save(update_fields=['role'])
        self.client.force_login(self.user)
        response = self.client.post(
            reverse('apply_scheme_admin', args=[application.id, self.central_scheme.id]),
        )
        self.assertRedirects(response, reverse('dashboard'), fetch_redirect_response=False)
        application.refresh_from_db()
        self.assertEqual(application.status, 'Submitted')

    @patch.dict(os.environ, {}, clear=True)
    def test_security_settings_use_safe_development_defaults(self):
        self.assertFalse(_get_debug_setting())
        self.assertNotEqual(
            _get_secret_key(),
            "django-insecure-m2es_c4rc4tmq6tb-#ct#*_v8^xx_*kl+v+-8_*qmmx#qdiwpr",
        )

    @patch.dict(os.environ, {'DJANGO_DEBUG': 'true'})
    def test_security_settings_allow_explicit_debug_development(self):
        self.assertTrue(_get_debug_setting())

    @patch.dict(
        os.environ,
        {'DJANGO_ENV': 'production', 'DJANGO_DEBUG': 'true'},
        clear=True,
    )
    def test_security_settings_disable_debug_in_production(self):
        self.assertFalse(_get_debug_setting())

    @patch.dict(
        os.environ,
        {'DJANGO_ENV': 'production'},
        clear=True,
    )
    def test_security_settings_require_production_secret(self):
        with self.assertRaisesMessage(
            ImproperlyConfigured,
            'DJANGO_SECRET_KEY must be configured in production.',
        ):
            _get_secret_key()

    def test_official_website_link_has_security_attributes(self):
        response = self.client.get(reverse('scheme_awareness'), {'type': 'Central'})

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'href="https://example.gov.in/central"', html=False)
        self.assertContains(response, 'target="_blank"', html=False)
        self.assertContains(response, 'rel="noopener noreferrer"', html=False)

    def test_missing_official_website_is_not_rendered_as_a_broken_link(self):
        self.central_scheme.official_website = ''
        self.central_scheme.save(update_fields=['official_website'])

        response = self.client.get(reverse('scheme_detail', args=[self.central_scheme.id]))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Official website unavailable')
        self.assertNotContains(response, 'href=""', html=False)

    def test_state_api_rejects_non_http_official_links(self):
        self.central_scheme.official_website = 'javascript:alert(1)'
        self.central_scheme.save(update_fields=['official_website'])

        response = self.client.get(reverse('schemes_api', args=['India']))

        self.assertEqual(response.status_code, 200)
        scheme = next(item for item in response.json() if item['name'] == 'Central Test Scheme')
        self.assertIsNone(scheme['official_website'])
        self.assertEqual(scheme['apply_link'], 'https://example.gov.in/apply')

    def test_rkvy_official_website_uses_ministry_portal(self):
        rkvy_scheme = Scheme.objects.create(
            scheme_name='Rashtriya Krishi Vikas Yojana',
            scheme_type='Central',
            state='India',
            department='Agriculture',
            official_website='https://agriwelfare.gov.in/en/Major',
            apply_link='https://agriwelfare.gov.in/en/Major',
        )

        response = self.client.get(reverse('scheme_detail', args=[rkvy_scheme.id]))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'href="https://agriwelfare.gov.in/en/Major"', html=False)

    def test_map_overview_api_returns_shape_used_by_dashboard(self):
        response = self.client.get(reverse('india_map_overview_api'))

        self.assertEqual(response.status_code, 200)
        self.assertIn('active_states', response.json())
        self.assertIn('top_state', response.json())
        self.assertIn('category_counts', response.json())
        self.assertIn('central_schemes', response.json())
        self.assertIn('state_schemes', response.json())
        self.assertIn('top_states', response.json())

    def test_state_schemes_api_returns_matching_state_and_central_records(self):
        response = self.client.get(reverse('schemes_api', args=['Test-State']))

        self.assertEqual(response.status_code, 200)
        schemes = response.json()
        self.assertEqual({item['name'] for item in schemes}, {
            'Central Test Scheme',
            'State Test Scheme',
        })
        state_scheme = next(item for item in schemes if item['name'] == 'State Test Scheme')
        self.assertEqual(state_scheme['id'], self.state_scheme.id)
        self.assertEqual(state_scheme['scheme_type'], 'State')

    def test_state_schemes_api_returns_central_schemes_for_unknown_state(self):
        response = self.client.get(reverse('schemes_api', args=['Unknown-State']))

        self.assertEqual(response.status_code, 200)
        self.assertEqual([item['name'] for item in response.json()], ['Central Test Scheme'])

    def test_india_map_uses_registered_api_and_directs_to_scheme_voice_controls(self):
        response = self.client.get(reverse('india_map_schemes'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'vendor/leaflet/leaflet.css')
        self.assertContains(response, 'vendor/leaflet/leaflet.js')
        self.assertNotContains(response, 'https://unpkg.com/leaflet')
        self.assertContains(response, 'data-overview-url="/api/india-map/overview/"', html=False)
        self.assertContains(response, 'data-site-language')
        self.assertContains(response, 'language-switcher.js')
        self.assertContains(response, 'select a language and press Listen on the specific scheme')
        self.assertNotContains(response, 'id="audio-play"')
        self.assertNotContains(response, 'tile.openstreetmap.org')

    def test_state_dashboard_uses_registered_scheme_api_and_shared_voice_script(self):
        response = self.client.get(reverse('state_dashboard', args=['Test State']))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'data-state-schemes-url="/api/schemes/__state__/"', html=False)
        self.assertContains(response, 'data-speech-base-url="/api/schemes/0/speech/"', html=False)
        self.assertContains(response, 'scheme-voice.js')
        self.assertNotContains(response, 'tts-proxy')
        self.assertContains(response, 'data-site-language')
        self.assertContains(response, 'data-voice-language')
        self.assertContains(response, 'data-language-code="en"', html=False)
        self.assertContains(response, 'scheme-localization.js')
        self.assertContains(response, 'css/state-dashboard.css')
        self.assertContains(response, 'vendor/chartjs/chart.umd.js')
        self.assertNotContains(response, 'cdn.tailwindcss.com')
        self.assertNotContains(response, 'cdn.jsdelivr.net/npm/chart.js')
        self.assertNotContains(response, 'fonts.googleapis.com')

    def test_base_template_uses_local_offline_frontend_assets(self):
        response = self.client.get(reverse('home'))

        self.assertEqual(response.status_code, 200)
        for asset in (
            'vendor/bootstrap/bootstrap.min.css',
            'vendor/bootstrap/bootstrap.bundle.min.js',
            'vendor/chartjs/chart.umd.js',
            'vendor/fontawesome/all.min.css',
        ):
            self.assertContains(response, asset)
        for external_url in (
            'cdn.jsdelivr.net/npm/bootstrap',
            'cdn.jsdelivr.net/npm/chart.js',
            'cdnjs.cloudflare.com/ajax/libs/font-awesome',
        ):
            self.assertNotContains(response, external_url)

    def test_interactive_map_uses_compiled_local_stylesheet(self):
        rendered = get_template('interactive_india_map.html').render({})

        self.assertIn('css/interactive-india-map.css', rendered)
        self.assertNotIn('cdn.tailwindcss.com', rendered)

    def test_dashboard_and_recommendation_images_are_local(self):
        self.client.force_login(self.user)
        dashboard = self.client.get(reverse('dashboard'))
        recommendation = self.client.get(reverse('ai_recommendation'))

        self.assertEqual(dashboard.status_code, 200)
        self.assertEqual(recommendation.status_code, 200)
        for response in (dashboard, recommendation):
            content = response.content.decode()
            self.assertNotIn('images.unsplash.com', content)
            self.assertNotIn('upload.wikimedia.org', content)
        self.assertContains(dashboard, 'images/gov_emblem.png')
        self.assertContains(dashboard, 'class="india-flag"')
        self.assertContains(dashboard, 'aria-label="Flag of India"')
        self.assertContains(dashboard, 'images/farmer_1.jpg')
        self.assertContains(recommendation, 'images/farmer_1.jpg')
        self.assertContains(recommendation, 'images/farmer_7.jpg')

    def test_language_preference_persists_for_anonymous_user_and_preserves_page_query(self):
        response = self.client.post(
            reverse('set_language'),
            {'language': 'hi', 'next': '/schemes/?type=Central#categories'},
        )

        self.assertRedirects(
            response,
            '/hi/schemes/?type=Central#categories',
            fetch_redirect_response=False,
        )
        self.assertEqual(response.cookies['django_language'].value, 'hi')

        localized_page = self.client.get('/hi/schemes/?type=Central')
        self.assertEqual(localized_page.status_code, 200)
        self.assertContains(localized_page, '<html lang="hi">', html=False)
        self.assertContains(localized_page, '<option value="hi" selected>', html=False)

    def test_language_switching_rejects_external_next_redirects(self):
        response = self.client.post(
            reverse('set_language'),
            {'language': 'mr', 'next': 'https://evil.example/redirect'},
        )

        self.assertRedirects(response, '/mr/', fetch_redirect_response=False)
        self.assertEqual(response.cookies['django_language'].value, 'mr')

    def test_language_switching_rejects_invalid_language_codes(self):
        response = self.client.post(
            reverse('set_language'),
            {'language': 'gu', 'next': '/'},
        )

        self.assertRedirects(response, '/', fetch_redirect_response=False)
        self.assertNotIn('django_language', response.cookies)

    def test_language_selector_uses_csrf_protected_post_form(self):
        response = self.client.get(reverse('scheme_awareness'))

        self.assertContains(response, '<form method="post"', html=False)
        self.assertContains(response, 'name="language"', html=False)
        self.assertContains(response, 'name="next"', html=False)
        self.assertContains(response, 'name="csrfmiddlewaretoken"', html=False)

    def test_language_switcher_only_offers_the_four_supported_languages(self):
        response = self.client.get(reverse('scheme_awareness'))

        self.assertEqual(response.status_code, 200)
        for code in ('en', 'hi', 'mr', 'te'):
            self.assertContains(response, f'<option value="{code}"', html=False)
        for code in ('gu', 'bn', 'ta', 'kn', 'ml', 'pa', 'ur', 'or', 'as', 'ne'):
            self.assertNotContains(response, f'<option value="{code}"', html=False)
        self.assertContains(response, 'language-switcher.js')

    def test_major_pages_render_translated_labels_in_supported_languages(self):
        translations = {
            'hi': ('विवरण', 'आवश्यक दस्तावेज़', 'सभी योजनाएँ'),
            'mr': ('वर्णन', 'आवश्यक कागदपत्रे', 'सर्व योजना'),
            'te': ('వివరణ', 'అవసరమైన పత్రాలు', 'అన్ని పథకాలు'),
        }

        for language, expected in translations.items():
            with self.subTest(language=language):
                urls = (
                    translate_url(reverse('scheme_awareness'), language),
                    translate_url(
                        reverse('scheme_detail', args=[self.central_scheme.id]),
                        language,
                    ),
                    translate_url(reverse('india_map_schemes'), language),
                    translate_url(
                        reverse('state_dashboard', args=['Test State']),
                        language,
                    ),
                )
                responses = [self.client.get(url) for url in urls]
                for response in responses:
                    self.assertEqual(response.status_code, 200)
                    self.assertContains(response, f'<html lang="{language}"', html=False)

                self.assertContains(responses[0], expected[2])
                self.assertContains(responses[1], expected[0])
                self.assertContains(responses[1], expected[1])

    def test_authentication_and_application_pages_render_localized_content(self):
        translations = {
            'hi': ('खाता बनाएं', 'चयनित योजना का विवरण', 'सहायता के लिए आवेदन जमा करें'),
            'mr': ('खाते तयार करा', 'निवडलेल्या योजनेचा तपशील', 'सहाय्यासाठीचा अर्ज सादर करा'),
            'te': ('ఖాతా సృష్టించండి', 'ఎంచుకున్న పథకం వివరాలు', 'సహాయం కోసం దరఖాస్తును సమర్పించండి'),
        }
        self.client.force_login(self.user)

        for language, expected in translations.items():
            with self.subTest(language=language):
                register = self.client.get(
                    translate_url(reverse('register'), language),
                )
                application = self.client.get(
                    translate_url(reverse('apply_assistance'), language),
                    {'scheme_id': self.central_scheme.id},
                )

                self.assertEqual(register.status_code, 200)
                self.assertEqual(application.status_code, 200)
                self.assertContains(register, expected[0])
                self.assertContains(application, expected[1])
                self.assertContains(application, expected[2])

    def test_invalid_password_reset_link_message_is_localized(self):
        messages = {
            'hi': 'पासवर्ड रीसेट लिंक अमान्य है या पहले ही इस्तेमाल किया जा चुका है।',
            'mr': 'पासवर्ड रीसेट दुवा अवैध आहे किंवा आधीच वापरला आहे.',
            'te': 'పాస్‌వర్డ్ రీసెట్ లింక్ చెల్లదు లేదా ఇప్పటికే ఉపయోగించబడింది.',
        }
        reset_url = reverse(
            'password_reset_confirm',
            kwargs={'uidb64': 'invalid', 'token': 'invalid-token'},
        )

        for language, expected_message in messages.items():
            with self.subTest(language=language):
                response = self.client.get(f'/{language}{reset_url}')

                self.assertEqual(response.status_code, 200)
                self.assertContains(response, expected_message)

    def test_dynamic_map_and_audio_placeholders_are_translatable(self):
        expected = {
            'hi': (
                'योजना संबंधी जानकारी और विवरण देखने के लिए कोई राज्य चुनें।',
                'सुनें दबाएँ।',
            ),
            'mr': (
                'योजनांची माहिती व तपशील पाहण्यासाठी राज्य निवडा.',
                'ऐका दाबा.',
            ),
            'te': (
                'పథకాల సమాచారం మరియు వివరాలను చూడటానికి ఒక రాష్ట్రాన్ని ఎంచుకోండి.',
                'వినండి నొక్కండి.',
            ),
        }
        map_url = reverse('india_map_schemes')
        state_dashboard_url = reverse('state_dashboard', args=['Test State'])

        for language, (map_text, audio_text) in expected.items():
            with self.subTest(language=language):
                map_response = self.client.get(f'/{language}{map_url}')
                dashboard_response = self.client.get(
                    f'/{language}{state_dashboard_url}',
                )

                self.assertContains(map_response, map_text)
                self.assertContains(map_response, '{state}')
                self.assertContains(dashboard_response, '{language}')
                self.assertIn(audio_text, dashboard_response.content.decode())

    def test_major_public_and_authenticated_pages_render_in_each_target_language(self):
        self.client.force_login(self.user)
        page_urls = (
            reverse('home'),
            reverse('scheme_awareness'),
            reverse('scheme_detail', args=[self.central_scheme.id]),
            reverse('india_map_schemes'),
            reverse('state_dashboard', args=['Test State']),
            reverse('dashboard'),
            reverse('login'),
            reverse('register'),
            reverse('profile'),
            reverse('apply_assistance'),
            reverse('application_status'),
            reverse('my_apps'),
        )

        for language in ('hi', 'mr', 'te'):
            with self.subTest(language=language):
                for page_url in page_urls:
                    response = self.client.get(
                        f'/{language}{page_url}',
                        {'scheme_id': self.central_scheme.id}
                        if page_url == reverse('apply_assistance')
                        else None,
                    )
                    self.assertEqual(response.status_code, 200, page_url)
                    self.assertIn(
                        f'<html lang="{language}"',
                        response.content.decode(),
                        page_url,
                    )

    def test_voice_language_selector_matches_persisted_website_language(self):
        self.client.post(reverse('set_language'), {'language': 'mr', 'next': '/'})

        response = self.client.get(f'/mr/schemes/{self.central_scheme.id}/')

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, '<html lang="mr">', html=False)
        self.assertContains(response, '<option value="mr" selected>', html=False)
        self.assertContains(response, 'data-site-language')
        self.assertContains(response, 'data-voice-language')

    def test_scheme_translation_api_translates_only_the_public_scheme_fields(self):
        with (
            patch('farmers.views.cache.get', return_value=None),
            patch('farmers.views.cache.set') as cache_set,
            patch(
                'farmers.views._translate_text',
                side_effect=lambda text, language: f'{language}:{text}',
            ) as translate,
        ):
            response = self.client.get(
                reverse('scheme_translation_api'),
                {'scheme_id': self.central_scheme.id, 'lang': 'hi'},
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['fields'], {
            'scheme_name': 'hi:Central Test Scheme',
            'description': 'hi:Central scheme description.',
            'eligibility': 'hi:Eligible citizens.',
            'documents_required': 'hi:Identity proof.',
        })
        self.assertEqual(translate.call_count, 4)
        cache_set.assert_called_once()

    def test_local_translation_catalog_returns_supported_language_text(self):
        expected = {
            'hi': 'पात्रता',
            'mr': 'पात्रता',
            'te': 'అర్హత',
        }
        for language, translated_text in expected.items():
            with self.subTest(language=language):
                translation = lookup_local_translation('Eligibility', language)
                self.assertTrue(translation.available)
                self.assertEqual(translation.text, translated_text)

    def test_local_translation_catalog_preserves_unknown_english_text(self):
        translation = lookup_local_translation('Uncatalogued scheme detail', 'mr')

        self.assertFalse(translation.available)
        self.assertIsNone(translation.text)

    def test_scheme_translation_api_reports_offline_unavailable_translation(self):
        response = self.client.get(
            reverse('scheme_translation_api'),
            {
                'scheme_id': self.central_scheme.id,
                'lang': 'te',
                'offline': '1',
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['translation_status'], 'unavailable')
        self.assertEqual(response.json()['source'], 'local')
        self.assertIn('English text is preserved', response.json()['message'])

    def test_scheme_translation_api_reports_service_failure_without_returning_success(self):
        with (
            patch('farmers.views.cache.get', return_value=None),
            patch(
                'farmers.views._translate_text',
                side_effect=VoiceServiceError('Translation service is unavailable.'),
            ),
        ):
            response = self.client.get(
                reverse('scheme_translation_api'),
                {'scheme_id': self.central_scheme.id, 'lang': 'mr'},
            )

        self.assertEqual(response.status_code, 503)
        self.assertIn('unavailable', response.json()['error'])
        self.assertEqual(response.json()['original_language'], 'en')

    def test_scheme_translation_api_rejects_unsupported_language_and_bad_id(self):
        unsupported_language = self.client.get(
            reverse('scheme_translation_api'),
            {'scheme_id': self.central_scheme.id, 'lang': 'gu'},
        )
        invalid_scheme_id = self.client.get(
            reverse('scheme_translation_api'),
            {'scheme_id': 'not-an-id', 'lang': 'hi'},
        )

        self.assertEqual(unsupported_language.status_code, 400)
        self.assertEqual(invalid_scheme_id.status_code, 400)

    def test_authenticated_language_preference_is_saved_in_cookie(self):
        self.client.login(username='citizen', password='secret123')

        response = self.client.post(
            reverse('set_language'),
            {'language': 'te', 'next': '/dashboard/'},
        )

        self.assertRedirects(response, '/te/dashboard/', fetch_redirect_response=False)
        self.assertEqual(response.cookies['django_language'].value, 'te')

    def test_apply_requires_login_and_redirects_to_login(self):
        response = self.client.get(reverse('apply', args=[self.central_scheme.id]))

        self.assertEqual(response.status_code, 302)
        self.assertRedirects(response, f"/login/?next={reverse('apply', args=[self.central_scheme.id])}")

    def test_login_returns_to_selected_scheme_application(self):
        application_url = f"{reverse('apply_assistance')}?scheme_id={self.central_scheme.id}"

        response = self.client.post(
            reverse('login'),
            {
                'username': 'citizen',
                'password': 'secret123',
                'next': application_url,
            },
        )

        self.assertRedirects(response, application_url)

    def test_admin_site_is_reachable_for_staff_user(self):
        self.user.is_staff = True
        self.user.save(update_fields=['is_staff'])
        self.client.login(username='citizen', password='secret123')

        response = self.client.get(reverse('admin:index'))

        self.assertEqual(response.status_code, 200)

    def test_scheme_pages_send_apply_action_to_smartassist_form(self):
        listing = self.client.get(reverse('scheme_awareness'), {'type': 'Central'})
        detail = self.client.get(reverse('scheme_detail', args=[self.central_scheme.id]))
        application_url = f'{reverse("apply_assistance")}?scheme_id={self.central_scheme.id}'

        self.assertEqual(listing.status_code, 200)
        self.assertContains(
            listing,
            f"handleApplyNow('{self.central_scheme.id}', '{application_url}')",
            html=False,
        )
        self.assertEqual(detail.status_code, 200)
        self.assertContains(detail, f'data-apply-url="{application_url}"', html=False)

    def test_detail_page_has_listen_control_for_current_scheme(self):
        response = self.client.get(reverse('scheme_detail', args=[self.central_scheme.id]))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'id="scheme-listen-button"')
        self.assertContains(response, 'data-scheme-translation-card')
        self.assertContains(response, 'data-scheme-field="eligibility"')
        self.assertContains(response, 'scheme-localization.js')
        self.assertContains(
            response,
            f'data-speech-base-url="/api/schemes/{self.central_scheme.id}/speech/"',
            html=False,
        )
        self.assertContains(response, 'data-scheme-name="Central Test Scheme"')
        self.assertContains(response, 'data-scheme-description="Central scheme description."')
        self.assertContains(response, 'href="/static/css/scheme-platform.css"')
        self.assertContains(response, 'src="/static/js/scheme-platform.js"')

    def test_scheme_voice_audio_translates_only_the_selected_scheme(self):
        with (
            patch('farmers.views.cache.get', return_value=None),
            patch('farmers.views.cache.set'),
            patch('farmers.views._translate_scheme_voice_text', return_value='हिंदी में योजना') as translate,
            patch(
                'farmers.views._synthesize_scheme_voice',
                return_value=b'fake-mp3-audio',
            ) as fetch_audio,
        ):
            response = self.client.get(
                reverse('scheme_voice_audio', args=[self.central_scheme.id]),
                {'lang': 'hi'},
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'audio/mpeg')
        self.assertEqual(response.content, b'fake-mp3-audio')
        source_text = translate.call_args.args[0]
        self.assertEqual(source_text, _scheme_voice_text(self.central_scheme))
        self.assertEqual(
            source_text,
            'Scheme name: Government scheme called Central Test Scheme\n'
            'About this scheme: Central scheme description.\n'
            'Eligibility: Eligible citizens.\n'
            'Required documents: Identity proof.',
        )
        self.assertIn('Central scheme description.', source_text)
        self.assertNotIn('State scheme description.', source_text)
        fetch_audio.assert_called_once_with('हिंदी में योजना', 'hi-IN-SwaraNeural')

    def test_scheme_voice_translation_failure_is_reported(self):
        with (
            patch('farmers.views.cache.get', return_value=None),
            patch('farmers.views._translate_scheme_voice_text', side_effect=VoiceServiceError('Translation quota reached.')),
        ):
            response = self.client.get(
                reverse('scheme_voice_audio', args=[self.central_scheme.id]),
                {'lang': 'mr'},
            )

        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()['error'], 'Translation quota reached.')

    def test_scheme_voice_tts_failure_returns_translated_text_for_browser_fallback(self):
        with (
            patch('farmers.views.cache.get', return_value=None),
            patch('farmers.views._translate_scheme_voice_text', return_value='తెలుగులో పథకం'),
            patch('farmers.views._synthesize_scheme_voice', side_effect=VoiceServiceError('Speech service unavailable.')),
        ):
            response = self.client.get(
                reverse('scheme_voice_audio', args=[self.central_scheme.id]),
                {'lang': 'te'},
            )

        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()['translated_text'], 'తెలుగులో పథకం')
        self.assertEqual(response.json()['language'], 'te')

    def test_english_tts_failure_returns_selected_scheme_text_for_browser_fallback(self):
        with (
            patch('farmers.views.cache.get', return_value=None),
            patch('farmers.views._synthesize_scheme_voice', side_effect=VoiceServiceError('Speech service unavailable.')),
        ):
            response = self.client.get(
                reverse('scheme_voice_audio', args=[self.central_scheme.id]),
                {'lang': 'en'},
            )

        self.assertEqual(response.status_code, 503)
        self.assertEqual(
            response.json()['translated_text'],
            _scheme_voice_text(self.central_scheme),
        )

    def test_chatbot_rejects_oversized_messages(self):
        response = self.client.get(
            reverse('chatbot'),
            {'message': 'x' * 4001},
        )

        self.assertEqual(response.status_code, 413)
        self.assertEqual(
            response.json()['error'],
            'Messages must be 4000 characters or fewer.',
        )

    def test_chatbot_rate_limits_requests_per_client(self):
        with patch('farmers.views.cache.add', return_value=False), patch(
            'farmers.views.cache.incr',
            return_value=21,
        ):
            response = self.client.get(
                reverse('chatbot'),
                {'message': 'hello'},
            )

        self.assertEqual(response.status_code, 429)
        self.assertIn('Too many chatbot requests', response.json()['error'])

    def test_chatbot_accepts_twenty_requests_and_rejects_twenty_first(self):
        with patch(
            'farmers.views._rate_limit_request',
            side_effect=[True] * 20 + [False],
        ):
            responses = [
                self.client.get(reverse('chatbot'), {'message': 'hello', 'mode': 'local'})
                for _ in range(21)
            ]

        self.assertTrue(all(response.status_code == 200 for response in responses[:20]))
        self.assertEqual(responses[20].status_code, 429)

    def test_chatbot_fails_closed_when_cache_is_unavailable(self):
        with patch('farmers.views.cache.add', side_effect=RuntimeError('cache down')):
            response = self.client.get(reverse('chatbot'), {'message': 'hello'})

        self.assertEqual(response.status_code, 503)
        self.assertNotIn('cache down', response.json()['error'])

    def test_chatbot_rejects_oversized_requests(self):
        from farmers.views import _chatbot_request_error

        request = RequestFactory().get(reverse('chatbot'), {'message': 'hello'})
        request.META['CONTENT_LENGTH'] = '16385'

        self.assertEqual(
            _chatbot_request_error(request),
            'Chatbot requests must be 16KB or smaller.',
        )

    def test_transcribe_voice_rejects_unsupported_audio_format(self):
        self.client.force_login(self.user)
        upload = SimpleUploadedFile(
            'voice.exe',
            b'not audio',
            content_type='application/octet-stream',
        )

        response = self.client.post(
            reverse('voice_transcribe'),
            {'audio': upload, 'language': 'te'},
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn('Unsupported audio format', response.json()['error'])

    def test_transcribe_voice_rejects_oversized_audio(self):
        self.client.force_login(self.user)
        upload = SimpleUploadedFile(
            'voice.wav',
            b'x' * (10 * 1024 * 1024 + 1),
            content_type='audio/wav',
        )

        response = self.client.post(reverse('voice_transcribe'), {'audio': upload})

        self.assertEqual(response.status_code, 400)
        self.assertIn('too large', response.json()['error'])

    def test_transcribe_voice_validates_content_before_openai(self):
        self.client.force_login(self.user)
        upload = SimpleUploadedFile(
            'voice.wav',
            b'not audio',
            content_type='audio/wav',
        )
        with patch(
            'farmers.views._validate_audio_content',
            return_value='The uploaded file is not a valid audio recording.',
        ), patch('farmers.views._transcribe_audio_with_openai') as openai_transcribe:
            response = self.client.post(reverse('voice_transcribe'), {'audio': upload})

        self.assertEqual(response.status_code, 400)
        openai_transcribe.assert_not_called()

    def test_transcribe_voice_uses_local_hindi_provider(self):
        self.client.force_login(self.user)
        upload = SimpleUploadedFile(
            'voice.wav', b'audio', content_type='audio/wav'
        )
        with patch.dict(os.environ, {'TRANSCRIPTION_PROVIDER': 'local'}), patch(
            'farmers.views._validate_audio_content',
            return_value='',
        ), patch(
            'farmers.views.transcribe_local_audio',
            return_value='नमस्ते',
        ) as local_transcribe, patch(
            'farmers.views._transcribe_audio_with_openai'
        ) as openai_transcribe, patch(
            'farmers.views._transcribe_audio_without_openai'
        ) as google_transcribe:
            response = self.client.post(
                reverse('voice_transcribe'),
                {'audio': upload, 'language': 'hi'},
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(),
            {
                'transcript': 'नमस्ते',
                'provider': 'vosk',
                'offline': True,
                'language': 'hi',
            },
        )
        local_transcribe.assert_called_once()
        openai_transcribe.assert_not_called()
        google_transcribe.assert_not_called()

    def test_transcribe_voice_uses_local_telugu_provider(self):
        self.client.force_login(self.user)
        upload = SimpleUploadedFile(
            'voice.wav', b'audio', content_type='audio/wav'
        )
        with patch.dict(os.environ, {'TRANSCRIPTION_PROVIDER': 'local'}), patch(
            'farmers.views._validate_audio_content',
            return_value='',
        ), patch(
            'farmers.views.transcribe_local_audio',
            return_value='నమస్కారం',
        ) as local_transcribe:
            response = self.client.post(
                reverse('voice_transcribe'),
                {'audio': upload, 'language': 'te'},
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['provider'], 'vosk')
        self.assertTrue(response.json()['offline'])
        self.assertEqual(response.json()['language'], 'te')
        local_transcribe.assert_called_once()

    def test_transcribe_voice_local_mode_rejects_marathi(self):
        self.client.force_login(self.user)
        upload = SimpleUploadedFile(
            'voice.wav', b'audio', content_type='audio/wav'
        )
        with patch.dict(os.environ, {'TRANSCRIPTION_PROVIDER': 'local'}), patch(
            'farmers.views._validate_audio_content',
            return_value='',
        ), patch('farmers.views.transcribe_local_audio') as local_transcribe:
            response = self.client.post(
                reverse('voice_transcribe'),
                {'audio': upload, 'language': 'mr'},
            )

        self.assertEqual(response.status_code, 400)
        self.assertIn('Hindi and Telugu', response.json()['error'])
        self.assertIn('Marathi', response.json()['error'])
        local_transcribe.assert_not_called()

    def test_transcribe_voice_local_mode_hides_missing_model_details(self):
        self.client.force_login(self.user)
        upload = SimpleUploadedFile(
            'voice.wav', b'audio', content_type='audio/wav'
        )
        with patch.dict(os.environ, {'TRANSCRIPTION_PROVIDER': 'local'}), patch(
            'farmers.views._validate_audio_content',
            return_value='',
        ), patch(
            'farmers.views.transcribe_local_audio',
            side_effect=ModelUnavailableError(
                'missing model at /sensitive/model/path'
            ),
        ):
            response = self.client.post(
                reverse('voice_transcribe'),
                {'audio': upload, 'language': 'hi'},
            )

        self.assertEqual(response.status_code, 503)
        self.assertEqual(
            response.json()['error'],
            'The requested offline transcription model is unavailable.',
        )
        self.assertNotIn('/sensitive/model/path', response.content.decode())

    def test_transcribe_voice_auto_uses_online_fallback_after_local_failure(self):
        self.client.force_login(self.user)
        upload = SimpleUploadedFile(
            'voice.wav', b'audio', content_type='audio/wav'
        )
        with patch.dict(os.environ, {'TRANSCRIPTION_PROVIDER': 'auto'}), patch(
            'farmers.views._validate_audio_content',
            return_value='',
        ), patch(
            'farmers.views.transcribe_local_audio',
            side_effect=ModelUnavailableError('missing'),
        ), patch(
            'farmers.views._transcribe_audio_with_openai',
            return_value='online text',
        ) as openai_transcribe, patch(
            'farmers.views._transcribe_audio_without_openai'
        ) as google_transcribe:
            response = self.client.post(
                reverse('voice_transcribe'),
                {'audio': upload, 'language': 'hi'},
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['provider'], 'openai')
        self.assertFalse(response.json()['offline'])
        openai_transcribe.assert_called_once()
        google_transcribe.assert_not_called()

    def test_transcribe_voice_openai_mode_does_not_use_other_providers(self):
        self.client.force_login(self.user)
        upload = SimpleUploadedFile(
            'voice.wav', b'audio', content_type='audio/wav'
        )
        with patch.dict(os.environ, {'TRANSCRIPTION_PROVIDER': 'openai'}), patch(
            'farmers.views._validate_audio_content',
            return_value='',
        ), patch(
            'farmers.views._transcribe_audio_with_openai',
            return_value='openai text',
        ), patch('farmers.views.transcribe_local_audio') as local_transcribe, patch(
            'farmers.views._transcribe_audio_without_openai'
        ) as google_transcribe:
            response = self.client.post(
                reverse('voice_transcribe'),
                {'audio': upload, 'language': 'te'},
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['provider'], 'openai')
        local_transcribe.assert_not_called()
        google_transcribe.assert_not_called()

    def test_transcribe_voice_google_mode_uses_google_only(self):
        self.client.force_login(self.user)
        upload = SimpleUploadedFile(
            'voice.wav', b'audio', content_type='audio/wav'
        )
        with patch.dict(os.environ, {'TRANSCRIPTION_PROVIDER': 'google'}), patch(
            'farmers.views._validate_audio_content',
            return_value='',
        ), patch('farmers.views.transcribe_local_audio') as local_transcribe, patch(
            'farmers.views._transcribe_audio_with_openai'
        ) as openai_transcribe, patch(
            'farmers.views._transcribe_audio_without_openai',
            return_value=('google text', ''),
        ) as google_transcribe:
            response = self.client.post(
                reverse('voice_transcribe'),
                {'audio': upload, 'language': 'hi'},
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['provider'], 'google')
        self.assertFalse(response.json()['offline'])
        local_transcribe.assert_not_called()
        openai_transcribe.assert_not_called()
        google_transcribe.assert_called_once()

    def test_audio_validation_cleans_up_after_duration_failure(self):
        upload = SimpleUploadedFile('voice.wav', b'not audio', content_type='audio/wav')
        with patch(
            'farmers.views.subprocess.run',
            return_value=type(
                'CompletedProcess',
                (),
                {
                    'returncode': 0,
                    'stderr': b'Duration: 00:06:00.00, start: 0.000000',
                },
            )(),
        ), patch('farmers.views.os.remove') as remove:
            error = _validate_audio_content(upload)

        self.assertIn('5 minutes', error)
        remove.assert_called_once()

    def test_local_vosk_model_paths_support_hindi_and_telugu(self):
        with patch.dict(
            os.environ,
            {
                'SMARTASSIST_VOSK_MODEL_DIR': (
                    '/tmp/smartassist-test-vosk-models'
                )
            },
            clear=False,
        ):
            self.assertEqual(
                get_model_path('hi').as_posix(),
                '/tmp/smartassist-test-vosk-models/hindi/'
                'vosk-model-small-hi-0.22',
            )
            self.assertEqual(
                get_model_path('te').as_posix(),
                '/tmp/smartassist-test-vosk-models/telugu/'
                'vosk-model-small-te-0.42',
            )

    def test_local_vosk_rejects_unsupported_marathi(self):
        with self.assertRaises(UnsupportedLanguageError):
            get_model_path('mr')

    def test_local_vosk_reports_missing_model(self):
        with patch.dict(
            os.environ,
            {'SMARTASSIST_VOSK_MODEL_DIR': '/tmp/does-not-exist'},
            clear=False,
        ):
            with self.assertRaises(ModelUnavailableError):
                _load_model('hi')

    def test_local_vosk_invalid_audio_cleans_up_input_file(self):
        with patch(
            'farmers.transcription.subprocess.run',
            return_value=SimpleNamespace(returncode=1, stderr=b'invalid audio'),
        ), patch(
            'farmers.transcription._ffmpeg_binary',
            return_value='ffmpeg',
        ):
            with self.assertRaises(InvalidAudioError):
                transcribe_audio(
                    SimpleUploadedFile(
                        'voice.wav', b'audio', content_type='audio/wav'
                    ),
                    language='hi',
                )

    def test_telugu_fallback_uses_te_in_locale(self):
        class AudioFile:
            def __init__(self, path):
                self.path = path

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return None

        recognizer = SimpleNamespace(
            record=lambda source: 'audio-data',
            recognize_google=lambda audio, language: language,
        )
        fake_speech_recognition = SimpleNamespace(
            Recognizer=lambda: recognizer,
            AudioFile=AudioFile,
            UnknownValueError=ValueError,
            RequestError=RuntimeError,
        )
        ffmpeg_result = SimpleNamespace(
            returncode=0,
            stderr=b'Duration: 00:00:05.00, start: 0.000000',
        )
        with patch.dict(sys.modules, {'speech_recognition': fake_speech_recognition}), patch(
            'farmers.views.subprocess.run',
            return_value=ffmpeg_result,
        ), patch('farmers.views._ffmpeg_binary', return_value='ffmpeg'):
            text, error = _transcribe_audio_without_openai(
                SimpleUploadedFile('voice.wav', b'audio', content_type='audio/wav'),
                language='te',
            )

        self.assertEqual((text, error), ('te-IN', ''))

    def test_speech_languages_use_matching_edge_neural_voices(self):
        from farmers.views import VOICE_LANGUAGES

        expected_voices = {
            'en': 'en-IN-NeerjaNeural',
            'hi': 'hi-IN-SwaraNeural',
            'mr': 'mr-IN-AarohiNeural',
            'te': 'te-IN-ShrutiNeural',
        }
        for code, voice in expected_voices.items():
            with self.subTest(language=code):
                self.assertEqual(VOICE_LANGUAGES[code][2], voice)

    def test_edge_tts_rate_limit_is_reported_clearly(self):
        rate_limit_error = ClientResponseError(None, (), status=429)
        with patch('farmers.views._stream_edge_speech', side_effect=rate_limit_error):
            with self.assertRaisesMessage(VoiceServiceError, 'rate-limited'):
                _synthesize_scheme_voice('test scheme text', 'hi-IN-SwaraNeural')

    def test_apply_route_redirects_to_scheme_assistance_form(self):
        self.client.login(username='citizen', password='secret123')

        response = self.client.get(reverse('apply', args=[self.central_scheme.id]))

        self.assertRedirects(
            response,
            f"{reverse('apply_assistance')}?scheme_id={self.central_scheme.id}",
        )

    def test_scheme_assistance_form_submits_application_for_selected_scheme(self):
        self.client.login(username='citizen', password='secret123')
        response = self.client.get(
            reverse('apply_assistance'),
            {'scheme_id': self.central_scheme.id},
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Request help applying for Central Test Scheme')
        self.assertContains(response, 'Eligible citizens.')
        self.assertContains(response, 'name="scheme_id"', html=False)
        self.assertContains(response, 'class="form-control"', html=False)

        response = self.client.post(
            f"{reverse('apply_assistance')}?scheme_id={self.central_scheme.id}",
            {
                'scheme_id': str(self.central_scheme.id),
                'name': 'Citizen User',
                'age': '30',
                'gender': 'Female',
                'mobile': '9876543210',
                'email': 'citizen@example.com',
                'education': 'Graduate',
                'income': '300000',
                'category': 'General',
                'state': 'India',
                'district': 'Test District',
            },
        )

        self.assertRedirects(response, reverse('application_status'))
        application = self.client.get(reverse('application_status')).context['applications'].get()
        self.assertEqual(application.scheme, self.central_scheme)
        self.assertEqual(application.name, 'Citizen User')
        self.assertEqual(application.status, 'Submitted')

    @patch('farmers.emails.send_mail')
    def test_active_duplicate_scheme_applications_are_blocked_without_side_effects(
        self,
        send_mail,
    ):
        self.client.login(username='citizen', password='secret123')
        payload = {
            'scheme_id': str(self.central_scheme.id),
            'name': 'Citizen User',
            'age': '30',
            'gender': 'Female',
            'mobile': '9876543210',
            'email': 'citizen@example.com',
            'education': 'Graduate',
            'income': '300000',
            'category': 'General',
            'state': 'India',
            'district': 'Test District',
        }

        for status in ('Submitted', 'Applied', 'Under Review', 'Approved', 'Pending'):
            with self.subTest(status=status):
                existing = ApplicationRequest.objects.create(
                    user=self.user,
                    scheme=self.central_scheme,
                    status=status,
                    name='Existing Farmer',
                    age=30,
                    gender='Female',
                    mobile='9876543210',
                    email='existing@example.com',
                    education='Graduate',
                    income=300000,
                    category='General',
                    state='India',
                    district='Test District',
                )

                response = self.client.post(
                    reverse('apply_assistance'),
                    payload,
                )

                self.assertEqual(response.status_code, 200)
                self.assertIn(
                    'You already have an active application for this scheme.',
                    ' '.join(response.context['form'].non_field_errors()),
                )
                self.assertEqual(
                    ApplicationRequest.objects.filter(
                        user=self.user,
                        scheme=self.central_scheme,
                    ).count(),
                    1,
                )
                self.assertFalse(
                    Notification.objects.filter(user=self.user).exists()
                )
                send_mail.assert_not_called()
                existing.delete()

    @patch('farmers.notification_queue.mail.send_mail')
    def test_rejected_scheme_application_allows_reapplication(self, send_mail):
        self.client.login(username='citizen', password='secret123')
        ApplicationRequest.objects.create(
            user=self.user,
            scheme=self.central_scheme,
            status='Rejected',
            name='Rejected Farmer',
            age=30,
            gender='Female',
            mobile='9876543210',
            email='rejected@example.com',
            education='Graduate',
            income=300000,
            category='General',
            state='India',
            district='Test District',
        )

        response = self.client.post(
            reverse('apply_assistance'),
            {
                'scheme_id': str(self.central_scheme.id),
                'name': 'Citizen User',
                'age': '30',
                'gender': 'Female',
                'mobile': '9876543210',
                'email': 'citizen@example.com',
                'education': 'Graduate',
                'income': '300000',
                'category': 'General',
                'state': 'India',
                'district': 'Test District',
            },
        )

        self.assertRedirects(response, reverse('application_status'))
        self.assertEqual(
            ApplicationRequest.objects.filter(
                user=self.user,
                scheme=self.central_scheme,
            ).count(),
            2,
        )
        self.assertEqual(
            ApplicationRequest.objects.filter(
                user=self.user,
                scheme=self.central_scheme,
                status='Submitted',
            ).count(),
            1,
        )
        self.assertEqual(Notification.objects.filter(user=self.user).count(), 1)
        process_pending_notifications()
        send_mail.assert_called_once()

    def test_invalid_assistance_form_renders_errors_and_preserves_scheme(self):
        self.client.login(username='citizen', password='secret123')

        response = self.client.post(
            f"{reverse('apply_assistance')}?scheme_id={self.central_scheme.id}",
            {'scheme_id': str(self.central_scheme.id), 'name': ''},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['scheme'], self.central_scheme)
        self.assertIn('name', response.context['form'].errors)
        self.assertContains(response, 'Please correct the following errors:')
        self.assertContains(response, 'Central Test Scheme')

    def test_authenticated_user_can_submit_application_and_view_status(self):
        self.client.login(username='citizen', password='secret123')
        response = self.client.post(
            reverse('apply_assistance'),
            {
                'name': 'Citizen User',
                'age': '30',
                'gender': 'Female',
                'mobile': '9876543210',
                'email': 'citizen@example.com',
                'education': 'Graduate',
                'income': '300000',
                'category': 'General',
                'state': 'Test State',
                'district': 'Test District',
            },
        )

        self.assertEqual(response.status_code, 302)
        self.assertRedirects(response, reverse('application_status'))
        application = self.client.get(reverse('application_status')).context['applications'].get()
        self.assertEqual(application.scheme, None)
        self.assertEqual(application.status, 'Submitted')
        self.assertContains(self.client.get(reverse('application_status')), 'Citizen User')
        self.assertEqual(Notification.objects.filter(user=self.user).count(), 1)

    def test_application_status_requires_login(self):
        response = self.client.get(reverse('application_status'))

        self.assertRedirects(
            response,
            f"{reverse('login')}?next={reverse('application_status')}",
            fetch_redirect_response=False,
        )

    def test_application_status_only_shows_current_users_applications(self):
        other_user = User.objects.create_user(username='other-citizen', password='secret123')
        own_application = ApplicationRequest.objects.create(
            user=self.user,
            scheme=self.central_scheme,
            name='Own Applicant',
            age=30,
            gender='Female',
            mobile='9876543210',
            email='own@example.com',
            education='Graduate',
            income=300000,
            category='General',
            state='India',
            district='Own District',
            status='Approved',
        )
        ApplicationRequest.objects.create(
            user=other_user,
            scheme=self.state_scheme,
            name='Other Applicant',
            age=31,
            gender='Male',
            mobile='9123456780',
            email='other@example.com',
            education='Graduate',
            income=250000,
            category='General',
            state='Test State',
            district='Other District',
            status='Rejected',
        )

        self.client.force_login(self.user)
        response = self.client.get(reverse('application_status'))

        self.assertEqual(response.status_code, 200)
        self.assertQuerySetEqual(
            response.context['applications'],
            [own_application],
            transform=lambda application: application,
        )
        self.assertContains(response, 'Central Test Scheme')
        self.assertContains(response, own_application.get_status_display())
        self.assertContains(response, 'Submitted on')
        self.assertContains(response, str(own_application.id))
        self.assertContains(response, 'All Applications')
        self.assertContains(response, 'Under Review')
        for status in ('Submitted', 'Under Review', 'Applied', 'Approved', 'Rejected'):
            self.assertContains(response, f'data-status="{status}"', html=False)
        self.assertContains(response, 'data-application-status="Approved"', html=False)
        self.assertNotContains(response, 'State Test Scheme')
        self.assertNotContains(response, 'Other Applicant')

    def test_application_status_shows_empty_state_without_applications(self):
        self.client.force_login(self.user)

        response = self.client.get(reverse('application_status'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'No Applications Yet')
        self.assertContains(response, 'Apply Now')
        self.assertContains(response, 'All Applications')
        for status in ('Submitted', 'Under Review', 'Applied', 'Approved', 'Rejected'):
            self.assertContains(response, status)

    def test_legacy_pending_counts_as_submitted_and_renders_canonical_status(self):
        application = ApplicationRequest.objects.create(
            user=self.user,
            scheme=self.central_scheme,
            name='Legacy Applicant',
            age=30,
            gender='Other',
            mobile='9876543210',
            email='legacy@example.com',
            education='Graduate',
            income=100000,
            category='General',
            state='India',
            district='Pune',
            status='Pending',
        )
        self.client.force_login(self.user)

        dashboard_response = self.client.get(reverse('farmer_dashboard'))
        self.assertEqual(dashboard_response.context['pending_review'], 1)

        status_response = self.client.get(reverse('application_status'))
        self.assertContains(
            status_response,
            'data-application-status="Submitted"',
            html=False,
        )
        self.assertContains(status_response, 'Submitted')
        self.assertNotContains(status_response, '>Pending<', html=False)
        self.assertEqual(application.get_compatibility_status(), 'Submitted')

    def test_admin_counts_reconcile_legacy_pending_with_total(self):
        profile = UserProfile.objects.get(user=self.user)
        profile.role = 'admin'
        profile.save(update_fields=['role'])
        self.user.refresh_from_db()
        for status in ('Pending', 'Submitted', 'Applied'):
            ApplicationRequest.objects.create(
                user=self.user,
                name=f'{status} Applicant',
                age=30,
                gender='Other',
                mobile='9876543210',
                email=f'{status.lower().replace(" ", "-")}@example.com',
                education='Graduate',
                income=100000,
                category='General',
                state='India',
                district='Pune',
                status=status,
            )

        self.client.force_login(self.user)
        response = self.client.get(reverse('admin_dashboard'))

        self.assertEqual(response.context['total_applications'], 3)
        self.assertEqual(response.context['status_counts']['Submitted'], 2)
        self.assertEqual(response.context['status_counts']['Applied'], 1)
        self.assertEqual(sum(response.context['status_counts'].values()), 3)

    def test_invalid_application_status_is_not_saved(self):
        profile = UserProfile.objects.get(user=self.user)
        profile.role = 'admin'
        profile.save(update_fields=['role'])
        self.user.refresh_from_db()
        application = ApplicationRequest.objects.create(
            user=self.user,
            name='Status Applicant',
            age=30,
            gender='Other',
            mobile='9876543210',
            email='status@example.com',
            education='Graduate',
            income=100000,
            category='General',
            state='India',
            district='Pune',
            status='Submitted',
        )

        self.client.force_login(self.user)
        response = self.client.post(
            reverse('update_status', args=[application.id]),
            {'status': 'Pending', 'notes': 'Invalid legacy update'},
        )

        self.assertRedirects(response, reverse('admin_dashboard'), fetch_redirect_response=False)
        application.refresh_from_db()
        self.assertEqual(application.status, 'Submitted')


class LegacyApplicationStatusMigrationTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='migration-user', password='secret123')

    def _application(self, status):
        return ApplicationRequest.objects.create(
            user=self.user,
            name=f'{status} Applicant',
            age=30,
            gender='Other',
            mobile='9876543210',
            email='migration@example.com',
            education='Graduate',
            income=100000,
            category='General',
            state='India',
            district='Pune',
            status=status,
        )

    def test_migration_changes_only_exact_pending_values(self):
        legacy = self._application('Pending')
        submitted = self._application('Submitted')
        approved = self._application('Approved')
        original_values = {
            legacy.id: (legacy.user_id, legacy.created_at, legacy.notes),
            submitted.id: (submitted.user_id, submitted.created_at, submitted.notes),
            approved.id: (approved.user_id, approved.created_at, approved.notes),
        }

        class Apps:
            @staticmethod
            def get_model(app_label, model_name):
                self.assertEqual((app_label, model_name), ('farmers', 'ApplicationRequest'))
                return ApplicationRequest

        normalize_legacy_pending_status(Apps(), None)

        legacy.refresh_from_db()
        submitted.refresh_from_db()
        approved.refresh_from_db()
        self.assertEqual(legacy.status, 'Submitted')
        self.assertEqual(submitted.status, 'Submitted')
        self.assertEqual(approved.status, 'Approved')
        for application in (legacy, submitted, approved):
            self.assertEqual(
                (application.user_id, application.created_at, application.notes),
                original_values[application.id],
            )


@override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend')
class ApplicationStatusEmailTests(TestCase):
    def setUp(self):
        self.citizen = User.objects.create_user(
            username='email-citizen',
            password='secret123',
            email='farmer@example.com',
        )
        self.admin = User.objects.create_user(
            username='email-admin',
            password='secret123',
            email='admin@example.com',
        )
        self.admin.userprofile.role = 'admin'
        self.admin.userprofile.save(update_fields=['role'])
        self.application = ApplicationRequest.objects.create(
            user=self.citizen,
            name='Email Citizen',
            age=35,
            gender='Female',
            mobile='9876543210',
            email='farmer@example.com',
            education='Graduate',
            income=300000,
            category='General',
            state='India',
            district='Test District',
            status='Submitted',
        )

    def test_approval_sends_email_to_the_applicant(self):
        self.citizen.email = 'registered-farmer@example.com'
        self.citizen.save(update_fields=['email'])
        self.application.email = 'old-application@example.com'
        self.application.save(update_fields=['email'])
        self.client.force_login(self.admin)

        response = self.client.post(
            reverse('update_status', args=[self.application.id]),
            {
                'status': 'Approved',
                'notes': 'Documents need further verification. Internal only.',
                'farmer_message': (
                    'Your application has been approved. Please check your '
                    'application dashboard for further details.'
                ),
            },
        )

        self.assertRedirects(
            response,
            reverse('admin_dashboard'),
            fetch_redirect_response=False,
        )
        self.application.refresh_from_db()
        self.assertEqual(self.application.status, 'Approved')
        self.assertEqual(
            self.application.notes,
            'Documents need further verification. Internal only.',
        )
        self.assertIn('Your application has been approved.', self.application.farmer_message)
        process_pending_notifications()
        self.assertEqual(len(mail.outbox), 1)
        sent = mail.outbox[0]
        self.assertEqual(sent.to, ['registered-farmer@example.com'])
        self.assertNotIn(self.admin.email, sent.to)
        self.assertIn('Approved', sent.subject)
        self.assertIn('Message from SmartAssist Team:', sent.body)
        self.assertIn('Your application has been approved.', sent.body)
        self.assertNotIn('Documents need further verification', sent.body)

        notification = Notification.objects.get(user=self.citizen)
        self.assertEqual(notification.application_id, self.application.id)
        self.assertIn('Your application has been approved.', notification.message)
        self.assertNotIn('Documents need further verification', notification.message)

        self.client.force_login(self.citizen)
        status_response = self.client.get(reverse('application_status'))
        self.assertContains(status_response, 'Your application has been approved.')
        self.assertNotContains(status_response, 'Documents need further verification')

        notification_response = self.client.get(reverse('notifications'))
        self.assertContains(notification_response, 'Your application has been approved.')
        self.assertNotContains(notification_response, 'Documents need further verification')
        self.assertContains(notification_response, 'Status')
        self.assertContains(notification_response, 'General Assistance')
        self.assertContains(notification_response, str(self.application.id))

    def test_application_email_is_fallback_when_account_email_is_missing(self):
        self.citizen.email = ''
        self.citizen.save(update_fields=['email'])
        self.application.email = 'application-fallback@example.com'
        self.application.save(update_fields=['email'])
        self.client.force_login(self.admin)

        self.client.post(
            reverse('update_status', args=[self.application.id]),
            {
                'status': 'Approved',
                'notes': 'Internal rejection review note.',
            },
        )

        process_pending_notifications()
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, ['application-fallback@example.com'])
        self.assertNotIn('Internal rejection review note.', mail.outbox[0].body)
        notification = Notification.objects.get(user=self.citizen)
        self.assertNotIn('Internal rejection review note.', notification.message)

    def test_status_notification_respects_disabled_email_preference(self):
        self.application.email = 'old-application@example.com'
        self.application.save(update_fields=['email'])
        self.citizen.userprofile.email_notifications = False
        self.citizen.userprofile.save(update_fields=['email_notifications'])
        self.client.force_login(self.admin)

        self.client.post(
            reverse('update_status', args=[self.application.id]),
            {'status': 'Approved'},
        )

        self.assertEqual(len(mail.outbox), 0)
        notification = Notification.objects.get(user=self.citizen)
        self.assertFalse(notification.is_sent)
        self.assertIn('disabled', notification.email_error)

    def test_rejection_sends_email_to_the_applicant(self):
        self.client.force_login(self.admin)

        self.client.post(
            reverse('update_status', args=[self.application.id]),
            {
                'status': 'Rejected',
                'notes': 'Income above limit is an internal note.',
                'farmer_message': 'Please review the eligibility requirements and reapply.',
            },
        )

        self.application.refresh_from_db()
        self.assertEqual(self.application.status, 'Rejected')
        process_pending_notifications()
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn('Rejected', mail.outbox[0].subject)
        self.assertIn('Please review the eligibility requirements and reapply.', mail.outbox[0].body)
        self.assertNotIn('Income above limit is an internal note.', mail.outbox[0].body)

    def test_citizen_cannot_update_application_status(self):
        self.client.force_login(self.citizen)

        response = self.client.post(
            reverse('update_status', args=[self.application.id]),
            {'status': 'Approved', 'notes': 'self-approved'},
        )

        self.application.refresh_from_db()
        self.assertEqual(self.application.status, 'Submitted')
        self.assertIsNone(self.application.applied_by)
        self.assertEqual(len(mail.outbox), 0)
        self.assertRedirects(response, reverse('dashboard'), fetch_redirect_response=False)

    def test_status_change_without_email_address_is_stored_without_sending_email(self):
        self.citizen.email = ''
        self.citizen.save(update_fields=['email'])
        self.application.email = ''
        self.application.save(update_fields=['email'])
        self.client.force_login(self.admin)

        self.client.post(
            reverse('update_status', args=[self.application.id]),
            {'status': 'Approved'},
        )

        self.application.refresh_from_db()
        self.assertEqual(self.application.status, 'Approved')
        self.assertEqual(len(mail.outbox), 0)
        self.assertEqual(Notification.objects.filter(user=self.citizen).count(), 1)


class NotificationCenterTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username='notification-user',
            password='secret123',
            email='user@example.com',
        )
        self.other_user = User.objects.create_user(
            username='notification-other',
            password='secret123',
            email='other@example.com',
        )
        self.notification = Notification.objects.create(
            user=self.user,
            notification_type='email',
            subject='Application update',
            message='Your application was received.',
        )
        self.other_notification = Notification.objects.create(
            user=self.other_user,
            notification_type='email',
            subject='Private update',
            message='This belongs to another user.',
        )

    def test_notification_history_requires_authentication(self):
        response = self.client.get(reverse('notifications'))

        self.assertRedirects(
            response,
            f"{reverse('login')}?next={reverse('notifications')}",
            fetch_redirect_response=False,
        )

    def test_notification_history_is_limited_to_current_user(self):
        self.client.force_login(self.user)

        response = self.client.get(reverse('notifications'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Application update')
        self.assertNotContains(response, 'Private update')
        self.assertEqual(response.context['page_obj'].paginator.count, 1)

    def test_user_can_mark_own_notification_read(self):
        self.client.force_login(self.user)

        response = self.client.post(
            reverse('mark_notification_read', args=[self.notification.pk]),
        )

        self.assertRedirects(response, reverse('notifications'))
        self.notification.refresh_from_db()
        self.assertTrue(self.notification.is_read)
        self.assertIsNotNone(self.notification.read_at)

    def test_user_cannot_mark_another_users_notification_read(self):
        self.client.force_login(self.user)

        response = self.client.post(
            reverse('mark_notification_read', args=[self.other_notification.pk]),
        )

        self.assertEqual(response.status_code, 404)
        self.other_notification.refresh_from_db()
        self.assertFalse(self.other_notification.is_read)

    def test_get_cannot_modify_notification_status(self):
        self.client.force_login(self.user)

        response = self.client.get(
            reverse('mark_notification_read', args=[self.notification.pk]),
        )

        self.assertEqual(response.status_code, 405)
        self.notification.refresh_from_db()
        self.assertFalse(self.notification.is_read)

    def test_mark_all_read_affects_only_current_user(self):
        self.client.force_login(self.user)
        another_notification = Notification.objects.create(
            user=self.user,
            notification_type='email',
            subject='Second update',
            message='Another update.',
        )

        response = self.client.post(reverse('mark_all_notifications_read'))

        self.assertRedirects(response, reverse('notifications'))
        self.assertFalse(Notification.objects.filter(
            user=self.user,
            is_read=False,
        ).exists())
        self.other_notification.refresh_from_db()
        self.assertFalse(self.other_notification.is_read)
        another_notification.refresh_from_db()
        self.assertIsNotNone(another_notification.read_at)

    def test_unread_count_is_shown_in_navigation(self):
        self.client.force_login(self.user)

        response = self.client.get(reverse('notifications'))

        self.assertEqual(response.context['unread_notification_count'], 1)
        self.assertContains(response, 'class="sa-notification-count"')

    @patch('farmers.notification_queue.mail.send_mail', return_value=1)
    def test_email_delivery_success_is_recorded(self, send_mail):
        from farmers.emails import notify

        notification = notify(self.user, 'Delivered', 'Message')
        process_notification(notification.pk)

        notification.refresh_from_db()
        self.assertTrue(notification.is_sent)
        self.assertEqual(notification.delivery_status, 'sent')
        self.assertEqual(notification.email_error, '')
        send_mail.assert_called_once()

    @patch('farmers.notification_queue.mail.send_mail', side_effect=RuntimeError('SMTP unavailable'))
    def test_email_delivery_failure_is_recorded_without_raising(self, send_mail):
        from farmers.emails import notify

        notification = notify(self.user, 'Failed', 'Message')
        process_notification(notification.pk)

        notification.refresh_from_db()
        self.assertFalse(notification.is_sent)
        self.assertEqual(notification.email_error, 'SMTP unavailable')
        self.assertEqual(notification.delivery_status, 'failed')
        self.assertEqual(notification.retry_count, 1)
        send_mail.assert_called_once()

    @patch('farmers.notification_queue.mail.send_mail')
    def test_disabled_email_preference_stores_without_sending(self, send_mail):
        from farmers.emails import notify

        UserProfile.objects.filter(user=self.user).update(email_notifications=False)
        notification = notify(self.user, 'In-app only', 'Message')

        notification.refresh_from_db()
        self.assertFalse(notification.is_sent)
        self.assertEqual(
            notification.email_error,
            'Email notifications are disabled in your settings.',
        )
        send_mail.assert_not_called()

    @patch('farmers.notification_queue.mail.send_mail', return_value=1)
    def test_notify_persists_pending_queue_without_smtp_in_request(self, send_mail):
        from farmers.emails import notify

        notification = notify(self.user, 'Queued', 'Message')

        notification.refresh_from_db()
        self.assertEqual(notification.delivery_status, 'pending')
        self.assertFalse(notification.is_sent)
        send_mail.assert_not_called()

    def test_notification_command_supports_dry_run(self):
        from farmers.emails import notify

        notification = notify(self.user, 'Dry run', 'Message')
        with patch('farmers.notification_queue.mail.send_mail') as send_mail:
            call_command('process_notifications', '--dry-run')

        notification.refresh_from_db()
        self.assertEqual(notification.delivery_status, 'pending')
        send_mail.assert_not_called()

    @patch('farmers.notification_queue.mail.send_mail', side_effect=RuntimeError('SMTP unavailable'))
    def test_temporary_failure_is_retryable_with_backoff(self, send_mail):
        from farmers.emails import notify

        notification = notify(self.user, 'Retry', 'Message')
        process_notification(notification.pk)

        notification.refresh_from_db()
        self.assertEqual(notification.delivery_status, 'failed')
        self.assertFalse(notification.is_permanent_failure)
        self.assertIsNotNone(notification.next_attempt_at)
        self.assertEqual(notification.retry_count, 1)

    @patch('farmers.notification_queue.mail.send_mail', side_effect=RuntimeError('SMTP unavailable'))
    def test_maximum_retry_limit_marks_failure_permanent(self, send_mail):
        from farmers.emails import notify

        with patch.dict(os.environ, {'SMARTASSIST_EMAIL_MAX_RETRIES': '2'}):
            notification = notify(self.user, 'Retry limit', 'Message')
            process_notification(notification.pk)
            notification.refresh_from_db()
            notification.next_attempt_at = timezone.now()
            notification.save(update_fields=['next_attempt_at'])
            process_notification(notification.pk)

        notification.refresh_from_db()
        self.assertTrue(notification.is_permanent_failure)
        self.assertEqual(notification.retry_count, 2)
        self.assertIsNone(notification.next_attempt_at)
        self.assertEqual(send_mail.call_count, 2)

    @patch('farmers.notification_queue.mail.send_mail', side_effect=ValueError('invalid recipient'))
    def test_permanent_recipient_failure_is_not_retried(self, send_mail):
        from farmers.emails import notify

        notification = notify(self.user, 'Permanent', 'Message')
        process_notification(notification.pk)
        process_notification(notification.pk)

        notification.refresh_from_db()
        self.assertTrue(notification.is_permanent_failure)
        self.assertEqual(notification.retry_count, 1)
        send_mail.assert_called_once()

    @patch('farmers.notification_queue.mail.send_mail', return_value=1)
    def test_sent_notification_is_not_delivered_twice(self, send_mail):
        from farmers.emails import notify

        notification = notify(self.user, 'Once', 'Message')
        process_pending_notifications()
        process_pending_notifications()

        notification.refresh_from_db()
        self.assertEqual(notification.delivery_status, 'sent')
        send_mail.assert_called_once()

    def test_legacy_reconciliation_preserves_records_and_errors(self):
        legacy_sent = [
            Notification.objects.create(
                user=self.user,
                subject=f'Legacy sent {index}',
                message='Historical message',
                is_sent=True,
                is_legacy_notification=True,
                email_error='historical error',
                last_error='historical queue error',
            )
            for index in range(7)
        ]
        legacy_unsent = [
            Notification.objects.create(
                user=self.user,
                subject=f'Legacy unsent {index}',
                message='Historical message',
                is_sent=False,
                is_legacy_notification=True,
                email_error='historical error',
                last_error='historical queue error',
            )
            for index in range(36)
        ]
        original_ids = set(Notification.objects.values_list('pk', flat=True))

        class HistoricalApps:
            @staticmethod
            def get_model(app_label, model_name):
                self.assertEqual((app_label, model_name), ('farmers', 'Notification'))
                return Notification

        reconcile_legacy_notifications(HistoricalApps(), None)

        self.assertEqual(Notification.objects.count(), len(original_ids))
        self.assertEqual(
            set(Notification.objects.values_list('pk', flat=True)),
            original_ids,
        )
        for notification in legacy_sent:
            notification.refresh_from_db()
            self.assertTrue(notification.is_sent)
            self.assertTrue(notification.is_legacy_notification)
            self.assertEqual(notification.delivery_status, 'sent')
            self.assertFalse(notification.is_permanent_failure)
            self.assertEqual(notification.email_recipient, '')
            self.assertEqual(notification.retry_count, 0)
            self.assertIsNone(notification.delivered_at)
            self.assertIsNone(notification.last_attempt_at)
            self.assertIsNone(notification.next_attempt_at)
            self.assertEqual(notification.email_error, 'historical error')
            self.assertEqual(notification.last_error, 'historical queue error')
        for notification in legacy_unsent:
            notification.refresh_from_db()
            self.assertFalse(notification.is_sent)
            self.assertTrue(notification.is_legacy_notification)
            self.assertEqual(notification.delivery_status, 'failed')
            self.assertTrue(notification.is_permanent_failure)
            self.assertEqual(notification.email_recipient, '')
            self.assertEqual(notification.retry_count, 0)
            self.assertIsNone(notification.delivered_at)
            self.assertIsNone(notification.last_attempt_at)
            self.assertIsNone(notification.next_attempt_at)
            self.assertEqual(notification.email_error, 'historical error')
            self.assertEqual(notification.last_error, 'historical queue error')

    @patch('farmers.notification_queue.mail.send_mail')
    def test_reconciled_legacy_notifications_are_not_sent_again(self, send_mail):
        sent = Notification.objects.create(
            user=self.user,
            subject='Historical sent',
            message='Historical message',
            is_sent=True,
            is_legacy_notification=True,
        )
        unsent = Notification.objects.create(
            user=self.user,
            subject='Historical unsent',
            message='Historical message',
            is_sent=False,
            is_legacy_notification=True,
        )

        class HistoricalApps:
            @staticmethod
            def get_model(app_label, model_name):
                return Notification

        reconcile_legacy_notifications(HistoricalApps(), None)
        results = process_pending_notifications()

        sent.refresh_from_db()
        unsent.refresh_from_db()
        self.assertEqual(results['eligible'], 0)
        self.assertEqual(results['sent'], 0)
        self.assertTrue(sent.is_sent)
        self.assertFalse(unsent.is_sent)
        send_mail.assert_not_called()

    def test_reconciliation_does_not_change_nonlegacy_notifications(self):
        from farmers.emails import notify

        current_sent = Notification.objects.create(
            user=self.user,
            subject='Current sent',
            message='Current message',
            is_sent=True,
            delivery_status='sent',
            delivered_at=timezone.now(),
        )
        current_unsent = notify(self.user, 'Current pending', 'Current message')
        legacy = Notification.objects.create(
            user=self.user,
            subject='Historical',
            message='Historical message',
            is_sent=False,
            is_legacy_notification=True,
        )

        class HistoricalApps:
            @staticmethod
            def get_model(app_label, model_name):
                return Notification

        reconcile_legacy_notifications(HistoricalApps(), None)

        current_sent.refresh_from_db()
        current_unsent.refresh_from_db()
        legacy.refresh_from_db()
        self.assertFalse(current_sent.is_legacy_notification)
        self.assertEqual(current_sent.delivery_status, 'sent')
        self.assertIsNotNone(current_sent.delivered_at)
        self.assertFalse(current_unsent.is_legacy_notification)
        self.assertEqual(current_unsent.delivery_status, 'pending')
        self.assertFalse(current_unsent.is_sent)
        self.assertEqual(legacy.delivery_status, 'failed')
        self.assertTrue(legacy.is_permanent_failure)

    def test_new_notification_remains_pending_and_admin_labels_distinguish_history(self):
        from farmers.emails import notify

        legacy_sent = Notification.objects.create(
            user=self.user,
            subject='Historical sent',
            message='Historical message',
            is_sent=True,
            is_legacy_notification=True,
        )
        legacy_unsent = Notification.objects.create(
            user=self.user,
            subject='Historical unsent',
            message='Historical message',
            is_sent=False,
            is_legacy_notification=True,
        )

        class HistoricalApps:
            @staticmethod
            def get_model(app_label, model_name):
                return Notification

        reconcile_legacy_notifications(HistoricalApps(), None)
        current = notify(self.user, 'Current', 'Current message')

        self.assertEqual(current.delivery_status, 'pending')
        self.assertFalse(current.is_sent)
        self.assertFalse(current.is_legacy_notification)
        self.assertEqual(
            Notification.objects.filter(
                delivery_status='sent',
                delivered_at__isnull=True,
            ).count(),
            1,
        )
        self.assertEqual(
            Notification.objects.filter(
                subject='Historical unsent',
                delivery_status='failed',
                is_permanent_failure=True,
                last_attempt_at__isnull=True,
            ).count(),
            1,
        )

        self.client.force_login(self.user)
        response = self.client.get(reverse('notifications'))
        self.assertContains(response, 'Email marked as sent (historical)')
        self.assertContains(response, 'Email not delivered (historical)')

        profile = UserProfile.objects.get(user=self.user)
        profile.role = 'admin'
        profile.save(update_fields=['role'])
        self.user.refresh_from_db()
        self.client.force_login(self.user)
        response = self.client.get(reverse('admin_dashboard'))
        self.assertEqual(response.context['notification_queue_counts']['sent'], 1)
        self.assertEqual(response.context['notification_queue_counts']['sent_historical'], 1)
        self.assertEqual(response.context['notification_queue_counts']['sent_verified'], 0)

    def test_in_app_notification_is_available_without_email_delivery(self):
        from farmers.emails import notify

        user_without_email = User.objects.create_user(
            username='offline-notification-user',
            password='secret123',
        )
        notification = notify(user_without_email, 'Offline', 'Message')

        self.assertTrue(
            Notification.objects.filter(
                pk=notification.pk,
                subject='Offline',
                message='Message',
            ).exists()
        )
        notification.refresh_from_db()
        self.assertEqual(notification.delivery_status, 'failed')
        self.assertTrue(notification.is_permanent_failure)


class DeploymentSettingsTests(TestCase):
    def test_local_cache_is_used_without_redis_url(self):
        with patch.dict(os.environ, {}, clear=True):
            cache_config = _get_cache_config()

        self.assertEqual(
            cache_config["default"]["BACKEND"],
            "django.core.cache.backends.locmem.LocMemCache",
        )

    def test_production_cache_requires_redis_url(self):
        with patch.dict(os.environ, {"DJANGO_ENV": "production"}, clear=True):
            with self.assertRaisesMessage(
                ImproperlyConfigured,
                "DJANGO_CACHE_URL must be configured in production.",
            ):
                _get_cache_config()

    def test_production_cache_uses_redis_backend(self):
        with patch.dict(
            os.environ,
            {
                "DJANGO_ENV": "production",
                "DJANGO_CACHE_URL": "redis://redis.internal:6379/1",
            },
            clear=True,
        ):
            cache_config = _get_cache_config()

        self.assertEqual(
            cache_config["default"]["BACKEND"],
            "django.core.cache.backends.redis.RedisCache",
        )
        self.assertEqual(
            cache_config["default"]["LOCATION"],
            "redis://redis.internal:6379/1",
        )

    def test_production_cache_rejects_empty_or_whitespace_url(self):
        for cache_url in ("", "   "):
            with self.subTest(cache_url=repr(cache_url)), patch.dict(
                os.environ,
                {"DJANGO_ENV": "production", "DJANGO_CACHE_URL": cache_url},
                clear=True,
            ):
                with self.assertRaises(ImproperlyConfigured):
                    _get_cache_config()

    def test_local_host_defaults_are_preserved(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(
                _get_allowed_hosts(),
                ["localhost", "127.0.0.1", "0.0.0.0", "[::1]", "testserver"],
            )
            self.assertEqual(_get_csrf_trusted_origins(), [])

    def test_production_hosts_and_origins_are_parsed(self):
        with patch.dict(
            os.environ,
            {
                "DJANGO_ENV": "production",
                "DJANGO_ALLOWED_HOSTS": "app.example.com, admin.example.com ",
                "DJANGO_CSRF_TRUSTED_ORIGINS": (
                    "https://app.example.com, https://admin.example.com"
                ),
            },
            clear=True,
        ):
            self.assertEqual(
                _get_allowed_hosts(),
                ["app.example.com", "admin.example.com"],
            )
            self.assertEqual(
                _get_csrf_trusted_origins(),
                ["https://app.example.com", "https://admin.example.com"],
            )

    def test_production_host_configuration_is_required(self):
        with patch.dict(os.environ, {"DJANGO_ENV": "production"}, clear=True):
            with self.assertRaises(ImproperlyConfigured):
                _get_allowed_hosts()
            with self.assertRaises(ImproperlyConfigured):
                _get_csrf_trusted_origins()

    def test_invalid_host_configuration_is_rejected(self):
        with patch.dict(os.environ, {"DJANGO_ALLOWED_HOSTS": "*"}, clear=True):
            with self.assertRaises(ImproperlyConfigured):
                _get_allowed_hosts()

    def test_invalid_csrf_origin_configuration_is_rejected(self):
        with patch.dict(
            os.environ,
            {"DJANGO_CSRF_TRUSTED_ORIGINS": "app.example.com"},
            clear=True,
        ):
            with self.assertRaises(ImproperlyConfigured):
                _get_csrf_trusted_origins()

    def test_security_environment_values_are_validated(self):
        with patch.dict(
            os.environ,
            {
                "DJANGO_SECURE_SSL_REDIRECT": "yes",
                "DJANGO_SECURE_HSTS_SECONDS": "31536000",
                "DJANGO_SECURE_HSTS_INCLUDE_SUBDOMAINS": "false",
                "DJANGO_SECURE_HSTS_PRELOAD": "0",
            },
            clear=True,
        ):
            self.assertTrue(_get_bool_setting("DJANGO_SECURE_SSL_REDIRECT"))
            self.assertEqual(_get_nonnegative_int_setting("DJANGO_SECURE_HSTS_SECONDS"), 31536000)
            self.assertFalse(_get_bool_setting("DJANGO_SECURE_HSTS_INCLUDE_SUBDOMAINS"))
            self.assertFalse(_get_bool_setting("DJANGO_SECURE_HSTS_PRELOAD"))

    def test_invalid_security_environment_values_are_rejected(self):
        with patch.dict(os.environ, {"DJANGO_SECURE_SSL_REDIRECT": "sometimes"}, clear=True):
            with self.assertRaises(ImproperlyConfigured):
                _get_bool_setting("DJANGO_SECURE_SSL_REDIRECT")
        with patch.dict(os.environ, {"DJANGO_SECURE_HSTS_SECONDS": "-1"}, clear=True):
            with self.assertRaises(ImproperlyConfigured):
                _get_nonnegative_int_setting("DJANGO_SECURE_HSTS_SECONDS")
