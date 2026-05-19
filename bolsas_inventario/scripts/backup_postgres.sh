#!/bin/sh
set -eu

BACKUP_ROOT="${BACKUP_ROOT:-/backups/postgres}"
RETENTION_DAYS="${BACKUP_RETENTION_DAYS:-14}"
POSTGRES_HOST="${POSTGRES_HOST:-db}"
POSTGRES_PORT="${POSTGRES_PORT:-5432}"

if [ -z "${POSTGRES_DB:-}" ]; then
    echo "[backup] ERROR: POSTGRES_DB no está definido." >&2
    exit 1
fi

if [ -z "${POSTGRES_USER:-}" ]; then
    echo "[backup] ERROR: POSTGRES_USER no está definido." >&2
    exit 1
fi

if [ -z "${POSTGRES_PASSWORD:-}" ]; then
    echo "[backup] ERROR: POSTGRES_PASSWORD no está definido." >&2
    exit 1
fi

mkdir -p "$BACKUP_ROOT"

timestamp="$(date +%Y%m%d_%H%M)"
filename="inventario_${timestamp}.sql.gz"
tmp_file="${BACKUP_ROOT}/.${filename}.tmp"
backup_file="${BACKUP_ROOT}/${filename}"

echo "[backup] Iniciando backup PostgreSQL..."
echo "[backup] Host: ${POSTGRES_HOST}:${POSTGRES_PORT}"
echo "[backup] DB: ${POSTGRES_DB}"
echo "[backup] Destino: ${backup_file}"

export PGPASSWORD="$POSTGRES_PASSWORD"

pg_dump \
    -h "$POSTGRES_HOST" \
    -p "$POSTGRES_PORT" \
    -U "$POSTGRES_USER" \
    -d "$POSTGRES_DB" \
    --no-owner \
    --no-acl \
    | gzip > "$tmp_file"

if [ ! -s "$tmp_file" ]; then
    echo "[backup] ERROR: el archivo generado está vacío." >&2
    rm -f "$tmp_file"
    exit 1
fi

mv "$tmp_file" "$backup_file"

size_bytes="$(wc -c < "$backup_file" | tr -d ' ')"
echo "[backup] Backup creado correctamente: ${backup_file}"
echo "[backup] Tamaño: ${size_bytes} bytes"

echo "[backup] Eliminando backups mayores a ${RETENTION_DAYS} día(s)..."
find "$BACKUP_ROOT" -type f -name 'inventario_*.sql.gz' -mtime +"$RETENTION_DAYS" -print -delete

echo "[backup] Backups disponibles:"
ls -lh "$BACKUP_ROOT"/inventario_*.sql.gz 2>/dev/null || true
echo "[backup] Finalizado."
