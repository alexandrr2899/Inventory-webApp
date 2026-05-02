#!/bin/bash
set -e

echo "📦 Actualizando repo..."
cd ~/apps/Inventory-webApp
git pull origin master

echo "🐳 Reconstruyendo contenedores..."
cd ~/apps/Inventory-webApp/bolsas_inventario
docker compose down
docker compose up -d --build

echo "🗄️ Aplicando migraciones..."
docker compose exec web python manage.py migrate

echo "🎨 Recolectando archivos estáticos..."
docker compose exec web python manage.py collectstatic --noinput

echo "🔄 Reiniciando app..."
docker compose restart web

echo "✅ Actualización completada"
docker compose ps
