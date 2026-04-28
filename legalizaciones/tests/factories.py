"""
Helpers para crear datos de prueba de forma rápida y reutilizable.
"""
from decimal import Decimal

from django.contrib.auth.models import Group, User

from legalizaciones.models import Gasto, Legalizacion


def crear_grupo(nombre: str) -> Group:
    grupo, _ = Group.objects.get_or_create(name=nombre)
    return grupo


def crear_usuario(username: str, grupo: str | None = None, **kwargs) -> User:
    usuario = User.objects.create_user(
        username=username,
        password="Test1234!",
        **kwargs,
    )
    if grupo:
        usuario.groups.add(crear_grupo(grupo))
    return usuario


def crear_legalizacion(elaboro: User, **kwargs) -> Legalizacion:
    defaults = {
        "monto_aprobado": Decimal("500000.00"),
        "fecha_solicitud": "2026-04-27",
        "estado": Legalizacion.Estado.BORRADOR,
    }
    defaults.update(kwargs)
    return Legalizacion.objects.create(elaboro=elaboro, **defaults)


def crear_gasto(legalizacion: Legalizacion, valor: Decimal = Decimal("100000.00"), **kwargs) -> Gasto:
    defaults = {
        "fecha": "2026-04-27",
        "cliente_proveedor": "Proveedor Test",
        "cedula_nit": "900000000-1",
        "numero_factura": "F-001",
        "centro_costos": "ADM-01",
        "valor": valor,
    }
    defaults.update(kwargs)
    return Gasto.objects.create(legalizacion=legalizacion, **defaults)
