from django.db import transaction
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import filters, status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from .models import Gasto, Legalizacion
from .serializers import (
    GastoSerializer,
    LegalizacionSerializer,
)


class LegalizacionViewSet(viewsets.ModelViewSet):
    """
    CRUD completo de Legalizaciones.

    - `GET /api/v1/legalizaciones/`: lista con gastos anidados.
    - `POST /api/v1/legalizaciones/`: crea cabecera + gastos en un solo payload.
    - `POST /api/v1/legalizaciones/bulk/`: alias semántico para inserción masiva.
    - `POST /api/v1/legalizaciones/{numero}/agregar-gastos/`: agrega gastos a una legalización existente.
    - `POST /api/v1/legalizaciones/{numero}/aprobar/`: cambia estado a APROBADO.
    - `POST /api/v1/legalizaciones/{numero}/rechazar/`: cambia estado a RECHAZADO.
    """

    queryset = Legalizacion.objects.all().prefetch_related("gastos")
    serializer_class = LegalizacionSerializer
    permission_classes = [IsAuthenticated]
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = ["estado", "elaboro", "aprobado_por", "fecha_solicitud"]
    search_fields = ["numero", "elaboro__username", "aprobado_por__username"]
    ordering_fields = ["fecha_solicitud", "fecha_consignacion", "monto_aprobado", "saldo"]

    @action(detail=False, methods=["post"], url_path="bulk")
    def bulk_create(self, request):
        """
        Inserción masiva: recibe la cabecera y la lista de gastos en un único payload JSON.
        Equivalente a POST / con `gastos` anidados, expuesto explícitamente para claridad.
        """
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        instancia = serializer.save()
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
            data=[{**g, "legalizacion": legalizacion.pk} for g in gastos_payload],
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
        legalizacion = self.get_object()
        legalizacion.estado = Legalizacion.Estado.APROBADO
        if request.user.is_authenticated:
            legalizacion.aprobado_por = request.user
        legalizacion.save()
        return Response(LegalizacionSerializer(legalizacion).data)

    @action(detail=True, methods=["post"])
    def rechazar(self, request, pk=None):
        legalizacion = self.get_object()
        legalizacion.estado = Legalizacion.Estado.RECHAZADO
        legalizacion.save()
        return Response(LegalizacionSerializer(legalizacion).data)


class GastoViewSet(viewsets.ModelViewSet):
    """CRUD individual de Gastos. Las mutaciones disparan recálculo automático de saldo."""

    queryset = Gasto.objects.select_related("legalizacion").all()
    serializer_class = GastoSerializer
    permission_classes = [IsAuthenticated]
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = ["legalizacion", "centro_costos", "fecha", "cedula_nit"]
    search_fields = ["cliente_proveedor", "numero_factura", "cedula_nit"]
    ordering_fields = ["fecha", "valor"]
