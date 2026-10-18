"""Diagnose the outgoing email configuration and send a test message.

    python manage.py send_test_email                 # show the resolved config only
    python manage.py send_test_email you@gmail.com   # actually send a test email
"""
from django.conf import settings
from django.core.mail import send_mail
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = 'Show the resolved email configuration and optionally send a test message.'

    def add_arguments(self, parser):
        parser.add_argument('recipient', nargs='?', help='Address to send the test message to.')

    def handle(self, *args, **options):
        self.stdout.write('Resolved email configuration')
        self.stdout.write(f'  EMAIL_BACKEND   : {settings.EMAIL_BACKEND}')
        self.stdout.write(f'  EMAIL_HOST      : {settings.EMAIL_HOST}:{settings.EMAIL_PORT}')
        self.stdout.write(f'  TLS / SSL       : {settings.EMAIL_USE_TLS} / {settings.EMAIL_USE_SSL}')
        self.stdout.write(f'  EMAIL_HOST_USER : {settings.EMAIL_HOST_USER or "(not set)"}')
        self.stdout.write(f'  Password        : {"set" if settings.EMAIL_HOST_PASSWORD else "(not set)"}')
        self.stdout.write(f'  From address    : {settings.DEFAULT_FROM_EMAIL}')
        self.stdout.write('')

        problems = []
        if not settings.EMAIL_HOST_USER:
            problems.append('EMAIL_HOST_USER is empty. Export it, then restart the server.')
        if not settings.EMAIL_HOST_PASSWORD:
            problems.append('EMAIL_HOST_PASSWORD is empty. Use a Gmail App Password, not your login password.')
        if settings.EMAIL_USE_SSL and settings.EMAIL_USE_TLS:
            problems.append('Both EMAIL_USE_SSL and EMAIL_USE_TLS are True; enable exactly one.')
        if not settings.EMAIL_USE_SSL and not settings.EMAIL_USE_TLS:
            problems.append('Neither TLS nor SSL is enabled; Gmail requires one.')

        if problems:
            self.stdout.write(self.style.ERROR('Configuration problems found:'))
            for problem in problems:
                self.stdout.write(f'  - {problem}')
            self.stdout.write('')
            self.stdout.write('Email cannot be delivered until these are fixed.')
            self.stdout.write('')

        recipient = options.get('recipient')
        if not recipient:
            self.stdout.write('Re-run with an address to send a test message, for example:')
            self.stdout.write('  python manage.py send_test_email you@gmail.com')
            return

        self.stdout.write(f'Sending a test message to {recipient} ...')
        try:
            send_mail(
                subject='SmartAssist email test',
                message='If you are reading this, SmartAssist can send email.',
                from_email=settings.DEFAULT_FROM_EMAIL,
                recipient_list=[recipient],
                fail_silently=False,
            )
        except Exception as exc:
            self.stdout.write(self.style.ERROR(f'FAILED: {type(exc).__name__}: {exc}'))
            self.stdout.write('')
            self.stdout.write('Common causes:')
            self.stdout.write('  535 "Username and Password not accepted" -> wrong App Password, or 2-Step Verification is off.')
            self.stdout.write('  534 -> you used your normal Gmail password; create an App Password instead.')
            self.stdout.write('  Timeout / refused -> the port is blocked. Try EMAIL_PORT=587, EMAIL_USE_TLS=True, EMAIL_USE_SSL=False.')
            self.stdout.write('  Name resolution / DNS -> this machine has no internet access.')
            return

        self.stdout.write(self.style.SUCCESS('Sent. Check the inbox (and the spam folder).'))
