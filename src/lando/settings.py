"""
Django settings for lando project.

Generated by 'django-admin startproject' using Django 5.0b1.

For more information on this file, see
https://docs.djangoproject.com/en/dev/topics/settings/

For the full list of settings and their values, see
https://docs.djangoproject.com/en/dev/ref/settings/
"""

import os
from pathlib import Path

# Build paths inside the project like this: BASE_DIR / 'subdir'.
BASE_DIR = Path(__file__).resolve().parent

SECRET_KEY = os.getenv(
    "SECRET_KEY",
    "django-insecure-26k#ouat@%d6w5gmuhvo_vc=_@on^6=eh9*g!p-k9ynjvyc#(_",
)

DEBUG = os.getenv("DEBUG", "").lower() in ("true", "1")
ALLOWED_HOSTS = os.getenv("ALLOWED_HOSTS", "localhost,lando.local,lando.test").split(
    ","
)
CSRF_TRUSTED_ORIGINS = os.getenv(
    "CSRF_TRUSTED_ORIGINS", "https://localhost,https://lando.local"
).split(",")

# Application definition

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "mozilla_django_oidc",
    "lando.main",
    "lando.utils",
    "lando.api",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "lando.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.jinja2.Jinja2",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {"environment": "lando.jinja.environment"},
    },
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "lando.wsgi.application"


# Database
# https://docs.djangoproject.com/en/dev/ref/settings/#databases

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": os.getenv("DEFAULT_DB_NAME", "postgres"),
        "USER": os.getenv("DEFAULT_DB_USER", "postgres"),
        "PASSWORD": os.getenv("DEFAULT_DB_PASSWORD", "postgres"),
        "HOST": os.getenv("DEFAULT_DB_HOST", "db"),
        "PORT": os.getenv("DEFAULT_DB_PORT", "5432"),
    }
}


# Password validation
# https://docs.djangoproject.com/en/dev/ref/settings/#auth-password-validators

AUTH_PASSWORD_VALIDATORS = [
    {
        "NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.CommonPasswordValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.NumericPasswordValidator",
    },
]


# Internationalization
# https://docs.djangoproject.com/en/dev/topics/i18n/

LANGUAGE_CODE = "en-us"

TIME_ZONE = "UTC"

USE_I18N = True

USE_TZ = True


# Static files (CSS, JavaScript, Images)
# https://docs.djangoproject.com/en/dev/howto/static-files/

STATIC_URL = "static/"
STATIC_ROOT = "/staticfiles"

# Directories to include in static file collection.
STATICFILES_DIRS = [
    BASE_DIR / "static_src",
]

MEDIA_URL = "media/"
MEDIA_ROOT = "/mediafiles"

REPO_ROOT = f"{MEDIA_ROOT}/repos"

SITE_URL = os.getenv("SITE_URL", "https://lando.test")

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

OIDC_DOMAIN = os.getenv("OIDC_DOMAIN")
OIDC_OP_TOKEN_ENDPOINT = f"{OIDC_DOMAIN}/oauth/token"
OIDC_OP_USER_ENDPOINT = f"{OIDC_DOMAIN}/userinfo"
OIDC_OP_AUTHORIZATION_ENDPOINT = f"{OIDC_DOMAIN}/authorize"
OIDC_REDIRECT_REQUIRE_HTTPS = True

OIDC_RP_CLIENT_ID = os.getenv("OIDC_RP_CLIENT_ID")
OIDC_RP_CLIENT_SECRET = os.getenv("OIDC_RP_CLIENT_SECRET")

AUTHENTICATION_BACKENDS = [
    "django.contrib.auth.backends.ModelBackend",
    "mozilla_django_oidc.auth.OIDCAuthenticationBackend",
]

LINT_PATHS = tuple(f"{BASE_DIR}/{path}" for path in ("main", "utils", "api"))

GITHUB_ACCESS_TOKEN = os.getenv("LANDO_GITHUB_ACCESS_TOKEN")
PHABRICATOR_URL = os.getenv("PHABRICATOR_URL", "http://phabricator.test")
PHABRICATOR_ADMIN_API_KEY = os.getenv("PHABRICATOR_ADMIN_API_KEY", "")
PHABRICATOR_UNPRIVILEGED_API_KEY = os.getenv("PHABRICATOR_UNPRIVILEGED_API_KEY", "")

ENVIRONMENT = os.getenv("ENVIRONMENT", "test")

CELERY_BROKER_URL = os.getenv("CELERY_BROKER_URL", "redis://lando.redis:6379")
CELERY_RESULT_BACKEND = CELERY_BROKER_URL
CELERY_ACCEPT_CONTENT = ["json"]
CELERY_TASK_SERIALIZER = "json"

DEFAULT_FROM_EMAIL = "Lando <lando@lando.test>"
