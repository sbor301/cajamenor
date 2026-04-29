from decimal import Decimal

from django.contrib import messages
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.db.models import Count, Q, Sum
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from legalizaciones.models import Gasto, Legalizacion


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
            estado = request.POST.get("estado", Legalizacion.Estado.BORRADOR)
            fecha_consignacion = request.POST.get("fecha_consignacion") or None

            leg = Legalizacion.objects.create(
                monto_aprobado=Decimal(monto),
                fecha_solicitud=fecha,
                fecha_consignacion=fecha_consignacion,
                elaboro=request.user,
                estado=estado,
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

    context = {"estados": Legalizacion.Estado.choices}
    return render(request, "legalizaciones/create.html", context)


@never_cache
@login_required
def legalizacion_detail(request, pk):
    user = request.user
    es_aprobador = user.is_superuser or user.groups.filter(name="Aprobadores").exists()
    leg = get_object_or_404(Legalizacion, pk=pk)

    if not es_aprobador and leg.elaboro != user:
        messages.error(request, "No tienes permiso para ver esta legalización.")
        return redirect("legalizacion_list")

    context = {
        "leg": leg,
        "gastos": leg.gastos.all(),
        "es_aprobador": es_aprobador,
        "puede_editar": leg.estado in (Legalizacion.Estado.BORRADOR, Legalizacion.Estado.ENVIADO),
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
    messages.error(request, "Legalización rechazada.")
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
    if leg.estado == Legalizacion.Estado.BORRADOR:
        leg.estado = Legalizacion.Estado.ENVIADO
        leg.save()
        messages.success(request, "Legalización enviada para aprobación.")
    return redirect("legalizacion_detail", pk=pk)
