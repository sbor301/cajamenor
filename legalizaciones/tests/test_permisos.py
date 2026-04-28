"""
Tests de permisos: Empleados vs Aprobadores.
"""
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase
from rest_framework_simplejwt.tokens import RefreshToken

from legalizaciones.models import Legalizacion
from .factories import crear_legalizacion, crear_usuario


def token_para(usuario):
    refresh = RefreshToken.for_user(usuario)
    return {"HTTP_AUTHORIZATION": f"Bearer {refresh.access_token}"}


class PermisosAprobacionTest(APITestCase):

    def setUp(self):
        self.empleado = crear_usuario("emp_perm", grupo="Empleados")
        self.aprobador = crear_usuario("apr_perm", grupo="Aprobadores")
        self.legalizacion = crear_legalizacion(self.empleado)

    def test_empleado_no_puede_aprobar(self):
        url = reverse("legalizacion-aprobar", kwargs={"pk": self.legalizacion.pk})
        response = self.client.post(url, **token_para(self.empleado))
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_empleado_no_puede_rechazar(self):
        url = reverse("legalizacion-rechazar", kwargs={"pk": self.legalizacion.pk})
        response = self.client.post(url, **token_para(self.empleado))
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_aprobador_puede_aprobar(self):
        url = reverse("legalizacion-aprobar", kwargs={"pk": self.legalizacion.pk})
        response = self.client.post(url, **token_para(self.aprobador))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["estado"], Legalizacion.Estado.APROBADO)
        self.assertEqual(response.data["aprobado_por"], self.aprobador.pk)

    def test_aprobador_puede_rechazar(self):
        url = reverse("legalizacion-rechazar", kwargs={"pk": self.legalizacion.pk})
        response = self.client.post(url, **token_para(self.aprobador))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["estado"], Legalizacion.Estado.RECHAZADO)

    def test_sin_token_devuelve_401(self):
        url = reverse("legalizacion-list")
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_empleado_no_ve_legalizaciones_de_otros(self):
        otro_empleado = crear_usuario("emp_otro", grupo="Empleados")
        crear_legalizacion(otro_empleado)
        url = reverse("legalizacion-list")
        response = self.client.get(url, **token_para(self.empleado))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        for leg in response.data["results"]:
            self.assertEqual(leg["elaboro"], self.empleado.pk)

    def test_empleado_no_puede_ver_detalle_de_otro(self):
        otro_empleado = crear_usuario("emp_otro2", grupo="Empleados")
        leg_ajena = crear_legalizacion(otro_empleado)
        url = reverse("legalizacion-detail", kwargs={"pk": leg_ajena.pk})
        response = self.client.get(url, **token_para(self.empleado))
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_aprobador_registrado_en_aprobacion(self):
        url = reverse("legalizacion-aprobar", kwargs={"pk": self.legalizacion.pk})
        self.client.post(url, **token_para(self.aprobador))
        self.legalizacion.refresh_from_db()
        self.assertEqual(self.legalizacion.aprobado_por, self.aprobador)
