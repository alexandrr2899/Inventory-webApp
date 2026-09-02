# Inventario Bolsas - Sistema de Control de Inventario

App web mobile-first para controlar inventario, movimientos, conteos fisicos,
produccion, clientes, facturas, cobros, maquinas, usuarios, backups y alertas
operativas.

Stack principal: Django 4.2, PostgreSQL 15, Bootstrap 5, Gunicorn,
WhiteNoise, openpyxl, django-axes y Docker Compose.

---

## Modulos incluidos

| Modulo | Descripcion |
|---|---|
| **Dashboard** | Resumen operativo, alertas de stock bajo, acciones rapidas y accesos principales |
| **Inventario** | Items, categorias, ubicaciones, stock por ubicacion, historial por item y orden de listados |
| **Movimientos** | Entradas, salidas, transferencias, edicion, anulacion, eliminacion logica y exportacion CSV |
| **Conteos fisicos** | Conteos manana/tarde por tipo, diferencias sistema vs fisico, conciliacion y anulacion |
| **Produccion** | Registro de producto terminado hacia bodega con fecha/hora operativa |
| **Maquinas** | Catalogo de maquinas por area para salidas de repuestos |
| **Clientes** | Registro, alias, busqueda global, salidas, facturas y estado de cuenta por cliente |
| **Facturas y envios** | Carga individual o por lote, revision, identificacion de cliente, vencimientos, PDFs y anulacion |
| **Cobros** | Abonos, reparto entre documentos, saldo a favor, comprobantes y metodos de pago configurables |
| **Reportes** | Stock bajo, produccion, produccion avanzada y consumo de pigmentos |
| **Importacion Excel** | Descarga de plantilla e importacion masiva de items |
| **Usuarios y permisos** | Roles Administrador, Supervisor y Operador con permisos por modulo |
| **Backups** | Backup diario de PostgreSQL y archivos adjuntos, manual desde Docker o panel web, verificacion de integridad, descarga y registro de trabajos |
| **Notificaciones** | Envio opcional de eventos/reportes a n8n mediante `N8N_WEBHOOK_URL`, Web Push (VAPID) y alertas programadas (facturas vencidas, cobertura de pigmentos) |
| **Integraciones** | Ingesta autenticada de documentos y API interna de Jaime, de solo lectura y con token independiente |
| **Salud** | Sonda `/healthz` (sin autenticacion) usada por los healthchecks de Docker en `web`, `worker` y `beat` |

---

## Requisitos previos

- Docker y Docker Compose.
- Para correr sin Docker: Python 3.11+ y PostgreSQL 15+.

---

## Opcion A - Correr con Docker

### 1. Entrar al proyecto

```bash
cd bolsas_inventario
```

### 2. Crear `.env`

```bash
cp .env.example .env
```

Completa como minimo:

```env
SECRET_KEY=generar-una-clave-larga-y-aleatoria
DEBUG=False
ALLOWED_HOSTS=localhost,127.0.0.1
CSRF_TRUSTED_ORIGINS=
DB_NAME=bolsas_inventario
DB_USER=bolsas_user
DB_PASSWORD=generar-una-contrasena-fuerte
DB_HOST=db
DB_PORT=5432
POSTGRES_HOST=db
BACKUP_DIR=./backups
BACKUP_RETENTION_DAYS=14
BACKUP_TIMEOUT_SECONDS=900
APP_PORT=8000
N8N_WEBHOOK_URL=
FACTURAS_INGEST_TOKEN=
JAIME_API_TOKEN=
ADMIN_URL=gestion-interna/
```

Notas importantes:

- `SECRET_KEY` y `DB_PASSWORD` son obligatorios.
- `FACTURAS_INGEST_TOKEN` habilita la ingesta automatica de documentos desde n8n.
- `JAIME_API_TOKEN` habilita la API interna de consulta; si queda vacio, esa API rechaza todo acceso.
- `ADMIN_URL` define la ruta real del admin Django. `/admin/` devuelve 404 a proposito.
- Si usas Cloudflare Tunnel o dominio publico, agrega el dominio a `ALLOWED_HOSTS` y el origen completo a `CSRF_TRUSTED_ORIGINS`.

