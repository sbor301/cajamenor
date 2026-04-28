from django.db import transaction
from rest_framework import serializers

from .models import Gasto, Legalizacion


class GastoSerializer(serializers.ModelSerializer):
    class Meta:
        model = Gasto
        fields = [
            "id",
            "legalizacion",
            "fecha",
            "cliente_proveedor",
            "cedula_nit",
            "numero_factura",
            "centro_costos",
            "valor",
            "observaciones",
            "creado_en",
            "actualizado_en",
        ]
        read_only_fields = ["id", "creado_en", "actualizado_en"]


class GastoAnidadoSerializer(serializers.ModelSerializer):
    """Variante usada dentro de Legalizacion: omite el FK ya que se infiere del padre."""

    id = serializers.IntegerField(required=False)

    class Meta:
        model = Gasto
        fields = [
            "id",
            "fecha",
            "cliente_proveedor",
            "cedula_nit",
            "numero_factura",
            "centro_costos",
            "valor",
            "observaciones",
        ]


class LegalizacionSerializer(serializers.ModelSerializer):
    """
    Serializer principal para Legalizacion.
    - GET: incluye los gastos anidados.
    - POST/PUT/PATCH: acepta `gastos` como lista anidada para creación / actualización masiva.
    """

    gastos = GastoAnidadoSerializer(many=True, required=False)
    estado_display = serializers.CharField(source="get_estado_display", read_only=True)

    class Meta:
        model = Legalizacion
        fields = [
            "numero",
            "monto_aprobado",
            "fecha_solicitud",
            "fecha_consignacion",
            "elaboro",
            "saldo",
            "estado",
            "estado_display",
            "aprobado_por",
            "gastos",
            "creado_en",
            "actualizado_en",
        ]
        read_only_fields = ["numero", "saldo", "elaboro", "aprobado_por", "creado_en", "actualizado_en"]

    @transaction.atomic
    def create(self, validated_data):
        gastos_data = validated_data.pop("gastos", [])
        legalizacion = Legalizacion.objects.create(**validated_data)
        for gasto_data in gastos_data:
            gasto_data.pop("id", None)
            Gasto.objects.create(legalizacion=legalizacion, **gasto_data)
        legalizacion.recalcular_saldo(save=True)
        legalizacion.refresh_from_db()
        return legalizacion

    @transaction.atomic
    def update(self, instance, validated_data):
        gastos_data = validated_data.pop("gastos", None)

        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        instance.save()

        if gastos_data is not None:
            existentes = {g.id: g for g in instance.gastos.all()}
            ids_recibidos = set()

            for gasto_data in gastos_data:
                gasto_id = gasto_data.pop("id", None)
                if gasto_id and gasto_id in existentes:
                    gasto = existentes[gasto_id]
                    for attr, value in gasto_data.items():
                        setattr(gasto, attr, value)
                    gasto.save()
                    ids_recibidos.add(gasto_id)
                else:
                    Gasto.objects.create(legalizacion=instance, **gasto_data)

            for gasto_id, gasto in existentes.items():
                if gasto_id not in ids_recibidos:
                    gasto.delete()

        instance.recalcular_saldo(save=True)
        instance.refresh_from_db()
        return instance


class LegalizacionBulkCreateSerializer(serializers.Serializer):
    """
    Serializer dedicado para inserción masiva: cabecera + lista de gastos en un solo payload.
    """

    legalizacion = LegalizacionSerializer()

    def create(self, validated_data):
        legalizacion_data = validated_data["legalizacion"]
        serializer = LegalizacionSerializer(data=self.initial_data["legalizacion"])
        serializer.is_valid(raise_exception=True)
        return serializer.save()
