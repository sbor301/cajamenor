# ── Imagen base ──────────────────────────────────────────────────────────────
FROM python:3.12-slim

# Variables de entorno para Python
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

# Directorio de trabajo
WORKDIR /app

# Instalar dependencias Python
# psycopg[binary] incluye binarios precompilados, no requiere libpq-dev ni gcc
COPY requirements.txt .
RUN pip install --upgrade pip && pip install -r requirements.txt

# Copiar código fuente
COPY . .

# Script de entrada
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

# Puerto expuesto
EXPOSE 8000

ENTRYPOINT ["/entrypoint.sh"]
