from decimal import Decimal, InvalidOperation
from django import template

register = template.Library()


@register.filter
def nombre_display(user):
    """
    Devuelve el nombre visible de un usuario del sistema.

    Prioridad:
      1. Perfil.nombre_completo  (campo propio — siempre se llena en el perfil)
      2. User.get_full_name()    (first_name + last_name de Django auth)
      3. User.username           (fallback final)

    Uso en plantillas:  {{ sol.aprobador_area|nombre_display }}
    """
    if not user:
        return ""
    try:
        nombre = user.perfil.nombre_completo
        if nombre and nombre.strip():
            return nombre.strip()
    except Exception:
        pass
    nombre_django = user.get_full_name()
    return nombre_django if nombre_django else (user.username or "")


@register.filter
def iniciales(value):
    """
    Devuelve las iniciales (máx. 2 caracteres mayúsculas) de un nombre completo.
    Ej: "Sebastian Ojeda" → "SO", "analistatic" → "A"

    Uso:  {{ sol.aprobador_area|nombre_display|iniciales }}
    """
    partes = str(value).split()
    if not partes:
        return "?"
    if len(partes) == 1:
        return partes[0][:1].upper()
    return (partes[0][:1] + partes[-1][:1]).upper()


@register.filter
def abs_value(value):
    """Devuelve el valor absoluto de un número. Útil para mostrar saldos negativos."""
    try:
        return abs(Decimal(str(value)))
    except (InvalidOperation, TypeError, ValueError):
        return value


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
