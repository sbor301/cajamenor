"""
Vistas del flujo de Solicitud de Caja.

Flujo de estados:
    BORRADOR → PEND_AREA → PEND_CORP → APROBADA → DESEMBOLSADA → LEGALIZADA
                                            ↓
                                       RECHAZADA (en cualquier paso)
"""
from datetime import date
from decimal import Decimal, InvalidOperation

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.db import transaction
from django.db.models import Q
from django.http import HttpResponseForbidden
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from legalizaciones.models import (
    CentroCosto,
    ItemSolicitud,
    Notificacion,
    Perfil,
    SolicitudCaja,
    TipoCuenta,
)


# ── Helpers de roles ─────────────────────────────────────────────────────────

def es_gerencia_area(user) -> bool:
    return user.is_superuser or user.groups.filter(name="Gerencia Área").exists()


def es_gerencia_corp(user) -> bool:
    return user.is_superuser or user.groups.filter(name="Gerencia Corporativa").exists()


def es_aprobador_caja(user) -> bool:
    """Quién marca el desembolso (tesorería). Por ahora reusamos 'Aprobadores'."""
    return user.is_superuser or user.groups.filter(name="Aprobadores").exists()


def usuarios_grupo(nombre_grupo):
    return User.objects.filter(
        Q(is_superuser=True) | Q(groups__name=nombre_grupo)
    ).distinct()


# ── Helper de notificaciones para solicitudes ────────────────────────────────

def _notificar_sol(destinatario, tipo, titulo, mensaje, solicitud):
    if not destinatario:
        return
    Notificacion.objects.create(
        destinatario=destinatario,
        tipo=tipo,
        titulo=titulo,
        mensaje=mensaje,
        url=reverse("solicitud_detail", args=[solicitud.pk]),
        solicitud=solicitud,
    )


# ── Helper para validar archivo de firma subido ─────────────────────────────

ALLOWED_FIRMA_TYPES = {"image/png", "image/jpeg", "image/jpg", "image/webp"}
MAX_FIRMA_BYTES = 2 * 1024 * 1024  # 2 MB


def _validar_archivo_firma(archivo) -> str | None:
    """Retorna mensaje de error o None si está OK."""
    if not archivo:
        return "Debes adjuntar tu firma."
    if archivo.size > MAX_FIRMA_BYTES:
        return "La firma supera el tamaño máximo de 2 MB."
    if archivo.content_type not in ALLOWED_FIRMA_TYPES:
        return "Formato no permitido. Usa PNG, JPG o WEBP."
    return None


# ── Lista ────────────────────────────────────────────────────────────────────

@login_required
def solicitud_list(request):
    """
    Lista filtrada por rol:
    - Gerencia Área:        ve PEND_AREA + las que ya pasaron por área
    - Gerencia Corporativa: ve PEND_CORP + APROBADA + DESEMBOLSADA + LEGALIZADA
    - Tesorería:            ve APROBADA (lista para desembolsar)
    - Empleado:             ve sus propias solicitudes
    """
    user = request.user
    qs = SolicitudCaja.objects.select_related("solicitante").order_by("-creado_en")

    filtro = request.GET.get("estado", "").strip()

    # Vista por defecto según rol
    if user.is_superuser:
        pass  # ve todo
    elif es_gerencia_corp(user):
        qs = qs.filter(estado__in=[
            SolicitudCaja.Estado.PEND_CORP,
            SolicitudCaja.Estado.APROBADA,
            SolicitudCaja.Estado.DESEMBOLSADA,
            SolicitudCaja.Estado.LEGALIZADA,
            SolicitudCaja.Estado.RECHAZADA,
        ])
    elif es_gerencia_area(user):
        qs = qs.filter(estado__in=[
            SolicitudCaja.Estado.PEND_AREA,
            SolicitudCaja.Estado.PEND_CORP,
            SolicitudCaja.Estado.APROBADA,
            SolicitudCaja.Estado.DESEMBOLSADA,
            SolicitudCaja.Estado.LEGALIZADA,
            SolicitudCaja.Estado.RECHAZADA,
        ])
    elif es_aprobador_caja(user):
        qs = qs.filter(estado__in=[
            SolicitudCaja.Estado.APROBADA,
            SolicitudCaja.Estado.DESEMBOLSADA,
            SolicitudCaja.Estado.LEGALIZADA,
        ])
    else:
        qs = qs.filter(solicitante=user)

    if filtro:
        qs = qs.filter(estado=filtro)

    return render(request, "solicitudes/list.html", {
        "solicitudes": qs[:200],
        "estados": SolicitudCaja.Estado.choices,
        "filtro": filtro,
    })


