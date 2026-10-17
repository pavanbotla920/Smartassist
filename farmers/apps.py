from django.apps import AppConfig


class FarmersConfig(AppConfig):
    name = 'farmers'

    def ready(self):
        import farmers.signals
