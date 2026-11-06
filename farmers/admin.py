from django.contrib import admin
from .models import Scheme, ApplicationRequest, Notification, UserProfile


# -----------------------------
# SCHEME ADMIN
# -----------------------------
class SchemeAdmin(admin.ModelAdmin):
    list_display = ('scheme_name', 'scheme_type', 'state', 'department')
    search_fields = ('scheme_name', 'state')
    list_filter = ('scheme_type', 'state')


# -----------------------------
# APPLICATION REQUEST ADMIN
# -----------------------------
class ApplicationRequestAdmin(admin.ModelAdmin):
    list_display = (
        'name',
        'mobile',
        'state',
        'status',
        'application_number',
        'created_at',
    )
    search_fields = ('name', 'mobile', 'application_number', 'notes', 'farmer_message')
    list_filter = ('status', 'state')


# -----------------------------
# NOTIFICATION ADMIN
# -----------------------------
class NotificationAdmin(admin.ModelAdmin):
    list_display = (
        'user',
        'application',
        'notification_type',
        'subject',
        'sent_at',
        'delivery_status',
        'retry_count',
        'is_sent',
        'is_read',
        'email_error_preview',
        'last_error_preview',
    )
    search_fields = ('user__username', 'subject', 'message', 'email_error', 'last_error')
    list_filter = ('notification_type', 'delivery_status', 'is_sent', 'is_read')
    readonly_fields = ('sent_at', 'read_at', 'delivered_at', 'last_attempt_at')

    @staticmethod
    def _error_preview(value):
        value = (value or '').strip()
        return value if len(value) <= 80 else f'{value[:77]}...'

    @admin.display(description='Email error', ordering='email_error', empty_value='-')
    def email_error_preview(self, obj):
        return self._error_preview(obj.email_error)

    @admin.display(description='Last queue error', ordering='last_error', empty_value='-')
    def last_error_preview(self, obj):
        return self._error_preview(obj.last_error)


# -----------------------------
# USER PROFILE ADMIN
# -----------------------------
class UserProfileAdmin(admin.ModelAdmin):
    list_display = ('user', 'role', 'state', 'district', 'category', 'phone')
    search_fields = ('user__username', 'role', 'state', 'district', 'category', 'phone')
    list_filter = ('role', 'state', 'district', 'category')


# REGISTER MODELS
admin.site.register(Scheme, SchemeAdmin)
admin.site.register(ApplicationRequest, ApplicationRequestAdmin)
admin.site.register(Notification, NotificationAdmin)
admin.site.register(UserProfile, UserProfileAdmin)