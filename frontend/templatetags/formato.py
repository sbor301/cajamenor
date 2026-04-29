from decimal import Decimal, InvalidOperation
from django import template

register = template.Library()


@register.filter
def cop(value):
    """
    Formatea un número en formato colombiano: separador de miles con punto,
    sin decimales. Ej: 9066285 → 9.066.285
    """
    try:
        n = int(Decimal(str(value)))
        # Python usa coma como separador de miles; reemplazamos por punto
        return f"{n:,}".replace(",", ".")
    except (InvalidOperation, TypeError, ValueError):
        return value


@register.filter
def cop_decimal(value):
    """
    Formatea con dos decimales en formato colombiano.
    Ej: 9066285.50 → 9.066.285,50
    """
    try:
        n = Decimal(str(value))
        entero = int(n)
        centavos = abs(n - entero)
        parte_entera = f"{entero:,}".replace(",", ".")
        parte_decimal = f"{centavos:.2f}"[1:]          # ",50"
        parte_decimal = parte_decimal.replace(".", ",")
        return f"{parte_entera}{parte_decimal}"
    except (InvalidOperation, TypeError, ValueError):
        return value
