FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

# postgresql-client-15, NO el 'postgresql-client' de Debian.
#
# La base corre PostgreSQL 15, pero Debian trixie empaqueta el cliente 17. Un
# pg_dump 17 contra un servidor 15 produce un dump con directivas propias de
# 17 (`SET transaction_timeout`), que PG15 no reconoce: restaurar ese archivo
# con `psql -v ON_ERROR_STOP=1` aborta al primer comando. Los backups del
# panel web y de la tarea programada salen de ESTE contenedor, así que el
# cliente tiene que coincidir con el servidor.
# Si algún día se sube la base a otra versión mayor, actualizar ambos a la vez.
RUN apt-get update && apt-get install -y --no-install-recommends \
        curl ca-certificates gnupg \
    && install -d /usr/share/postgresql-common/pgdg \
    && curl -fsSL https://www.postgresql.org/media/keys/ACCC4CF8.asc \
        -o /usr/share/postgresql-common/pgdg/apt.postgresql.org.asc \
    && echo "deb [signed-by=/usr/share/postgresql-common/pgdg/apt.postgresql.org.asc] https://apt.postgresql.org/pub/repos/apt trixie-pgdg main" \
        > /etc/apt/sources.list.d/pgdg.list \
    && apt-get update && apt-get install -y --no-install-recommends \
        postgresql-client-15 gzip tar \
    && apt-get purge -y --auto-remove curl gnupg \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Crear directorios de estáticos aunque no vengan con el código
RUN mkdir -p static/images static/icons staticfiles

RUN chmod +x entrypoint.sh

EXPOSE 8000

ENTRYPOINT ["sh", "entrypoint.sh"]
