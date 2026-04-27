import uuid
from decimal import Decimal

from django.conf import settings
from django.db import models
from django.db.models import Sum


class Legalizacion(models.Model):
    class Estado(models.TextChoices):
        BORRADOR = "BORRADOR", "Borrador"
        ENVIADO = "ENVIADO", "Enviado"
        APROBADO = "APROBADO", "Aprobado"
        RECHAZADO = "RECHAZADO", "Rechazado"

    numero = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False,
        verbose_name="Número",
    )
    monto_aprobado = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        verbose_name="Monto aprobado",
    )
    fecha_solicitud = models.DateField(verbose_name="Fecha de solicitud")
    fecha_consignacion = models.DateField(
        null=True,
        blank=True,
        verbose_name="Fecha de consignación",
    )
    elaboro = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="legalizaciones_elaboradas",
        verbose_name="Elaboró",
    )
    saldo = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        default=Decimal("0.00"),
        editable=False,
        verbose_name="Saldo",
        help_text=(
            "Calculado automáticamente: monto_aprobado - sum(valor de gastos). "
            "Positivo: a favor de la empresa. Negativo: a favor del empleado."
        ),
    )
    estado = models.CharField(
        max_length=10,
        choices=Estado.choices,
        default=Estado.BORRADOR,
        verbose_name="Estado",
    )
    aprobado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="legalizaciones_aprobadas",
        verbose_name="Aprobado por",
    )
    creado_en = models.DateTimeField(auto_now_add=True)
    actualizado_en = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Legalización"
        verbose_name_plural = "Legalizaciones"
        ordering = ["-fecha_solicitud", "-creado_en"]

    def __str__(self):
        return f"Legalización {self.numero} ({self.get_estado_display()})"

    def recalcular_saldo(self, save: bool = True) -> Decimal:
        total_gastos = self.gastos.aggregate(total=Sum("valor"))["total"] or Decimal("0.00")
        self.saldo = (self.monto_aprobado or Decimal("0.00")) - total_gastos
        if save:
            Legalizacion.objects.filter(pk=self.pk).update(saldo=self.saldo)
        return self.saldo

    def save(self, *args, **kwargs):
        is_new = self._state.adding
        super().save(*args, **kwargs)
        if not is_new:
            self.recalcular_saldo(save=True)


class Gasto(models.Model):
    legalizacion = models.ForeignKey(
        Legalizacion,
        on_delete=models.CASCADE,
        related_name="gastos",
        verbose_name="Legalización",
    )
    fecha = models.DateField(verbose_name="Fecha")
    cliente_proveedor = models.CharField(
        max_length=255,
        verbose_name="Cliente / Proveedor",
    )
    cedula_nit = models.CharField(max_length=32, verbose_name="Cédula / NIT")
    numero_factura = models.CharField(max_length=64, verbose_name="Número de factura")
    centro_costos = models.CharField(max_length=64, verbose_name="Centro de costos")
    valor = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        verbose_name="Valor",
    )
    observaciones = models.TextField(
        null=True,
        blank=True,
        verbose_name="Observaciones",
    )
    creado_en = models.DateTimeField(auto_now_add=True)
    actualizado_en = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Gasto"
        verbose_name_plural = "Gastos"
        ordering = ["fecha", "creado_en"]
        indexes = [
            models.Index(fields=["legalizacion", "fecha"]),
            models.Index(fields=["centro_costos"]),
        ]

    def __str__(self):
        return f"{self.numero_factura} - {self.cliente_proveedor} (${self.valor})"
