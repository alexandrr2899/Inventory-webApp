# Inventario Bolsas — Sistema de Control de Inventario

App web mobile-first para control de inventario de planta de producción de bolsas.
Desarrollada con Django + PostgreSQL + Bootstrap 5.

---

## Módulos incluidos

| Módulo | Descripción |
|---|---|
| **Dashboard** | Resumen del día, alertas de stock bajo, producción estimada, acciones rápidas |
| **Inventario** | Gestión de ítems (productos, repuestos, consumibles) y ubicaciones |
| **Movimientos** | Entradas, salidas, transferencias con actualización automática de stock |
| **Conteos físicos** | Conteo mañana/tarde, comparación sistema vs físico, ajuste por diferencia |
| **Producción** | Cálculo diario: Tarde − Mañana + Salidas |
| **Máquinas** | Catálogo de máquinas por área |
| **Clientes** | Registro de clientes para salidas de producto terminado |
| **Reportes** | Stock bajo con exportación CSV, historial de movimientos con filtros |

---

## Requisitos previos

- **Docker** y **Docker Compose** instalados  
  _O_ Python 3.11+ y PostgreSQL 15+ si prefieres correr local sin Docker

---

## Opción A — Correr con Docker (recomendado)

### 1. Clonar / descargar el proyecto

```bash
cd bolsas_inventario
```

### 2. Crear el archivo de entorno

```bash
cp .env.example .env
```

Edita `.env` y cambia al menos `SECRET_KEY` en producción:

```env
DEBUG=True
SECRET_KEY=cambia-esto-por-una-clave-segura
DB_HOST=db
DB_NAME=bolsas_inventario
DB_USER=bolsas_user
DB_PASSWORD=bolsas_pass
DB_PORT=5432
ALLOWED_HOSTS=localhost,127.0.0.1
```

### 3. Construir y levantar los contenedores

```bash
docker-compose up --build
```

La primera vez tarda unos minutos. Verás en la consola:

```
web_1  | Esperando base de datos...
web_1  | Base de datos lista.
web_1  | Superusuario admin creado (password: admin123)
```

### 4. Abrir en el navegador

```
http://localhost:8000
```

**Usuario por defecto:** `admin` / **Contraseña:** `admin123`

> ⚠️ Cambia la contraseña del admin en `/admin/` antes de usar en producción.

### 5. Detener

```bash
docker-compose down          # detiene y elimina contenedores
docker-compose down -v       # también elimina los volúmenes (borra la BD)
```

---

## Opción B — Correr local sin Docker

### 1. Crear entorno virtual e instalar dependencias

```bash
cd bolsas_inventario
python3 -m venv venv
source venv/bin/activate          # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

### 2. Crear base de datos PostgreSQL

```bash
psql -U postgres -c "CREATE DATABASE bolsas_inventario;"
psql -U postgres -c "CREATE USER bolsas_user WITH PASSWORD 'bolsas_pass';"
psql -U postgres -c "GRANT ALL PRIVILEGES ON DATABASE bolsas_inventario TO bolsas_user;"
```

### 3. Configurar variables de entorno

```bash
cp .env.example .env
# Edita .env con tus valores de DB_HOST=localhost, etc.
```

### 4. Aplicar migraciones y crear superusuario

```bash
python manage.py migrate
python manage.py createsuperuser
```

### 5. Cargar datos iniciales de ejemplo (opcional)

```bash
python manage.py shell -c "
from apps.core.models import Categoria, Ubicacion, Maquina
Categoria.objects.get_or_create(nombre='Bolsas de polietileno')
Categoria.objects.get_or_create(nombre='Bolsas biodegradables')
Categoria.objects.get_or_create(nombre='Materia prima')
Ubicacion.objects.get_or_create(nombre='Bodega Principal', defaults={'tipo':'bodega'})
Ubicacion.objects.get_or_create(nombre='Área de Producción', defaults={'tipo':'produccion'})
Ubicacion.objects.get_or_create(nombre='Estante A', defaults={'tipo':'estante'})
Maquina.objects.get_or_create(codigo='M-001', defaults={'nombre':'Extrusora 1', 'area':'Producción'})
Maquina.objects.get_or_create(codigo='M-002', defaults={'nombre':'Selladora 1', 'area':'Producción'})
print('Datos de ejemplo creados.')
"
```

### 6. Correr el servidor de desarrollo

```bash
python manage.py runserver
```

Abrir en `http://127.0.0.1:8000`

