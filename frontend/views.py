from decimal import Decimal

from django.contrib import messages
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.db.models import Count, Q, Sum
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.timesince import timesince
from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from legalizaciones.models import Gasto, Legalizacion, Notificacion


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
    es_aprobador = user.is_superuser or user.groups.filter(name="Aprobadores").exists()

    qs = Legalizacion.objects.all() if es_aprobador else Legalizacion.objects.filter(elaboro=user)

    stats = qs.aggregate(
        total=Count("numero"),
        monto_total=Sum("monto_aprobado"),
        saldo_total=Sum("saldo"),
        pendientes=Count("numero", filter=Q(estado=Legalizacion.Estado.BORRADOR)),
        enviadas=Count("numero", filter=Q(estado=Legalizacion.Estado.ENVIADO)),
        aprobadas=Count("numero", filter=Q(estado=Legalizacion.Estado.APROBADO)),
        rechazadas=Count("numero", filter=Q(estado=Legalizacion.Estado.RECHAZADO)),
    )

    recientes = qs.order_by("-creado_en")[:5]

    context = {
        "stats": stats,
        "recientes": recientes,
        "es_aprobador": es_aprobador,
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
    if request.method == "POST":
        try:
            monto = request.POST.get("monto_aprobado")
            fecha = request.POST.get("fecha_solicitud")

            leg = Legalizacion.objects.create(
                monto_aprobado=Decimal(monto),
                fecha_solicitud=fecha,
                fecha_consignacion=None,   # solo la asigna el aprobador
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
    total_gastos = (
        gastos.filter(rechazado=False).aggregate(t=Sum("valor"))["t"] or Decimal("0")
    )

    # ¿Puede el empleado editar gastos rechazados? Solo en estado DEVUELTO y si es el elaborador
    puede_editar_gastos = (
        not es_aprobador
        and leg.estado == Legalizacion.Estado.DEVUELTO
        and leg.elaboro == user
    )

    context = {
        "leg": leg,
        "gastos": gastos,
        "total_gastos": total_gastos,
        "es_aprobador": es_aprobador,
        "puede_editar": leg.estado in (Legalizacion.Estado.BORRADOR, Legalizacion.Estado.ENVIADO),
        "puede_editar_gastos": puede_editar_gastos,
    }
    return render(request, "legalizaciones/detail.html", context)


@login_required
def legalizacion_aprobar(request, pk):
    user = request.user
    es_aprobador = user.is_superuser or user.groups.filter(name="Aprobadores").exists()
    if not es_aprobador:
        messages.error(request, "No tienes permiso para aprobar legalizaciones.")
        return redirect("legalizacion_detail", pk=pk)

    leg = get_object_or_404(Legalizacion, pk=pk)
    leg.estado = Legalizacion.Estado.APROBADO
    leg.aprobado_por = user
    leg.save()

    _notificar(
        destinatario=leg.elaboro,
        tipo=Notificacion.Tipo.APROBADA,
        titulo=f"Legalización {leg.codigo} aprobada",
        mensaje=f"Tu legalización fue aprobada por {user.get_full_name() or user.username}.",
        url=reverse("legalizacion_detail", args=[leg.pk]),
        legalizacion=leg,
    )

    messages.success(request, "Legalización aprobada correctamente.")
    return redirect("legalizacion_detail", pk=pk)


@login_required
def legalizacion_rechazar(request, pk):
    user = request.user
    es_aprobador = user.is_superuser or user.groups.filter(name="Aprobadores").exists()
    if not es_aprobador:
        messages.error(request, "No tienes permiso para rechazar legalizaciones.")
        return redirect("legalizacion_detail", pk=pk)

    leg = get_object_or_404(Legalizacion, pk=pk)
    leg.estado = Legalizacion.Estado.RECHAZADO
    leg.aprobado_por = user
    leg.save()

    _notificar(
        destinatario=leg.elaboro,
        tipo=Notificacion.Tipo.RECHAZADA,
        titulo=f"Legalización {leg.codigo} rechazada",
        mensaje=f"Tu legalización fue rechazada por {user.get_full_name() or user.username}.",
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
def legalizacion_enviar(request, pk):
    leg = get_object_or_404(Legalizacion, pk=pk, elaboro=request.user)
    if leg.estado in (Legalizacion.Estado.BORRADOR, Legalizacion.Estado.DEVUELTO):
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

    leg.estado = Legalizacion.Estado.DEVUELTO
    leg.aprobado_por = user
    leg.save()

    _notificar(
        destinatario=leg.elaboro,
        tipo=Notificacion.Tipo.DEVUELTA,
        titulo=f"Legalización {leg.codigo} devuelta para corrección",
        mensaje=f"Revisa los gastos rechazados, corrígelos y reenvía la legalización.",
        url=reverse("legalizacion_detail", args=[leg.pk]),
        legalizacion=leg,
    )

    messages.warning(request, "Legalización devuelta al empleado para corrección.")
    return redirect("legalizacion_detail", pk=pk)


@login_required
def gasto_editar(request, pk):
    """Empleado edita un gasto rechazado mientras la legalización está en estado DEVUELTO."""
    gasto = get_object_or_404(Gasto, pk=pk)
    leg = gasto.legalizacion

    if leg.elaboro != request.user:
        messages.error(request, "No tienes permiso para editar este gasto.")
        return redirect("legalizacion_detail", pk=leg.pk)

    if leg.estado != Legalizacion.Estado.DEVUELTO:
        messages.error(request, "Solo se pueden editar gastos de legalizaciones devueltas para corrección.")
        return redirect("legalizacion_detail", pk=leg.pk)

    if request.method == "POST":
        try:
            from datetime import datetime
            gasto.fecha = request.POST.get("fecha")
            gasto.cliente_proveedor = request.POST.get("cliente_proveedor", "").strip()
            gasto.cedula_nit = request.POST.get("cedula_nit", "").strip()
            gasto.numero_factura = request.POST.get("numero_factura", "").strip()
            gasto.centro_costos = request.POST.get("centro_costos", "").strip()
            gasto.valor_base = Decimal(request.POST.get("valor_base") or "0")
            gasto.iva = Decimal(request.POST.get("iva") or "0")
            gasto.observaciones = request.POST.get("observaciones", "").strip() or None
            if "archivo_factura" in request.FILES:
                gasto.archivo_factura = request.FILES["archivo_factura"]
            # Al guardar la edición, se limpia el rechazo
            gasto.rechazado = False
            gasto.motivo_rechazo = None
            gasto.full_clean()
            gasto.save()
            leg.recalcular_saldo(save=True)
            messages.success(request, "Gasto actualizado correctamente.")
            return redirect("legalizacion_detail", pk=leg.pk)
        except Exception as e:
            messages.error(request, f"Error al guardar el gasto: {e}")

    context = {"gasto": gasto, "leg": leg}
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
        .select_related("legalizacion")
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
    """Marca todas las notificaciones del usuario como leídas."""
    Notificacion.objects.filter(
        destinatario=request.user, leida=False
    ).update(leida=True)
    return JsonResponse({"ok": True})


@login_required
def notificaciones_list(request):
    """Página completa con todas las notificaciones del usuario."""
    qs = Notificacion.objects.filter(
        destinatario=request.user
    ).select_related("legalizacion").order_by("-creado_en")
    return render(request, "notificaciones/list.html", {"notificaciones": qs})
