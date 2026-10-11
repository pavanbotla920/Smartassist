from django import forms
from django.contrib.auth.models import User
from django.contrib.auth.forms import UserCreationForm
from django.utils.translation import gettext_lazy as _
from .models import UserProfile, Scheme, ApplicationRequest


class UserRegisterForm(UserCreationForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['username'].label = _('Username')
        self.fields['email'].label = _('Email address')
        self.fields['password1'].label = _('Password')
        self.fields['password2'].label = _('Confirm password')

    class Meta:
        model = User
        fields = ['username', 'email', 'password1', 'password2']


class UserUpdateForm(forms.ModelForm):
    class Meta:
        model = User
        fields = ['username', 'email']
        labels = {'username': _('Username'), 'email': _('Email address')}


class UserProfileForm(forms.ModelForm):
    class Meta:
        model = UserProfile
        fields = ['phone', 'state', 'district', 'age', 'gender', 'education', 'income_range', 'category']
        labels = {
            'phone': _('Phone number'),
            'state': _('State'),
            'district': _('District'),
            'age': _('Age'),
            'gender': _('Gender'),
            'education': _('Education'),
            'income_range': _('Income range'),
            'category': _('Category'),
        }


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


class SchemeForm(forms.ModelForm):
    class Meta:
        model = Scheme
        fields = '__all__'