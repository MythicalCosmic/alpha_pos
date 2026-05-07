import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

DEBUG = os.environ.get('DEBUG', 'False').lower() in ('true', '1', 'yes')

SECRET_KEY = os.environ.get('SECRET_KEY', '')
if not SECRET_KEY:
    if DEBUG:
        SECRET_KEY = 'django-insecure-dev-only-key-do-not-use-in-production'
    else:
        from django.core.exceptions import ImproperlyConfigured
        raise ImproperlyConfigured(
            "SECRET_KEY environment variable must be set when DEBUG is False."
        )

if DEBUG:
    ALLOWED_HOSTS = ['*']
else:
    ALLOWED_HOSTS = os.environ.get('ALLOWED_HOSTS', 'localhost,127.0.0.1').split(',')


# Application definition

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'corsheaders',
    'base',
    'customers',
    'admins',
    'stock',
    'hr',
    'waiters',
    'discounts',
    'notifications',
]

MIDDLEWARE = [
    'corsheaders.middleware.CorsMiddleware',
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
    'base.middlewares.force_json_middleware.JSONOnlyMiddleware'
]

ROOT_URLCONF = 'alpha_pos.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

WSGI_APPLICATION = 'alpha_pos.wsgi.application'


if os.environ.get('DB_ENGINE'):
    DATABASES = {
        'default': {
            'ENGINE': os.environ['DB_ENGINE'],
            'NAME': os.environ.get('DB_NAME', 'alpha_pos'),
            'USER': os.environ.get('DB_USER', 'alpha_pos'),
            'PASSWORD': os.environ.get('DB_PASSWORD', ''),
            'HOST': os.environ.get('DB_HOST', 'db'),
            'PORT': os.environ.get('DB_PORT', '5432'),
        }
    }
else:
    DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.sqlite3',
            'NAME': BASE_DIR / 'db.sqlite3',
        }
    }


# Password validation
# https://docs.djangoproject.com/en/5.2/ref/settings/#auth-password-validators

AUTH_PASSWORD_VALIDATORS = [
    {
        'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator',
    },
]


# Internationalization
# https://docs.djangoproject.com/en/5.2/topics/i18n/

LANGUAGE_CODE = 'en-us'

TIME_ZONE = 'UTC'

USE_I18N = True

USE_TZ = True


# Static files (CSS, JavaScript, Images)
# https://docs.djangoproject.com/en/5.2/howto/static-files/

STATIC_URL = 'static/'
STATIC_ROOT = BASE_DIR / 'staticfiles'

# Private media (HR documents). Files are NOT served by Django's static
# file machinery — they're streamed only via auth-gated download views.
MEDIA_ROOT = os.environ.get('MEDIA_ROOT', str(BASE_DIR / 'private_media'))
MEDIA_URL = '/private-media/'  # not actually served; placeholder for FileField.url

# Default primary key field type
# https://docs.djangoproject.com/en/5.2/ref/settings/#default-auto-field

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

BRANCH_ID = 'main'
DEPLOYMENT_MODE = 'local'
SYNC_ON_SAVE = False

GEMINI_API_KEY = os.environ.get('GEMINI_API_KEY', '')

REDIS_URL = os.environ.get('REDIS_URL', 'redis://127.0.0.1:6379/0')

if os.environ.get('USE_REDIS', '').lower() in ('true', '1', 'yes'):
    CACHES = {
        'default': {
            'BACKEND': 'django_redis.cache.RedisCache',
            'LOCATION': REDIS_URL,
            'OPTIONS': {
                'CLIENT_CLASS': 'django_redis.client.DefaultClient',
            },
            'KEY_PREFIX': 'alpha_pos',
            'TIMEOUT': 300,
        }
    }
else:
    CACHES = {
        'default': {
            'BACKEND': 'django.core.cache.backends.locmem.LocMemCache',
            'LOCATION': 'alpha-pos-cache',
            'TIMEOUT': 300,
        }
}

SESSION_CACHE_TTL = 300

SYNC_ENABLED = False
CLOUD_SYNC_URL = ''
CLOUD_SYNC_TOKEN = ''
SYNC_INTERVAL = 30
SYNC_RETRY_INTERVAL = 60
SYNC_TIMEOUT = 30
SYNC_MAX_RETRIES = 5
SYNC_BATCH_SIZE = 500
ALLOWED_BRANCH_TOKENS = []
# Bind sync tokens to a specific branch so X-Branch-ID cannot be spoofed.
# Format: {"branch_token_string": "branch_id"}. When set, this takes
# precedence over ALLOWED_BRANCH_TOKENS (which has no per-branch binding).
BRANCH_TOKEN_MAP = {}
SYNC_PULL_ENABLED = True

