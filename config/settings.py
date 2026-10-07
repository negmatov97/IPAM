"""
IPAM sozlamalari.

Barcha muhitga bog'liq qiymatlar (maxfiy kalit, DEBUG, baza, domen) kodda emas,
muhit o'zgaruvchilarida yoki loyiha ildizidagi `.env` faylida saqlanadi.
Namuna: `.env.example`. Ishga tushirishdan oldin: `python manage.py check --deploy`.
"""

import os
from pathlib import Path

from django.core.exceptions import ImproperlyConfigured
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent

# .env fayli bo'lsa, undagi qiymatlar yuklanadi (haqiqiy muhit o'zgaruvchilari ustun turadi)
load_dotenv(BASE_DIR / ".env")


def env(name, default=None):
    return os.environ.get(name, default)


def env_bool(name, default=False):
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in ("1", "true", "yes", "on", "ha")


def env_list(name, default=""):
    return [item.strip() for item in os.environ.get(name, default).split(",") if item.strip()]


# ---------- Asosiy ----------

DEBUG = env_bool("DJANGO_DEBUG", False)

SECRET_KEY = env("DJANGO_SECRET_KEY")
if not SECRET_KEY:
    if DEBUG:
        # Faqat ishlab chiqish uchun: haqiqiy serverda kalit albatta .env orqali beriladi
        SECRET_KEY = "dev-only-insecure-key-do-not-use-in-production"
    else:
        raise ImproperlyConfigured(
            "DJANGO_SECRET_KEY o'rnatilmagan. .env.example faylidan nusxa olib, .env yarating."
        )

ALLOWED_HOSTS = env_list("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1")

# HTTPS orqali ishlaganda formalar uchun: https://ipam.example.uz
CSRF_TRUSTED_ORIGINS = env_list("DJANGO_CSRF_TRUSTED_ORIGINS")


# ---------- Ilovalar ----------

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'ipam',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'whitenoise.middleware.WhiteNoiseMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'ipam.audit.AuditMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'config.urls'

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

WSGI_APPLICATION = 'config.wsgi.application'


# ---------- Ma'lumotlar bazasi ----------
# DB_ENGINE=sqlite (standart) yoki DB_ENGINE=postgres

DB_ENGINE = env("DB_ENGINE", "sqlite").lower()

if DB_ENGINE in ("postgres", "postgresql"):
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.postgresql",
            "NAME": env("DB_NAME", "ipam"),
            "USER": env("DB_USER", "ipam"),
            "PASSWORD": env("DB_PASSWORD", ""),
            "HOST": env("DB_HOST", "localhost"),
            "PORT": env("DB_PORT", "5432"),
            "CONN_MAX_AGE": int(env("DB_CONN_MAX_AGE", "60")),
            "CONN_HEALTH_CHECKS": True,
        }
    }
elif DB_ENGINE == "sqlite":
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            # IPAM_DB — avvalgi nomi, moslik uchun qoldirildi
            "NAME": env("DB_NAME") or env("IPAM_DB") or BASE_DIR / "db.sqlite3",
        }
    }
else:
    raise ImproperlyConfigured(f"Noma'lum DB_ENGINE: {DB_ENGINE!r} (sqlite yoki postgres bo'lishi kerak)")


# ---------- Parollar ----------

AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator', 'OPTIONS': {'min_length': 10}},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]


# ---------- Til va vaqt ----------

LANGUAGE_CODE = 'uz'
TIME_ZONE = 'Asia/Tashkent'
USE_I18N = True
USE_TZ = True


# ---------- Statik fayllar ----------
# Serverda: python manage.py collectstatic — fayllar STATIC_ROOT ga yig'iladi,
# WhiteNoise ularni siqilgan holda va keshlash bilan beradi.

STATIC_URL = 'static/'
STATIC_ROOT = Path(env("DJANGO_STATIC_ROOT", BASE_DIR / "staticfiles"))
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {
        "BACKEND": (
            "django.contrib.staticfiles.storage.StaticFilesStorage" if DEBUG
            else "whitenoise.storage.CompressedManifestStaticFilesStorage"
        ),
    },
}

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

LOGIN_URL = 'login'
LOGIN_REDIRECT_URL = 'ipam:dashboard'
LOGOUT_REDIRECT_URL = 'login'


# ---------- Xavfsizlik (DEBUG=False bo'lganda) ----------

if not DEBUG:
    # Nginx HTTPS'ni qabul qilib, ilovaga HTTP orqali uzatadi — shu sarlavha bo'yicha HTTPS deb tanlanadi
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    SECURE_SSL_REDIRECT = env_bool("DJANGO_SECURE_SSL_REDIRECT", True)
    SESSION_COOKIE_SECURE = env_bool("DJANGO_SECURE_COOKIES", True)
    CSRF_COOKIE_SECURE = env_bool("DJANGO_SECURE_COOKIES", True)
    SECURE_HSTS_SECONDS = int(env("DJANGO_HSTS_SECONDS", "31536000"))
    SECURE_HSTS_INCLUDE_SUBDOMAINS = env_bool("DJANGO_HSTS_INCLUDE_SUBDOMAINS", False)
    SECURE_HSTS_PRELOAD = False  # brauzerlar "preload" ro'yxatiga yozilish — ixtiyoriy, alohida qaror
    SILENCED_SYSTEM_CHECKS = ["security.W021"]
    SECURE_CONTENT_TYPE_NOSNIFF = True
    SECURE_REFERRER_POLICY = "same-origin"
    X_FRAME_OPTIONS = "DENY"

SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_AGE = int(env("DJANGO_SESSION_AGE", str(8 * 60 * 60)))  # 8 soat — bir ish kuni


# ---------- Zaxira nusxalar ----------

BACKUP_DIR = Path(env("IPAM_BACKUP_DIR", BASE_DIR / "backups"))
BACKUP_KEEP_DAYS = int(env("IPAM_BACKUP_KEEP_DAYS", "30"))


# ---------- Loglar ----------

LOG_DIR = Path(env("IPAM_LOG_DIR", BASE_DIR / "logs"))
LOG_DIR.mkdir(parents=True, exist_ok=True)

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "default": {"format": "{asctime} {levelname} {name}: {message}", "style": "{"},
    },
    "handlers": {
        "console": {"class": "logging.StreamHandler", "formatter": "default"},
        "file": {
            "class": "logging.handlers.RotatingFileHandler",
            "filename": LOG_DIR / "ipam.log",
            "maxBytes": 5 * 1024 * 1024,
            "backupCount": 10,
            "encoding": "utf-8",
            "formatter": "default",
        },
    },
    "root": {"handlers": ["console", "file"], "level": "INFO"},
    "loggers": {
        "django": {"handlers": ["console", "file"], "level": "INFO", "propagate": False},
        "django.request": {"handlers": ["console", "file"], "level": "ERROR", "propagate": False},
    },
}
