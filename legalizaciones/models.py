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


# ── Perfil de empleado ────────────────────────────────────────────────────────

class TipoCuenta(models.TextChoices):
    AHORROS = "AHORROS", "Ahorros"
    CORRIENTE = "CORRIENTE", "Corriente"


# Tarifas de IVA vigentes en Colombia
IVA_OPCIONES = [
    (0,  "0 % — Excluido / Exento"),
    (5,  "5 %"),
    (19, "19 % — Tarifa general"),
]


class Perfil(models.Model):
    """
    Información personal y bancaria del empleado.
    Se autocompleta al crear una solicitud de caja.
    """
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="perfil",
    )
    nombre_completo = models.CharField(max_length=200, blank=True)
    cedula = models.CharField(
        max_length=32,
        blank=True,
        validators=[validar_cedula_nit],
        verbose_name="Cédula",
    )
    ciudad = models.CharField(max_length=80, blank=True)
    entidad_bancaria = models.CharField(max_length=80, blank=True)
    numero_cuenta = models.CharField(max_length=40, blank=True)
    tipo_cuenta = models.CharField(
        max_length=10,
        choices=TipoCuenta.choices,
        blank=True,
    )
    firma_imagen = models.ImageField(
        upload_to="firmas/perfil/",
        null=True,
        blank=True,
        help_text="Firma reutilizable. Puedes sobreescribirla en cada solicitud.",
    )
    actualizado_en = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Perfil"
        verbose_name_plural = "Perfiles"

    def __str__(self):
        return self.nombre_completo or self.user.get_username()


# ── Catálogo de centros de costos ─────────────────────────────────────────────

class CentroCosto(models.Model):
    codigo = models.CharField(max_length=20, unique=True)
    nombre = models.CharField(max_length=120)
    activo = models.BooleanField(default=True)

    class Meta:
        verbose_name = "Centro de costos"
        verbose_name_plural = "Centros de costos"
        ordering = ["codigo"]

    def __str__(self):
        return f"{self.codigo} — {self.nombre}"


# ── Solicitud de Caja ─────────────────────────────────────────────────────────

