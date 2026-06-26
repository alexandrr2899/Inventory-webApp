"""
Django settings — Transformadora de Empaques Inventory
Todas las variables sensibles se leen del entorno (Portainer / .env).
"""

from pathlib import Path
from decouple import config, UndefinedValueError

BASE_DIR = Path(__file__).resolve().parent.parent

# ─── SEGURIDAD BÁSICA ─────────────────────────────────────────────────────────

# SECRET_KEY es obligatorio — sin fallback para evitar claves inseguras en prod.
SECRET_KEY = config('SECRET_KEY')

# DEBUG=False en producción. Portainer envía la variable; local puede usar .env.
DEBUG = config('DEBUG', default=False, cast=bool)

# Hosts permitidos separados por coma: 127.0.0.1,inventario.tempaques.com
ALLOWED_HOSTS = [h.strip() for h in config('ALLOWED_HOSTS', default='localhost,127.0.0.1').split(',') if h.strip()]

# ─── CLOUDFLARE TUNNEL / PROXY ────────────────────────────────────────────────

# Cloudflare Tunnel entrega las peticiones por HTTP al contenedor pero
# el cliente ve HTTPS. Le decimos a Django que confíe en el header del proxy.
SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')

# Necesario para que request.get_host() devuelva el dominio real del tunnel.
USE_X_FORWARDED_HOST = True

# Orígenes CSRF permitidos (con esquema completo): https://inventario.tempaques.com
_csrf_raw = config('CSRF_TRUSTED_ORIGINS', default='')
CSRF_TRUSTED_ORIGINS = [o.strip() for o in _csrf_raw.split(',') if o.strip()]

# ─── SEGURIDAD HTTPS / COOKIES ────────────────────────────────────────────────

# Cloudflare ya maneja el redirect HTTP→HTTPS externo, así que no forzamos
# redirect interno (evita loops de redirección con el tunnel).
SECURE_SSL_REDIRECT = False

# Activar cookies seguras solo en producción (cuando DEBUG=False).
SESSION_COOKIE_SECURE = not DEBUG
CSRF_COOKIE_SECURE    = not DEBUG

# Cabeceras de seguridad adicionales.
SECURE_CONTENT_TYPE_NOSNIFF = True
X_FRAME_OPTIONS = 'DENY'

# ─── APLICACIONES ─────────────────────────────────────────────────────────────

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'django.contrib.humanize',   # formato de miles (intcomma)
    'axes',          # brute-force login protection
    'apps.core',
]

# ─── MIDDLEWARE ───────────────────────────────────────────────────────────────

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'whitenoise.middleware.WhiteNoiseMiddleware',   # sirve estáticos en prod
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'axes.middleware.AxesMiddleware',              # debe ir DESPUÉS de AuthenticationMiddleware
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

# ─── URLS / WSGI ──────────────────────────────────────────────────────────────

ROOT_URLCONF   = 'config.urls'
WSGI_APPLICATION = 'config.wsgi.application'

# ─── TEMPLATES ────────────────────────────────────────────────────────────────

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [BASE_DIR / 'templates'],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
                'django.template.context_processors.tz',
                'apps.core.context_processors.facturas_flags',
            ],
        },
    },
]

# ─── BASE DE DATOS ────────────────────────────────────────────────────────────

# DB_PASSWORD es obligatorio — sin fallback.
DATABASES = {
    'default': {
        'ENGINE':   'django.db.backends.postgresql',
        'HOST':     config('DB_HOST', default='db'),
        'NAME':     config('DB_NAME', default='bolsas_inventario'),
        'USER':     config('DB_USER', default='bolsas_user'),
        'PASSWORD': config('DB_PASSWORD'),           # requerido, sin default
        'PORT':     config('DB_PORT', default='5432'),
        'OPTIONS': {
            'connect_timeout': 10,
        },
    }
}

# ─── VALIDADORES DE CONTRASEÑA ────────────────────────────────────────────────

AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator'},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]

# ─── CACHÉ ────────────────────────────────────────────────────────────────────

# Redis compartido entre workers de gunicorn. Imprescindible para que el
# anti-spam de alertas de stock (apps/core/services/notifications.py) tenga
# un estado único — con LocMemCache cada worker tiene su propia copia y las
# alertas se duplican. Si REDIS_URL está vacío (local/tests) se usa memoria.
REDIS_URL = config('REDIS_URL', default='')

if REDIS_URL:
    CACHES = {
        'default': {
            'BACKEND':  'django.core.cache.backends.redis.RedisCache',
            'LOCATION': REDIS_URL,
        }
    }
else:
    CACHES = {
        'default': {
            'BACKEND':  'django.core.cache.backends.locmem.LocMemCache',
            'LOCATION': 'inventario-locmem',
        }
    }

# ─── INTERNACIONALIZACIÓN ─────────────────────────────────────────────────────

LANGUAGE_CODE = 'es'
TIME_ZONE     = 'America/Tegucigalpa'
USE_I18N      = True
USE_TZ        = True

# ─── ARCHIVOS ESTÁTICOS ───────────────────────────────────────────────────────

STATIC_URL  = '/static/'
STATIC_ROOT = BASE_DIR / 'staticfiles'

