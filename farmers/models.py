from django.db import models
from django.contrib.auth.models import User
from django.core.mail import send_mail
from django.conf import settings

class UserProfile(models.Model):
    ROLE_CHOICES = [
        ('citizen', 'Citizen'),
        ('volunteer', 'Volunteer'),
        ('admin', 'Admin'),
    ]

    USER_CATEGORY_CHOICES = [
        ('General', 'General'),
        ('OBC', 'OBC'),
        ('SC', 'SC'),
        ('ST', 'ST'),
        ('EWS', 'EWS'),
        ('Minority', 'Minority'),
    ]

    user = models.OneToOneField(User, on_delete=models.CASCADE)
    role = models.CharField(max_length=20, choices=ROLE_CHOICES, default='citizen')
    
    # --- Existing Basic Fields ---
    phone = models.CharField(max_length=15, blank=True, null=True)
    age = models.PositiveIntegerField(blank=True, null=True)
    gender = models.CharField(max_length=10, blank=True, null=True)
    education = models.CharField(max_length=50, blank=True, null=True)
    income_range = models.CharField(max_length=50, blank=True, null=True)
    category = models.CharField(max_length=20, choices=USER_CATEGORY_CHOICES, blank=True, null=True)
    
    # --- Location ---
    state = models.CharField(max_length=100, blank=True, null=True)
    district = models.CharField(max_length=100, blank=True, null=True)
    taluka = models.CharField(max_length=100, blank=True, null=True)
    village_panchayat = models.CharField(max_length=100, blank=True, null=True)
    rural_urban = models.CharField(max_length=20, blank=True, null=True)
    pin_code = models.CharField(max_length=10, blank=True, null=True)

    # --- Personal Details ---
    full_name = models.CharField(max_length=150, blank=True, null=True)
    ration_card_type = models.CharField(max_length=50, blank=True, null=True)
    family_size = models.PositiveIntegerField(blank=True, null=True)
    occupation = models.CharField(max_length=100, blank=True, null=True)
    disability_status = models.CharField(max_length=100, blank=True, null=True)
    marital_status = models.CharField(max_length=50, blank=True, null=True)
    photo = models.ImageField(upload_to='profile_photos/', blank=True, null=True)

    # --- Farm Details ---
    landholding_size = models.DecimalField(max_digits=6, decimal_places=2, blank=True, null=True)
    ownership_type = models.CharField(max_length=50, blank=True, null=True)
    survey_no = models.CharField(max_length=50, blank=True, null=True)
    hissa_no = models.CharField(max_length=50, blank=True, null=True)
    crops_grown = models.CharField(max_length=200, blank=True, null=True)
    livestock_assets = models.TextField(blank=True, null=True)
    farmer_type = models.CharField(max_length=50, blank=True, null=True)

    # --- Banking (DBT) ---
    bank_name = models.CharField(max_length=100, blank=True, null=True)
    account_no = models.CharField(max_length=50, blank=True, null=True)
    ifsc_code = models.CharField(max_length=20, blank=True, null=True)
    aadhaar_seeded = models.BooleanField(default=False)
    upi_id = models.CharField(max_length=100, blank=True, null=True)

    def __str__(self):
        return f"{self.user.username}'s Profile"

    @property
    def get_completeness(self):
        """Calculates profile completeness percentage based on key fields."""
        # These are the critical fields for AI scheme matching
        critical_fields = [
            self.phone, self.age, self.gender, self.education, 
            self.income_range, self.category, self.state, self.district,
            self.full_name, self.landholding_size, self.ownership_type, 
            self.survey_no, self.bank_name, self.account_no, self.ifsc_code, 
            self.photo
        ]
        
        # Count how many are filled (not None and not empty string)
        filled = sum(1 for field in critical_fields if field)
        
        # Calculate percentage
        percentage = int((filled / len(critical_fields)) * 100)
        return percentage


class Scheme(models.Model):
    SCHEME_TYPE_CHOICES = [
        ('Central', 'Central'),
        ('State', 'State'),
    ]
    
    scheme_name = models.CharField(max_length=255)
    description = models.TextField(blank=True, null=True)
    eligibility = models.TextField(blank=True, null=True)
    benefits = models.TextField(blank=True, null=True)
    documents_required = models.TextField(blank=True, null=True)
    
    # Fields used for AI matching
    min_age = models.PositiveIntegerField(default=0)
    max_age = models.PositiveIntegerField(default=100)
    income_limit = models.PositiveIntegerField(default=9999999, help_text="Maximum annual income")
    category = models.CharField(max_length=50, default="All")
    
    # Metadata
    scheme_type = models.CharField(max_length=20, choices=SCHEME_TYPE_CHOICES, default='Central')
    state = models.CharField(max_length=100, blank=True, null=True, help_text="Leave blank if All India")
    department = models.CharField(max_length=255, blank=True, null=True)
    
    # Links
    official_website = models.URLField(blank=True, null=True)
    apply_link = models.URLField(blank=True, null=True)

    def __str__(self):
        return self.scheme_name


class ApplicationRequest(models.Model):
    STATUS_CHOICES = [
        ('Submitted', 'Submitted'),
        ('Under Review', 'Under Review'),
        ('Applied', 'Applied'),
        ('Approved', 'Approved'),
        ('Rejected', 'Rejected'),
    ]

    user = models.ForeignKey(User, on_delete=models.CASCADE)
    scheme = models.ForeignKey(Scheme, on_delete=models.SET_NULL, null=True, blank=True)
    
    # Applicant Details
    name = models.CharField(max_length=150)
    age = models.PositiveIntegerField()
    gender = models.CharField(max_length=10)
    mobile = models.CharField(max_length=15)
    email = models.EmailField(blank=True, null=True)
    education = models.CharField(max_length=50, blank=True, null=True)
    income = models.PositiveIntegerField(blank=True, null=True)
    category = models.CharField(max_length=50, blank=True, null=True)
    state = models.CharField(max_length=100, blank=True, null=True)
    district = models.CharField(max_length=100, blank=True, null=True)
    
    # Admin/Volunteer management
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='Submitted')
    notes = models.TextField(blank=True, null=True)
    applied_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='handled_applications')
    application_number = models.CharField(max_length=50, blank=True, null=True)
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.name} - {self.scheme.scheme_name if self.scheme else 'General'}"


class Notification(models.Model):
    NOTIFICATION_TYPES = [
        ('email', 'Email'),
        ('sms', 'SMS'),
        ('system', 'System'),
    ]

    user = models.ForeignKey(User, on_delete=models.CASCADE)
    notification_type = models.CharField(max_length=20, choices=NOTIFICATION_TYPES, default='system')
    subject = models.CharField(max_length=255)
    message = models.TextField()
    is_read = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    def save(self, *args, **kwargs):
        is_new = self.pk is None
        super().save(*args, **kwargs) # Save to database first

        # If this is a new email notification, send it
        if is_new and self.notification_type == 'email' and self.user.email:
            try:
                send_mail(
                    subject=self.subject,
                    message=self.message,
                    from_email=settings.DEFAULT_FROM_EMAIL,
                    recipient_list=[self.user.email],
                    fail_silently=False, # Set to False so we see errors in terminal
                )
                print(f"✅ Email sent to {self.user.email}")
            except Exception as e:
                print(f"❌ Email failed: {e}")

    def __str__(self):
        return f"{self.subject} - {self.user.username}"