from datetime import date
from decimal import Decimal

from django.contrib import messages
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.db import transaction
from django.db.models import Case, Count, DecimalField, Q, Sum, Value, When
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.timesince import timesince
from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from legalizaciones.models import Gasto, Legalizacion, Notificacion, SolicitudCaja


# ── Helper de notificaciones ──────────────────────────────────────────────────

def _notificar(destinatario, tipo, titulo, mensaje, url, legalizacion=None):
    """Crea una notificación en la base de datos."""
    Notificacion.objects.create(
        destinatario=destinatario,
        tipo=tipo,
        titulo=titulo,
        mensaje=mensaje,
        url=url,
        legalizacion=legalizacion,
    )


def _aprobadores():
    """Devuelve el queryset de usuarios aprobadores (superusers + grupo Aprobadores)."""
    return User.objects.filter(
        Q(is_superuser=True) | Q(groups__name="Aprobadores")
    ).distinct()


# ── Autenticación ─────────────────────────────────────────────────────────────

def login_view(request):
    if request.user.is_authenticated:
        return redirect("dashboard")
    if request.method == "POST":
        username = request.POST.get("username")
        password = request.POST.get("password")
        user = authenticate(request, username=username, password=password)
        if user:
            login(request, user)
            return redirect(request.GET.get("next", "dashboard"))
        messages.error(request, "Usuario o contraseña incorrectos.")
    return render(request, "auth/login.html")


def logout_view(request):
    logout(request)
    return redirect("login")


# ── Dashboard ─────────────────────────────────────────────────────────────────

@never_cache
@login_required
def dashboard(request):
    user = request.user
    es_aprobador  = user.is_superuser or user.groups.filter(name="Aprobadores").exists()
    es_ger_area   = user.is_superuser or user.groups.filter(name="Gerencia Área").exists()
    es_ger_corp   = user.is_superuser or user.groups.filter(name="Gerencia Corporativa").exists()

    # ── Legalizaciones ────────────────────────────────────────────────────
    qs_leg = Legalizacion.objects.all() if es_aprobador else Legalizacion.objects.filter(elaboro=user)

    stats_leg = qs_leg.aggregate(
        total=Count("numero"),
        monto_total=Sum("monto_aprobado"),
        saldo_total=Sum("saldo"),
        # saldo > 0 → empleado gastó menos → empresa recupera dinero
        saldo_empresa=Sum(
            Case(
                When(saldo__gt=0, then="saldo"),
                default=Value(Decimal("0")),
                output_field=DecimalField(),
            )
        ),
        # saldo < 0 → empleado gastó más → empresa debe al empleado (guardamos como positivo)
        saldo_empleado=Sum(
            Case(
                When(saldo__lt=0, then="saldo"),
                default=Value(Decimal("0")),
                output_field=DecimalField(),
            )
        ),
        borradores=Count("numero", filter=Q(estado=Legalizacion.Estado.BORRADOR)),
        enviadas=Count("numero", filter=Q(estado=Legalizacion.Estado.ENVIADO)),
        aprobadas=Count("numero", filter=Q(estado=Legalizacion.Estado.APROBADO)),
        rechazadas=Count("numero", filter=Q(estado=Legalizacion.Estado.RECHAZADO)),
        devueltas=Count("numero", filter=Q(estado=Legalizacion.Estado.DEVUELTO)),
    )
    recientes_leg = qs_leg.select_related("elaboro", "elaboro__perfil").order_by("-creado_en")[:5]

    # ── Solicitudes de Caja ───────────────────────────────────────────────
    if user.is_superuser:
        qs_sol = SolicitudCaja.objects.all()
    elif es_ger_corp:
        qs_sol = SolicitudCaja.objects.all()
    elif es_ger_area:
        qs_sol = SolicitudCaja.objects.all()
    else:
        qs_sol = SolicitudCaja.objects.filter(solicitante=user)

    stats_sol = qs_sol.aggregate(
        total=Count("numero"),
        monto_total=Sum("valor_caja"),
        borradores=Count("numero", filter=Q(estado=SolicitudCaja.Estado.BORRADOR)),
        pend_area=Count("numero", filter=Q(estado=SolicitudCaja.Estado.PEND_AREA)),
        pend_corp=Count("numero", filter=Q(estado=SolicitudCaja.Estado.PEND_CORP)),
        aprobadas=Count("numero", filter=Q(estado=SolicitudCaja.Estado.APROBADA)),
        desembolsadas=Count("numero", filter=Q(estado=SolicitudCaja.Estado.DESEMBOLSADA)),
        legalizadas=Count("numero", filter=Q(estado=SolicitudCaja.Estado.LEGALIZADA)),
        rechazadas=Count("numero", filter=Q(estado=SolicitudCaja.Estado.RECHAZADA)),
    )
    recientes_sol = qs_sol.select_related("solicitante", "solicitante__perfil").order_by("-creado_en")[:5]

    # ── Acciones pendientes según rol ─────────────────────────────────────
    acciones = []
    if es_ger_area:
        n = SolicitudCaja.objects.filter(estado=SolicitudCaja.Estado.PEND_AREA).count()
        if n:
            acciones.append({"texto": f"{n} solicitud{'es' if n > 1 else ''} esperando aprobación de Área", "url": "solicitud_list", "color": "amber"})
    if es_ger_corp:
        n = SolicitudCaja.objects.filter(estado=SolicitudCaja.Estado.PEND_CORP).count()
        if n:
            acciones.append({"texto": f"{n} solicitud{'es' if n > 1 else ''} esperando aprobación Corporativa", "url": "solicitud_list", "color": "orange"})
    if es_aprobador:
        n = Legalizacion.objects.filter(estado=Legalizacion.Estado.ENVIADO).count()
        if n:
            acciones.append({"texto": f"{n} legalización{'es' if n > 1 else ''} pendiente{'s' if n > 1 else ''} de revisión", "url": "legalizacion_list", "color": "violet"})

    stats_leg["rech_dev"] = (stats_leg.get("rechazadas") or 0) + (stats_leg.get("devueltas") or 0)
    stats_sol["pend_total"] = (stats_sol.get("pend_area") or 0) + (stats_sol.get("pend_corp") or 0)

    context = {
        "stats_leg": stats_leg,
        "stats_sol": stats_sol,
        "recientes_leg": recientes_leg,
        "recientes_sol": recientes_sol,
        "es_aprobador": es_aprobador,
        "es_ger_area": es_ger_area,
        "es_ger_corp": es_ger_corp,
        "acciones": acciones,
    }
    return render(request, "dashboard/index.html", context)


