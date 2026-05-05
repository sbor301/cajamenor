from django.conf import settings
from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver

from .models import Gasto, Perfil


@receiver(post_save, sender=Gasto)
def gasto_post_save(sender, instance: Gasto, **kwargs):
    instance.legalizacion.recalcular_saldo(save=True)


@receiver(post_delete, sender=Gasto)
def gasto_post_delete(sender, instance: Gasto, **kwargs):
    legalizacion = instance.legalizacion
    if legalizacion and legalizacion.pk:
        legalizacion.recalcular_saldo(save=True)


@receiver(post_save, sender=settings.AUTH_USER_MODEL)
def crear_perfil_usuario(sender, instance, created, **kwargs):
    """
    Cada vez que se crea un User, se le asocia un Perfil vacío.
    El empleado luego completa nombre completo, cédula, ciudad y datos bancarios.
    """
    if created:
        Perfil.objects.get_or_create(user=instance)
