from django.db import transaction
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import filters, status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from .models import Gasto, Legalizacion
from .permissions import (
    EsAprobador,
    EsPropietarioOAprobador,
    LegalizacionEnEstadoEditable,
)
from .serializers import (
    GastoSerializer,
    LegalizacionSerializer,
)


class LegalizacionViewSet(viewsets.ModelViewSet):
    """
    CRUD completo de Legalizaciones.

    Permisos:
    - Cualquier usuario autenticado puede crear y ver sus propias legalizaciones.
    - Aprobadores y superusuarios ven todas y pueden aprobar/rechazar.
    - No se puede editar/eliminar una legalización Aprobada o Rechazada.
    """

    # Requerido por DRF para introspección del modelo (PK = numero UUID).
    # El queryset real se resuelve en get_queryset().
    queryset = Legalizacion.objects.none()
    serializer_class = LegalizacionSerializer
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = ["estado", "elaboro", "aprobado_por", "fecha_solicitud"]
    search_fields = ["numero", "elaboro__username", "aprobado_por__username"]
    ordering_fields = ["fecha_solicitud", "fecha_consignacion", "monto_aprobado", "saldo"]

    def get_permissions(self):
        """
        Permisos dinámicos según la acción:
        - aprobar / rechazar → solo Aprobadores o superusuario
        - resto              → autenticado + propietario o aprobador
        """
        if self.action in ("aprobar", "rechazar"):
            return [EsAprobador()]
        return [EsPropietarioOAprobador(), LegalizacionEnEstadoEditable()]

    def get_queryset(self):
        """
        Empleados solo ven sus propias legalizaciones.
        Aprobadores y superusuarios ven todas.
        """
        if getattr(self, "swagger_fake_view", False):
            return Legalizacion.objects.none()
        user = self.request.user
        qs = Legalizacion.objects.prefetch_related("gastos")
        if user.is_superuser or user.groups.filter(name="Aprobadores").exists():
            return qs.all()
        return qs.filter(elaboro=user)

    def perform_create(self, serializer):
        """El campo elaboro se asigna automáticamente al usuario autenticado."""
        serializer.save(elaboro=self.request.user)

    @action(detail=False, methods=["post"], url_path="bulk")
    def bulk_create(self, request):
        """Inserción masiva: cabecera + lista de gastos en un único payload JSON."""
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        instancia = serializer.save(elaboro=request.user)
        return Response(
            self.get_serializer(instancia).data,
            status=status.HTTP_201_CREATED,
        )

    @action(detail=True, methods=["post"], url_path="agregar-gastos")
    @transaction.atomic
    def agregar_gastos(self, request, pk=None):
        """Adjunta una lista de gastos a una legalización existente."""
        legalizacion = self.get_object()
        gastos_payload = request.data.get("gastos", [])
        if not isinstance(gastos_payload, list) or not gastos_payload:
            return Response(
                {"detail": "Debe enviar una lista no vacía de gastos en el campo 'gastos'."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        serializer = GastoSerializer(
            data=[{**g, "legalizacion": str(legalizacion.pk)} for g in gastos_payload],
            many=True,
        )
        serializer.is_valid(raise_exception=True)
        serializer.save()
        legalizacion.recalcular_saldo(save=True)
        legalizacion.refresh_from_db()
        return Response(
            LegalizacionSerializer(legalizacion).data,
            status=status.HTTP_201_CREATED,
        )

    @action(detail=True, methods=["post"])
    def aprobar(self, request, pk=None):
        """Solo Aprobadores. Cambia estado a APROBADO y registra quién aprobó."""
        legalizacion = self.get_object()
        legalizacion.estado = Legalizacion.Estado.APROBADO
        legalizacion.aprobado_por = request.user
        legalizacion.save()
        return Response(LegalizacionSerializer(legalizacion).data)

    @action(detail=True, methods=["post"])
    def rechazar(self, request, pk=None):
        """Solo Aprobadores. Cambia estado a RECHAZADO."""
        legalizacion = self.get_object()
        legalizacion.estado = Legalizacion.Estado.RECHAZADO
        legalizacion.aprobado_por = request.user
        legalizacion.save()
        return Response(LegalizacionSerializer(legalizacion).data)


class GastoViewSet(viewsets.ModelViewSet):
    """
    CRUD individual de Gastos.
    - Empleados solo ven gastos de sus propias legalizaciones.
    - Aprobadores y superusuarios ven todos.
    """

    # Requerido por DRF para introspección del modelo.
    # El queryset real se resuelve en get_queryset().
    queryset = Gasto.objects.none()
    serializer_class = GastoSerializer
    permission_classes = [EsPropietarioOAprobador]
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = ["legalizacion", "centro_costos", "fecha", "cedula_nit"]
    search_fields = ["cliente_proveedor", "numero_factura", "cedula_nit"]
    ordering_fields = ["fecha", "valor"]

    def get_queryset(self):
        # drf-spectacular llama get_queryset con usuario anónimo al generar el schema
        if getattr(self, "swagger_fake_view", False):
            return Gasto.objects.none()
        user = self.request.user
        qs = Gasto.objects.select_related("legalizacion")
        if user.is_superuser or user.groups.filter(name="Aprobadores").exists():
            return qs.all()
        return qs.filter(legalizacion__elaboro=user)
