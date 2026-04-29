from legalizaciones.models import Notificacion


def notificaciones(request):
    """Inyecta el conteo de notificaciones no leídas en todos los templates."""
    if not request.user.is_authenticated:
        return {"notif_no_leidas": 0}
    count = Notificacion.objects.filter(
        destinatario=request.user, leida=False
    ).count()
    return {"notif_no_leidas": count}
