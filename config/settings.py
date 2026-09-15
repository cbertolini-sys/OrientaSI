import os
from pathlib import Path

import dj_database_url
from celery.schedules import crontab
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
    "apps.publico",
    "rest_framework",
    "drf_spectacular",
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
# Rotas de autenticação (config/urls.py, T9): login exige sessão, e as views
# de login/recuperação de senha redirecionam para "/" ao concluir.
LOGIN_URL = "/contas/login/"
LOGIN_REDIRECT_URL = "/"
LOGOUT_REDIRECT_URL = "/"
AUTH_PASSWORD_VALIDATORS = [
    {
        "NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator",
        # Sem esta opção o validador compara a senha com os atributos padrão
        # do Django (`username`, `first_name`, `last_name`, `email`) — e o
        # `Usuario` deste projeto não tem `username` nem nome dividido em
        # dois campos: o nome vive em `nome_completo`, que ficava de fora.
        # "Ana Silva" podia escolher "anasilva1" sem o validador reclamar.
        "OPTIONS": {"user_attributes": ("email", "nome_completo")},
    },
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

CELERY_BROKER_URL = os.environ.get("REDIS_URL", "redis://redis:6379/0")
CELERY_RESULT_BACKEND = os.environ.get("REDIS_URL", "redis://redis:6379/0")
CELERY_TASK_ALWAYS_EAGER = False
CELERY_TASK_TIME_LIMIT = 300
CELERY_TASK_ACKS_LATE = True
# Agendamento ESTÁTICO (T10, spec §3.8 linha 158 — "O prazo avança por
# tarefa periódica, com agendamento estático"), sem `django-celery-beat`: a
# dependência só se paga quando alguém precisa mudar a periodicidade pela
# interface, e ninguém precisa — mudar a cada quantas horas a cascata de
# candidaturas vencidas é revisada é uma decisão de código, não de operação.
# `celery_beat` (docker-compose.yml) é o processo que lê este dicionário e
# publica a tarefa na fila no horário certo; o `celery_worker` é quem de
# fato executa.
CELERY_BEAT_SCHEDULE = {
    "avancar-candidaturas-vencidas": {
        "task": "apps.projetos.tasks.avancar_candidaturas_vencidas",
        "schedule": crontab(minute=0),  # de hora em hora
    }
}

EMAIL_BACKEND = os.environ.get("EMAIL_BACKEND", "django.core.mail.backends.console.EmailBackend")
EMAIL_HOST = os.environ.get("EMAIL_HOST", "")
EMAIL_PORT = int(os.environ.get("EMAIL_PORT", "587"))
EMAIL_USE_TLS = True
EMAIL_HOST_USER = os.environ.get("EMAIL_HOST_USER", "")
EMAIL_HOST_PASSWORD = os.environ.get("EMAIL_HOST_PASSWORD", "")
DEFAULT_FROM_EMAIL = os.environ.get("DEFAULT_FROM_EMAIL", "nao-responda@orientasi.local")

# Base para montar links absolutos em e-mails (convites, notificações). Lido tanto
# pelo serviço de convites quanto pelo corpo do e-mail (spec do convite, T7).
URL_BASE = os.environ.get("URL_BASE", "http://localhost:8000")
CONVITE_VALIDADE_DIAS = 7

# Mês em que o 2º período letivo começa: usado por apps/comum/semestre.py para
# derivar o semestre vigente a partir da data corrente (spec do Bloco B, §3.3).
# É constante, não modelo nem tela, de propósito — o calendário acadêmico não
# acompanha o civil (greve, reposição, pandemia deslocam a virada), e ajustar
# um número aqui precisa bastar, sem migração.
MES_INICIO_PERIODO_2 = 8
# Prazo, em dias, para um professor responder a uma opção de candidatura antes
# da cascata avançar sozinha para a próxima (spec do Bloco B, §3.2).
PRAZO_RESPOSTA_DIAS = 7

S3_ACCESS_KEY = os.environ.get("S3_ACCESS_KEY", "")
S3_SECRET_KEY = os.environ.get("S3_SECRET_KEY", "")


def _armazenamento_s3():
    """Configuração do backend S3 (MinIO em dev, S3 de verdade em produção).

    É função, e não um dicionário no nível do módulo, porque `S3_ACCESS_KEY` e
    `S3_SECRET_KEY` são reatribuídos por `obrigatorio()` dentro do bloco de
    produção logo abaixo: um dicionário montado antes do bloco congelaria os
    valores lidos do ambiente sem a imposição.
    """
    return {
        "BACKEND": "storages.backends.s3.S3Storage",
        "OPTIONS": {
            "bucket_name": os.environ.get("S3_BUCKET", "orientasi"),
            # `endpoint_url` é OPCIONAL, e é por isso que ele não decide mais
            # qual backend usar (ver `STORAGES` abaixo): o MinIO precisa de um
            # endpoint próprio, mas a AWS S3 real não usa nenhum — o boto3
            # resolve o endpoint pela região. `None` é exatamente o que o
            # django-storages espera para "use o endpoint padrão da AWS".
            "endpoint_url": os.environ.get("S3_ENDPOINT") or None,
            "access_key": S3_ACCESS_KEY,
            "secret_key": S3_SECRET_KEY,
            "default_acl": None,
            "querystring_auth": True,
            "file_overwrite": False,
        },
    }


# MinIO fala o protocolo S3: dev e produção usam o mesmo backend, mudando apenas
# o endpoint e as credenciais (spec §3.7).
_ARMAZENAMENTO_LOCAL = {"BACKEND": "django.core.files.storage.FileSystemStorage"}

if AMBIENTE == "producao":
    DEBUG = False
    SECRET_KEY = obrigatorio("SECRET_KEY")
    ALLOWED_HOSTS = obrigatorio("ALLOWED_HOSTS").split(",")
    # A spec §3.7 justifica o arquivo único de settings com "impor os valores
    # em vez de lê-los". Estas cinco variáveis entraram na imposição porque a
    # ausência de cada uma produz comportamento errado EM SILÊNCIO, nunca um
    # erro: sem `URL_BASE`, todo convite sai com link para
    # `http://localhost:8000` e ninguém consegue se cadastrar; sem
    # `EMAIL_BACKEND`, o padrão é o backend de console e os convites vão para
    # o log do Gunicorn; sem as credenciais do S3, todo upload falha na
    # autenticação com o bucket.
    URL_BASE = obrigatorio("URL_BASE")
    EMAIL_BACKEND = obrigatorio("EMAIL_BACKEND")
    EMAIL_HOST = obrigatorio("EMAIL_HOST")
    S3_ACCESS_KEY = obrigatorio("S3_ACCESS_KEY")
    S3_SECRET_KEY = obrigatorio("S3_SECRET_KEY")
    SECURE_SSL_REDIRECT = True
    # O Gunicorn roda atrás de um proxy (o cenário de uma universidade), que
    # termina o TLS e repassa a requisição em HTTP puro. Sem este cabeçalho,
    # `request.is_secure()` é sempre False: o `SECURE_SSL_REDIRECT` acima
    # redireciona para HTTPS uma requisição que o proxy já entregou por
    # HTTPS, em laço infinito, e o `{{ protocol }}` do
    # templates/registration/password_reset_email.html (derivado do mesmo
    # `is_secure()`) monta o link de recuperação com `http://`.
    #
    # ATENÇÃO, é uma configuração de confiança: o proxy DEVE ser configurado
    # para SOBRESCREVER o `X-Forwarded-Proto` de toda requisição que recebe.
    # Servir o Gunicorn diretamente na internet com esta linha ligada é
    # inseguro — qualquer cliente pode mandar o cabeçalho e fazer o Django
    # tratar uma conexão em texto claro como segura (cookies de sessão
    # marcados `Secure` viajariam por HTTP).
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_HSTS_SECONDS = 31_536_000
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True
    SECURE_HSTS_PRELOAD = True
    SECURE_CONTENT_TYPE_NOSNIFF = True
    # Produção SEMPRE grava mídia no S3, e quem decide isso é o `AMBIENTE`, não
    # a presença de `S3_ENDPOINT` (achado da revisão final). A variável de
    # endpoint existe por causa do MinIO; um deploy correto contra a AWS S3
    # não a define, e a seleção antiga caía em silêncio no
    # `FileSystemStorage` — fotos, PDFs e `.docx` gravados no disco efêmero
    # do container e perdidos no primeiro restart, sem erro nenhum.
    #
    # O manifesto exige collectstatic; por isso ele só existe em produção,
    # onde o Dockerfile o executa durante o build.
    STORAGES = {
        "default": _armazenamento_s3(),
        "staticfiles": {"BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"},
    }
else:
    DEBUG = True
    SECRET_KEY = os.environ.get("SECRET_KEY", "chave-de-desenvolvimento-nao-use-em-producao")
    ALLOWED_HOSTS = ["*"]
    # Só em dev o fallback local existe, e só para quem roda sem o MinIO da
    # stack (o `.env.example` define `S3_ENDPOINT`, então o ambiente padrão do
    # projeto usa o MinIO).
    STORAGES = {
        "default": (_armazenamento_s3() if os.environ.get("S3_ENDPOINT") else _ARMAZENAMENTO_LOCAL),
        "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
    }

REST_FRAMEWORK = {
    "DEFAULT_PERMISSION_CLASSES": ["rest_framework.permissions.AllowAny"],
    "DEFAULT_PAGINATION_CLASS": "rest_framework.pagination.PageNumberPagination",
    "PAGE_SIZE": 20,
    "DEFAULT_RENDERER_CLASSES": [
        "rest_framework.renderers.JSONRenderer",
        "rest_framework.renderers.BrowsableAPIRenderer",
    ],
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
}

SPECTACULAR_SETTINGS = {
    "TITLE": "OrientaSI API",
    "DESCRIPTION": "API pública de leitura do catálogo de TCCs e do calendário de apresentações.",
    "VERSION": "1.0.0",
}
