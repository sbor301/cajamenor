from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver

from .models import Gasto


@receiver(post_save, sender=Gasto)
def gasto_post_save(sender, instance: Gasto, **kwargs):
    instance.legalizacion.recalcular_saldo(save=True)


@receiver(post_delete, sender=Gasto)
def gasto_post_delete(sender, instance: Gasto, **kwargs):
    legalizacion = instance.legalizacion
    if legalizacion and legalizacion.pk:
        legalizacion.recalcular_saldo(save=True)