### 3. Construir y levantar

```bash
docker compose up --build
```

En segundo plano:

```bash
docker compose up -d --build
```

La app queda disponible en:

```text
http://localhost:8000
```

Si defines otro puerto:

```env
APP_PORT=8001
```

abre `http://localhost:8001`.

### 4. Crear superusuario y roles

```bash
docker compose exec web python manage.py createsuperuser
docker compose exec web python manage.py setup_groups
```

No hay usuario por defecto por seguridad.

### Web Push

Web Push es opcional e independiente de Telegram/n8n. Generá una sola vez las
claves VAPID:

```bash
docker compose run --rm --entrypoint python web manage.py generar_vapid
```

Copiá `VAPID_PRIVATE_KEY`, `VAPID_PUBLIC_KEY` y `VAPID_SUBJECT` al entorno de
Portainer. Conservá el mismo par entre despliegues; cambiarlo obliga a volver a
suscribir todos los dispositivos. Los servicios `worker` y `beat` entregan los
avisos y revisan facturas vencidas diariamente a las 8:00 a. m.

### 5. Comandos utiles

```bash
docker compose exec web python manage.py migrate
docker compose exec web python manage.py check
docker compose exec web python manage.py setup_groups
docker compose logs -f web
docker compose down
docker compose down -v
```

`docker compose down -v` borra los volumenes, incluida la base de datos.

---

## Opcion B - Correr local sin Docker

### 1. Crear entorno e instalar dependencias

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### 2. Crear base PostgreSQL

```bash
psql -U postgres -c "CREATE DATABASE bolsas_inventario;"
psql -U postgres -c "CREATE USER bolsas_user WITH PASSWORD '<contrasena-fuerte>';"
psql -U postgres -c "GRANT ALL PRIVILEGES ON DATABASE bolsas_inventario TO bolsas_user;"
```

### 3. Configurar entorno

```bash
cp .env.example .env
```

Para local, usa `DB_HOST=localhost` y completa `SECRET_KEY` y `DB_PASSWORD`.

### 4. Migrar, crear roles y usuario

```bash
python manage.py migrate
python manage.py setup_groups
python manage.py createsuperuser
python manage.py runserver
```

Abrir:

```text
http://127.0.0.1:8000
```

---

## Roles y permisos

Los grupos se crean o actualizan con:

```bash
python manage.py setup_groups
```

En Docker:

```bash
docker compose exec web python manage.py setup_groups
```

Roles incluidos:

| Rol | Permisos principales |
|---|---|
| **Administrador** | Inventario, movimientos, conteos, reportes, importacion, produccion, backups y gestion avanzada de movimientos |
| **Supervisor** | Inventario, entradas/salidas, conteos, conciliacion, reportes y produccion |
| **Operador** | Inventario, conteos y produccion |

La gestion de usuarios dentro de la app esta restringida a superusuarios.

---

## Importacion Excel

Ruta de la app:

```text
/importar/items/
```

La plantilla se descarga desde:

```text
/importar/plantilla/
```

Columnas requeridas:

- `codigo`
- `nombre`
- `tipo` (`producto`, `repuesto` o `consumible`)
- `unidad_medida`

Columnas opcionales:

- `stock_minimo`
- `categoria`
- `descripcion`

Si el codigo ya existe, el item se actualiza. Si no existe, se crea.

---

## Conteos fisicos

En un renglon que ya tiene item y ubicacion, dejar vacia la cantidad significa
usar la existencia actual del sistema. Esto permite confirmar rapidamente los
items sin diferencia; para registrar existencia cero hay que escribir `0`.

En conteos de tipo **Otros**, los renglones completamente vacios se ignoran. Un
renglon parcialmente lleno sigue siendo invalido y debe completarse antes de
guardar.

---

## Integraciones autenticadas

- `POST /facturas/api/ingest/` recibe documentos desde la automatizacion de
  facturas. Requiere el encabezado `X-API-Key` con `FACTURAS_INGEST_TOKEN`.
- `/api/jaime/` ofrece consultas JSON de solo lectura mediante
  `Authorization: Bearer <JAIME_API_TOKEN>`. Incluye busqueda de clientes,
  saldos, documentos pendientes o vencidos e inventario.

