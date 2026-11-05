from django.db import models
from django.contrib.auth.models import User


# -----------------------------
# USER PROFILE MODEL (ENHANCED)
# -----------------------------
class UserProfile(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE)
    role = models.CharField(max_length=20, choices=[
        ('citizen', 'Citizen'),
        ('volunteer', 'Volunteer'),
        ('admin', 'Admin')
    ], default='citizen')
    phone = models.CharField(max_length=15, blank=True, null=True)
    email_notifications = models.BooleanField(default=True)
    state = models.CharField(max_length=100, blank=True, null=True)
    district = models.CharField(max_length=100, blank=True, null=True)
    taluka = models.CharField(max_length=100, blank=True, null=True)
    village_panchayat = models.CharField(max_length=100, blank=True, null=True)
    rural_urban = models.CharField(max_length=20, blank=True, null=True)
    pin_code = models.CharField(max_length=6, blank=True, null=True)
    full_name = models.CharField(max_length=150, blank=True, null=True)
    ration_card_type = models.CharField(max_length=50, blank=True, null=True)
    family_size = models.PositiveIntegerField(blank=True, null=True)
    occupation = models.CharField(max_length=100, blank=True, null=True)
    disability_status = models.CharField(max_length=100, blank=True, null=True)
    marital_status = models.CharField(max_length=50, blank=True, null=True)
    landholding_size = models.DecimalField(
        max_digits=8,
        decimal_places=2,
        blank=True,
        null=True,
    )
    ownership_type = models.CharField(max_length=50, blank=True, null=True)
    survey_no = models.CharField(max_length=50, blank=True, null=True)
    hissa_no = models.CharField(max_length=50, blank=True, null=True)
    crops_grown = models.CharField(max_length=200, blank=True, null=True)
    livestock_assets = models.TextField(blank=True, null=True)
    farmer_type = models.CharField(max_length=50, blank=True, null=True)
    age = models.IntegerField(blank=True, null=True)
    gender = models.CharField(max_length=10, blank=True, null=True)
    education = models.CharField(max_length=100, blank=True, null=True)
    income_range = models.CharField(max_length=50, blank=True, null=True)
    category = models.CharField(max_length=50, blank=True, null=True)  # SC/ST/OBC/General

    def __str__(self):
        return f"{self.user.username}'s profile"


# -----------------------------
# SCHEME MODEL
# -----------------------------
class Scheme(models.Model):
    scheme_name = models.CharField(max_length=255)
    scheme_type = models.CharField(max_length=50, choices=[
        ('Central', 'Central'),
        ('State', 'State')
    ])
    state = models.CharField(max_length=100)
    department = models.CharField(max_length=100)

    # 🔥 DETAILS
    description = models.TextField(blank=True, null=True)
    benefits = models.TextField(blank=True, null=True)
    eligibility = models.TextField(blank=True, null=True)
    documents_required = models.TextField(blank=True, null=True)
    official_website = models.URLField(null=True, blank=True)
    apply_link = models.URLField(null=True, blank=True)

    # 🔥 FILTERING FIELDS
    min_age = models.IntegerField(default=18)
    max_age = models.IntegerField(default=65)
    income_limit = models.IntegerField(default=1000000)
    category = models.CharField(max_length=50, default="All")  # SC/ST/OBC/General/All
    education_required = models.CharField(max_length=100, blank=True, null=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.scheme_name


# -----------------------------
# APPLICATION REQUEST MODEL
# -----------------------------
class ApplicationRequest(models.Model):
    LEGACY_STATUS_ALIASES = {
        'Pending': 'Submitted',
    }

    STATUS_CHOICES = [
        ('Submitted', 'Submitted'),
        ('Under Review', 'Under Review'),
        ('Applied', 'Applied'),
        ('Approved', 'Approved'),
        ('Rejected', 'Rejected'),
    ]

    user = models.ForeignKey(User, on_delete=models.CASCADE)
    scheme = models.ForeignKey(Scheme, on_delete=models.CASCADE, null=True, blank=True)

    # Citizen details (copied for reference)
    name = models.CharField(max_length=100)
    age = models.IntegerField()
    gender = models.CharField(max_length=10)
    mobile = models.CharField(max_length=15)
    email = models.EmailField(blank=True, null=True)
    education = models.CharField(max_length=100)
    income = models.IntegerField()
    category = models.CharField(max_length=50)
    state = models.CharField(max_length=100)
    district = models.CharField(max_length=100)

    # Application details
    applied_by = models.ForeignKey(User, related_name='applied_applications', on_delete=models.SET_NULL, null=True, blank=True)  # Volunteer/Admin
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='Submitted')
    application_number = models.CharField(max_length=100, blank=True, null=True)
    notes = models.TextField(blank=True, null=True)
    farmer_message = models.TextField(blank=True, default='')

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.name} - {self.scheme.scheme_name if self.scheme else 'No Scheme'}"

    def get_compatibility_status(self):
        """Return the canonical status while legacy rows are being migrated."""
        return self.LEGACY_STATUS_ALIASES.get(self.status, self.status)

    def get_status_class(self):
        return {
            'Submitted': 'status-submitted',
            'Under Review': 'status-underreview',
            'Applied': 'status-applied',
            'Approved': 'status-approved',
            'Rejected': 'status-rejected'
        }.get(self.get_compatibility_status(), 'status-submitted')


# -----------------------------
# NOTIFICATION MODEL
# -----------------------------
class Notification(models.Model):
    NOTIFICATION_TYPES = [
        ('email', 'Email'),
        ('sms', 'SMS'),
    ]

    user = models.ForeignKey(User, on_delete=models.CASCADE)
    application = models.ForeignKey(
        ApplicationRequest,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='notifications',
    )
    notification_type = models.CharField(max_length=10, choices=NOTIFICATION_TYPES, default='email')
    subject = models.CharField(max_length=255, blank=True, null=True)
    message = models.TextField()
    sent_at = models.DateTimeField(auto_now_add=True)
    is_sent = models.BooleanField(default=False)



        # Notification tracking
    is_read = models.BooleanField(default=False)
    read_at = models.DateTimeField(null=True, blank=True)
    email_error = models.TextField(blank=True, default='')




    def __str__(self):
        return f"{self.notification_type} to {self.user.username}"