# ── Crear solicitud ──────────────────────────────────────────────────────────

@login_required
def solicitud_create(request):
    """
    Empleado crea una solicitud. Datos se autocompletan desde Perfil.
    Soporta guardar como BORRADOR o enviar directo a Gerencia Área.
    """
    perfil, _ = Perfil.objects.get_or_create(user=request.user)
    centros = CentroCosto.objects.filter(activo=True)

    if request.method == "POST":
        accion = request.POST.get("accion", "guardar")  # 'guardar' | 'enviar'
        return _solicitud_create_post(request, perfil, accion)

    # GET — render formulario
    contexto = {
        "perfil": perfil,
        "centros": centros,
        "tipos_cuenta": TipoCuenta.choices,
        "tipos_item": ItemSolicitud.TipoItem.choices,
        "hoy": date.today(),
    }
    return render(request, "solicitudes/create.html", contexto)


def _parse_decimal(s, default=Decimal("0")) -> Decimal:
    if s is None or s == "":
        return default
    try:
        return Decimal(str(s).replace(",", "").replace("$", "").strip())
    except (InvalidOperation, ValueError):
        return default


@transaction.atomic
def _solicitud_create_post(request, perfil, accion):
    """Procesa el POST de creación. Construye solicitud + items en una transacción."""
    P = request.POST

    # Cabecera
    ciudad           = P.get("ciudad", "").strip()
    nombre_completo  = P.get("nombre_completo", "").strip()
    cedula           = P.get("cedula", "").strip()
    valor_caja       = _parse_decimal(P.get("valor_caja"))
    entidad_bancaria = P.get("entidad_bancaria", "").strip()
    numero_cuenta    = P.get("numero_cuenta", "").strip()
    tipo_cuenta      = P.get("tipo_cuenta", "").strip()
    observaciones    = P.get("observaciones", "").strip()

    # Items en arrays paralelos (item[], centro[], cantidad[], valor[], obs[])
    items_tipo  = P.getlist("item_tipo")
    items_cc    = P.getlist("item_centro")
    items_cant  = P.getlist("item_cantidad")
    items_val   = P.getlist("item_valor")
    items_obs   = P.getlist("item_observaciones")

    errores = []
    if not ciudad:           errores.append("Ciudad es obligatoria.")
    if not nombre_completo:  errores.append("Nombre completo es obligatorio.")
    if not cedula:           errores.append("Cédula es obligatoria.")
    if valor_caja <= 0:      errores.append("El valor de la caja debe ser mayor a cero.")
    if not entidad_bancaria: errores.append("Entidad bancaria es obligatoria.")
    if not numero_cuenta:    errores.append("Número de cuenta es obligatorio.")
    if tipo_cuenta not in dict(TipoCuenta.choices):
        errores.append("Selecciona el tipo de cuenta.")

    items_validos = []
    for i, tipo in enumerate(items_tipo):
        tipo = (tipo or "").strip()
        if not tipo:
            continue  # fila vacía — la ignoramos
        cc_id   = items_cc[i] if i < len(items_cc) else ""
        cant    = _parse_decimal(items_cant[i] if i < len(items_cant) else "0")
        val     = _parse_decimal(items_val[i] if i < len(items_val) else "0")
        obs     = (items_obs[i] if i < len(items_obs) else "").strip()

        if tipo not in dict(ItemSolicitud.TipoItem.choices):
            errores.append(f"Fila {i+1}: ítem inválido.")
            continue
        if not cc_id:
            errores.append(f"Fila {i+1}: selecciona el centro de costos.")
            continue
        if cant <= 0:
            errores.append(f"Fila {i+1}: cantidad debe ser mayor a cero.")
            continue
        if val <= 0:
            errores.append(f"Fila {i+1}: valor unitario debe ser mayor a cero.")
            continue
        if tipo == ItemSolicitud.TipoItem.OTROS and not obs:
            errores.append(f"Fila {i+1}: 'Otros' requiere justificación en observaciones.")
            continue

        items_validos.append({
            "tipo": tipo,
            "cc_id": cc_id,
            "cantidad": cant,
            "valor": val,
            "obs": obs,
        })

    if not items_validos:
        errores.append("Debes agregar al menos un ítem antes de guardar.")

    # Si va a enviar a Gerencia Área, exige firma del empleado
    firma_archivo = request.FILES.get("firma_empleado")
    if accion == "enviar":
        msg = _validar_archivo_firma(firma_archivo)
        if msg:
            errores.append(msg)

    if errores:
        for e in errores:
            messages.error(request, e)
        return render(request, "solicitudes/create.html", {
            "perfil": perfil,
            "centros": CentroCosto.objects.filter(activo=True),
            "tipos_cuenta": TipoCuenta.choices,
            "tipos_item": ItemSolicitud.TipoItem.choices,
            "hoy": date.today(),
            "form_data": P,
        })

    # Crear solicitud
    sol = SolicitudCaja.objects.create(
        solicitante=request.user,
        fecha_solicitud=date.today(),
        ciudad=ciudad,
        nombre_completo=nombre_completo,
        cedula=cedula,
        valor_caja=valor_caja,
        entidad_bancaria=entidad_bancaria,
        numero_cuenta=numero_cuenta,
        tipo_cuenta=tipo_cuenta,
        observaciones=observaciones,
        estado=SolicitudCaja.Estado.BORRADOR,
    )

    # Crear items
    for it in items_validos:
        ItemSolicitud.objects.create(
            solicitud=sol,
            item=it["tipo"],
            centro_costo_id=it["cc_id"],
            cantidad=it["cantidad"],
            valor_unitario=it["valor"],
            observaciones=it["obs"],
        )

    # Si envía: adjuntar firma + cambiar estado + notificar
    if accion == "enviar":
        sol.firma_empleado = firma_archivo
        sol.firma_empleado_fecha = date.today()
        sol.estado = SolicitudCaja.Estado.PEND_AREA
        sol.save()

        for u in usuarios_grupo("Gerencia Área"):
            _notificar_sol(
                u, Notificacion.Tipo.SOL_ENVIADA_AREA,
                f"Nueva solicitud para revisar — {sol.codigo}",
                f"{sol.nombre_completo} solicita una caja por ${sol.valor_caja:,.0f}.",
                sol,
            )
        messages.success(request, f"Solicitud {sol.codigo} enviada a Gerencia Área.")
    else:
        messages.success(request, f"Solicitud {sol.codigo} guardada como borrador.")

    return redirect("solicitud_detail", pk=sol.pk)


