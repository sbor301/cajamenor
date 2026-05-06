"""
Middleware del frontend.
"""


class NoCacheAuthMiddleware:
    """
    Añade cabeceras HTTP que impiden que el navegador almacene en caché
    las páginas de usuarios autenticados.

    Sin esto, al hacer logout y presionar "atrás" el navegador muestra
    la versión cacheada del dashboard aunque la sesión ya esté cerrada.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)

        # Solo aplicar a respuestas HTML de usuarios autenticados
        if request.user.is_authenticated:
            content_type = response.get("Content-Type", "")
            if "text/html" in content_type:
                response["Cache-Control"] = "no-cache, no-store, must-revalidate, private"
                response["Pragma"] = "no-cache"
                response["Expires"] = "0"

        return response
