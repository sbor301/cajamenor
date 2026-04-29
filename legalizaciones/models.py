import re
import uuid
from datetime import date
from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.db import models
from django.db.models import Sum


# ── Validadores reutilizables ─────────────────────────────────────────────────

def validar_cedula_nit(value):
    """Valida cédula o NIT colombiano: solo dígitos y guión opcional, 5-12 dígitos."""
    clean = re.sub(r"[\s\-]", "", value)
    if not clean.isdigit():
        raise ValidationError(
            "Solo debe contener dígitos. Formato aceptado: 123456789 o 900123456-7"
        )
    if not (5 <= len(clean) <= 12):
        raise ValidationError(
            f"Debe tener entre 5 y 12 dígitos (ingresaste {len(clean)})."
        )


class Legalizacion(models.Model):
    class Estado(models.TextChoices):
        BORRADOR  = "BORRADOR",  "Borrador"
        ENVIADO   = "ENVIADO",   "Enviado"
        DEVUELTO  = "DEVUELTO",  "Devuelto para corrección"
        APROBADO  = "APROBADO",  "Aprobado"
        RECHAZADO = "RECHAZADO", "Rechazado"

    numero = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False,
        verbose_name="Número",
    )
    codigo = models.CharField(
        max_length=20,
        unique=True,
        editable=False,
        blank=True,
        verbose_name="Código",
        help_text="Código legible auto-generado. Formato: LC-YYYY-NNN",
    )
    monto_aprobado = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        verbose_name="Monto aprobado",
        validators=[MinValueValidator(Decimal("0.01"), message="El monto aprobado debe ser mayor a cero.")],
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

    def clean(self):
        errors = {}
        if self.monto_aprobado is not None and self.monto_aprobado <= 0:
            errors["monto_aprobado"] = "El monto aprobado debe ser mayor a cero."
        if self.fecha_consignacion and self.fecha_solicitud:
            if self.fecha_consignacion < self.fecha_solicitud:
                errors["fecha_consignacion"] = (
                    "La fecha de consignación no puede ser anterior a la fecha de solicitud."
                )
        if errors:
            raise ValidationError(errors)

    def __str__(self):
        return f"Legalización {self.codigo or self.numero} ({self.get_estado_display()})"

    @classmethod
    def _generar_codigo(cls) -> str:
        """
        Genera el siguiente código correlativo anual.
        Formato: LC-YYYY-NNN  (ej: LC-2025-001)
        El contador se reinicia cada año.
        """
        from django.utils import timezone
        anio = timezone.now().year
        prefijo = f"LC-{anio}-"
        ultimo = (
            cls.objects.filter(codigo__startswith=prefijo)
            .order_by("codigo")
            .values_list("codigo", flat=True)
            .last()
        )
        if ultimo:
            try:
                n = int(ultimo.split("-")[-1]) + 1
            except (ValueError, IndexError):
                n = 1
        else:
            n = 1
        return f"{prefijo}{n:03d}"

    def recalcular_saldo(self, save: bool = True) -> Decimal:
        # Solo cuenta gastos NO rechazados
        total_gastos = (
            self.gastos.filter(rechazado=False).aggregate(total=Sum("valor"))["total"]
            or Decimal("0.00")
        )
        self.saldo = (self.monto_aprobado or Decimal("0.00")) - total_gastos
        if save:
            Legalizacion.objects.filter(pk=self.pk).update(saldo=self.saldo)
        return self.saldo

    def save(self, *args, **kwargs):
        if not self.codigo:
            self.codigo = self._generar_codigo()
        super().save(*args, **kwargs)
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
    cedula_nit = models.CharField(
        max_length=32,
        verbose_name="Cédula / NIT",
        validators=[validar_cedula_nit],
    )
    numero_factura = models.CharField(max_length=64, verbose_name="Número de factura")
    centro_costos = models.CharField(max_length=64, verbose_name="Centro de costos")
    valor_base = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        default=Decimal("0.00"),
        verbose_name="Valor base",
        validators=[MinValueValidator(Decimal("0.01"), message="El valor base debe ser mayor a cero.")],
    )
    iva = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        default=Decimal("0.00"),
        verbose_name="IVA",
        validators=[MinValueValidator(Decimal("0"), message="El IVA no puede ser negativo.")],
    )
    valor = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        default=Decimal("0.00"),
        editable=False,
        verbose_name="Valor total",
        help_text="Calculado automáticamente: valor_base + IVA",
    )
    archivo_factura = models.FileField(
        upload_to="facturas/%Y/%m/",
        null=True,
        blank=True,
        verbose_name="Archivo factura",
        help_text="Foto (JPG/PNG) o PDF de la factura",
    )
    observaciones = models.TextField(
        null=True,
        blank=True,
        verbose_name="Observaciones",
    )
    rechazado = models.BooleanField(
        default=False,
        verbose_name="Rechazado",
    )
    motivo_rechazo = models.TextField(
        null=True,
        blank=True,
        verbose_name="Motivo de rechazo",
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

    def clean(self):
        errors = {}
        if self.valor_base is not None and self.valor_base <= 0:
            errors["valor_base"] = "El valor base debe ser mayor a cero."
        if self.iva is not None and self.iva < 0:
            errors["iva"] = "El IVA no puede ser negativo."
        if self.fecha and self.fecha > date.today():
            errors["fecha"] = "La fecha del gasto no puede ser en el futuro."
        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        self.valor = (self.valor_base or Decimal("0.00")) + (self.iva or Decimal("0.00"))
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.numero_factura} - {self.cliente_proveedor} (${self.valor})"


class Notificacion(models.Model):
    class Tipo(models.TextChoices):
        ENVIADA         = "ENVIADA",         "Legalización enviada"
        APROBADA        = "APROBADA",        "Legalización aprobada"
        RECHAZADA       = "RECHAZADA",       "Legalización rechazada"
        DEVUELTA        = "DEVUELTA",        "Devuelta para corrección"
        GASTO_RECHAZADO = "GASTO_RECHAZADO", "Gasto rechazado"

    destinatario = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="notificaciones",
        verbose_name="Destinatario",
    )
    tipo = models.CharField(max_length=20, choices=Tipo.choices, verbose_name="Tipo")
    titulo = models.CharField(max_length=200, verbose_name="Título")
    mensaje = models.TextField(blank=True, verbose_name="Mensaje")
    url = models.CharField(max_length=500, blank=True, verbose_name="URL de acceso")
    leida = models.BooleanField(default=False, verbose_name="Leída")
    legalizacion = models.ForeignKey(
        Legalizacion,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="notificaciones",
        verbose_name="Legalización",
    )
    creado_en = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Notificación"
        verbose_name_plural = "Notificaciones"
        ordering = ["-creado_en"]
        indexes = [
            models.Index(fields=["destinatario", "leida", "-creado_en"]),
        ]

    def __str__(self):
        return f"[{self.tipo}] {self.titulo} → {self.destinatario}"
