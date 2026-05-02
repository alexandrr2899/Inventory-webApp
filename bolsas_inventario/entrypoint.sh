#!/bin/bash
set -e

echo "Esperando base de datos..."
while ! pg_isready -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" > /dev/null 2>&1; do
    sleep 1
done
echo "Base de datos lista."

python manage.py makemigrations --noinput
python manage.py migrate --noinput

# Generar íconos PWA desde logo-icon.png si existe y los iconos no fueron generados
if [ -f "static/images/logo-icon.png" ] && [ ! -f "static/icons/icon-192.png" ]; then
    echo "Generando íconos PWA desde logo-icon.png..."
    python create_icons.py
fi

python manage.py collectstatic --noinput

# Crear superusuario si no existe
python manage.py shell -c "
from django.contrib.auth import get_user_model
User = get_user_model()
if not User.objects.filter(username='admin').exists():
    User.objects.create_superuser('admin', 'admin@bolsas.com', 'admin123')
    print('Superusuario admin creado (password: admin123)')
"

exec gunicorn config.wsgi:application --bind 0.0.0.0:8000 --workers 2 --timeout 120
