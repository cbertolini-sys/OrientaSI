import os
from pathlib import Path

import dj_database_url
from django.core.exceptions import ImproperlyConfigured

BASE_DIR = Path(__file__).resolve().parent.parent
AMBIENTE = os.environ.get("AMBIENTE", "dev")


def obrigatorio(nome):
    """Lê uma variável de ambiente que não tem padrão seguro em produção."""
    valor = os.environ.get(nome)
    if not valor:
        raise ImproperlyConfigured(f"A variável de ambiente {nome} é obrigatória em produção.")
    return valor


INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "apps.comum",
    "apps.contas",
    "apps.projetos",
    "apps.bancas",
    "apps.documentos",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"

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

DATABASES = {
    "default": dj_database_url.config(
        default=os.environ.get("DATABASE_URL", "postgres://orientasi:orientasi@db:5432/orientasi"),
        conn_max_age=600,
    )
}

AUTH_USER_MODEL = "contas.Usuario"
AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "pt-br"
TIME_ZONE = "America/Sao_Paulo"
USE_I18N = True
USE_TZ = True

STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STATICFILES_DIRS = [BASE_DIR / "static"]
MEDIA_ROOT = BASE_DIR / "media"
MEDIA_URL = "/media/"

# O test runner do Django força DEBUG=False durante os testes. Sem isto, o
# WhiteNoise trataria autorefresh como desligado mesmo em dev e escanearia
# staticfiles/ (que só existe após collectstatic, rodado apenas em produção),
# transformando o aviso de diretório ausente em erro por causa do
# filterwarnings do pytest.
WHITENOISE_AUTOREFRESH = AMBIENTE != "producao"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# Limite de upload aplicado pelos validators de apps.comum (spec §3, regra 7).
TAMANHO_MAXIMO_UPLOAD_MB = 15

if AMBIENTE == "producao":
    DEBUG = False
    SECRET_KEY = obrigatorio("SECRET_KEY")
    ALLOWED_HOSTS = obrigatorio("ALLOWED_HOSTS").split(",")
    SECURE_SSL_REDIRECT = True
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_HSTS_SECONDS = 31_536_000
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True
    SECURE_HSTS_PRELOAD = True
    SECURE_CONTENT_TYPE_NOSNIFF = True
    # O manifesto exige collectstatic; por isso ele só existe em produção,
    # onde o Dockerfile o executa durante o build.
    STORAGES = {
        "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
        "staticfiles": {"BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"},
    }
else:
    DEBUG = True
    SECRET_KEY = os.environ.get("SECRET_KEY", "chave-de-desenvolvimento-nao-use-em-producao")
    ALLOWED_HOSTS = ["*"]
    STORAGES = {
        "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
        "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
    }