# ── Detalle ──────────────────────────────────────────────────────────────────

@login_required
def solicitud_detail(request, pk):
    sol = get_object_or_404(
        SolicitudCaja.objects.select_related(
            "solicitante", "aprobador_area", "aprobador_corp"
        ).prefetch_related("items__centro_costo"),
        pk=pk,
    )

    user = request.user
    es_dueno = (sol.solicitante_id == user.pk)
    rol_area = es_gerencia_area(user)
    rol_corp = es_gerencia_corp(user)
    rol_caja = es_aprobador_caja(user)

    # Permisos básicos para ver
    if not (user.is_superuser or es_dueno or rol_area or rol_corp or rol_caja):
        return HttpResponseForbidden("No tienes acceso a esta solicitud.")

    # Acciones disponibles según rol y estado
    puede_editar  = es_dueno and sol.estado == SolicitudCaja.Estado.BORRADOR
    puede_enviar  = es_dueno and sol.estado == SolicitudCaja.Estado.BORRADOR
    puede_aprob_area = rol_area and sol.estado == SolicitudCaja.Estado.PEND_AREA
    puede_aprob_corp = rol_corp and sol.estado == SolicitudCaja.Estado.PEND_CORP
    puede_rechazar   = (
        (rol_area and sol.estado == SolicitudCaja.Estado.PEND_AREA) or
        (rol_corp and sol.estado == SolicitudCaja.Estado.PEND_CORP)
    )
    puede_desembolsar = rol_caja and sol.estado == SolicitudCaja.Estado.APROBADA

    contexto = {
        "sol": sol,
        "items": sol.items.all(),
        "total_items": sol.total_items(),
        "puede_editar": puede_editar,
        "puede_enviar": puede_enviar,
        "puede_aprob_area": puede_aprob_area,
        "puede_aprob_corp": puede_aprob_corp,
        "puede_rechazar": puede_rechazar,
        "puede_desembolsar": puede_desembolsar,
    }
    return render(request, "solicitudes/detail.html", contexto)


# ── Acciones (POST) ──────────────────────────────────────────────────────────