La referencia completa de endpoints y respuestas de Jaime esta en
[docs/JAIME_API.md](docs/JAIME_API.md). Use tokens distintos, largos y
aleatorios para cada integracion y no los guarde en el repositorio.

---

## Backups completos (PostgreSQL + archivos)

El proyecto tiene tres formas de ejecutar backups:

1. **Automatico diario** — tarea Celery `scheduled_backup`, ejecutada por el
   worker a la hora de `BACKUP_SCHEDULE_HOUR:BACKUP_SCHEDULE_MINUTE` (2:30 AM
   por defecto). No requiere intervencion humana.
2. Servicio Docker `backup` (manual).
3. Panel web `/backups/` para usuarios con permiso `gestionar_backups`.

Los tres generan un paquete comprimido con `database.sql.gz` y la carpeta
`media/` completa (incluidos PDFs de facturas y comprobantes):

```text
<BACKUP_DIR>/postgres/inventario_YYYYMMDD_HHMM.tar.gz
```

Todo backup se verifica antes de marcarse como exitoso: se valida la compresión
y la presencia de `database.sql.gz`. Un archivo truncado, corrupto o incompleto
se registra como `BackupJob` fallido y dispara el evento `backup_fallido`.

### Copia fuera del host (importante)

`BACKUP_DIR` vive en el **mismo disco** que la base de datos. Si se pierde el
equipo, se pierden la base y todos sus respaldos a la vez. Para evitarlo,
configura `BACKUP_POST_HOOK` con la ruta de un script (accesible dentro del
contenedor `worker`) que reciba el `.tar.gz` recien creado como primer
argumento y lo copie a otro lado:

```env
BACKUP_POST_HOOK=/scripts/subir_backup.sh
```

```bash
#!/bin/sh
# scripts/subir_backup.sh — recibe la ruta del backup como $1
set -eu
rclone copy "$1" remoto:inventario-backups/
```

El hook se ejecuta despues de verificar la integridad. Si falla, se registra
en el log pero el backup local sigue siendo valido.

### Configurar ubicacion persistente

En local:

```env
BACKUP_DIR=./backups
BACKUP_RETENTION_DAYS=14
```

En Raspberry/Portainer usa una ruta absoluta persistente:

```env
BACKUP_DIR=/apps/inventario/backups
BACKUP_RETENTION_DAYS=14
```

### Backup manual por Docker

```bash
docker compose run --rm backup
```

El contenedor ejecuta `pg_dump`, incluye el volumen `media_files`, comprime el
paquete, valida que no esté vacío y elimina respaldos mayores a
`BACKUP_RETENTION_DAYS`.

### Backup desde panel web

Ruta:

```text
/backups/
```

Requiere superusuario o permiso `gestionar_backups`. El panel permite:

- Ejecutar un backup.
- Ver los ultimos trabajos (`BackupJob`).
- Listar backups disponibles.
- Descargar paquetes `.tar.gz` (y backups antiguos `.sql.gz`).

### Restaurar

La restauracion esta documentada en [RESTORE.md](RESTORE.md). No restaures en produccion sin detener la app web y confirmar el archivo de backup.

Buenas practicas:

- Ejecuta un backup antes de actualizar produccion.
- Copia backups importantes fuera de la Raspberry.
- Prueba restauraciones en un entorno de prueba.
- No subas archivos `.sql`, `.sql.gz` ni `.tar.gz` de respaldo al repositorio.

---

## Notificaciones y n8n

Si `N8N_WEBHOOK_URL` esta definido, la app envia eventos estructurados por HTTP:

- stock bajo o en cero
- resumen de pigmentos
- cobertura de pigmentos (proyeccion de dias restantes)
- movimientos
- backups exitosos o fallidos
- reportes manuales
- eventos de seguridad relevantes

Si `N8N_WEBHOOK_URL` esta vacio, las notificaciones quedan deshabilitadas sin romper el flujo de la app.

Panel manual:

```text
/notificaciones/
```

Requiere superusuario, grupo Administrador o grupo Supervisor.

