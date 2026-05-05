import logging
import sys

from django.apps import AppConfig

logger = logging.getLogger(__name__)

# Comandos que no deben arrancar el scheduler
_SKIP_SCHEDULER = {
    "migrate", "makemigrations", "collectstatic",
    "shell", "shell_plus", "test", "check",
    "showmigrations", "enviar_alertas_cierre",
}


class LegalizacionesConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "legalizaciones"
    verbose_name = "Legalizaciones de Caja Menor"

    def ready(self):
        from . import signals  # noqa: F401

        # No arrancar el scheduler en comandos de management
        if set(sys.argv) & _SKIP_SCHEDULER:
            return

        try:
            from .scheduler import iniciar_scheduler
            iniciar_scheduler()
        except Exception:
            logger.exception("No se pudo iniciar el scheduler de alertas")
