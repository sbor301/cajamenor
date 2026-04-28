from rest_framework.permissions import BasePermission, IsAuthenticated


class EsEmpleado(BasePermission):
    """Pertenece al grupo Empleados o es superusuario."""

    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        if request.user.is_superuser:
            return True
        return request.user.groups.filter(name="Empleados").exists()


class EsAprobador(BasePermission):
    """Pertenece al grupo Aprobadores o es superusuario."""

    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        if request.user.is_superuser:
            return True
        return request.user.groups.filter(name="Aprobadores").exists()


class EsPropietarioOAprobador(BasePermission):
    """
    A nivel de objeto:
    - Aprobadores y superusuarios ven/editan todo.
    - Empleados solo ven/editan sus propias legalizaciones.
    """

    def has_permission(self, request, view):
        return request.user and request.user.is_authenticated

    def has_object_permission(self, request, view, obj):
        if request.user.is_superuser:
            return True
        if request.user.groups.filter(name="Aprobadores").exists():
            return True
        # Empleado solo accede a sus propias legalizaciones
        return obj.elaboro == request.user


class LegalizacionEnEstadoEditable(BasePermission):
    """
    Impide modificar una legalización que ya fue Aprobada o Rechazada.
    Solo aplica a métodos de escritura (PUT, PATCH, DELETE).
    """

    METODOS_ESCRITURA = ("PUT", "PATCH", "DELETE")

    def has_object_permission(self, request, view, obj):
        from .models import Legalizacion

        if request.method not in self.METODOS_ESCRITURA:
            return True
        estados_bloqueados = (
            Legalizacion.Estado.APROBADO,
            Legalizacion.Estado.RECHAZADO,
        )
        if obj.estado in estados_bloqueados:
            self.message = (
                f"No se puede modificar una legalización en estado '{obj.get_estado_display()}'."
            )
            return False
        return True
