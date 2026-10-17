import re
from django import forms
from django.contrib.auth.models import User
from django.contrib.auth.forms import UserCreationForm
from django.core.exceptions import ValidationError
from .models import UserProfile, Scheme, ApplicationRequest
from .password_validator import validate as validate_password
from .location_data import get_state_choices

# --- Validation Helpers ---
def validate_phone(value):
    if not re.match(r'^\d{10}$', value):
        raise ValidationError('Phone number must be exactly 10 digits.')

def validate_alphabetic(value):
    if not re.match(r'^[a-zA-Z\s]+$', value):
        raise ValidationError('This field must contain only alphabets and spaces.')

def validate_ifsc(value):
    if not re.match(r'^[A-Z]{4}0[A-Z0-9]{6}$', value):
        raise ValidationError('Enter a valid IFSC code (e.g., SBIN0001234).')

def validate_account_no(value):
    if not re.match(r'^\d{9,18}$', value):
        raise ValidationError('Account number must be between 9 and 18 digits.')

# --- Auth Forms ---
class UserRegisterForm(UserCreationForm):
    email = forms.EmailField()
    class Meta:
        model = User
        fields = ['username', 'email', 'password1']
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields.pop('password2', None)
        for field in self.fields.values():
            field.help_text = ''
    def clean_password1(self):
        password = self.cleaned_data.get('password1')
        username = self.cleaned_data.get('username', '')
        email = self.cleaned_data.get('email', '')
        if password:
            result = validate_password(password, username=username, email=email)
            if not result['accepted']:
                for reason in result['reasons']:
                    self.add_error('password1', reason)
        return password

class UserUpdateForm(forms.ModelForm):
    email = forms.EmailField()
    class Meta:
        model = User
        fields = ['username', 'email']