@login_required
@require_POST
def solicitud_enviar(request, pk):
    """Empleado envía su BORRADOR a Gerencia Área (requiere firma)."""
    sol = get_object_or_404(SolicitudCaja, pk=pk)

    if sol.solicitante_id != request.user.pk:
        return HttpResponseForbidden("Solo el solicitante puede enviar.")
    if sol.estado != SolicitudCaja.Estado.BORRADOR:
        messages.error(request, "Esta solicitud ya fue enviada.")
        return redirect("solicitud_detail", pk=pk)
    if not sol.items.exists():
        messages.error(request, "Agrega al menos un ítem antes de enviar.")
        return redirect("solicitud_detail", pk=pk)

    firma = request.FILES.get("firma_empleado")
    msg = _validar_archivo_firma(firma)
    if msg:
        messages.error(request, msg)
        return redirect("solicitud_detail", pk=pk)

    sol.firma_empleado = firma
    sol.firma_empleado_fecha = date.today()
    sol.estado = SolicitudCaja.Estado.PEND_AREA
    sol.save()

    for u in usuarios_grupo("Gerencia Área"):
        _notificar_sol(
            u, Notificacion.Tipo.SOL_ENVIADA_AREA,
            f"Nueva solicitud para revisar — {sol.codigo}",
            f"{sol.nombre_completo} solicita una caja por ${sol.valor_caja:,.0f}.",
            sol,
        )

    messages.success(request, "Solicitud enviada a Gerencia Área.")
    return redirect("solicitud_detail", pk=pk)


@login_required
@require_POST
def solicitud_aprobar_area(request, pk):
    sol = get_object_or_404(SolicitudCaja, pk=pk)

    if not es_gerencia_area(request.user):
        return HttpResponseForbidden("Solo Gerencia Área puede aprobar este paso.")
    if sol.estado != SolicitudCaja.Estado.PEND_AREA:
        messages.error(request, "Esta solicitud no está pendiente de Gerencia Área.")
        return redirect("solicitud_detail", pk=pk)

    firma = request.FILES.get("firma_area")
    msg = _validar_archivo_firma(firma)
    if msg:
        messages.error(request, msg)
        return redirect("solicitud_detail", pk=pk)

    sol.aprobador_area = request.user
    sol.firma_area = firma
    sol.firma_area_fecha = date.today()
    sol.estado = SolicitudCaja.Estado.PEND_CORP
    sol.save()

    # Notificar al empleado y a Gerencia Corporativa
    _notificar_sol(
        sol.solicitante, Notificacion.Tipo.SOL_APROBADA_AREA,
        f"Tu solicitud {sol.codigo} fue aprobada por Gerencia Área",
        "Ahora pasa a aprobación de Gerencia Corporativa.",
        sol,
    )
    for u in usuarios_grupo("Gerencia Corporativa"):
        _notificar_sol(
            u, Notificacion.Tipo.SOL_ENVIADA_AREA,
            f"Solicitud para aprobación corporativa — {sol.codigo}",
            f"{sol.nombre_completo} — ${sol.valor_caja:,.0f}.",
            sol,
        )

    messages.success(request, "Aprobada por Gerencia Área. Pasa a Corporativa.")
    return redirect("solicitud_detail", pk=pk)


@login_required
@require_POST
def solicitud_aprobar_corp(request, pk):
    sol = get_object_or_404(SolicitudCaja, pk=pk)

    if not es_gerencia_corp(request.user):
        return HttpResponseForbidden("Solo Gerencia Corporativa puede aprobar este paso.")
    if sol.estado != SolicitudCaja.Estado.PEND_CORP:
        messages.error(request, "Esta solicitud no está pendiente de Gerencia Corporativa.")
        return redirect("solicitud_detail", pk=pk)

    firma = request.FILES.get("firma_corp")
    msg = _validar_archivo_firma(firma)
    if msg:
        messages.error(request, msg)
        return redirect("solicitud_detail", pk=pk)

    sol.aprobador_corp = request.user
    sol.firma_corp = firma
    sol.firma_corp_fecha = date.today()
    sol.estado = SolicitudCaja.Estado.APROBADA
    sol.save()

    # Notificar al empleado y a Tesorería (Aprobadores)
    _notificar_sol(
        sol.solicitante, Notificacion.Tipo.SOL_APROBADA_CORP,
        f"Tu solicitud {sol.codigo} fue aprobada — pendiente desembolso",
        "Tesorería desembolsará los fondos próximamente.",
        sol,
    )
    for u in usuarios_grupo("Aprobadores"):
        _notificar_sol(
            u, Notificacion.Tipo.SOL_APROBADA_CORP,
            f"Solicitud lista para desembolsar — {sol.codigo}",
            f"{sol.nombre_completo} — ${sol.valor_caja:,.0f}.",
            sol,
        )

    messages.success(request, "Aprobada por Gerencia Corporativa.")
    return redirect("solicitud_detail", pk=pk)