---

## Estructura del proyecto

```
bolsas_inventario/
├── config/                  # Configuración Django
│   ├── settings.py
│   ├── urls.py
│   └── wsgi.py
├── apps/
│   └── core/                # Aplicación principal
│       ├── models.py        # Item, Stock, Movimiento, Conteo, etc.
│       ├── views.py         # Todas las vistas
│       ├── forms.py         # Formularios con validación
│       ├── urls.py          # Rutas URL
│       └── admin.py         # Panel de administración
├── templates/               # Plantillas HTML (Bootstrap 5)
│   ├── base.html            # Layout base con nav mobile
│   ├── dashboard.html
│   ├── inventario/
│   ├── movimientos/
│   ├── conteos/
│   ├── maquinas/
│   ├── clientes/
│   └── reportes/
├── static/                  # CSS y JS personalizados
├── Dockerfile
├── docker-compose.yml
├── entrypoint.sh
├── requirements.txt
└── .env.example
```

---

## Flujo de trabajo diario

### Conteo de inventario (2 veces al día)

1. Ir a **Conteos → Nuevo Conteo**
2. Seleccionar **fecha**, **turno** (mañana o tarde) y **ubicación general**
3. Ingresar la cantidad física contada para cada producto
4. Guardar — el sistema calcula la diferencia vs. el stock del sistema
5. Si hay diferencias, revisar y opcionalmente **Aplicar Ajuste**

### Registrar producción / salidas

- **Nueva Entrada**: para ingresar materia prima o productos recibidos
- **Nueva Salida**: para despacho a clientes (productos terminados) o consumo de repuestos
- **Transferencia**: para mover stock entre ubicaciones

### Ver producción estimada del día

1. Dashboard → sección producción, **o**
2. **Reportes → Producción Diaria**

La fórmula es: `Producción = Conteo Tarde − Conteo Mañana + Salidas del día`

---

## Variables de entorno

| Variable | Descripción | Default |
|---|---|---|
| `DEBUG` | Modo debug (False en producción) | `True` |
| `SECRET_KEY` | Clave secreta Django | — |
| `DB_HOST` | Host PostgreSQL | `localhost` |
| `DB_NAME` | Nombre de la base de datos | `bolsas_inventario` |
| `DB_USER` | Usuario PostgreSQL | `bolsas_user` |
| `DB_PASSWORD` | Contraseña PostgreSQL | `bolsas_pass` |
| `DB_PORT` | Puerto PostgreSQL | `5432` |
| `ALLOWED_HOSTS` | Hosts permitidos (separados por coma) | `localhost,127.0.0.1` |

---

## URLs principales

| URL | Descripción |
|---|---|
| `/` | Dashboard |
| `/inventario/` | Lista de ítems |
| `/movimientos/entrada/` | Nueva entrada |
| `/movimientos/salida/` | Nueva salida |
| `/conteos/nuevo/` | Nuevo conteo físico |
| `/reportes/stock-bajo/` | Ítems bajo stock mínimo |
| `/reportes/produccion/` | Producción del día |
| `/admin/` | Panel de administración Django |

---

## Notas para producción

```bash
# En .env:
DEBUG=False
SECRET_KEY=clave-larga-aleatoria-segura
ALLOWED_HOSTS=tu-dominio.com,www.tu-dominio.com
```

```bash
# Colectar archivos estáticos
python manage.py collectstatic

# Usar Gunicorn (ya configurado en entrypoint.sh)
gunicorn config.wsgi:application --bind 0.0.0.0:8000
```

Para HTTPS en producción se recomienda poner **Nginx** como proxy reverso frente a Gunicorn.
