"""
Comando para inicializar los grupos y permisos del sistema.

Uso:
    python manage.py setup_grupos
"""

from django.contrib.auth.models import Group, Permission
from django.contrib.contenttypes.models import ContentType
from django.core.management.base import BaseCommand

from legalizaciones.models import Gasto, Legalizacion


class Command(BaseCommand):
    help = "Crea los grupos Empleados y Aprobadores con sus permisos correspondientes."

    def handle(self, *args, **options):
        ct_legalizacion = ContentType.objects.get_for_model(Legalizacion)
        ct_gasto = ContentType.objects.get_for_model(Gasto)

        # ── Grupo: Empleados ─────────────────────────────────────────────────
        empleados, creado = Group.objects.get_or_create(name="Empleados")
        permisos_empleados = Permission.objects.filter(
            content_type__in=[ct_legalizacion, ct_gasto],
            codename__in=[
                "add_legalizacion",
                "change_legalizacion",
                "view_legalizacion",
                "add_gasto",
                "change_gasto",
                "delete_gasto",
                "view_gasto",
            ],
        )
        empleados.permissions.set(permisos_empleados)
        self.stdout.write(
            self.style.SUCCESS(
                f"{'Creado' if creado else 'Actualizado'}: Grupo 'Empleados' "
                f"({permisos_empleados.count()} permisos)"
            )
        )

        # ── Grupo: Aprobadores ───────────────────────────────────────────────
        aprobadores, creado = Group.objects.get_or_create(name="Aprobadores")
        permisos_aprobadores = Permission.objects.filter(
            content_type__in=[ct_legalizacion, ct_gasto],
        )
        aprobadores.permissions.set(permisos_aprobadores)
        self.stdout.write(
            self.style.SUCCESS(
                f"{'Creado' if creado else 'Actualizado'}: Grupo 'Aprobadores' "
                f"({permisos_aprobadores.count()} permisos)"
            )
        )

        self.stdout.write(self.style.SUCCESS("\nGrupos configurados correctamente."))
        self.stdout.write(
            "\nPara asignar un usuario a un grupo: Admin > Usuarios > [usuario] > Grupos\n"
        )
