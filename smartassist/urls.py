from django.contrib import admin
from django.urls import path
from django.contrib.auth import views as auth_views
from django.conf.urls.i18n import i18n_patterns

from farmers.views import (
    dashboard,
    recommend_schemes,
    apply_scheme,
    my_applications,
    chatbot,
    chatbot_stream,
    transcribe_voice,
    schemes_by_state_api,
    state_schemes_public_api,
    india_map_overview_api,
    india_map_state_analytics_api,
    india_map_schemes,
    state_dashboard,
    scheme_voice_audio,
    scheme_translation_api,
    register,
    profile,
    settings_view,
    home,
    scheme_awareness,
    scheme_detail,
    apply_for_assistance,
    application_status,
    admin_dashboard,
    manage_schemes,
    update_application_status,
    apply_scheme_admin,
    reports,
    set_language,
    logout_user
)

urlpatterns = [
    path('admin/', admin.site.urls),
    path('i18n/setlang/', set_language, name='set_language'),
]

urlpatterns += i18n_patterns(
    # Home
    path('', home, name='home'),

    # Dashboard
    path('dashboard/', dashboard, name='dashboard'),

    # Citizen Pages
    path('schemes/', scheme_awareness, name='scheme_awareness'),
    path('schemes/<int:scheme_id>/', scheme_detail, name='scheme_detail'),
    path('apply/', apply_for_assistance, name='apply_assistance'),
    path('status/', application_status, name='application_status'),

    # Recommendation
    path('recommend/', recommend_schemes, name='recommend'),

    # Apply scheme
    path('apply/<int:scheme_id>/', apply_scheme, name='apply'),

    # My applications
    path('my-applications/', my_applications, name='my_apps'),

    # Auth
    path('login/', auth_views.LoginView.as_view(template_name='login.html'), name='login'),
    path('logout/', logout_user, name='logout'),
    path('register/', register, name='register'),
    path('profile/', profile, name='profile'),
    path('settings/', settings_view, name='settings'),

    # Password Reset
    path('password-reset/', auth_views.PasswordResetView.as_view(template_name='password_reset.html'), name='password_reset'),
    path('password-reset/done/', auth_views.PasswordResetDoneView.as_view(template_name='password_reset_done.html'), name='password_reset_done'),
    path('password-reset-confirm/<uidb64>/<token>/', auth_views.PasswordResetConfirmView.as_view(template_name='password_reset_confirm.html'), name='password_reset_confirm'),
    path('password-reset-complete/', auth_views.PasswordResetCompleteView.as_view(template_name='password_reset_complete.html'), name='password_reset_complete'),

    # Admin/Volunteer
    path('admin-dashboard/', admin_dashboard, name='admin_dashboard'),
    path('manage-schemes/', manage_schemes, name='manage_schemes'),
    path('update-status/<int:app_id>/', update_application_status, name='update_status'),
    path('apply-scheme/<int:app_id>/<int:scheme_id>/', apply_scheme_admin, name='apply_scheme_admin'),
    path('reports/', reports, name='reports'),

    # ✅ CHATBOT (IMPORTANT)
    path('chatbot/', chatbot, name='chatbot'),
    path('chatbot/stream/', chatbot_stream, name='chatbot_stream'),
    path('voice-transcribe/', transcribe_voice, name='voice_transcribe'),

    # API endpoints
    path('api/state-schemes/<str:state_name>/', schemes_by_state_api, name='state_schemes_api'),
    path('api/schemes/<str:state_name>/', state_schemes_public_api, name='schemes_api'),
    path('api/schemes/<int:scheme_id>/speech/', scheme_voice_audio, name='scheme_voice_audio'),
    path('api/scheme-translation/', scheme_translation_api, name='scheme_translation_api'),
    path('api/india-map/overview/', india_map_overview_api, name='india_map_overview_api'),
    path('api/india-map/state/<str:state_name>/', india_map_state_analytics_api, name='india_map_state_analytics_api'),
    path('india-map/', india_map_schemes, name='india_map_schemes'),
    path('state-dashboard/<str:state_name>/', state_dashboard, name='state_dashboard'),

    prefix_default_language=False
)