# ── Legalizaciones ────────────────────────────────────────────────────────────

@never_cache
@login_required
def legalizacion_list(request):
    user = request.user
    es_aprobador = user.is_superuser or user.groups.filter(name="Aprobadores").exists()
    qs = Legalizacion.objects.all() if es_aprobador else Legalizacion.objects.filter(elaboro=user)
    qs = qs.select_related("elaboro", "aprobado_por").prefetch_related("gastos")

    estado = request.GET.get("estado", "")
    buscar = request.GET.get("buscar", "")

    if estado:
        qs = qs.filter(estado=estado)
    if buscar:
        qs = qs.filter(
            Q(elaboro__username__icontains=buscar)
            | Q(elaboro__first_name__icontains=buscar)
            | Q(elaboro__last_name__icontains=buscar)
        )

    qs = qs.order_by("-fecha_solicitud")

    context = {
        "legalizaciones": qs,
        "estados": Legalizacion.Estado.choices,
        "estado_filtro": estado,
        "buscar": buscar,
        "es_aprobador": es_aprobador,
    }

    if request.headers.get("HX-Request"):
        return render(request, "legalizaciones/partials/tabla.html", context)
    return render(request, "legalizaciones/list.html", context)


@never_cache
@login_required
def legalizacion_create(request):
    # Crear legalizaciones standalone solo está disponible para administradores.
    # El flujo normal genera la legalización automáticamente al desembolsar una caja.
    if not request.user.is_superuser:
        messages.error(
            request,
            "Las legalizaciones se generan automáticamente al desembolsar una caja. "
            "Solicita una caja menor para iniciar el proceso.",
        )
        return redirect("solicitud_create")

    if request.method == "POST":
        try:
            monto = request.POST.get("monto_aprobado")
            fecha = date.today()   # siempre la fecha real del servidor
            periodo_desde = request.POST.get("periodo_desde") or None
            periodo_hasta = request.POST.get("periodo_hasta") or None

            leg = Legalizacion.objects.create(
                monto_aprobado=Decimal(monto),
                fecha_solicitud=fecha,
                periodo_desde=periodo_desde,
                periodo_hasta=periodo_hasta,
                fecha_consignacion=None,
                elaboro=request.user,
                estado=Legalizacion.Estado.BORRADOR,  # siempre inicia en Borrador
            )

            fechas        = request.POST.getlist("gasto_fecha[]")
            proveedores   = request.POST.getlist("gasto_proveedor[]")
            nits          = request.POST.getlist("gasto_nit[]")
            facturas      = request.POST.getlist("gasto_factura[]")
            centros       = request.POST.getlist("gasto_centro[]")
            bases         = request.POST.getlist("gasto_valor_base[]")
            ivas          = request.POST.getlist("gasto_iva[]")
            observaciones = request.POST.getlist("gasto_obs[]")
            archivos      = request.FILES.getlist("gasto_archivo[]")

            for i in range(len(fechas)):
                if fechas[i] and bases[i]:
                    archivo = archivos[i] if i < len(archivos) else None
                    Gasto.objects.create(
                        legalizacion=leg,
                        fecha=fechas[i],
                        cliente_proveedor=proveedores[i],
                        cedula_nit=nits[i],
                        numero_factura=facturas[i],
                        centro_costos=centros[i],
                        valor_base=Decimal(bases[i]),
                        iva=Decimal(ivas[i]) if ivas[i] else Decimal("0"),
                        observaciones=observaciones[i] or None,
                        archivo_factura=archivo or None,
                    )

            leg.recalcular_saldo(save=True)
            messages.success(request, "Legalización creada correctamente.")
            return redirect("legalizacion_detail", pk=leg.pk)
        except Exception as e:
            messages.error(request, f"Error al crear la legalización: {e}")

    return render(request, "legalizaciones/create.html", {})


