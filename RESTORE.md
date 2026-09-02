# Restaurar backup completo

Este procedimiento restaura la base de datos y los archivos adjuntos desde:

```text
inventario_YYYYMMDD_HHMM.tar.gz
```

El paquete contiene `database.sql.gz` y `media/`. La base se restaura con
`psql` y `gunzip`; los PDFs y comprobantes se copian nuevamente al volumen
Docker `media_files`. `pg_restore` solo aplica a backups custom como
`pg_dump -Fc`.

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
inventario_20260811_1200.tar.gz
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

## 3. Detener procesos que escriben datos

La base de datos debe quedar corriendo, pero la app no debe aceptar escrituras.

```bash
docker compose stop web worker beat
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

## 5. Extraer el paquete

Usa una carpeta temporal y conserva esa terminal abierta durante el proceso:

```bash
RESTORE_TMP="$(mktemp -d)"
tar -xzf ./backups/postgres/inventario_YYYYMMDD_HHMM.tar.gz -C "$RESTORE_TMP"
test -s "$RESTORE_TMP/database.sql.gz"
test -d "$RESTORE_TMP/media"
```

En Raspberry, sustituye la ruta del archivo por
`/apps/inventario/backups/postgres/inventario_YYYYMMDD_HHMM.tar.gz`.

## 6. Restaurar la base de datos

Local:

```bash
gunzip -c "$RESTORE_TMP/database.sql.gz" | \
  docker compose exec -T db psql \
    -U "${DB_USER:-bolsas_user}" \
    -d "${DB_NAME:-bolsas_inventario}" \
    -v ON_ERROR_STOP=1
```

Reemplaza `inventario_YYYYMMDD_HHMM.tar.gz` por el archivo real.

`-v ON_ERROR_STOP=1` aborta al primer error en vez de seguir adelante y
dejarte una base a medio restaurar que *parece* haber funcionado. Si el
comando termina con codigo distinto de 0, la restauracion NO se completo.

---

## 7. Restaurar PDFs y demás archivos adjuntos

Este paso reemplaza el contenido actual de `media_files` por el contenido del
backup. Ejecútalo solamente después de confirmar que `RESTORE_TMP/media`
corresponde al respaldo correcto:

```bash
test -d "$RESTORE_TMP/media" && \
tar -C "$RESTORE_TMP/media" -cf - . | \
  docker compose run --rm -T --no-deps --entrypoint sh web -c \
  'find /app/media -mindepth 1 -maxdepth 1 -exec rm -rf -- {} + && tar -xf - -C /app/media'
```

Al terminar, elimina la extracción temporal:

```bash
rm -rf -- "$RESTORE_TMP"
unset RESTORE_TMP
```

## 7b. Ensayo de restauracion (hacerlo periodicamente)

Un backup que nunca se restauro es una suposicion, no un respaldo. Este
ensayo restaura sobre una base descartable sin tocar produccion:

```bash
# 0. Extraer el paquete en una carpeta temporal
DRILL_TMP="$(mktemp -d)"
tar -xzf ./backups/postgres/inventario_YYYYMMDD_HHMM.tar.gz -C "$DRILL_TMP"

# 1. Crear base scratch
docker compose exec -T db psql -U "${DB_USER:-bolsas_user}" -d postgres \
  -c "DROP DATABASE IF EXISTS restore_drill;" \
  -c "CREATE DATABASE restore_drill;"

# 2. Restaurar el backup mas reciente en modo estricto
gunzip -c "$DRILL_TMP/database.sql.gz" | \
  docker compose exec -T db psql -U "${DB_USER:-bolsas_user}" \
    -d restore_drill -v ON_ERROR_STOP=1
echo "exit=$?"   # debe ser 0

# 3. Verificar que las tablas llegaron
docker compose exec -T db psql -U "${DB_USER:-bolsas_user}" -d restore_drill \
  -tAc "SELECT count(*) FROM information_schema.tables WHERE table_schema='public';"

# 4. Limpiar
docker compose exec -T db psql -U "${DB_USER:-bolsas_user}" -d postgres \
  -c "DROP DATABASE restore_drill;"

# 5. Limpiar archivos temporales
rm -rf -- "$DRILL_TMP"
unset DRILL_TMP
```

Nota sobre versiones: el `pg_dump` de la imagen de la app esta fijado a la
misma version mayor que el servidor (PostgreSQL 15, ver `Dockerfile`). Un
cliente mas nuevo genera dumps con directivas que PG15 no entiende y que
hacen fallar la restauracion estricta. Si algun dia se sube la version mayor
de la base, hay que subir tambien `postgresql-client-15` en el `Dockerfile`.

---

## 8. Aplicar migraciones

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

## 9. Levantar la app

```bash
docker compose up -d web worker beat
docker compose logs -f web
```

---

## 10. Verificacion rapida

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
- Abrir varios PDFs de facturas y comprobantes restaurados.

Si usas notificaciones, confirma que `N8N_WEBHOOK_URL` siga configurado.
Si usas integraciones, confirma tambien `FACTURAS_INGEST_TOKEN` y
`JAIME_API_TOKEN`: estos secretos viven en el entorno y no dentro del backup.

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