@login_required
@require_POST
def solicitud_rechazar(request, pk):
    sol = get_object_or_404(SolicitudCaja, pk=pk)

    user = request.user
    autorizado = (
        (es_gerencia_area(user) and sol.estado == SolicitudCaja.Estado.PEND_AREA) or
        (es_gerencia_corp(user) and sol.estado == SolicitudCaja.Estado.PEND_CORP)
    )
    if not autorizado:
        return HttpResponseForbidden("No puedes rechazar en este paso.")

    motivo = request.POST.get("motivo", "").strip()
    if not motivo:
        messages.error(request, "Debes indicar el motivo del rechazo.")
        return redirect("solicitud_detail", pk=pk)

    sol.estado = SolicitudCaja.Estado.RECHAZADA
    sol.motivo_rechazo = motivo
    sol.save()

    _notificar_sol(
        sol.solicitante, Notificacion.Tipo.SOL_RECHAZADA,
        f"Tu solicitud {sol.codigo} fue rechazada",
        motivo,
        sol,
    )
    messages.success(request, "Solicitud rechazada.")
    return redirect("solicitud_detail", pk=pk)


@login_required
@require_POST
def solicitud_desembolsar(request, pk):
    """
    Tesorería marca el desembolso. Esto dispara la creación de la Legalización
    asociada (Fase 6 lo conecta — por ahora solo cambia el estado).
    """
    sol = get_object_or_404(SolicitudCaja, pk=pk)

    if not es_aprobador_caja(request.user):
        return HttpResponseForbidden("Solo tesorería puede registrar el desembolso.")
    if sol.estado != SolicitudCaja.Estado.APROBADA:
        messages.error(request, "Solo solicitudes APROBADAS pueden desembolsarse.")
        return redirect("solicitud_detail", pk=pk)

    fecha_str = request.POST.get("fecha_desembolso", "").strip()
    try:
        from datetime import datetime
        fecha = datetime.strptime(fecha_str, "%Y-%m-%d").date()
    except (ValueError, TypeError):
        messages.error(request, "Fecha de desembolso inválida.")
        return redirect("solicitud_detail", pk=pk)

    sol.fecha_desembolso = fecha
    sol.estado = SolicitudCaja.Estado.DESEMBOLSADA
    sol.save()

    # En Fase 6 acá creamos la Legalización + fecha_cierre = +8 días hábiles
    _notificar_sol(
        sol.solicitante, Notificacion.Tipo.SOL_DESEMBOLSADA,
        f"Caja desembolsada — {sol.codigo}",
        f"Tu caja por ${sol.valor_caja:,.0f} fue desembolsada el {fecha.strftime('%d/%m/%Y')}.",
        sol,
    )
    messages.success(request, "Desembolso registrado.")
    return redirect("solicitud_detail", pk=pk)


# ── Perfil del empleado ──────────────────────────────────────────────────────

@login_required
def perfil_editar(request):
    perfil, _ = Perfil.objects.get_or_create(user=request.user)

    if request.method == "POST":
        perfil.nombre_completo  = request.POST.get("nombre_completo", "").strip()
        perfil.cedula           = request.POST.get("cedula", "").strip()
        perfil.ciudad           = request.POST.get("ciudad", "").strip()
        perfil.entidad_bancaria = request.POST.get("entidad_bancaria", "").strip()
        perfil.numero_cuenta    = request.POST.get("numero_cuenta", "").strip()
        perfil.tipo_cuenta      = request.POST.get("tipo_cuenta", "").strip()

        firma = request.FILES.get("firma_imagen")
        if firma:
            msg = _validar_archivo_firma(firma)
            if msg:
                messages.error(request, msg)
                return redirect("perfil_editar")
            perfil.firma_imagen = firma

        try:
            perfil.full_clean()
            perfil.save()
            messages.success(request, "Perfil actualizado.")
        except Exception as e:
            messages.error(request, f"Error al guardar: {e}")

        return redirect("perfil_editar")

    return render(request, "solicitudes/perfil.html", {
        "perfil": perfil,
        "tipos_cuenta": TipoCuenta.choices,
    })