@never_cache
@never_cache
@login_required
def legalizacion_detail(request, pk):
    user = request.user
    es_aprobador = user.is_superuser or user.groups.filter(name="Aprobadores").exists()
    leg = get_object_or_404(Legalizacion, pk=pk)

    if not es_aprobador and leg.elaboro != user:
        messages.error(request, "No tienes permiso para ver esta legalización.")
        return redirect("legalizacion_list")

    gastos = leg.gastos.all()
    gastos_activos = gastos.filter(rechazado=False)
    total_gastos = gastos_activos.aggregate(t=Sum("valor"))["t"] or Decimal("0")

    # EXISTS es más eficiente que count() > 0: detiene el scan al primer resultado.
    tiene_gastos = gastos_activos.exists()

    # ¿Puede agregar/editar gastos?
    # - Elaborador (empleado) en estado BORRADOR o DEVUELTO
    # - Superusuario siempre (para gestión y pruebas)
    puede_editar_gastos = (
        leg.estado in (Legalizacion.Estado.BORRADOR, Legalizacion.Estado.DEVUELTO)
        and (leg.elaboro == user or user.is_superuser)
    )

    context = {
        "leg": leg,
        "gastos": gastos,
        "total_gastos": total_gastos,
        "tiene_gastos": tiene_gastos,
        "es_aprobador": es_aprobador,
        "puede_editar": leg.estado in (Legalizacion.Estado.BORRADOR, Legalizacion.Estado.ENVIADO),
        "puede_editar_gastos": puede_editar_gastos,
    }
    return render(request, "legalizaciones/detail.html", context)


