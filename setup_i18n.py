#!/usr/bin/env python
"""
Setup script for Django i18n (internationalization).
Generates empty translation files for all configured languages.
Run: python setup_i18n.py
"""
import os
import sys
import django
from pathlib import Path

# Setup Django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'smartassist.settings')
django.setup()

from django.conf import settings
from django.core.management import call_command

BASE_DIR = Path(__file__).resolve().parent
LOCALE_DIR = BASE_DIR / 'locale'

def setup_i18n():
    """Create locale directories and initialize translation files for all languages."""
    
    # Ensure locale directory exists
    LOCALE_DIR.mkdir(exist_ok=True)
    
    # Extract language codes from settings
    language_codes = [code for code, name in settings.LANGUAGES if code != 'en']
    
    print(f"Setting up translations for {len(language_codes)} languages...")
    print(f"Languages: {', '.join(language_codes)}\n")
    
    # Create locale structure for all languages
    for lang in language_codes:
        lang_dir = LOCALE_DIR / lang / 'LC_MESSAGES'
        lang_dir.mkdir(parents=True, exist_ok=True)
        print(f"✓ Created directory: {lang_dir}")
    
    print("\nGenerating translation files (makemessages)...")
    # Run makemessages for each language
    for lang in language_codes:
        try:
            call_command('makemessages', locale=lang, use_default_locale=True, verbosity=0)
            print(f"✓ Generated messages for {lang}")
        except Exception as e:
            print(f"✗ Error generating messages for {lang}: {e}")
    
    print("\nCompiling translations (compilemessages)...")
    try:
        call_command('compilemessages', verbosity=1)
        print("✓ Successfully compiled all translations")
    except Exception as e:
        print(f"✗ Error compiling messages: {e}")
    
    print("\n✅ i18n setup complete!")
    print(f"Translation files are located in: {LOCALE_DIR}")

if __name__ == '__main__':
    setup_i18n()
