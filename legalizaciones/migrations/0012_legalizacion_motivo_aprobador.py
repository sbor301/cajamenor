from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("legalizaciones", "0011_gasto_iva_porcentaje"),
    ]

    operations = [
        migrations.AddField(
            model_name="legalizacion",
            name="motivo_aprobador",
            field=models.TextField(
                blank=True,
                verbose_name="Observación del aprobador",
                help_text="Justificación del aprobador al aprobar, rechazar o devolver la legalización.",
            ),
        ),
    ]