@login_required
@require_POST
def legalizacion_aprobar(request, pk):
    user = request.user
    es_aprobador = user.is_superuser or user.groups.filter(name="Aprobadores").exists()
    if not es_aprobador:
        messages.error(request, "No tienes permiso para aprobar legalizaciones.")
        return redirect("legalizacion_detail", pk=pk)

    justificacion = request.POST.get("justificacion", "").strip()
    if not justificacion:
        messages.error(request, "Debes ingresar una justificación para aprobar la legalización.")
        return redirect("legalizacion_detail", pk=pk)

    leg = get_object_or_404(Legalizacion, pk=pk)
    if leg.estado != Legalizacion.Estado.ENVIADO:
        messages.error(request, "Solo se pueden aprobar legalizaciones en estado Enviado.")
        return redirect("legalizacion_detail", pk=pk)

    # Segregación de funciones: un aprobador no puede aprobar lo que él mismo elaboró.
    # Superusuario mantiene la capacidad de override (admin de respaldo).
    if leg.elaboro_id == user.pk and not user.is_superuser:
        messages.error(request, "No puedes aprobar tu propia legalización.")
        return redirect("legalizacion_detail", pk=pk)

    with transaction.atomic():
        leg.estado = Legalizacion.Estado.APROBADO
        leg.aprobado_por = user
        leg.motivo_aprobador = justificacion
        leg.fecha_aprobacion = date.today()
        leg.save()

        # Si esta legalización proviene de una solicitud, marcarla como LEGALIZADA
        if leg.solicitud_id:
            SolicitudCaja.objects.filter(pk=leg.solicitud_id).update(
                estado=SolicitudCaja.Estado.LEGALIZADA
            )

    _notificar(
        destinatario=leg.elaboro,
        tipo=Notificacion.Tipo.APROBADA,
        titulo=f"Legalización {leg.codigo} aprobada",
        mensaje=f"Tu legalización fue aprobada por {user.get_full_name() or user.username}. {justificacion}",
        url=reverse("legalizacion_detail", args=[leg.pk]),
        legalizacion=leg,
    )

    messages.success(request, "Legalización aprobada correctamente.")
    return redirect("legalizacion_detail", pk=pk)


@login_required
@require_POST
def legalizacion_rechazar(request, pk):
    user = request.user
    es_aprobador = user.is_superuser or user.groups.filter(name="Aprobadores").exists()
    if not es_aprobador:
        messages.error(request, "No tienes permiso para rechazar legalizaciones.")
        return redirect("legalizacion_detail", pk=pk)

    motivo = request.POST.get("motivo", "").strip()
    if not motivo:
        messages.error(request, "Debes ingresar el motivo de rechazo.")
        return redirect("legalizacion_detail", pk=pk)

    leg = get_object_or_404(Legalizacion, pk=pk)
    if leg.estado != Legalizacion.Estado.ENVIADO:
        messages.error(request, "Solo se pueden rechazar legalizaciones en estado Enviado.")
        return redirect("legalizacion_detail", pk=pk)

    # Segregación de funciones (ver legalizacion_aprobar).
    if leg.elaboro_id == user.pk and not user.is_superuser:
        messages.error(request, "No puedes rechazar tu propia legalización.")
        return redirect("legalizacion_detail", pk=pk)

    leg.estado = Legalizacion.Estado.RECHAZADO
    leg.aprobado_por = user
    leg.motivo_aprobador = motivo
    leg.save()

    _notificar(
        destinatario=leg.elaboro,
        tipo=Notificacion.Tipo.RECHAZADA,
        titulo=f"Legalización {leg.codigo} rechazada",
        mensaje=f"Tu legalización fue rechazada por {user.get_full_name() or user.username}. Motivo: {motivo}",
        url=reverse("legalizacion_detail", args=[leg.pk]),
        legalizacion=leg,
    )

    messages.error(request, "Legalización rechazada.")
    return redirect("legalizacion_detail", pk=pk)


@login_required
@require_POST
def legalizacion_set_consignacion(request, pk):
    """Solo aprobadores pueden registrar la fecha de consignación."""
    user = request.user
    es_aprobador = user.is_superuser or user.groups.filter(name="Aprobadores").exists()
    if not es_aprobador:
        messages.error(request, "No tienes permiso para registrar la fecha de consignación.")
        return redirect("legalizacion_detail", pk=pk)

    leg = get_object_or_404(Legalizacion, pk=pk)
    fecha = request.POST.get("fecha_consignacion", "").strip()

    if not fecha:
        messages.error(request, "Debes ingresar una fecha de consignación válida.")
        return redirect("legalizacion_detail", pk=pk)

    from datetime import datetime
    try:
        f = datetime.strptime(fecha, "%Y-%m-%d").date()
        if f < leg.fecha_solicitud:
            messages.error(request, "La fecha de consignación no puede ser anterior a la fecha de solicitud.")
            return redirect("legalizacion_detail", pk=pk)
        leg.fecha_consignacion = f
        leg.save()
        messages.success(request, "Fecha de consignación registrada correctamente.")
    except ValueError:
        messages.error(request, "Formato de fecha inválido.")

    return redirect("legalizacion_detail", pk=pk)


