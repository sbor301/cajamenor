"""
Tests de modelos: lógica de negocio del saldo.
"""
from decimal import Decimal

from django.test import TestCase

from legalizaciones.models import Legalizacion
from .factories import crear_gasto, crear_legalizacion, crear_usuario


class SaldoLegalizacionTest(TestCase):

    def setUp(self):
        self.empleado = crear_usuario("empleado_test", grupo="Empleados")
        self.legalizacion = crear_legalizacion(
            elaboro=self.empleado,
            monto_aprobado=Decimal("500000.00"),
        )

    def test_saldo_inicial_igual_a_monto_aprobado(self):
        """Sin gastos el saldo debe ser igual al monto aprobado."""
        self.legalizacion.refresh_from_db()
        self.assertEqual(self.legalizacion.saldo, Decimal("500000.00"))

    def test_saldo_se_reduce_al_agregar_gasto(self):
        """Al crear un gasto el saldo debe reducirse correctamente."""
        crear_gasto(self.legalizacion, valor=Decimal("120000.00"))
        self.legalizacion.refresh_from_db()
        self.assertEqual(self.legalizacion.saldo, Decimal("380000.00"))

    def test_saldo_con_multiples_gastos(self):
        """El saldo debe reflejar la suma de todos los gastos."""
        crear_gasto(self.legalizacion, valor=Decimal("100000.00"))
        crear_gasto(self.legalizacion, valor=Decimal("50000.00"))
        crear_gasto(self.legalizacion, valor=Decimal("75000.00"))
        self.legalizacion.refresh_from_db()
        self.assertEqual(self.legalizacion.saldo, Decimal("275000.00"))

    def test_saldo_negativo_cuando_gastos_superan_monto(self):
        """Saldo negativo indica que el empleado debe recibir reembolso."""
        crear_gasto(self.legalizacion, valor=Decimal("600000.00"))
        self.legalizacion.refresh_from_db()
        self.assertEqual(self.legalizacion.saldo, Decimal("-100000.00"))

    def test_saldo_aumenta_al_eliminar_gasto(self):
        """Al eliminar un gasto el saldo debe aumentar."""
        gasto = crear_gasto(self.legalizacion, valor=Decimal("200000.00"))
        self.legalizacion.refresh_from_db()
        self.assertEqual(self.legalizacion.saldo, Decimal("300000.00"))

        gasto.delete()
        self.legalizacion.refresh_from_db()
        self.assertEqual(self.legalizacion.saldo, Decimal("500000.00"))

    def test_saldo_se_actualiza_al_modificar_gasto(self):
        """Al cambiar el valor de un gasto el saldo debe recalcularse."""
        gasto = crear_gasto(self.legalizacion, valor=Decimal("100000.00"))
        self.legalizacion.refresh_from_db()
        self.assertEqual(self.legalizacion.saldo, Decimal("400000.00"))

        gasto.valor = Decimal("200000.00")
        gasto.save()
        self.legalizacion.refresh_from_db()
        self.assertEqual(self.legalizacion.saldo, Decimal("300000.00"))

    def test_estado_inicial_es_borrador(self):
        """El estado por defecto debe ser BORRADOR."""
        self.assertEqual(self.legalizacion.estado, Legalizacion.Estado.BORRADOR)

    def test_str_representacion(self):
        """El __str__ debe incluir el número y estado."""
        texto = str(self.legalizacion)
        self.assertIn("Borrador", texto)
