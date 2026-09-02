"""
Base settings for the Nirova Healthcare Operating System.

Two classes of Django app exist in this project and the distinction is
load-bearing -- it drives database routing, migrations and provisioning:

CONTROL_PLANE_APPS
    Live in the single control-plane database (`default`). They describe the
    SaaS business itself: who the customers are, what they bought, what they
    are entitled to, what they have used, and what changes they have asked
    for. Platform staff operate on these.

TENANT_APPS
    Live in a per-organization database. They describe one customer's
    operations -- facilities, staff, patients, stock, money. A row in a tenant
    app cannot be read while another tenant's connection is active, because it
    is in a physically different database.

Never add an app to both lists. See docs/adr/0001-database-per-tenant.md.
"""

from datetime import timedelta
from pathlib import Path

import environ

BASE_DIR = Path(__file__).resolve().parent.parent.parent

env = environ.Env()
environ.Env.read_env(BASE_DIR / ".env")

SECRET_KEY = env("DJANGO_SECRET_KEY", default="dev-insecure-change-me")
DEBUG = env.bool("DJANGO_DEBUG", default=False)
ALLOWED_HOSTS = env.list("DJANGO_ALLOWED_HOSTS", default=["localhost", "127.0.0.1"])

# ---------------------------------------------------------------------------
# Applications
# ---------------------------------------------------------------------------

DJANGO_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
]

THIRD_PARTY_APPS = [
    "rest_framework",
    "corsheaders",
    "django_filters",
    "drf_spectacular",
]

# Apps whose tables live only in the control-plane database.
CONTROL_PLANE_APPS = [
    "apps.tenancy",
    "apps.catalog",
    "apps.subscriptions",
    "apps.entitlements",
    "apps.metering",
    "apps.identity",
    "apps.provisioning",
    "apps.platform_api",
]

# Apps whose tables live only in a tenant database, one copy per organization.
TENANT_APPS = [
    "apps.organization",
    "apps.rbac",
    "apps.audit",
    "apps.patients",
    "apps.scheduling",
    "apps.encounters",
    "apps.prescriptions",
    "apps.billing",
    "apps.diagnostics",
    "apps.pharmacy",
    "apps.procurement",
    "apps.pos",
]

LOCAL_APPS = ["apps.common"] + CONTROL_PLANE_APPS + TENANT_APPS

INSTALLED_APPS = DJANGO_APPS + THIRD_PARTY_APPS + LOCAL_APPS

# django.contrib tables belong to the control plane: identity, permissions
# plumbing and the Django admin are platform-level concerns.
CONTROL_PLANE_DJANGO_LABELS = {"admin", "auth", "contenttypes", "sessions"}

MIDDLEWARE = [
    "corsheaders.middleware.CorsMiddleware",
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "apps.tenancy.middleware.TenantContextMiddleware",
    "apps.audit.middleware.AuditContextMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"

# ---------------------------------------------------------------------------
# Databases
# ---------------------------------------------------------------------------

DATABASES = {"default": env.db_url("CONTROL_DATABASE_URL")}
DATABASES["default"]["ATOMIC_REQUESTS"] = False
DATABASES["default"]["CONN_MAX_AGE"] = 60

DATABASE_ROUTERS = ["apps.tenancy.router.TenantDatabaseRouter"]

# Connection template used when provisioning a new tenant database.
TENANT_DATABASE = {
    "ENGINE": "django.db.backends.postgresql",
    "HOST": env("TENANT_DB_HOST", default="localhost"),
    "PORT": env("TENANT_DB_PORT", default="5432"),
    "USER": env("TENANT_DB_USER", default="nirova"),
    "PASSWORD": env("TENANT_DB_PASSWORD", default="nirova"),
    "NAME_PREFIX": env("TENANT_DB_NAME_PREFIX", default="nirova_tenant_"),
    "CONN_MAX_AGE": 60,
}

AUTH_USER_MODEL = "identity.User"

AUTH_PASSWORD_VALIDATORS = [
    {
        "NAME": "django.contrib.auth.password_validation."
        "UserAttributeSimilarityValidator"
    },
    {
        "NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
        "OPTIONS": {"min_length": 10},
    },
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

PASSWORD_HASHERS = [
    "django.contrib.auth.hashers.Argon2PasswordHasher",
    "django.contrib.auth.hashers.PBKDF2PasswordHasher",
]

# ---------------------------------------------------------------------------
# Localisation
# ---------------------------------------------------------------------------

LANGUAGE_CODE = "en-us"
TIME_ZONE = "Asia/Kathmandu"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
MEDIA_URL = "media/"
MEDIA_ROOT = BASE_DIR / "media"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# ---------------------------------------------------------------------------
# API
# ---------------------------------------------------------------------------

REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": (
        "rest_framework_simplejwt.authentication.JWTAuthentication",
    ),
    "DEFAULT_PERMISSION_CLASSES": ("rest_framework.permissions.IsAuthenticated",),
    "DEFAULT_PAGINATION_CLASS": "apps.common.pagination.DefaultPagination",
    "PAGE_SIZE": 25,
    "DEFAULT_FILTER_BACKENDS": (
        "django_filters.rest_framework.DjangoFilterBackend",
        "rest_framework.filters.SearchFilter",
        "rest_framework.filters.OrderingFilter",
    ),
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
    "EXCEPTION_HANDLER": "apps.common.exceptions.api_exception_handler",
}

SPECTACULAR_SETTINGS = {
    "TITLE": "Nirova Healthcare OS API",
    "DESCRIPTION": "Multi-tenant healthcare operating system for Nepal.",
    "VERSION": "0.1.0",
    "SERVE_INCLUDE_SCHEMA": False,
}

SIMPLE_JWT = {
    "ACCESS_TOKEN_LIFETIME": timedelta(minutes=30),
    "REFRESH_TOKEN_LIFETIME": timedelta(days=7),
    "ROTATE_REFRESH_TOKENS": True,
    "UPDATE_LAST_LOGIN": True,
    "AUTH_HEADER_TYPES": ("Bearer",),
}

CORS_ALLOWED_ORIGINS = env.list(
    "CORS_ALLOWED_ORIGINS", default=["http://localhost:5173", "http://127.0.0.1:5173"]
)
CORS_ALLOW_CREDENTIALS = True
CORS_ALLOW_HEADERS = (
    "accept",
    "authorization",
    "content-type",
    "origin",
    "user-agent",
    "x-organization",
    "x-facility",
)

CELERY_BROKER_URL = env("REDIS_URL", default="redis://localhost:6379/0")
CELERY_RESULT_BACKEND = CELERY_BROKER_URL

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "verbose": {"format": "{levelname} {asctime} {name} {message}", "style": "{"},
    },
    "handlers": {"console": {"class": "logging.StreamHandler", "formatter": "verbose"}},
    "root": {"handlers": ["console"], "level": "INFO"},
    "loggers": {
        "nirova": {"handlers": ["console"], "level": "DEBUG", "propagate": False},
    },
}
