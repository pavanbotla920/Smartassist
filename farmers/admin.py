from django.contrib import admin
from .models import Scheme, ApplicationRequest, Notification, UserProfile

@admin.register(Scheme)
class SchemeAdmin(admin.ModelAdmin):
    list_display = ('scheme_name', 'scheme_type', 'state', 'category')
    search_fields = ('scheme_name', 'state', 'category')
    list_filter = ('scheme_type', 'category')

@admin.register(ApplicationRequest)
class ApplicationRequestAdmin(admin.ModelAdmin):
    list_display = ('name', 'scheme', 'status', 'created_at')
    search_fields = ('name', 'mobile', 'application_number')
    list_filter = ('status', 'state')

@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    list_display = ('user', 'notification_type', 'subject') # <--- Temporarily removed sent_at and is_sent
    list_filter = ('notification_type',) # <--- Temporarily removed is_sent
    search_fields = ('subject', 'message')
@admin.register(UserProfile)
class UserProfileAdmin(admin.ModelAdmin):
    list_display = ('user', 'role', 'state', 'district', 'phone')
    search_fields = ('user__username', 'phone', 'full_name')
    list_filter = ('role', 'state')