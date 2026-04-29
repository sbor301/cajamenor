import re
from datetime import date
from decimal import Decimal

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
            "valor_base",
            "iva",
            "valor",
            "observaciones",
            "creado_en",
            "actualizado_en",
        ]
        read_only_fields = ["id", "valor", "creado_en", "actualizado_en"]


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
            "valor_base",
            "iva",
            "valor",
            "observaciones",
        ]
        read_only_fields = ["valor"]

    def validate_fecha(self, value):
        if value > date.today():
            raise serializers.ValidationError("La fecha del gasto no puede ser en el futuro.")
        return value

    def validate_cedula_nit(self, value):
        clean = re.sub(r"[\s\-]", "", value)
        if not clean.isdigit():
            raise serializers.ValidationError(
                "Solo debe contener dígitos. Formato: 123456789 o 900123456-7"
            )
        if not (5 <= len(clean) <= 12):
            raise serializers.ValidationError(
                f"Debe tener entre 5 y 12 dígitos (ingresaste {len(clean)})."
            )
        return value

    def validate_valor_base(self, value):
        if value <= Decimal("0"):
            raise serializers.ValidationError("El valor base debe ser mayor a cero.")
        return value

    def validate_iva(self, value):
        if value < Decimal("0"):
            raise serializers.ValidationError("El IVA no puede ser negativo.")
        return value


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

    def validate_monto_aprobado(self, value):
        if value <= Decimal("0"):
            raise serializers.ValidationError("El monto aprobado debe ser mayor a cero.")
        return value

    def validate(self, attrs):
        fecha_solicitud = attrs.get("fecha_solicitud")
        fecha_consignacion = attrs.get("fecha_consignacion")
        if fecha_consignacion and fecha_solicitud and fecha_consignacion < fecha_solicitud:
            raise serializers.ValidationError({
                "fecha_consignacion": (
                    "La fecha de consignación no puede ser anterior a la fecha de solicitud."
                )
            })
        return attrs

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