# --- Profile Form (Expanded) ---
class UserProfileForm(forms.ModelForm):
    # Dropdown Choices
    GENDER_CHOICES = [('', 'Select...'), ('male', 'Male'), ('female', 'Female'), ('other', 'Other')]
    EDUCATION_CHOICES = [('', 'Select...'), ('none', 'No Formal Education'), ('primary', 'Primary'), ('secondary', 'Secondary'), ('higher_secondary', 'Higher Secondary'), ('graduate', 'Graduate'), ('postgraduate', 'Post Graduate')]
    INCOME_CHOICES = [('', 'Select...'), ('below_1l', 'Below ₹1 Lakh'), ('1l_3l', '₹1L - ₹3L'), ('3l_5l', '₹3L - ₹5L'), ('above_5l', 'Above ₹5L')]
    CATEGORY_CHOICES = [('', 'Select...'), ('General', 'General'), ('OBC', 'OBC'), ('SC', 'SC'), ('ST', 'ST'), ('EWS', 'EWS'), ('Minority', 'Minority')]
    RATION_CHOICES = [('', 'Select...'), ('antyodaya', 'Antyodaya'), ('phh', 'PHH'), ('apl', 'APL'), ('none', 'None')]
    MARITAL_CHOICES = [('', 'Select...'), ('single', 'Single'), ('married', 'Married'), ('widowed', 'Widowed'), ('divorced', 'Divorced')]
    DISABILITY_CHOICES = [('', 'Select...'), ('none', 'None'), ('locomotor', 'Locomotor'), ('visual', 'Visual'), ('hearing', 'Hearing'), ('other', 'Other')]
    OWNERSHIP_CHOICES = [('', 'Select...'), ('owner', 'Owner'), ('tenant', 'Tenant'), ('sharecropper', 'Sharecropper'), ('oral_lessee', 'Oral Lessee')]
    RURAL_URBAN_CHOICES = [('', 'Select...'), ('rural', 'Rural'), ('urban', 'Urban')]
    FARMER_TYPE_CHOICES = [('', 'Select...'), ('small', 'Small & Marginal'), ('medium', 'Medium'), ('large', 'Large'), ('landless', 'Landless')]

    # Overrides
    phone = forms.CharField(widget=forms.TextInput(attrs={'type': 'tel', 'maxlength': '10'}), required=True)
    age = forms.IntegerField(widget=forms.NumberInput(attrs={'min': '18', 'max': '100'}), required=True)
    full_name = forms.CharField(required=True)
    gender = forms.ChoiceField(choices=GENDER_CHOICES, required=True)
    education = forms.ChoiceField(choices=EDUCATION_CHOICES, required=True)
    income_range = forms.ChoiceField(choices=INCOME_CHOICES, required=True)
    category = forms.ChoiceField(choices=CATEGORY_CHOICES, required=True)
    
    state = forms.ChoiceField(choices=get_state_choices(), required=True)
    district = forms.CharField(widget=forms.Select(attrs={'id': 'id_district'}), required=True)

    # Fields you requested to match exactly (standard fields)
    ration_card_type = forms.ChoiceField(choices=RATION_CHOICES, required=False)
    family_size = forms.IntegerField(required=False, min_value=1)
    occupation = forms.CharField(required=False)
    disability_status = forms.ChoiceField(choices=DISABILITY_CHOICES, required=False)
    marital_status = forms.ChoiceField(choices=MARITAL_CHOICES, required=False)
    rural_urban = forms.ChoiceField(choices=RURAL_URBAN_CHOICES, required=False)
    ownership_type = forms.ChoiceField(choices=OWNERSHIP_CHOICES, required=False)
    landholding_size = forms.DecimalField(required=False, min_value=0, widget=forms.NumberInput(attrs={'step': '0.1'}))
    survey_no = forms.CharField(required=False)
    hissa_no = forms.CharField(required=False)
    crops_grown = forms.CharField(required=False)
    livestock_assets = forms.CharField(required=False)
    bank_name = forms.CharField(required=False)
    account_no = forms.CharField(required=False)
    ifsc_code = forms.CharField(required=False)
    aadhaar_seeded = forms.BooleanField(required=False)
    upi_id = forms.CharField(required=False)
    farmer_type = forms.ChoiceField(choices=FARMER_TYPE_CHOICES, required=False)
    pin_code = forms.CharField(required=False, max_length=6)
    taluka = forms.CharField(required=False)
    village_panchayat = forms.CharField(required=False)

    class Meta:
        model = UserProfile
        fields = '__all__'
        exclude = ['user', 'role']

    # --- Validation ---
    def clean_phone(self):
        phone = self.cleaned_data.get('phone')
        validate_phone(phone)
        return phone

    def clean_age(self):
        age = self.cleaned_data.get('age')
        if age and (age < 18 or age > 100):
            raise ValidationError('Age must be between 18 and 100.')
        return age

    def clean_full_name(self):
        name = self.cleaned_data.get('full_name')
        validate_alphabetic(name)
        return name

    def clean_ifsc_code(self):
        ifsc = self.cleaned_data.get('ifsc_code')
        if ifsc:
            validate_ifsc(ifsc)
        return ifsc

    def clean_account_no(self):
        acc = self.cleaned_data.get('account_no')
        if acc:
            validate_account_no(acc)
        return acc

    def clean(self):
        cleaned_data = super().clean()
        # Core fields required for scheme matching
        required_fields = ['phone', 'age', 'gender', 'education', 'income_range', 'category', 'full_name', 'state', 'district']
        for field in required_fields:
            if not cleaned_data.get(field):
                self.add_error(field, 'This field is required for scheme matching.')
        return cleaned_data

# --- Application Form ---
class CitizenApplicationForm(forms.ModelForm):
    class Meta:
        model = ApplicationRequest
        fields = ['name', 'age', 'gender', 'mobile', 'email', 'education', 'income', 'category', 'state', 'district']
        widgets = {
            'income': forms.NumberInput(attrs={'placeholder': 'Annual Income in Rupees'}),
            'mobile': forms.TextInput(attrs={'type': 'tel', 'maxlength': '10'}),
        }
    def clean_mobile(self):
        mobile = self.cleaned_data.get('mobile')
        validate_phone(mobile)
        return mobile
    def clean_name(self):
        name = self.cleaned_data.get('name')
        validate_alphabetic(name)
        return name

class SchemeForm(forms.ModelForm):
    class Meta:
        model = Scheme
        fields = '__all__'