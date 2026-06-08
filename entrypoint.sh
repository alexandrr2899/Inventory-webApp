#!/bin/bash
set -e

echo "Esperando base de datos..."
while ! pg_isready -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" > /dev/null 2>&1; do
    sleep 1
done
echo "Base de datos lista."

python manage.py makemigrations --noinput
python manage.py migrate --noinput
python manage.py setup_groups

# Generar íconos PWA desde logo-icon.png si existe y los iconos no fueron generados
if [ -f "static/images/logo-icon.png" ] && [ ! -f "static/icons/icon-192.png" ]; then
    echo "Generando íconos PWA desde logo-icon.png..."
    python create_icons.py
fi

python manage.py collectstatic --noinput

echo "Superusuario automático deshabilitado por seguridad."
echo "Si necesitás crear uno: docker compose exec web python manage.py createsuperuser"

exec gunicorn config.wsgi:application --bind 0.0.0.0:8000 --workers 2 --timeout 120
