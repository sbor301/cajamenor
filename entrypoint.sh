#!/bin/sh
set -e

echo "Aplicando migraciones..."
python manage.py migrate --noinput

echo "Inicializando grupos y permisos..."
python manage.py setup_grupos

echo "Recolectando archivos estáticos..."
python manage.py collectstatic --noinput

echo "Iniciando servidor Gunicorn..."
exec gunicorn cajamenor.wsgi:application \
    --bind 0.0.0.0:8000 \
    --workers 3 \
    --timeout 120 \
    --access-logfile - \
    --error-logfile -
