# Restaurar backup PostgreSQL

Este procedimiento restaura la base de datos desde un archivo:

```text
inventario_YYYYMMDD_HHMM.sql.gz
```

El proyecto genera backups en formato SQL plano comprimido (`.sql.gz`), por eso se restauran con `psql` y `gunzip`. `pg_restore` solo aplica a backups custom como `pg_dump -Fc`.

No ejecutes una restauracion improvisada en produccion. Antes de empezar, confirma:

- El archivo existe y no esta vacio.
- Sabes exactamente que base de datos se va a reemplazar.
- La app web esta detenida para evitar escrituras durante la restauracion.
- Tienes un backup adicional reciente para volver atras.
- Las variables `DB_NAME`, `DB_USER` y `DB_PASSWORD` apuntan a la base correcta.

---

## 1. Ubicar el backup

Los backups se guardan en la carpeta configurada por `BACKUP_DIR`, dentro de `postgres/`.

Local:

```bash
ls -lh ./backups/postgres/
```

Raspberry/Portainer, si usas `BACKUP_DIR=/apps/inventario/backups`:

```bash
ls -lh /apps/inventario/backups/postgres/
```

Ejemplo:

```text
inventario_20260519_2130.sql.gz
```

Tambien puedes descargar backups desde el panel web:

```text
/backups/
```

Requiere superusuario o permiso `gestionar_backups`.

---

## 2. Crear un backup de seguridad antes de restaurar

Desde la carpeta del stack:

```bash
docker compose run --rm backup
```

Verifica que el archivo nuevo exista:

```bash
ls -lh ./backups/postgres/
```

En Raspberry:

```bash
ls -lh /apps/inventario/backups/postgres/
```

---

## 3. Detener la app web

La base de datos debe quedar corriendo, pero la app no debe aceptar escrituras.

```bash
docker compose stop web
```

Confirma que `db` sigue arriba:

```bash
docker compose ps
```

---

## 4. Limpiar el schema actual

Esto borra las tablas actuales dentro de la base seleccionada.

```bash
docker compose exec db psql \
  -U "${DB_USER:-bolsas_user}" \
  -d "${DB_NAME:-bolsas_inventario}" \
  -c "DROP SCHEMA public CASCADE; CREATE SCHEMA public;"
```

Si tu shell no expande esas variables porque estas fuera del entorno del proyecto, usa los valores reales:

```bash
docker compose exec db psql \
  -U bolsas_user \
  -d bolsas_inventario \
  -c "DROP SCHEMA public CASCADE; CREATE SCHEMA public;"
```

---

## 5. Restaurar el archivo `.sql.gz`

Local:

```bash
gunzip -c ./backups/postgres/inventario_YYYYMMDD_HHMM.sql.gz | \
  docker compose exec -T db psql \
    -U "${DB_USER:-bolsas_user}" \
    -d "${DB_NAME:-bolsas_inventario}" \
    -v ON_ERROR_STOP=1
```

Raspberry/Portainer:

```bash
gunzip -c /apps/inventario/backups/postgres/inventario_YYYYMMDD_HHMM.sql.gz | \
  docker compose exec -T db psql \
    -U "${DB_USER:-bolsas_user}" \
    -d "${DB_NAME:-bolsas_inventario}" \
    -v ON_ERROR_STOP=1
```

Reemplaza `inventario_YYYYMMDD_HHMM.sql.gz` por el archivo real.

`-v ON_ERROR_STOP=1` aborta al primer error en vez de seguir adelante y
dejarte una base a medio restaurar que *parece* haber funcionado. Si el
comando termina con codigo distinto de 0, la restauracion NO se completo.

---

## 5b. Ensayo de restauracion (hacerlo periodicamente)

Un backup que nunca se restauro es una suposicion, no un respaldo. Este
ensayo restaura sobre una base descartable sin tocar produccion:

```bash
# 1. Crear base scratch
docker compose exec -T db psql -U "${DB_USER:-bolsas_user}" -d postgres \
  -c "DROP DATABASE IF EXISTS restore_drill;" \
  -c "CREATE DATABASE restore_drill;"

# 2. Restaurar el backup mas reciente en modo estricto
gunzip -c ./backups/postgres/inventario_YYYYMMDD_HHMM.sql.gz | \
  docker compose exec -T db psql -U "${DB_USER:-bolsas_user}" \
    -d restore_drill -v ON_ERROR_STOP=1
echo "exit=$?"   # debe ser 0

# 3. Verificar que las tablas llegaron
docker compose exec -T db psql -U "${DB_USER:-bolsas_user}" -d restore_drill \
  -tAc "SELECT count(*) FROM information_schema.tables WHERE table_schema='public';"

# 4. Limpiar
docker compose exec -T db psql -U "${DB_USER:-bolsas_user}" -d postgres \
  -c "DROP DATABASE restore_drill;"
```

Nota sobre versiones: el `pg_dump` de la imagen de la app esta fijado a la
misma version mayor que el servidor (PostgreSQL 15, ver `Dockerfile`). Un
cliente mas nuevo genera dumps con directivas que PG15 no entiende y que
hacen fallar la restauracion estricta. Si algun dia se sube la version mayor
de la base, hay que subir tambien `postgresql-client-15` en el `Dockerfile`.

---

## 6. Aplicar migraciones

Despues de restaurar, aplica migraciones por si el codigo actual tiene cambios de schema posteriores al backup.

Como el `entrypoint.sh` normal del servicio `web` termina arrancando Gunicorn, para ejecutar comandos puntuales con `docker compose run` se sobrescribe el entrypoint:

```bash
docker compose run --rm --entrypoint python web manage.py migrate
```

Luego sincroniza grupos/permisos:

```bash
docker compose run --rm --entrypoint python web manage.py setup_groups
```

---

## 7. Levantar la app

```bash
docker compose up -d web
docker compose logs -f web
```

---

## 8. Verificacion rapida

Ejecuta:

```bash
docker compose exec web python manage.py check
```

Luego entra al sistema y revisa:

- Login.
- Dashboard.
- Inventario y stock por ubicacion.
- Movimientos recientes.
- Conteos y conciliaciones.
- Reportes principales.
- Panel de backups.

Si usas notificaciones, confirma que `N8N_WEBHOOK_URL` siga configurado.

---

## Restaurar en un contenedor de prueba

Para validar un backup sin tocar produccion, puedes levantar `web-test` en el puerto 8005 con:

```bash
docker compose -f docker-compose.yml -f docker-compose.test.yml build web-test
docker compose -f docker-compose.yml -f docker-compose.test.yml up -d web-test
```

Ese servicio reutiliza el `db` del stack, asi que para una prueba de restauracion realmente aislada conviene usar otra base o un stack separado. No lo uses como restauracion "segura" si apunta a la misma base de produccion.

---

## Problemas comunes

### `FATAL: password authentication failed`

Revisa que `DB_USER`, `DB_PASSWORD` y `DB_NAME` coincidan con el contenedor `db`.

### `role "..." does not exist`

Estas restaurando con un usuario que no existe dentro del contenedor PostgreSQL. Usa `DB_USER` o crea el rol antes.

### `relation already exists`

El schema no se limpio antes de restaurar. Repite el paso de limpieza y restaura de nuevo.

### `gunzip: not in gzip format`

El archivo no es `.gz` valido o se descargo incompleto. Verifica tamano y origen del backup.

### La app levanta pero faltan permisos

Ejecuta:

```bash
docker compose run --rm --entrypoint python web manage.py setup_groups
```
