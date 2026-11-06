from django import forms
from django.contrib.auth.models import User
from django.contrib.auth.forms import UserCreationForm
from django.utils.translation import gettext_lazy as _
from .models import UserProfile, Scheme, ApplicationRequest
from .password_validator import validate as validate_password


class UserRegisterForm(UserCreationForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['username'].label = _('Username')
        self.fields['email'].label = _('Email address')
        self.fields['password1'].label = _('Password')
        self.fields['password2'].label = _('Confirm password')

    def clean_password1(self):
        password = self.cleaned_data.get('password1') or ''
        result = validate_password(
            password,
            username=self.cleaned_data.get('username', ''),
            email=self.cleaned_data.get('email', ''),
        )
        if not result['accepted']:
            for reason in result['reasons']:
                self.add_error('password1', _(reason))
        return password

    class Meta:
        model = User
        fields = ['username', 'email', 'password1', 'password2']


class UserUpdateForm(forms.ModelForm):
    class Meta:
        model = User
        fields = ['username', 'email']
        labels = {'username': _('Username'), 'email': _('Email address')}


class UserProfileForm(forms.ModelForm):
    RURAL_URBAN_CHOICES = (
        ('', _('Select classification')),
        ('rural', _('Rural')),
        ('urban', _('Urban')),
    )
    rural_urban = forms.ChoiceField(
        choices=RURAL_URBAN_CHOICES,
        required=False,
    )
    OWNERSHIP_CHOICES = (
        ('', _('Select ownership type')),
        ('owner', _('Owner')),
        ('tenant', _('Tenant')),
        ('sharecropper', _('Sharecropper')),
        ('oral_lessee', _('Oral lessee')),
    )
    ownership_type = forms.ChoiceField(
        choices=OWNERSHIP_CHOICES,
        required=False,
    )
    FARMER_TYPE_CHOICES = (
        ('', _('Select farmer type')),
        ('small', _('Small')),
        ('medium', _('Medium')),
        ('large', _('Large')),
        ('landless', _('Landless')),
    )
    farmer_type = forms.ChoiceField(
        choices=FARMER_TYPE_CHOICES,
        required=False,
    )

    class Meta:
        model = UserProfile
        fields = [
            'phone', 'state', 'district', 'taluka', 'village_panchayat',
            'rural_urban', 'pin_code', 'age', 'gender',
            'education', 'income_range', 'category', 'ration_card_type',
            'family_size', 'occupation', 'landholding_size', 'ownership_type',
            'crops_grown', 'livestock_assets', 'farmer_type',
        ]
        labels = {
            'phone': _('Phone number'),
            'state': _('State'),
            'district': _('District'),
            'taluka': _('Taluka'),
            'village_panchayat': _('Village / Gram Panchayat'),
            'rural_urban': _('Rural / Urban'),
            'pin_code': _('PIN code'),
            'ration_card_type': _('Ration card type'),
            'family_size': _('Family size'),
            'occupation': _('Occupation'),
            'landholding_size': _('Landholding size (acres)'),
            'ownership_type': _('Land ownership type'),
            'crops_grown': _('Crops grown'),
            'livestock_assets': _('Livestock information'),
            'farmer_type': _('Farmer type'),
            'age': _('Age'),
            'gender': _('Gender'),
            'education': _('Education'),
            'income_range': _('Income range'),
            'category': _('Category'),
        }

    def clean_phone(self):
        phone = (self.cleaned_data.get('phone') or '').strip()
        if phone and not phone.isdigit():
            raise forms.ValidationError(_('Phone number must contain digits only.'))
        if phone and len(phone) != 10:
            raise forms.ValidationError(_('Phone number must be exactly 10 digits.'))
        return phone

    def clean_age(self):
        age = self.cleaned_data.get('age')
        if age is not None and not 18 <= age <= 120:
            raise forms.ValidationError(
                _('Please enter an age between 18 and 120.')
            )
        return age

    def clean_pin_code(self):
        pin_code = (self.cleaned_data.get('pin_code') or '').strip()
        if pin_code and (not pin_code.isdigit() or len(pin_code) != 6):
            raise forms.ValidationError(_('PIN code must contain exactly 6 digits.'))
        return pin_code

    def clean_family_size(self):
        family_size = self.cleaned_data.get('family_size')
        if family_size is not None and family_size < 1:
            raise forms.ValidationError(_('Family size must be at least 1.'))
        return family_size

    def clean_landholding_size(self):
        landholding_size = self.cleaned_data.get('landholding_size')
        if landholding_size is not None and landholding_size < 0:
            raise forms.ValidationError(_('Landholding size cannot be negative.'))
        return landholding_size

    def clean(self):
        cleaned_data = super().clean()
        farmer_type = cleaned_data.get('farmer_type')
        landholding_size = cleaned_data.get('landholding_size')

        if (
            farmer_type == 'landless'
            and landholding_size is not None
            and landholding_size > 0
        ):
            self.add_error(
                'landholding_size',
                _(
                    'Landless farmers cannot have a positive '
                    'landholding size.'
                ),
            )

        return cleaned_data


class CitizenApplicationForm(forms.ModelForm):
    class Meta:
        model = ApplicationRequest
        fields = ['name', 'age', 'gender', 'mobile', 'email', 'education', 'income', 'category', 'state', 'district']
        labels = {
            'name': _('Full Name'),
            'age': _('Age'),
            'gender': _('Gender'),
            'mobile': _('Mobile Number'),
            'email': _('Email'),
            'education': _('Education Level'),
            'income': _('Annual Income (₹)'),
            'category': _('Category'),
            'state': _('State'),
            'district': _('District'),
        }
        widgets = {
            'name': forms.TextInput(attrs={'class': 'form-control', 'autocomplete': 'name'}),
            'age': forms.NumberInput(attrs={'class': 'form-control', 'min': 1, 'max': 120}),
            'gender': forms.TextInput(attrs={'class': 'form-control', 'autocomplete': 'sex'}),
            'mobile': forms.TextInput(attrs={'class': 'form-control', 'type': 'tel', 'autocomplete': 'tel'}),
            'email': forms.EmailInput(attrs={'class': 'form-control', 'autocomplete': 'email'}),
            'education': forms.TextInput(attrs={'class': 'form-control'}),
            'income': forms.NumberInput(attrs={
                'class': 'form-control',
                'min': 0,
                'placeholder': _('Annual income in rupees'),
            }),
            'category': forms.TextInput(attrs={'class': 'form-control'}),
            'state': forms.TextInput(attrs={'class': 'form-control', 'autocomplete': 'address-level1'}),
            'district': forms.TextInput(attrs={'class': 'form-control', 'autocomplete': 'address-level2'}),
        }

    def clean_mobile(self):
        mobile = (self.cleaned_data.get('mobile') or '').strip()
        if not mobile.isdigit() or len(mobile) != 10:
            raise forms.ValidationError(_('Mobile number must contain exactly 10 digits.'))
        return mobile

    def clean_age(self):
        age = self.cleaned_data.get('age')
        if age is not None and age < 0:
            raise forms.ValidationError(_('Age cannot be negative.'))
        return age


class SchemeForm(forms.ModelForm):
    class Meta:
        model = Scheme
        fields = '__all__'

    def clean(self):
        cleaned_data = super().clean()
        name = (cleaned_data.get('scheme_name') or '').strip()
        scheme_type = cleaned_data.get('scheme_type')
        state = (cleaned_data.get('state') or '').strip()
        min_age = cleaned_data.get('min_age')
        max_age = cleaned_data.get('max_age')

        if min_age is not None and max_age is not None and min_age > max_age:
            self.add_error('max_age', _('Maximum age must be greater than or equal to minimum age.'))

        duplicate_query = Scheme.objects.filter(
            scheme_name__iexact=name,
            scheme_type=scheme_type,
            state__iexact=state,
        )
        if self.instance.pk:
            duplicate_query = duplicate_query.exclude(pk=self.instance.pk)
        if name and duplicate_query.exists():
            self.add_error(
                'scheme_name',
                _('A scheme with this name, type, and state already exists.'),
            )
        return cleaned_data