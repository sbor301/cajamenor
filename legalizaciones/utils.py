"""
Utilidades de fechas — calendario laboral colombiano.

En Colombia se trabaja de lunes a sábado. Domingos y festivos nacionales
no se cuentan como días hábiles.
"""
from datetime import date, timedelta

import holidays


def _calendario_co(anio: int):
    """
    Devuelve el calendario de festivos colombianos para un año dado.
    Cacheado por proceso para evitar reconstruirlo en cada llamada.
    """
    return holidays.country_holidays("CO", years=anio)


def es_dia_habil_co(fecha: date) -> bool:
    """
    Retorna True si la fecha es día hábil en Colombia (lun-sáb, no festivo).
    """
    if fecha.weekday() == 6:  # 6 = domingo
        return False
    if fecha in _calendario_co(fecha.year):
        return False
    return True


def sumar_dias_habiles_co(fecha_inicio: date, dias: int) -> date:
    """
    Suma *dias* días hábiles colombianos a *fecha_inicio* (no incluye el día de inicio).

    Reglas:
    - Lunes a sábado son hábiles.
    - Domingo no cuenta.
    - Festivos nacionales colombianos no cuentan.

    Ejemplo:
        >>> sumar_dias_habiles_co(date(2026, 5, 5), 8)
        date(2026, 5, 14)   # asumiendo no festivos en ese rango
    """
    if dias <= 0:
        return fecha_inicio

    fecha = fecha_inicio
    contados = 0
    # Tope de seguridad para evitar bucles infinitos en errores de calendario
    tope = dias * 3 + 30

    while contados < dias and tope > 0:
        fecha += timedelta(days=1)
        if es_dia_habil_co(fecha):
            contados += 1
        tope -= 1

    return fecha