### Tareas programadas (Celery beat)

| Tarea | Horario | Que hace |
|---|---|---|
| `notify_pigment_coverage` | 07:00 diario | Avisa que pigmentos se agotan antes de poder reponerlos, usando el consumo de los ultimos 30 dias. Solo notifica si hay pigmentos en estado critico (<3 dias) o bajo (<=7 dias); una sola vez por dia |
| `notify_overdue_invoices` | 08:00 diario | Resumen unico de documentos vencidos con saldo |
| `scheduled_backup` | 02:30 diario | Backup automatico de PostgreSQL (ver seccion Backups) |

Los horarios de backup se configuran con `BACKUP_SCHEDULE_HOUR` /
`BACKUP_SCHEDULE_MINUTE`. Las tareas se reintentan hasta 3 veces con backoff y
usan `acks_late`, asi que un worker que muere a mitad no pierde el trabajo.

---

## Seguridad operativa

- `SECRET_KEY` y `DB_PASSWORD` no tienen fallback seguro: deben existir en `.env` o en Portainer.
- El admin real usa `ADMIN_URL`; `/admin/` responde 404.
- `django-axes` bloquea intentos fallidos de login por IP despues de 5 fallos durante 1 hora.
- En produccion, cookies de sesion y CSRF se marcan como seguras cuando `DEBUG=False`.
- La app confia en `X-Forwarded-Proto` y `X-Forwarded-Host` para funcionar detras de Cloudflare Tunnel/proxy.

---

## Pruebas

Con entorno local configurado:

```bash
python manage.py test
```

Con Docker:

```bash
docker compose exec web python manage.py test
```

Tambien existe `docker-compose.test.yml` para levantar un contenedor `web-test` en el puerto 8005 reutilizando la base `db`:

```bash
docker compose -f docker-compose.yml -f docker-compose.test.yml build web-test
docker compose -f docker-compose.yml -f docker-compose.test.yml up -d web-test
```

---

## Estructura del proyecto

```text
bolsas_inventario/
├── config/                         # Settings, URLs globales, auth, admin configurable
├── apps/
│   └── core/
│       ├── models.py               # Inventario, conteos, clientes, facturas, pagos y backups
│       ├── forms.py                # Formularios operativos e importacion
│       ├── urls.py                 # Rutas del modulo core
│       ├── admin.py                # Admin Django
│       ├── signals.py              # Hooks de la app
│       ├── jaime_api/              # API JSON interna de solo lectura
│       ├── tests_facturas/         # Pruebas del modulo de facturacion y cobros
│       ├── services/
│       │   └── notifications.py    # Webhook n8n y payloads de alerta
│       ├── management/commands/
│       │   ├── setup_groups.py
│       │   └── auditar_stock_pendientes.py
│       └── views/                  # Vistas separadas por dominio
│           ├── dashboard.py
│           ├── inventario.py
│           ├── movimientos.py
│           ├── conteos.py
│           ├── catalogos.py
│           ├── reportes.py
│           ├── produccion.py
│           ├── facturas.py
│           ├── facturas_api.py
│           ├── facturas_cliente.py
│           ├── facturas_pagos.py
│           ├── notificaciones.py
│           ├── admin_ops.py
│           └── api.py
├── templates/                      # Bootstrap 5, PWA, pantallas y parciales
├── static/                         # CSS, JS, imagenes e iconos
├── scripts/
│   └── backup_postgres.sh
├── backups/                        # Backups locales, ignorar en Git
├── Dockerfile
├── docker-compose.yml
├── docker-compose.test.yml
├── entrypoint.sh
├── manage.py
├── requirements.txt
├── README.md
└── RESTORE.md
```

---

## Flujo recomendado de produccion

1. Completar `.env` o variables de Portainer.
2. Levantar stack con `docker compose up -d --build`.
3. Ejecutar migraciones.
4. Crear superusuario.
5. Ejecutar `setup_groups`.
6. Asignar roles a usuarios.
7. Confirmar backup manual.
8. Probar login, dashboard, inventario, movimientos y reportes.
9. Si se habilitan integraciones, verificar la ingesta y la API de Jaime con
   sus respectivos tokens.
