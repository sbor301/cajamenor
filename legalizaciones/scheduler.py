"""
Scheduler interno de Caja Menor
================================
Corre en un hilo de fondo dentro del proceso Django (APScheduler).
No requiere Celery ni configuración externa.

Tareas programadas
------------------
- enviar_alertas_cierre : todos los días a las 08:00
  Notifica al empleado y al aprobador cuando una legalización
  tiene su fecha de cierre en exactamente 2 días.
"""

import logging
from datetime import timedelta

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

logger = logging.getLogger(__name__)


# ── Lógica de alertas (reutilizada también por el management command) ─────────

def enviar_alertas_cierre(dias_anticipacion=2):
    """
    Busca legalizaciones con fecha_cierre = hoy + *dias_anticipacion* días y crea
    notificaciones ALERTA_CIERRE para el elaboró y el aprobador.
    Los duplicados se omiten automáticamente.

    Retorna el número de notificaciones nuevas creadas.
    """
    from django.urls import reverse
    from django.utils import timezone

    from legalizaciones.models import Legalizacion, Notificacion

    hoy = timezone.now().date()
    fecha_objetivo = hoy + timedelta(days=dias_anticipacion)

    legalizaciones = (
        Legalizacion.objects
        .filter(fecha_cierre=fecha_objetivo)
        .exclude(estado=Legalizacion.Estado.RECHAZADO)
        .select_related("elaboro", "aprobado_por")
    )

    enviadas = 0

    for leg in legalizaciones:
        url = reverse("legalizacion_detail", args=[leg.pk])
        dias_texto = "hoy" if dias_anticipacion == 0 else (
            "mañana" if dias_anticipacion == 1 else f"en {dias_anticipacion} días"
        )
        titulo = f"Cierre de caja {dias_texto} — {leg.codigo}"
        mensaje = (
            f"La legalización {leg.codigo} vence el "
            f"{leg.fecha_cierre.strftime('%d/%m/%Y')}. "
            "Asegúrate de que todo esté en orden antes del cierre."
        )

        destinatarios = {leg.elaboro}
        if leg.aprobado_por and leg.aprobado_por != leg.elaboro:
            destinatarios.add(leg.aprobado_por)

        for destinatario in destinatarios:
            ya_enviada = Notificacion.objects.filter(
                destinatario=destinatario,
                tipo=Notificacion.Tipo.ALERTA_CIERRE,
                legalizacion=leg,
            ).exists()

            if ya_enviada:
                logger.debug("Alerta ya enviada: %s → %s", leg.codigo, destinatario.username)
                continue

            Notificacion.objects.create(
                destinatario=destinatario,
                tipo=Notificacion.Tipo.ALERTA_CIERRE,
                titulo=titulo,
                mensaje=mensaje,
                url=url,
                legalizacion=leg,
            )
            logger.info("Alerta de cierre enviada: %s → %s", leg.codigo, destinatario.username)
            enviadas += 1

    return enviadas


# ── Arranque del scheduler ────────────────────────────────────────────────────

def iniciar_scheduler():
    """
    Crea e inicia el scheduler en un hilo de fondo.
    Llamar una sola vez desde AppConfig.ready().
    """
    scheduler = BackgroundScheduler(timezone="America/Bogota")

    scheduler.add_job(
        enviar_alertas_cierre,
        trigger=CronTrigger(hour=8, minute=0),   # todos los días a las 08:00
        id="alertas_cierre_caja",
        replace_existing=True,
        misfire_grace_time=3600,                  # tolera hasta 1 h de retraso
    )

    scheduler.start()
    logger.info("Scheduler iniciado — alertas de cierre corren diariamente a las 08:00")
