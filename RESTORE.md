# Restaurar backup PostgreSQL

Este procedimiento restaura la base de datos desde un archivo `inventario_YYYYMMDD_HHMM.sql.gz`.

No lo ejecutes improvisadamente en producción. Antes de restaurar, confirma que:

- El archivo de backup existe y no está vacío.
- Sabes qué datos se van a reemplazar.
- La app web está detenida para evitar escrituras durante la restauración.
- Tienes un backup adicional reciente por si necesitas volver atrás.

## 1. Ubicar el backup

Los backups manuales se guardan en la carpeta configurada por `BACKUP_DIR`.

Ejemplo en Raspberry:

```bash
ls -lh /apps/inventario/backups/postgres/
```

Ejemplo de archivo:

```text
inventario_20260519_2130.sql.gz
```

## 2. Detener la app web

Desde la carpeta del stack:

```bash
docker compose stop web
```

La base de datos debe quedar corriendo.

## 3. Limpiar el schema actual

Esto borra las tablas actuales dentro de la base seleccionada.

```bash
docker compose exec db psql \
  -U "${DB_USER:-bolsas_user}" \
  -d "${DB_NAME:-bolsas_inventario}" \
  -c "DROP SCHEMA public CASCADE; CREATE SCHEMA public;"
```

## 4. Restaurar el archivo `.sql.gz`

Si el backup está en `./backups/postgres/`:

```bash
gunzip -c ./backups/postgres/inventario_YYYYMMDD_HHMM.sql.gz | \
  docker compose exec -T db psql \
    -U "${DB_USER:-bolsas_user}" \
    -d "${DB_NAME:-bolsas_inventario}"
```

Si estás en Raspberry y `BACKUP_DIR=/apps/inventario/backups`:

```bash
gunzip -c /apps/inventario/backups/postgres/inventario_YYYYMMDD_HHMM.sql.gz | \
  docker compose exec -T db psql \
    -U "${DB_USER:-bolsas_user}" \
    -d "${DB_NAME:-bolsas_inventario}"
```

## 5. Aplicar migraciones

Después de restaurar, ejecuta migraciones por si el código actual tiene cambios de schema:

```bash
docker compose run --rm web python manage.py migrate
```

## 6. Levantar la app

```bash
docker compose up -d web
docker compose logs -f web
```

## 7. Verificación rápida

Entra al sistema y revisa:

- Dashboard.
- Inventario.
- Movimientos recientes.
- Conteos.
- Reportes principales.

También puedes ejecutar:

```bash
docker compose exec web python manage.py check
```

## Nota sobre `pg_restore`

Este proyecto genera backups en formato SQL plano comprimido (`.sql.gz`), por eso se restaura con `psql`.

`pg_restore` se usa para backups en formato custom (`pg_dump -Fc`), no para este formato.
