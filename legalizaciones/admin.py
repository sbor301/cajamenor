from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.contrib.auth.models import User

from .models import (
    CentroCosto,
    Gasto,
    ItemSolicitud,
    Legalizacion,
    Perfil,
    SolicitudCaja,
)


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


# ── Perfil inline en User admin ───────────────────────────────────────────────

class PerfilInline(admin.StackedInline):
    model = Perfil
    can_delete = False
    verbose_name = "Perfil del sistema"
    verbose_name_plural = "Perfil del sistema"
    fields = ("nombre_completo", "cedula", "ciudad", "entidad_bancaria",
              "numero_cuenta", "tipo_cuenta")
    extra = 0


class UserAdmin(BaseUserAdmin):
    """
    Extiende el admin de Django User para incluir el Perfil del sistema
    directamente en la misma pantalla de creación/edición de usuario.
    Así el administrador puede asignar nombre y datos bancarios sin
    navegar a una sección separada.
    """
    inlines = (PerfilInline,)
    list_display = ("username", "email", "nombre_perfil", "is_staff", "grupos")

    @admin.display(description="Nombre")
    def nombre_perfil(self, obj):
        try:
            return obj.perfil.nombre_completo or "—"
        except Perfil.DoesNotExist:
            return "—"

    @admin.display(description="Grupos")
    def grupos(self, obj):
        return ", ".join(g.name for g in obj.groups.all()) or "—"


# Reemplazamos el UserAdmin por defecto de Django
admin.site.unregister(User)
admin.site.register(User, UserAdmin)


# ── Catálogo y Perfiles ──────────────────────────────────────────────────────

@admin.register(CentroCosto)
class CentroCostoAdmin(admin.ModelAdmin):
    list_display = ("codigo", "nombre", "activo")
    list_filter = ("activo",)
    search_fields = ("codigo", "nombre")
    list_editable = ("activo",)


@admin.register(Perfil)
class PerfilAdmin(admin.ModelAdmin):
    list_display = ("user", "nombre_completo", "cedula", "ciudad", "tipo_cuenta")
    list_editable = ("nombre_completo",)
    search_fields = ("user__username", "nombre_completo", "cedula")
    list_filter = ("tipo_cuenta",)


# ── Solicitudes de Caja ──────────────────────────────────────────────────────

class ItemSolicitudInline(admin.TabularInline):
    model = ItemSolicitud
    extra = 0
    fields = ("item", "centro_costo", "cantidad", "valor_unitario", "total", "observaciones")
    readonly_fields = ("total",)


@admin.register(SolicitudCaja)
class SolicitudCajaAdmin(admin.ModelAdmin):
    list_display = (
        "numero_caja", "solicitante", "fecha_solicitud",
        "valor_caja", "estado", "fecha_desembolso",
    )
    list_filter = ("estado", "fecha_solicitud", "tipo_cuenta")
    search_fields = ("numero_caja", "nombre_completo", "cedula")
    readonly_fields = ("numero", "numero_caja", "creado_en", "actualizado_en")
    inlines = [ItemSolicitudInline]


@admin.register(ItemSolicitud)
class ItemSolicitudAdmin(admin.ModelAdmin):
    list_display = ("solicitud", "item", "centro_costo", "cantidad", "valor_unitario", "total")
    list_filter = ("item", "centro_costo")
    readonly_fields = ("total",)