@login_required
@require_POST
def legalizacion_editar_cabecera(request, pk):
    """Solo aprobadores y administradores pueden editar el monto aprobado de una legalización."""
    user = request.user
    es_aprobador = user.is_superuser or user.groups.filter(name="Aprobadores").exists()
    if not es_aprobador:
        messages.error(request, "Solo los aprobadores pueden modificar el monto de una legalización.")
        return redirect("legalizacion_detail", pk=pk)

    leg = get_object_or_404(Legalizacion, pk=pk)

    if leg.estado not in (Legalizacion.Estado.BORRADOR, Legalizacion.Estado.DEVUELTO):
        messages.error(request, "Solo se pueden editar los datos en estado Borrador o Devuelto.")
        return redirect("legalizacion_detail", pk=pk)

    try:
        monto = request.POST.get("monto_aprobado", "").strip()

        if not monto or Decimal(monto) <= 0:
            messages.error(request, "El monto aprobado debe ser mayor a cero.")
            return redirect("legalizacion_detail", pk=pk)

        leg.monto_aprobado = Decimal(monto)
        leg.full_clean()
        leg.save()
        leg.recalcular_saldo(save=True)
        messages.success(request, "Monto de la legalización actualizado.")
    except Exception as e:
        messages.error(request, f"Error al guardar: {e}")

    return redirect("legalizacion_detail", pk=pk)


@login_required
@require_POST
def legalizacion_set_cierre(request, pk):
    """Solo aprobadores pueden registrar la fecha de cierre."""
    user = request.user
    es_aprobador = user.is_superuser or user.groups.filter(name="Aprobadores").exists()
    if not es_aprobador:
        messages.error(request, "No tienes permiso para registrar la fecha de cierre.")
        return redirect("legalizacion_detail", pk=pk)

    leg = get_object_or_404(Legalizacion, pk=pk)
    fecha = request.POST.get("fecha_cierre", "").strip()

    if not fecha:
        messages.error(request, "Debes ingresar una fecha de cierre válida.")
        return redirect("legalizacion_detail", pk=pk)

    from datetime import datetime
    try:
        f = datetime.strptime(fecha, "%Y-%m-%d").date()
        leg.fecha_cierre = f
        leg.save()
        messages.success(request, "Fecha de cierre registrada correctamente.")
    except ValueError:
        messages.error(request, "Formato de fecha inválido.")

    return redirect("legalizacion_detail", pk=pk)


@login_required
@require_POST
def ocr_factura(request):
    """Analiza una factura (foto o PDF) con OCR y devuelve los campos detectados."""
    archivo = request.FILES.get("archivo")
    if not archivo:
        return JsonResponse({"ok": False, "mensaje": "No se recibió ningún archivo."}, status=400)

    # Validar tamaño (máx 10 MB)
    if archivo.size > 10 * 1024 * 1024:
        return JsonResponse({"ok": False, "mensaje": "El archivo supera el límite de 10 MB."}, status=400)

    from legalizaciones.ocr import analizar_archivo
    resultado = analizar_archivo(archivo, archivo.content_type)
    return JsonResponse(resultado)


@login_required
@require_POST
def legalizacion_enviar(request, pk):
    leg = get_object_or_404(Legalizacion, pk=pk, elaboro=request.user)
    if leg.estado in (Legalizacion.Estado.BORRADOR, Legalizacion.Estado.DEVUELTO):
        # Regla de negocio: una legalización sin gastos no tiene sentido.
        # EXISTS evita un COUNT completo; se detiene al primer resultado.
        if not leg.gastos.filter(rechazado=False).exists():
            messages.error(
                request,
                "Debes agregar al menos un gasto antes de enviar la legalización.",
            )
            return redirect("legalizacion_detail", pk=pk)

        leg.estado = Legalizacion.Estado.ENVIADO
        leg.save()

        elaboro_nombre = request.user.get_full_name() or request.user.username
        url_leg = reverse("legalizacion_detail", args=[leg.pk])
        for aprobador in _aprobadores().exclude(pk=request.user.pk):
            _notificar(
                destinatario=aprobador,
                tipo=Notificacion.Tipo.ENVIADA,
                titulo=f"Nueva legalización enviada — {leg.codigo}",
                mensaje=f"{elaboro_nombre} envió {leg.codigo} por ${leg.monto_aprobado} para revisión.",
                url=url_leg,
                legalizacion=leg,
            )

        messages.success(request, "Legalización enviada para aprobación.")
    return redirect("legalizacion_detail", pk=pk)


