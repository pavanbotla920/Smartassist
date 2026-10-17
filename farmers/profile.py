import re
from django import forms
from django.core.exceptions import ValidationError

def validate_alphabetic(value):
    """Allows only letters and spaces."""
    if not re.match(r'^[a-zA-Z\s]+$', value):
        raise ValidationError('This field must contain only alphabets and spaces.')

def validate_phone(value):
    """Allows exactly 10 digits."""
    if not re.match(r'^\d{10}$', value):
        raise ValidationError('Phone number must be exactly 10 digits.')

def validate_positive_number(value):
    """Allows decimals, no negatives."""
    if value < 0:
        raise ValidationError('This value cannot be negative.')

class UserProfileForm(forms.ModelForm):
    class Meta:
        model = None # Update this to your actual UserProfile model
        fields = ['phone', 'age', 'gender', 'education', 'state', 'district', 'income_range', 'category', 'landholding_size', 'primary_crop', 'farmer_type']
        
    def clean_phone(self):
        phone = self.cleaned_data.get('phone')
        validate_phone(phone)
        return phone

    def clean_age(self):
        age = self.cleaned_data.get('age')
        if age and (age < 18 or age > 120):
            raise ValidationError('Please enter a valid age between 18 and 120.')
        return age

    def clean_landholding_size(self):
        size = self.cleaned_data.get('landholding_size')
        if size is not None:
            validate_positive_number(size)
        return size

    def clean_primary_crop(self):
        crop = self.cleaned_data.get('primary_crop')
        if crop:
            validate_alphabetic(crop)
        return crop

    def clean(self):
        cleaned_data = super().clean()
        required_fields = ['phone', 'age', 'gender', 'education', 'state', 'district', 'income_range', 'category']
        
        # Ensure important fields are filled out
        for field in required_fields:
            if not cleaned_data.get(field):
                self.add_error(field, 'This detail is important for accurate scheme matching.')
        
        return cleaned_data