"""
Comando: enviar_alertas_cierre
==============================
Dispara manualmente la misma lógica que corre automáticamente
cada día a las 08:00 a través del scheduler interno.

Uso normal:
    python manage.py enviar_alertas_cierre

Uso para pruebas (buscar cierres en N días desde hoy):
    python manage.py enviar_alertas_cierre --dias 0   # fecha_cierre = hoy
    python manage.py enviar_alertas_cierre --dias 1   # fecha_cierre = mañana
    python manage.py enviar_alertas_cierre --dias 2   # producción (default)
"""

from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Ejecuta manualmente las alertas de cierre de caja"

    def add_arguments(self, parser):
        parser.add_argument(
            "--dias",
            type=int,
            default=2,
            help="Días desde hoy para buscar cierres (default: 2). Usa 0 para probar con fecha_cierre=hoy.",
        )

    def handle(self, *args, **options):
        from legalizaciones.scheduler import enviar_alertas_cierre

        dias = options["dias"]
        self.stdout.write(f"Buscando legalizaciones con cierre en {dias} día(s)…")

        try:
            enviadas = enviar_alertas_cierre(dias_anticipacion=dias)
            if enviadas == 0:
                self.stdout.write(self.style.WARNING(
                    f"Sin legalizaciones con fecha_cierre = hoy + {dias} día(s). "
                    "Asegúrate de que exista una legalización con esa fecha de cierre."
                ))
            else:
                self.stdout.write(self.style.SUCCESS(f"Alertas enviadas: {enviadas}"))
        except Exception as e:
            self.stderr.write(self.style.ERROR(f"Error: {e}"))
            raise