@login_required
@require_POST
def legalizacion_devolver(request, pk):
    """Aprobador devuelve la legalización al empleado para que corrija gastos rechazados."""
    user = request.user
    es_aprobador = user.is_superuser or user.groups.filter(name="Aprobadores").exists()
    if not es_aprobador:
        messages.error(request, "No tienes permiso para devolver legalizaciones.")
        return redirect("legalizacion_detail", pk=pk)

    leg = get_object_or_404(Legalizacion, pk=pk)
    if leg.estado != Legalizacion.Estado.ENVIADO:
        messages.error(request, "Solo se pueden devolver legalizaciones en estado Enviado.")
        return redirect("legalizacion_detail", pk=pk)

    # Segregación de funciones (ver legalizacion_aprobar).
    if leg.elaboro_id == user.pk and not user.is_superuser:
        messages.error(request, "No puedes devolver tu propia legalización.")
        return redirect("legalizacion_detail", pk=pk)

    comentario = request.POST.get("comentario", "").strip()

    leg.estado = Legalizacion.Estado.DEVUELTO
    leg.aprobado_por = user
    if comentario:
        leg.motivo_aprobador = comentario
    leg.save()

    msg_notif = "Revisa los gastos rechazados, corrígelos y reenvía la legalización."
    if comentario:
        msg_notif = f"{comentario} — Revisa los gastos indicados, corrígelos y reenvía."

    _notificar(
        destinatario=leg.elaboro,
        tipo=Notificacion.Tipo.DEVUELTA,
        titulo=f"Legalización {leg.codigo} devuelta para corrección",
        mensaje=msg_notif,
        url=reverse("legalizacion_detail", args=[leg.pk]),
        legalizacion=leg,
    )

    messages.warning(request, "Legalización devuelta al empleado para corrección.")
    return redirect("legalizacion_detail", pk=pk)


@login_required
def gasto_crear(request, leg_pk):
    """Empleado (o superusuario) agrega uno o varios gastos a una legalización en BORRADOR o DEVUELTO."""
    from legalizaciones.models import CentroCosto, Gasto
    leg = get_object_or_404(Legalizacion, pk=leg_pk)
    user = request.user

    puede = (
        leg.estado in (Legalizacion.Estado.BORRADOR, Legalizacion.Estado.DEVUELTO)
        and (leg.elaboro == user or user.is_superuser)
    )
    if not puede:
        messages.error(request, "No puedes agregar gastos a esta legalización en su estado actual.")
        return redirect("legalizacion_detail", pk=leg_pk)

    centros = CentroCosto.objects.filter(activo=True)

    if request.method == "POST":
        fechas       = request.POST.getlist("fecha[]")
        proveedores  = request.POST.getlist("cliente_proveedor[]")
        nits         = request.POST.getlist("cedula_nit[]")
        facturas     = request.POST.getlist("numero_factura[]")
        centros_post = request.POST.getlist("centro_costos[]")
        bases        = request.POST.getlist("valor_base[]")
        ivas         = request.POST.getlist("iva_porcentaje[]")
        obs_list     = request.POST.getlist("observaciones[]")

        def _v(lst, i, default=""):
            return lst[i].strip() if i < len(lst) else default

        guardados, errores = 0, []
        for i, fecha in enumerate(fechas):
            base_str = _v(bases, i)
            if not fecha.strip() or not base_str:
                continue
            try:
                iva_pct = int(_v(ivas, i, "19") or "19")
                if iva_pct not in (0, 5, 19):
                    iva_pct = 19
                gasto = Gasto(
                    legalizacion=leg,
                    fecha=fecha.strip(),
                    cliente_proveedor=_v(proveedores, i),
                    cedula_nit=_v(nits, i),
                    numero_factura=_v(facturas, i),
                    centro_costos=_v(centros_post, i),
                    valor_base=Decimal(base_str),
                    iva_porcentaje=iva_pct,
                    observaciones=_v(obs_list, i) or None,
                )
                key = f"archivo_{i}"
                if key in request.FILES:
                    gasto.archivo_factura = request.FILES[key]
                gasto.full_clean()
                gasto.save()   # save() calcula iva y valor automáticamente
                guardados += 1
            except Exception as exc:
                errores.append(f"Gasto {i + 1}: {exc}")

        for err in errores:
            messages.error(request, err)
        if guardados > 0:
            leg.recalcular_saldo(save=True)
            txt = "Gasto registrado" if guardados == 1 else f"{guardados} gastos registrados"
            messages.success(request, f"{txt} correctamente.")
            return redirect("legalizacion_detail", pk=leg_pk)
        elif not errores:
            messages.error(request, "No se encontraron datos válidos para guardar.")

    return render(request, "legalizaciones/crear_gasto.html", {
        "leg": leg,
        "centros": centros,
        "iva_opciones": [(0, "0 %"), (5, "5 %"), (19, "19 %")],
    })