SESSION_COOKIE_HTTPONLY = True
CSRF_COOKIE_HTTPONLY = True

# Security settings for production
if not DEBUG:
    SECURE_HSTS_SECONDS = 31536000
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True
    SECURE_HSTS_PRELOAD = True
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_BROWSER_XSS_FILTER = True
    SECURE_CONTENT_TYPE_NOSNIFF = True
    SECURE_REFERRER_POLICY = 'same-origin'
    X_FRAME_OPTIONS = 'DENY'
    # Only enable SSL redirect when explicitly opted in via env so reverse-proxy
    # setups (the typical deployment) don't end up with a redirect loop.
    SECURE_SSL_REDIRECT = os.environ.get(
        'SECURE_SSL_REDIRECT', 'False'
    ).lower() in ('true', '1', 'yes')
    # Trust X-Forwarded-Proto from a known-good reverse proxy when terminating
    # TLS at the proxy. Configure only when behind such a proxy.
    if os.environ.get('TRUST_FORWARDED_PROTO', '').lower() in ('true', '1', 'yes'):
        SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')

# Pagination limits
MAX_PER_PAGE = 100

# Logging — file rotation in prod, console in dev. Override the log directory
# via LOG_DIR env if you want logs outside the project root.
LOG_DIR = os.environ.get('LOG_DIR', str(BASE_DIR / 'logs'))
LOG_LEVEL = os.environ.get('LOG_LEVEL', 'INFO').upper()

if not DEBUG:
    try:
        os.makedirs(LOG_DIR, exist_ok=True)
    except OSError:
        # If the configured directory isn't writable, fall back to console-only
        # so the process still boots; an operator can fix LOG_DIR later.
        LOG_DIR = None

LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {
        'verbose': {
            'format': '{asctime} {levelname} {name} [{process:d}] {message}',
            'style': '{',
        },
        'simple': {
            'format': '{levelname} {name}: {message}',
            'style': '{',
        },
    },
    'handlers': {
        'console': {
            'class': 'logging.StreamHandler',
            'formatter': 'simple' if DEBUG else 'verbose',
            'level': LOG_LEVEL,
        },
        **(
            {
                'app_file': {
                    'class': 'logging.handlers.RotatingFileHandler',
                    'filename': os.path.join(LOG_DIR, 'app.log'),
                    'maxBytes': 10 * 1024 * 1024,
                    'backupCount': 5,
                    'formatter': 'verbose',
                    'level': LOG_LEVEL,
                },
                'error_file': {
                    'class': 'logging.handlers.RotatingFileHandler',
                    'filename': os.path.join(LOG_DIR, 'error.log'),
                    'maxBytes': 10 * 1024 * 1024,
                    'backupCount': 10,
                    'formatter': 'verbose',
                    'level': 'ERROR',
                },
            } if (not DEBUG and LOG_DIR) else {}
        ),
    },
    'loggers': {
        # Quiet down noisy third-party loggers; keep errors.
        'django.utils.autoreload': {'level': 'WARNING'},
        'urllib3': {'level': 'WARNING'},
        'requests': {'level': 'WARNING'},
    },
    'root': {
        'handlers': ['console'] + (['app_file', 'error_file'] if (not DEBUG and LOG_DIR) else []),
        'level': LOG_LEVEL,
    },
}

# CORS — Electron renderer talks cross-origin to the backend.
# Origins are env-driven so production gets an explicit allowlist; in DEBUG
# we permit all origins for local dev kiosks. Browsers reject the combination
# of CORS_ALLOW_ALL_ORIGINS=True with credentials, so we never ship that.
CORS_ALLOWED_ORIGINS = [
    o.strip() for o in os.environ.get('CORS_ALLOWED_ORIGINS', '').split(',') if o.strip()
]
CORS_ALLOW_CREDENTIALS = True
if DEBUG and not CORS_ALLOWED_ORIGINS:
    CORS_ALLOW_ALL_ORIGINS = True
    CORS_ALLOW_CREDENTIALS = False