# Solo incluir la carpeta fuente si existe (evita W004 en Docker cuando está vacía).
_static_src = BASE_DIR / 'static'
STATICFILES_DIRS = [_static_src] if _static_src.exists() else []

# Sin manifest: más tolerante a archivos opcionales como logos e íconos PWA.
STATICFILES_STORAGE = 'whitenoise.storage.CompressedStaticFilesStorage'

# ─── ARCHIVOS DE MEDIA ────────────────────────────────────────────────────────

MEDIA_URL  = '/media/'
MEDIA_ROOT = BASE_DIR / 'media'

# ─── MÓDULO FACTURAS ──────────────────────────────────────────────────────────
# Interruptor del módulo Facturas (Factura + Envío). Apagarlo lo oculta por
# completo (menú, tab de cliente y rutas → 404). No afecta inventario ni stock.
FACTURAS_MODULE_ENABLED = config('FACTURAS_MODULE_ENABLED', default=True, cast=bool)
# Token para el endpoint de ingesta automática (n8n → /facturas/api/ingest/).
# Vacío = endpoint deshabilitado. Generá uno largo y secreto.
FACTURAS_INGEST_TOKEN = config('FACTURAS_INGEST_TOKEN', default='')

# ─── MISC ─────────────────────────────────────────────────────────────────────

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

LOGIN_URL           = '/login/'
LOGIN_REDIRECT_URL  = '/'
LOGOUT_REDIRECT_URL = '/login/'

MESSAGE_STORAGE = 'django.contrib.messages.storage.session.SessionStorage'

# ─── INTEGRACIONES OPCIONALES ─────────────────────────────────────────────────

# Webhook de n8n para alertas de stock (dejar vacío para deshabilitar).
N8N_WEBHOOK_URL = config('N8N_WEBHOOK_URL', default='')

# ─── BRUTE-FORCE PROTECTION (django-axes) ────────────────────────────────────

AUTHENTICATION_BACKENDS = [
    'axes.backends.AxesStandaloneBackend',
    'django.contrib.auth.backends.ModelBackend',
]

# Bloquear después de 5 intentos fallidos.
AXES_FAILURE_LIMIT = 5

# Bloquear por 1 hora.
AXES_COOLOFF_TIME = 1   # horas (django-axes interpreta int como horas)

# Bloquear SOLO por IP — no por username ni combinación.
# Con 'username' o ['ip_address', 'username'] axes cuenta intentos
# por usuario: si alguien prueba un username inexistente N veces esa
# clave queda "caliente" y bloquea a cualquiera que lo intente después,
# aunque sea desde otra IP → efecto de bloqueo "global".
AXES_LOCKOUT_PARAMETERS = ['ip_address']

# Mensaje que verá el usuario bloqueado.
AXES_LOCKOUT_TEMPLATE = 'registration/lockout.html'

# Registrar intentos en DB para que el admin los vea.
AXES_ENABLE_ACCESS_FAILURE_LOG = True

# Limpiar contador de esa IP cuando el login es exitoso.
AXES_RESET_ON_SUCCESS = True

# ─── LOGGING DE SEGURIDAD ─────────────────────────────────────────────────────

LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {
        'security': {
            'format': '[SECURITY] %(asctime)s %(levelname)s %(name)s %(message)s',
            'datefmt': '%Y-%m-%d %H:%M:%S',
        },
        'events': {
            'format': '[EVENT] %(asctime)s %(levelname)s %(message)s',
            'datefmt': '%Y-%m-%d %H:%M:%S',
        },
        'standard': {
            'format': '%(asctime)s %(levelname)s %(name)s %(message)s',
            'datefmt': '%Y-%m-%d %H:%M:%S',
        },
    },
    'handlers': {
        'console': {
            'class': 'logging.StreamHandler',
            'formatter': 'standard',
        },
        'security_console': {
            'class': 'logging.StreamHandler',
            'formatter': 'security',
        },
        'events_console': {
            'class': 'logging.StreamHandler',
            'formatter': 'events',
        },
    },
    'loggers': {
        # Eventos de negocio: stock bajo, pigmentos, movimientos
        'events': {
            'handlers': ['events_console'],
            'level': 'INFO',
            'propagate': False,
        },
        # Métricas ligeras de vistas pesadas
        'performance': {
            'handlers': ['console'],
            'level': 'INFO',
            'propagate': False,
        },
        # Intentos fallidos y bloqueos de django-axes
        'axes': {
            'handlers': ['security_console'],
            'level': 'WARNING',
            'propagate': False,
        },
        # Eventos de seguridad propios de la app (vistas, permisos, etc.)
        'security': {
            'handlers': ['security_console'],
            'level': 'INFO',
            'propagate': False,
        },
        # Errores Django generales (500, excepciones)
        'django': {
            'handlers': ['console'],
            'level': 'WARNING',
            'propagate': False,
        },
        # Requests HTTP — solo WARNING+ para no saturar logs
        'django.request': {
            'handlers': ['security_console'],
            'level': 'WARNING',
            'propagate': False,
        },
        # Seguridad interna de Django (CSRF, headers, etc.)
        'django.security': {
            'handlers': ['security_console'],
            'level': 'WARNING',
            'propagate': False,
        },
    },
}