@login_required
def gasto_editar(request, pk):
    """Empleado edita un gasto rechazado mientras la legalización está en estado DEVUELTO."""
    gasto = get_object_or_404(Gasto, pk=pk)
    leg = gasto.legalizacion

    if leg.elaboro != request.user:
        messages.error(request, "No tienes permiso para editar este gasto.")
        return redirect("legalizacion_detail", pk=leg.pk)

    if leg.estado not in (Legalizacion.Estado.BORRADOR, Legalizacion.Estado.DEVUELTO):
        messages.error(request, "Solo se pueden editar gastos de legalizaciones en borrador o devueltas para corrección.")
        return redirect("legalizacion_detail", pk=leg.pk)

    if request.method == "POST":
        try:
            iva_pct = int(request.POST.get("iva_porcentaje") or "19")
            if iva_pct not in (0, 5, 19):
                iva_pct = 19
            gasto.fecha = request.POST.get("fecha")
            gasto.cliente_proveedor = request.POST.get("cliente_proveedor", "").strip()
            gasto.cedula_nit = request.POST.get("cedula_nit", "").strip()
            gasto.numero_factura = request.POST.get("numero_factura", "").strip()
            gasto.centro_costos = request.POST.get("centro_costos", "").strip()
            gasto.valor_base = Decimal(request.POST.get("valor_base") or "0")
            gasto.iva_porcentaje = iva_pct
            gasto.observaciones = request.POST.get("observaciones", "").strip() or None
            if "archivo_factura" in request.FILES:
                gasto.archivo_factura = request.FILES["archivo_factura"]
            gasto.rechazado = False
            gasto.motivo_rechazo = None
            gasto.full_clean()
            gasto.save()   # save() recalcula iva y valor
            leg.recalcular_saldo(save=True)
            messages.success(request, "Gasto actualizado correctamente.")
            return redirect("legalizacion_detail", pk=leg.pk)
        except Exception as e:
            messages.error(request, f"Error al guardar el gasto: {e}")

    context = {
        "gasto": gasto,
        "leg": leg,
        "iva_opciones": [(0, "0 %"), (5, "5 %"), (19, "19 %")],
    }
    return render(request, "legalizaciones/editar_gasto.html", context)


@login_required
@require_POST
def gasto_rechazar(request, pk):
    """Aprobador rechaza un gasto específico con un motivo obligatorio."""
    user = request.user
    es_aprobador = user.is_superuser or user.groups.filter(name="Aprobadores").exists()
    if not es_aprobador:
        messages.error(request, "No tienes permiso para rechazar gastos.")
        return redirect("legalizacion_list")

    gasto = get_object_or_404(Gasto, pk=pk)
    leg = gasto.legalizacion

    if leg.estado != Legalizacion.Estado.ENVIADO:
        messages.error(request, "Solo se pueden rechazar gastos de legalizaciones enviadas.")
        return redirect("legalizacion_detail", pk=leg.pk)

    motivo = request.POST.get("motivo", "").strip()
    if not motivo:
        messages.error(request, "Debes ingresar el motivo del rechazo.")
        return redirect("legalizacion_detail", pk=leg.pk)

    gasto.rechazado = True
    gasto.motivo_rechazo = motivo
    gasto.save()
    leg.recalcular_saldo(save=True)

    _notificar(
        destinatario=leg.elaboro,
        tipo=Notificacion.Tipo.GASTO_RECHAZADO,
        titulo=f"Gasto rechazado en {leg.codigo}",
        mensaje=f"El gasto de {gasto.cliente_proveedor} (${gasto.valor}) fue rechazado. Motivo: {motivo}",
        url=reverse("legalizacion_detail", args=[leg.pk]),
        legalizacion=leg,
    )

    messages.warning(request, f"Gasto '{gasto.cliente_proveedor}' rechazado.")
    return redirect("legalizacion_detail", pk=leg.pk)