class SolicitudCaja(models.Model):
    class Estado(models.TextChoices):
        BORRADOR     = "BORRADOR",     "Borrador"
        PEND_AREA    = "PEND_AREA",    "Pendiente Gerencia Área"
        PEND_CORP    = "PEND_CORP",    "Pendiente Gerencia Corporativa"
        APROBADA     = "APROBADA",     "Aprobada — lista para desembolso"
        DESEMBOLSADA = "DESEMBOLSADA", "Desembolsada"
        LEGALIZADA   = "LEGALIZADA",   "Legalizada"
        RECHAZADA    = "RECHAZADA",    "Rechazada"

    numero = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    numero_caja = models.CharField(
        max_length=20, unique=True, editable=False, blank=True,
        verbose_name="N° de caja",
        help_text="CAJA-YYYY-NNNN — asignado automáticamente al crear la solicitud",
    )

    solicitante = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="solicitudes",
    )
    fecha_solicitud = models.DateField(verbose_name="Fecha de solicitud")

    # Snapshot de datos del empleado (al momento de crear la solicitud)
    ciudad = models.CharField(max_length=80)
    nombre_completo = models.CharField(max_length=200)
    cedula = models.CharField(max_length=32, validators=[validar_cedula_nit])

    valor_caja = models.DecimalField(
        max_digits=14, decimal_places=2,
        validators=[MinValueValidator(Decimal("0.01"))],
        verbose_name="Caja por valor de",
    )

    entidad_bancaria = models.CharField(max_length=80)
    numero_cuenta = models.CharField(max_length=40)
    tipo_cuenta = models.CharField(max_length=10, choices=TipoCuenta.choices)

    observaciones = models.TextField(blank=True)

    estado = models.CharField(
        max_length=20, choices=Estado.choices,
        default=Estado.BORRADOR,
    )
    motivo_rechazo = models.TextField(blank=True)

    # Firmas (Empleado + 2 niveles de gerencia)
    firma_empleado = models.ImageField(
        upload_to="firmas/empleado/%Y/%m/", null=True, blank=True,
    )
    firma_empleado_fecha = models.DateField(null=True, blank=True)

    aprobador_area = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, related_name="solicitudes_aprob_area",
    )
    firma_area = models.ImageField(
        upload_to="firmas/area/%Y/%m/", null=True, blank=True,
    )
    firma_area_fecha = models.DateField(null=True, blank=True)

    aprobador_corp = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, related_name="solicitudes_aprob_corp",
    )
    firma_corp = models.ImageField(
        upload_to="firmas/corp/%Y/%m/", null=True, blank=True,
    )
    firma_corp_fecha = models.DateField(null=True, blank=True)

    fecha_desembolso = models.DateField(null=True, blank=True)

    creado_en = models.DateTimeField(auto_now_add=True)
    actualizado_en = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Solicitud de caja"
        verbose_name_plural = "Solicitudes de caja"
        ordering = ["-fecha_solicitud", "-creado_en"]
        indexes = [
            models.Index(fields=["estado", "-creado_en"]),
            models.Index(fields=["solicitante", "-creado_en"]),
        ]

    def __str__(self):
        return f"{self.numero_caja or self.numero} ({self.get_estado_display()})"

    # ── Número de caja correlativo ────────────────────────────────────────

    @classmethod
    def _generar_numero_caja(cls) -> str:
        from django.utils import timezone
        anio = timezone.now().year
        prefijo = f"CAJA-{anio}-"
        ultimo = (
            cls.objects.filter(numero_caja__startswith=prefijo)
            .order_by("numero_caja")
            .values_list("numero_caja", flat=True)
            .last()
        )
        n = 1
        if ultimo:
            try:
                n = int(ultimo.split("-")[-1]) + 1
            except (ValueError, IndexError):
                n = 1
        return f"{prefijo}{n:04d}"

    # ── Helpers de totales ────────────────────────────────────────────────

    def total_items(self) -> Decimal:
        return self.items.aggregate(s=Sum("total"))["s"] or Decimal("0.00")

    # ── Save ──────────────────────────────────────────────────────────────

    def save(self, *args, **kwargs):
        if not self.numero_caja:
            self.numero_caja = self._generar_numero_caja()
        super().save(*args, **kwargs)


