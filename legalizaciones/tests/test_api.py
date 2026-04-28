"""
Tests de API: CRUD de Legalizaciones y Gastos.
"""
from decimal import Decimal

from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase
from rest_framework_simplejwt.tokens import RefreshToken

from legalizaciones.models import Legalizacion
from .factories import crear_gasto, crear_legalizacion, crear_usuario


def token_para(usuario):
    """Retorna el header Authorization JWT para un usuario."""
    refresh = RefreshToken.for_user(usuario)
    return {"HTTP_AUTHORIZATION": f"Bearer {refresh.access_token}"}


class LegalizacionCRUDTest(APITestCase):

    def setUp(self):
        self.empleado = crear_usuario("emp_api", grupo="Empleados")
        self.aprobador = crear_usuario("apr_api", grupo="Aprobadores")
        self.auth = token_para(self.empleado)
        self.auth_apr = token_para(self.aprobador)

    # ── Crear ────────────────────────────────────────────────────────────────

    def test_crear_legalizacion_sin_gastos(self):
        url = reverse("legalizacion-list")
        payload = {
            "monto_aprobado": "300000.00",
            "fecha_solicitud": "2026-04-28",
            "estado": "BORRADOR",
        }
        response = self.client.post(url, payload, format="json", **self.auth)
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data["saldo"], "300000.00")
        self.assertEqual(response.data["elaboro"], self.empleado.pk)

    def test_crear_legalizacion_con_gastos_anidados(self):
        url = reverse("legalizacion-list")
        payload = {
            "monto_aprobado": "500000.00",
            "fecha_solicitud": "2026-04-28",
            "estado": "BORRADOR",
            "gastos": [
                {
                    "fecha": "2026-04-28",
                    "cliente_proveedor": "Proveedor A",
                    "cedula_nit": "900111222-3",
                    "numero_factura": "F-100",
                    "centro_costos": "ADM-01",
                    "valor": "150000.00",
                },
                {
                    "fecha": "2026-04-28",
                    "cliente_proveedor": "Proveedor B",
                    "cedula_nit": "900333444-5",
                    "numero_factura": "F-101",
                    "centro_costos": "ADM-01",
                    "valor": "100000.00",
                },
            ],
        }
        response = self.client.post(url, payload, format="json", **self.auth)
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(len(response.data["gastos"]), 2)
        self.assertEqual(response.data["saldo"], "250000.00")

    def test_crear_requiere_autenticacion(self):
        url = reverse("legalizacion-list")
        payload = {"monto_aprobado": "100000.00", "fecha_solicitud": "2026-04-28"}
        response = self.client.post(url, payload, format="json")
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    # ── Listar ───────────────────────────────────────────────────────────────

    def test_listar_retorna_solo_propias(self):
        """Empleado solo ve sus propias legalizaciones."""
        crear_legalizacion(self.empleado)
        crear_legalizacion(self.empleado)
        crear_legalizacion(self.aprobador)  # esta NO debe aparecer
        url = reverse("legalizacion-list")
        response = self.client.get(url, **self.auth)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["count"], 2)

    def test_aprobador_ve_todas(self):
        """Aprobador ve legalizaciones de todos los usuarios."""
        crear_legalizacion(self.empleado)
        crear_legalizacion(self.aprobador)
        url = reverse("legalizacion-list")
        response = self.client.get(url, **self.auth_apr)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["count"], 2)

    # ── Detalle ──────────────────────────────────────────────────────────────

    def test_detalle_incluye_gastos_anidados(self):
        leg = crear_legalizacion(self.empleado)
        crear_gasto(leg, valor=Decimal("80000.00"))
        url = reverse("legalizacion-detail", kwargs={"pk": leg.pk})
        response = self.client.get(url, **self.auth)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data["gastos"]), 1)
        self.assertEqual(response.data["saldo"], "420000.00")

    # ── Actualizar ───────────────────────────────────────────────────────────

    def test_actualizar_monto_recalcula_saldo(self):
        leg = crear_legalizacion(self.empleado, monto_aprobado=Decimal("500000.00"))
        crear_gasto(leg, valor=Decimal("100000.00"))
        url = reverse("legalizacion-detail", kwargs={"pk": leg.pk})
        response = self.client.patch(
            url, {"monto_aprobado": "600000.00"}, format="json", **self.auth
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["saldo"], "500000.00")

    def test_no_editar_legalizacion_aprobada(self):
        """No se puede modificar una legalización ya aprobada."""
        leg = crear_legalizacion(self.empleado, estado=Legalizacion.Estado.APROBADO)
        url = reverse("legalizacion-detail", kwargs={"pk": leg.pk})
        response = self.client.patch(
            url, {"monto_aprobado": "999999.00"}, format="json", **self.auth
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    # ── Eliminar ─────────────────────────────────────────────────────────────

    def test_eliminar_legalizacion(self):
        leg = crear_legalizacion(self.empleado)
        url = reverse("legalizacion-detail", kwargs={"pk": leg.pk})
        response = self.client.delete(url, **self.auth)
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        self.assertFalse(Legalizacion.objects.filter(pk=leg.pk).exists())

    # ── Agregar gastos ───────────────────────────────────────────────────────

    def test_agregar_gastos_actualiza_saldo(self):
        leg = crear_legalizacion(self.empleado, monto_aprobado=Decimal("500000.00"))
        url = reverse("legalizacion-agregar-gastos", kwargs={"pk": leg.pk})
        payload = {
            "gastos": [
                {
                    "fecha": "2026-04-28",
                    "cliente_proveedor": "Taxi",
                    "cedula_nit": "1234567890",
                    "numero_factura": "T-01",
                    "centro_costos": "ADM-01",
                    "valor": "45000.00",
                }
            ]
        }
        response = self.client.post(url, payload, format="json", **self.auth)
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data["saldo"], "455000.00")
