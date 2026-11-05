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
        'is_sent',
        'is_read',
        'email_error',
    )
    search_fields = ('user__username', 'subject', 'message', 'email_error')
    list_filter = ('notification_type', 'is_sent', 'is_read')
    readonly_fields = ('sent_at', 'read_at')


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