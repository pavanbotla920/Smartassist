from django.contrib.auth.models import User
from django.test import TestCase, override_settings
from django.urls import reverse, translate_url
from django.utils.translation import deactivate_all
from unittest.mock import patch

from aiohttp import ClientResponseError
from django.core import mail

from farmers.models import ApplicationRequest, Scheme
from farmers.views import VoiceServiceError, _scheme_voice_text, _synthesize_scheme_voice


@override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend')
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

    def test_official_website_link_has_security_attributes(self):
        # The official-site link now lives on the scheme detail page.
        response = self.client.get(reverse('scheme_detail', args=[self.central_scheme.id]))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'href="https://example.gov.in/central"', html=False)
        self.assertContains(response, 'target="_blank"', html=False)
        self.assertContains(response, 'rel="noopener noreferrer"', html=False)

    def test_missing_official_website_is_not_rendered_as_a_broken_link(self):
        self.central_scheme.official_website = ''
        self.central_scheme.save(update_fields=['official_website'])

        response = self.client.get(reverse('scheme_detail', args=[self.central_scheme.id]))

        self.assertEqual(response.status_code, 200)
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

    def test_language_preference_persists_for_anonymous_user_and_preserves_page_query(self):
        response = self.client.get(
            reverse('set_language'),
            {'lang': 'hi', 'next': '/schemes/?type=Central#categories'},
        )

        self.assertRedirects(
            response,
            '/hi/schemes/?type=Central#categories',
            fetch_redirect_response=False,
        )
        self.assertEqual(response.cookies['django_language'].value, 'hi')
        self.assertEqual(response.wsgi_request.session['_language'], 'hi')

        localized_page = self.client.get('/hi/schemes/?type=Central')
        self.assertEqual(localized_page.status_code, 200)
        self.assertContains(localized_page, '<html lang="hi">', html=False)
        self.assertContains(localized_page, '<option value="hi" selected>', html=False)

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
            'hi': ('इस योजना के बारे में', 'आवश्यक दस्तावेज़', 'विवरण देखें'),
            'mr': ('या योजनेबद्दल', 'आवश्यक कागदपत्रे', 'तपशील पहा'),
            'te': ('ఈ పథకం గురించి', 'అవసరమైన పత్రాలు', 'వివరాలను వీక్షించండి'),
        }

        for language, expected in translations.items():
            with self.subTest(language=language):
                urls = (
                    translate_url(reverse('scheme_awareness'), language),
                    translate_url(
                        reverse('scheme_detail', args=[self.central_scheme.id]),
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
            'mr': ('खाते तयार करा', 'निवडलेल्या योजनेचा तपशील', 'मदतीसाठी अर्ज सबमिट करा'),
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
            'hi': 'पासवर्ड रीसेट लिंक अमान्य है या पहले ही उपयोग किया जा चुका है। कृपया एक नया रीसेट लिंक का अनुरोध करें।',
            'mr': 'पासवर्ड रीसेट लिंक अवैध आहे किंवा आधीच वापरली गेली आहे. कृपया नवीन रीसेट लिंकची विनंती करा.',
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

    def test_major_public_and_authenticated_pages_render_in_each_target_language(self):
        self.client.force_login(self.user)
        page_urls = (
            reverse('home'),
            reverse('scheme_awareness'),
            reverse('scheme_detail', args=[self.central_scheme.id]),
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
        self.client.get(reverse('set_language'), {'lang': 'mr', 'next': '/'})

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

    def test_authenticated_language_preference_is_saved_in_session_and_cookie(self):
        self.client.login(username='citizen', password='secret123')

        response = self.client.get(
            reverse('set_language'),
            {'lang': 'te', 'next': '/dashboard/'},
        )

        self.assertRedirects(response, '/te/dashboard/', fetch_redirect_response=False)
        self.assertEqual(response.cookies['django_language'].value, 'te')
        self.assertEqual(response.wsgi_request.session['_language'], 'te')

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
        self.assertContains(listing, f'href="{application_url}"', html=False)
        self.assertEqual(detail.status_code, 200)
        self.assertContains(detail, f'data-apply-url="{application_url}"', html=False)

    def test_detail_page_has_listen_control_for_current_scheme(self):
        response = self.client.get(reverse('scheme_detail', args=[self.central_scheme.id]))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'id="scheme-listen-button"')
        self.assertContains(response, 'data-scheme-translation-card')
        self.assertContains(response, 'data-scheme-field="eligibility"')
        self.assertContains(response, 'scheme-localization.js')
        self.assertContains(response, 'data-speech-base-url="/api/schemes/0/speech/"', html=False)
        self.assertContains(response, 'data-scheme-name="Central Test Scheme"')
        self.assertContains(response, 'data-scheme-description="Central scheme description."')

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
        self.assertContains(response, 'Request help for Central Test Scheme')
        self.assertContains(response, 'Eligible citizens.')
        self.assertContains(response, 'name="scheme_id"', html=False)

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
        self.assertEqual(application.status, 'Pending')

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
        self.assertEqual(application.status, 'Pending')
        self.assertContains(self.client.get(reverse('application_status')), 'Citizen User')


@override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend')
class ApplicationStatusEmailTests(TestCase):
    """Email on status change, and the authorization that must gate it."""

    def setUp(self):
        self.citizen = User.objects.create_user(
            username='citizen_email', password='secret123', email='farmer@example.com',
        )
        self.admin = User.objects.create_user(
            username='admin_email', password='secret123',
        )
        self.admin.userprofile.role = 'admin'
        self.admin.userprofile.save()
        self.application = ApplicationRequest.objects.create(
            user=self.citizen,
            name='Citizen Email',
            age=35,
            gender='Female',
            mobile='9876543210',
            email='farmer@example.com',
            state='India',
            district='Test District',
        )

    def test_approval_sends_email_to_the_applicant(self):
        self.client.force_login(self.admin)

        self.client.post(
            reverse('update_status', args=[self.application.id]),
            {'status': 'Approved', 'notes': 'Documents verified'},
        )

        self.application.refresh_from_db()
        self.assertEqual(self.application.status, 'Approved')
        self.assertEqual(len(mail.outbox), 1)
        sent = mail.outbox[0]
        self.assertIn('farmer@example.com', sent.to)
        self.assertIn('Approved', sent.subject)
        self.assertIn('Documents verified', sent.body)

    def test_rejection_sends_email(self):
        self.client.force_login(self.admin)

        self.client.post(
            reverse('update_status', args=[self.application.id]),
            {'status': 'Rejected', 'notes': 'Income above limit'},
        )

        self.assertEqual(len(mail.outbox), 1)
        self.assertIn('Rejected', mail.outbox[0].subject)

    def test_update_status_page_loads_for_admin(self):
        """Regression: the GET branch must return the form, not None."""
        self.client.force_login(self.admin)

        response = self.client.get(reverse('update_status', args=[self.application.id]))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Update Application Status')

    def test_citizen_cannot_update_application_status(self):
        """Regression: a plain citizen must not approve their own application."""
        self.client.force_login(self.citizen)

        response = self.client.post(
            reverse('update_status', args=[self.application.id]),
            {'status': 'Approved', 'notes': 'self-approved'},
        )

        self.application.refresh_from_db()
        self.assertNotEqual(self.application.status, 'Approved')
        self.assertEqual(len(mail.outbox), 0)
        self.assertRedirects(response, reverse('dashboard'))

    def test_no_email_is_sent_when_no_address_is_on_file(self):
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