class ItemSolicitud(models.Model):
    """Líneas de gasto previstas dentro de una solicitud."""

    class TipoItem(models.TextChoices):
        GASOLINA    = "GASOLINA",    "Gasolina"
        RESTAURANTE = "RESTAURANTE", "Restaurante"
        PEAJES      = "PEAJES",      "Peajes"
        HIDRATACION = "HIDRATACION", "Hidratación"
        HOSPEDAJE   = "HOSPEDAJE",   "Hospedaje"
        OTROS       = "OTROS",       "Otros"

    solicitud = models.ForeignKey(
        SolicitudCaja, on_delete=models.CASCADE, related_name="items",
    )
    item = models.CharField(max_length=20, choices=TipoItem.choices)
    centro_costo = models.ForeignKey(
        CentroCosto, on_delete=models.PROTECT, related_name="items_solicitud",
    )
    cantidad = models.DecimalField(
        max_digits=12, decimal_places=2,
        validators=[MinValueValidator(Decimal("0.01"))],
    )
    valor_unitario = models.DecimalField(
        max_digits=14, decimal_places=2,
        validators=[MinValueValidator(Decimal("0.01"))],
    )
    total = models.DecimalField(
        max_digits=16, decimal_places=2, editable=False,
        default=Decimal("0.00"),
    )
    observaciones = models.TextField(
        blank=True,
        help_text="Obligatorio cuando el ítem es 'Otros' (justificación).",
    )
    creado_en = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Ítem de solicitud"
        verbose_name_plural = "Ítems de solicitud"
        ordering = ["creado_en"]

    def clean(self):
        errors = {}
        if self.item == self.TipoItem.OTROS and not (self.observaciones or "").strip():
            errors["observaciones"] = (
                "Para 'Otros' debes describir el ítem en observaciones."
            )
        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        self.total = (self.cantidad or Decimal("0")) * (self.valor_unitario or Decimal("0"))
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.get_item_display()} — {self.centro_costo.codigo} — ${self.total}"


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
    periodo_desde = models.DateField(
        null=True,
        blank=True,
        verbose_name="Período de caja — desde",
        help_text="Fecha de inicio del período que cubre esta caja menor.",
    )
    periodo_hasta = models.DateField(
        null=True,
        blank=True,
        verbose_name="Período de caja — hasta",
        help_text="Fecha de cierre del período que cubre esta caja menor.",
    )
    fecha_cierre = models.DateField(
        null=True,
        blank=True,
        verbose_name="Fecha de cierre",
        help_text="Fecha de cierre oficial registrada por el aprobador.",
    )
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
    solicitud = models.OneToOneField(
        "SolicitudCaja",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="legalizacion",
        verbose_name="Solicitud de caja",
        help_text="Solicitud de caja que originó esta legalización.",
    )
    motivo_aprobador = models.TextField(
        blank=True,
        verbose_name="Observación del aprobador",
        help_text="Justificación del aprobador al aprobar, rechazar o devolver la legalización.",
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
        if self.periodo_desde and self.periodo_hasta:
            if self.periodo_hasta < self.periodo_desde:
                errors["periodo_hasta"] = (
                    "La fecha 'hasta' no puede ser anterior a la fecha 'desde'."
                )
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
    iva_porcentaje = models.SmallIntegerField(
        choices=IVA_OPCIONES,
        default=19,
        verbose_name="% IVA",
        help_text="Tarifa de IVA aplicada. El monto se calcula automáticamente.",
    )
    iva = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        default=Decimal("0.00"),
        editable=False,
        verbose_name="IVA ($)",
        help_text="Calculado: valor_base × iva_porcentaje / 100",
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
        if self.fecha and self.fecha > date.today():
            errors["fecha"] = "La fecha del gasto no puede ser en el futuro."
        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        base = self.valor_base or Decimal("0.00")
        pct  = Decimal(self.iva_porcentaje or 0)
        self.iva   = (base * pct / Decimal("100")).quantize(Decimal("0.01"))
        self.valor = base + self.iva
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.numero_factura} - {self.cliente_proveedor} (${self.valor})"


class Notificacion(models.Model):
    class Tipo(models.TextChoices):
        ENVIADA            = "ENVIADA",            "Legalización enviada"
        APROBADA           = "APROBADA",           "Legalización aprobada"
        RECHAZADA          = "RECHAZADA",          "Legalización rechazada"
        DEVUELTA           = "DEVUELTA",           "Devuelta para corrección"
        GASTO_RECHAZADO    = "GASTO_RECHAZADO",    "Gasto rechazado"
        ALERTA_CIERRE      = "ALERTA_CIERRE",      "Alerta de cierre próximo"
        SOL_ENVIADA_AREA   = "SOL_ENVIADA_AREA",   "Solicitud → Gerencia Área"
        SOL_APROBADA_AREA  = "SOL_APROBADA_AREA",  "Solicitud aprobada por Área"
        SOL_APROBADA_CORP  = "SOL_APROBADA_CORP",  "Solicitud aprobada por Corporativa"
        SOL_DESEMBOLSADA   = "SOL_DESEMBOLSADA",   "Caja desembolsada"
        SOL_RECHAZADA      = "SOL_RECHAZADA",      "Solicitud rechazada"

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
    solicitud = models.ForeignKey(
        SolicitudCaja,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="notificaciones",
        verbose_name="Solicitud de caja",
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
