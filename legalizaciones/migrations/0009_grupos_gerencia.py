"""
Crea los grupos de aprobación de solicitudes de caja:
- Gerencia Área         (1er nivel de aprobación)
- Gerencia Corporativa  (2do nivel de aprobación)

Estos grupos se usan en las vistas para permitir/denegar acciones.
La migración es reversible: el rollback elimina los grupos.
"""
from django.db import migrations

GRUPOS = [
    "Gerencia Área",
    "Gerencia Corporativa",
]


def crear_grupos(apps, schema_editor):
    Group = apps.get_model("auth", "Group")
    for nombre in GRUPOS:
        Group.objects.get_or_create(name=nombre)


def eliminar_grupos(apps, schema_editor):
    Group = apps.get_model("auth", "Group")
    Group.objects.filter(name__in=GRUPOS).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("legalizaciones", "0008_centrocosto_alter_notificacion_tipo_perfil_and_more"),
    ]

    operations = [
        migrations.RunPython(crear_grupos, eliminar_grupos),
    ]
