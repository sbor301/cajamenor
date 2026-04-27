from django.contrib import admin

from .models import Gasto, Legalizacion


class GastoInline(admin.TabularInline):
    model = Gasto
    extra = 0
    fields = (
        "fecha",
        "cliente_proveedor",
        "cedula_nit",
        "numero_factura",
        "centro_costos",
        "valor",
        "observaciones",
    )


@admin.register(Legalizacion)
class LegalizacionAdmin(admin.ModelAdmin):
    list_display = (
        "numero",
        "fecha_solicitud",
        "fecha_consignacion",
        "elaboro",
        "monto_aprobado",
        "saldo",
        "estado",
        "aprobado_por",
    )
    list_filter = ("estado", "fecha_solicitud", "elaboro")
    search_fields = ("numero", "elaboro__username", "aprobado_por__username")
    readonly_fields = ("numero", "saldo", "creado_en", "actualizado_en")
    inlines = [GastoInline]


@admin.register(Gasto)
class GastoAdmin(admin.ModelAdmin):
    list_display = (
        "numero_factura",
        "fecha",
        "cliente_proveedor",
        "cedula_nit",
        "centro_costos",
        "valor",
        "legalizacion",
    )
    list_filter = ("fecha", "centro_costos")
    search_fields = ("cliente_proveedor", "cedula_nit", "numero_factura")
