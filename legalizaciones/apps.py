from django.apps import AppConfig


class LegalizacionesConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "legalizaciones"
    verbose_name = "Legalizaciones de Caja Menor"

    def ready(self):
        from . import signals  # noqa: F401
