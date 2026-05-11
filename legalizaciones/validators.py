"""Validadores de archivos subidos.

La política es lista blanca por extensión + content-type. Bloquea SVG, HTML
y otros formatos ejecutables-en-navegador que abriría un atacante para
ejecutar JS en el origen de la app (XSS desde archivo).
"""
from __future__ import annotations

import os
from typing import Final

from django.core.exceptions import ValidationError

# Tamaño máximo permitido para una factura (10 MB).
MAX_FACTURA_BYTES: Final[int] = 10 * 1024 * 1024

ALLOWED_FACTURA_EXT: Final[frozenset[str]] = frozenset(
    {".pdf", ".png", ".jpg", ".jpeg", ".webp"}
)

ALLOWED_FACTURA_MIME: Final[frozenset[str]] = frozenset(
    {
        "application/pdf",
        "image/png",
        "image/jpeg",
        "image/webp",
    }
)


def validar_archivo_factura(archivo) -> None:
    """Valida tamaño, extensión y content-type de una factura.

    Se llama desde el FileField como `validators=[validar_archivo_factura]`.
    El content-type proviene del cliente — no es de fiar por sí solo, pero
    sumado a la lista blanca de extensiones reduce el vector de subida de
    HTML/SVG/JS.
    """
    if archivo is None:
        return

    # Tamaño
    if archivo.size > MAX_FACTURA_BYTES:
        raise ValidationError(
            "El archivo supera el límite de 10 MB.",
            code="archivo_demasiado_grande",
        )

    # Extensión
    ext = os.path.splitext(archivo.name)[1].lower()
    if ext not in ALLOWED_FACTURA_EXT:
        raise ValidationError(
            "Formato no permitido. Usa PDF, PNG, JPG o WEBP.",
            code="extension_no_permitida",
        )

    # Content-Type (si el cliente lo envía; en algunos formularios viene vacío)
    content_type = getattr(archivo, "content_type", None)
    if content_type and content_type not in ALLOWED_FACTURA_MIME:
        raise ValidationError(
            "Tipo de contenido no permitido.",
            code="content_type_no_permitido",
        )