@login_required
@require_POST
def gasto_restaurar(request, pk):
    """Aprobador restaura un gasto previamente rechazado."""
    user = request.user
    es_aprobador = user.is_superuser or user.groups.filter(name="Aprobadores").exists()
    if not es_aprobador:
        messages.error(request, "No tienes permiso para restaurar gastos.")
        return redirect("legalizacion_list")

    gasto = get_object_or_404(Gasto, pk=pk)
    leg = gasto.legalizacion

    gasto.rechazado = False
    gasto.motivo_rechazo = None
    gasto.save()
    leg.recalcular_saldo(save=True)

    messages.success(request, f"Gasto '{gasto.cliente_proveedor}' restaurado.")
    return redirect("legalizacion_detail", pk=leg.pk)


# ── Notificaciones ────────────────────────────────────────────────────────────

@login_required
def notificaciones_api(request):
    """JSON: últimas 12 notificaciones del usuario para el dropdown."""
    qs = (
        Notificacion.objects
        .filter(destinatario=request.user)
        .select_related("legalizacion", "solicitud")
        .order_by("-creado_en")[:12]
    )
    items = [
        {
            "id": n.pk,
            "tipo": n.tipo,
            "titulo": n.titulo,
            "mensaje": n.mensaje,
            "url_leer": reverse("notificacion_leer", args=[n.pk]),
            "leida": n.leida,
            "hace": timesince(n.creado_en),
        }
        for n in qs
    ]
    no_leidas = Notificacion.objects.filter(
        destinatario=request.user, leida=False
    ).count()
    return JsonResponse({"items": items, "no_leidas": no_leidas})


@login_required
def notificacion_leer(request, pk):
    """Marca una notificación como leída y redirige a su URL destino."""
    n = get_object_or_404(Notificacion, pk=pk, destinatario=request.user)
    if not n.leida:
        n.leida = True
        n.save(update_fields=["leida"])
    return redirect(n.url or "dashboard")


@login_required
@require_POST
def notificaciones_marcar_todas(request):
    """Marca todas las notificaciones del usuario como leídas.
    - Fetch/AJAX (dropdown): devuelve JSON.
    - Form normal (página de notificaciones): redirige de vuelta.
    """
    Notificacion.objects.filter(
        destinatario=request.user, leida=False
    ).update(leida=True)
    if request.headers.get("X-Requested-With") == "XMLHttpRequest":
        return JsonResponse({"ok": True})
    return redirect("notificaciones_list")


@login_required
def notificaciones_count(request):
    """
    Endpoint ultraligero para polling: solo devuelve el conteo de no leídas.
    Una única query COUNT(*) — evita serializar notificaciones completas cada 15 s.
    """
    no_leidas = (
        Notificacion.objects
        .filter(destinatario=request.user, leida=False)
        .count()
    )
    return JsonResponse({"no_leidas": no_leidas})


@login_required
@require_POST
def notificacion_eliminar(request, pk):
    """Elimina una notificación del usuario. Devuelve JSON si es petición AJAX."""
    n = get_object_or_404(Notificacion, pk=pk, destinatario=request.user)
    era_no_leida = not n.leida
    n.delete()
    if request.headers.get("X-Requested-With") == "XMLHttpRequest":
        return JsonResponse({"ok": True, "era_no_leida": era_no_leida})
    return redirect("notificaciones_list")


@login_required
@require_POST
def notificaciones_eliminar_leidas(request):
    """Elimina en un solo DELETE todas las notificaciones leídas del usuario.
    Bulk delete — evita N queries individuales para listas grandes.
    """
    eliminadas, _ = (
        Notificacion.objects
        .filter(destinatario=request.user, leida=True)
        .delete()
    )
    if request.headers.get("X-Requested-With") == "XMLHttpRequest":
        return JsonResponse({"ok": True, "eliminadas": eliminadas})
    return redirect("notificaciones_list")


@login_required
def notificaciones_list(request):
    """Página completa con todas las notificaciones del usuario."""
    qs = Notificacion.objects.filter(
        destinatario=request.user
    ).select_related("legalizacion", "solicitud").order_by("-creado_en")
    return render(request, "notificaciones/list.html", {"notificaciones": qs})
