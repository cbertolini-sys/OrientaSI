# Fase 1 — Fundação e Contas: Plano de Implementação

> **Para executores agênticos:** SUB-SKILL OBRIGATÓRIA: use
> `superpowers:subagent-driven-development` (recomendado) ou
> `superpowers:executing-plans` para implementar tarefa a tarefa. Os passos usam
> caixas de seleção (`- [ ]`) para acompanhamento.

**Objetivo:** entregar a fundação técnica do OrientaSI e a app de contas, de modo que
uma pessoa seja convidada por e-mail, se cadastre pelo link e entre no sistema.

**Arquitetura:** Django 5 em Docker, com PostgreSQL, Redis, Celery e MinIO. Toda regra
de negócio vive em `services.py` por app; models e views permanecem sem lógica. A
interface é Django Templates com Tailwind v4 + DaisyUI, HTMX e Alpine.js, verificada
por uma suíte Playwright + axe-core que roda dentro do container.

**Stack:** Python 3.12, Django 5.1, PostgreSQL 16, Redis 7, Celery 5, MinIO,
Tailwind v4, DaisyUI 5, HTMX 2, Alpine.js 3, pytest, Playwright, axe-core.

**Spec:** `docs/superpowers/specs/2026-09-08-fundacao-e-contas-design.md`

## Restrições globais

Valem para toda tarefa, sem repetição em cada uma:

- **Idioma:** todo identificador de código em português (apps, modelos, campos,
  funções). Interface, mensagens de erro, comentários e commits também em português.
- **Camada de serviço:** nenhuma regra de negócio em `views.py` ou `models.py`. Models
  contêm apenas campos, `Meta` e `__str__`. Serviços mutáveis usam
  `@transaction.atomic`.
- **Sem CDN:** todo CSS, JS e fonte é servido do próprio projeto. Bibliotecas de
  terceiros são baixadas para `static/` com versão fixada.
- **Acessibilidade:** WCAG 2.1 AA. HTML semântico, `lang="pt-br"`, alvos de toque de
  no mínimo 44×44 px, layout sem rolagem horizontal a partir de 360 px.
- **Uploads:** extensões `.pdf` e `.docx` (e imagens, para fotos), com limite de 15MB,
  validados por *validators* no model.
- **Comandos:** tudo roda no container — `docker compose exec web <comando>`.
- **Segredos:** apenas em `.env`, nunca versionado. O repositório versiona
  `.env.example`.
- **Commits:** frequentes, um por tarefa concluída, em português.

## Desvio deliberado do spec §8.4

O spec ordena a execução como infraestrutura primeiro e "somente então, os modelos de
contas". Essa ordem não é executável no Django: `AUTH_USER_MODEL` precisa apontar para
o modelo de usuário definitivo **antes da primeira migração**. Trocá-lo depois exige
apagar o banco e recriar todas as migrações — é o erro mais caro e mais comum em
projetos Django.

**Resolução:** a Tarefa 1 cria o `Usuario` junto com o esqueleto, antes de qualquer
`migrate`. A *intenção* do spec §8.4 — validar cada degrau de infraestrutura antes de
construir sobre ele — é preservada: Celery (T2), MinIO (T3) e a suíte de
acessibilidade (T5) continuam sendo verificados isoladamente antes de qualquer regra
de negócio de contas (T7 em diante).

## Mapa de arquivos

| arquivo | responsabilidade | tarefa |
|---|---|---|
| `Dockerfile` | estágios `base`, `dev`, `prod` (+ `css` na T4) | T1, T4 |
| `docker-compose.yml` | orquestração dos serviços | T1–T4 |
| `requirements.txt` / `requirements-dev.txt` | dependências | T1 |
| `pyproject.toml` | configuração de ruff, black e pytest | T1 |
| `config/settings.py` | configuração única dirigida por `AMBIENTE` | T1–T3 |
| `config/celery.py` | aplicação Celery | T2 |
| `config/saude.py` | endpoint de healthcheck | T1 |
| `config/urls.py` | rotas raiz | T1 |
| `apps/comum/validators.py` | validators de upload (extensão e tamanho) | T1 |
| `apps/contas/models.py` | `Usuario`, perfis, `Area`, `Convite` | T1, T6, T7 |
| `apps/contas/validators.py` | CPF, SIAPE, matrícula | T1 |
| `apps/contas/services.py` | convites e coordenação | T7, T8, T11 |
| `apps/contas/permissions.py` | verificações de permissão | T7 |
| `apps/contas/tasks.py` | envio assíncrono de e-mails | T7 |
| `templates/base.html` | layout, região `aria-live`, marca | T4 |
| `static/css/entrada.css` | tema Tailwind + DaisyUI | T4 |
| `conftest.py` | fixtures e a lista única de rotas | T1, T5 |
| `tests/` | suíte transversal | T1, T5 |

---

## Tarefa 1: Fundação — Docker, Django e o modelo `Usuario`

**Arquivos:**
- Criar: `Dockerfile`, `docker-compose.yml`, `.env.example`, `.dockerignore`
- Criar: `requirements.txt`, `requirements-dev.txt`, `pyproject.toml`, `manage.py`
- Criar: `config/__init__.py`, `config/settings.py`, `config/urls.py`, `config/wsgi.py`, `config/asgi.py`, `config/saude.py`
- Criar: `apps/__init__.py` e, para cada uma de `comum`, `contas`, `projetos`, `bancas`, `documentos`: `__init__.py`, `apps.py`, `migrations/__init__.py`
- Criar: `apps/comum/validators.py`, `apps/contas/validators.py`, `apps/contas/models.py`, `apps/contas/admin.py`
- Criar: `conftest.py`
- Teste: `tests/__init__.py`, `tests/test_saude.py`, `tests/test_producao.py`, `tests/test_arquitetura.py`, `apps/contas/tests/test_usuario.py`

**Interfaces:**
- Consome: nada (primeira tarefa).
- Produz: `apps.contas.models.Usuario` (`AUTH_USER_MODEL = "contas.Usuario"`) com
  gerenciador `objects.create_user(email, password, **extra)` e
  `objects.create_superuser(email, password, **extra)`; constantes de papel
  `Usuario.ALUNO`, `Usuario.PROFESSOR`, `Usuario.SUGRAD`.
  `apps.comum.validators.valida_extensao_documento`, `valida_extensao_imagem`,
  `valida_tamanho_arquivo`. `apps.contas.validators.valida_cpf`.

- [ ] **Passo 1: Criar os arquivos de dependências e configuração de ferramentas**

`requirements.txt`:

```
django>=5.1,<6.0
psycopg[binary]>=3.2
dj-database-url>=2.2
python-dotenv>=1.0
Pillow>=10.4
celery[redis]>=5.4
redis>=5.0
django-storages[s3]>=1.14
weasyprint>=62
whitenoise>=6.7
gunicorn>=23
```

`requirements-dev.txt`:

```
-r requirements.txt
pytest>=8.0
pytest-django>=4.9
pytest-playwright>=0.5
axe-playwright-python>=0.1.3
model-bakery>=1.19
ruff>=0.6
black>=24.8
django-debug-toolbar>=4.4
```

`pyproject.toml`:

```toml
[tool.ruff]
line-length = 100
target-version = "py312"
exclude = ["*/migrations/*"]

[tool.ruff.lint]
select = ["E", "F", "I", "UP", "B", "DJ"]

[tool.black]
line-length = 100
target-version = ["py312"]
extend-exclude = "migrations"

[tool.pytest.ini_options]
DJANGO_SETTINGS_MODULE = "config.settings"
python_files = ["test_*.py"]
addopts = "-q --reuse-db"
# Avisos viram erro: uma depreciação do Django não passa despercebida. As exceções
# são de bibliotecas de terceiros, cujo cronograma não controlamos.
filterwarnings = [
    "error",
    "ignore::DeprecationWarning:botocore.*",
    "ignore::DeprecationWarning:kombu.*",
]
```

- [ ] **Passo 2: Criar o esqueleto Django**

`manage.py`:

```python
#!/usr/bin/env python
import os
import sys

if __name__ == "__main__":
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
    from django.core.management import execute_from_command_line

    execute_from_command_line(sys.argv)
```

`config/settings.py`:

```python
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
```

`config/saude.py`:

```python
from django.db import connection
from django.http import JsonResponse


def saude(request):
    """Healthcheck consumido pelo docker compose e pelo monitoramento."""
    with connection.cursor() as cursor:
        cursor.execute("SELECT 1")
    return JsonResponse({"estado": "ok"})
```

`config/urls.py`:

```python
from django.contrib import admin
from django.urls import path

from config.saude import saude

urlpatterns = [
    path("admin/", admin.site.urls),
    path("saude/", saude, name="saude"),
]
```

`config/wsgi.py` e `config/asgi.py`: os arquivos padrão gerados pelo Django,
apontando para `config.settings`.

`config/__init__.py`: vazio por enquanto (a Tarefa 2 acrescenta o Celery).

Para cada app em `comum`, `contas`, `projetos`, `bancas`, `documentos`, criar
`apps/<nome>/__init__.py` (vazio), `apps/<nome>/migrations/__init__.py` (vazio) e
`apps/<nome>/apps.py`:

```python
from django.apps import AppConfig


class ContasConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.contas"
    verbose_name = "Contas"
```

- [ ] **Passo 3: Escrever os validators**

`apps/comum/validators.py`:

```python
from pathlib import Path

from django.conf import settings
from django.core.exceptions import ValidationError

EXTENSOES_DOCUMENTO = {".pdf", ".docx"}
EXTENSOES_IMAGEM = {".jpg", ".jpeg", ".png", ".webp"}


def _valida_extensao(arquivo, permitidas):
    extensao = Path(arquivo.name).suffix.lower()
    if extensao not in permitidas:
        aceitas = ", ".join(sorted(permitidas))
        raise ValidationError(f"Extensão {extensao or 'ausente'} não aceita. Envie: {aceitas}.")


def valida_extensao_documento(arquivo):
    _valida_extensao(arquivo, EXTENSOES_DOCUMENTO)


def valida_extensao_imagem(arquivo):
    _valida_extensao(arquivo, EXTENSOES_IMAGEM)


def valida_tamanho_arquivo(arquivo):
    limite = settings.TAMANHO_MAXIMO_UPLOAD_MB * 1024 * 1024
    if arquivo.size > limite:
        raise ValidationError(
            f"Arquivo de {arquivo.size / 1024 / 1024:.1f}MB excede o limite de "
            f"{settings.TAMANHO_MAXIMO_UPLOAD_MB}MB."
        )
```

`apps/contas/validators.py`:

```python
from django.core.exceptions import ValidationError

SEQUENCIAS_INVALIDAS = {str(d) * 11 for d in range(10)}


def _digito(base, peso_inicial):
    soma = sum(int(d) * p for d, p in zip(base, range(peso_inicial, 1, -1), strict=True))
    resto = (soma * 10) % 11
    return 0 if resto == 10 else resto


def valida_cpf(valor):
    """Aceita apenas os 11 dígitos, já sem pontuação, com dígitos verificadores válidos."""
    if not valor.isdigit() or len(valor) != 11:
        raise ValidationError("O CPF deve conter exatamente 11 dígitos, sem pontos ou traços.")
    if valor in SEQUENCIAS_INVALIDAS:
        raise ValidationError("CPF inválido.")
    if _digito(valor[:9], 10) != int(valor[9]) or _digito(valor[:10], 11) != int(valor[10]):
        raise ValidationError("CPF inválido.")
```

- [ ] **Passo 4: Escrever o teste do `Usuario` (falhando)**

`apps/contas/tests/__init__.py` (vazio) e `apps/contas/tests/test_usuario.py`:

```python
import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction

from apps.contas.models import Usuario
from apps.contas.validators import valida_cpf


def test_valida_cpf_aceita_valido():
    valida_cpf("52998224725")


@pytest.mark.parametrize("invalido", ["11111111111", "52998224726", "529982247", "abcdefghijk"])
def test_valida_cpf_recusa_invalido(invalido):
    with pytest.raises(ValidationError):
        valida_cpf(invalido)


@pytest.mark.django_db
def test_cria_usuario_com_email_como_identificador():
    usuario = Usuario.objects.create_user(
        email="ana@ufsm.br", password="senha-forte-123", nome_completo="Ana", cpf="52998224725"
    )
    assert usuario.get_username() == "ana@ufsm.br"
    assert usuario.check_password("senha-forte-123")
    assert usuario.papel == Usuario.PROFESSOR


@pytest.mark.django_db
def test_aluno_sem_cpf_e_recusado_pelo_banco():
    with pytest.raises(IntegrityError), transaction.atomic():
        Usuario.objects.create_user(
            email="joao@ufsm.br", password="x", nome_completo="João", papel=Usuario.ALUNO, cpf=None
        )


@pytest.mark.django_db
def test_conta_sugrad_e_unica():
    Usuario.objects.create_user(
        email="sugrad@ufsm.br", password="x", nome_completo="SUGRAD", papel=Usuario.SUGRAD, cpf=None
    )
    with pytest.raises(IntegrityError), transaction.atomic():
        Usuario.objects.create_user(
            email="sugrad2@ufsm.br", password="x", nome_completo="SUGRAD 2",
            papel=Usuario.SUGRAD, cpf=None,
        )


@pytest.mark.django_db
def test_aluno_nao_pode_ser_coordenador():
    with pytest.raises(IntegrityError), transaction.atomic():
        Usuario.objects.create_user(
            email="ana@ufsm.br", password="x", nome_completo="Ana", papel=Usuario.ALUNO,
            cpf="52998224725", is_coordenador=True,
        )
```

- [ ] **Passo 5: Rodar o teste e confirmar que falha**

Executar: `docker compose exec web pytest apps/contas/tests/test_usuario.py -v`
Esperado: FALHA com `ModuleNotFoundError` ou `ImportError` em `apps.contas.models`.

- [ ] **Passo 6: Escrever o modelo `Usuario`**

`apps/contas/models.py`:

```python
from django.contrib.auth.models import AbstractBaseUser, BaseUserManager, PermissionsMixin
from django.db import models
from django.db.models import Q

from apps.comum.validators import valida_extensao_imagem, valida_tamanho_arquivo
from apps.contas.validators import valida_cpf


class GerenciadorUsuario(BaseUserManager):
    use_in_migrations = True

    def _criar(self, email, password, **extra):
        if not email:
            raise ValueError("O e-mail é obrigatório.")
        usuario = self.model(email=self.normalize_email(email), **extra)
        usuario.set_password(password)
        usuario.save(using=self._db)
        return usuario

    def create_user(self, email, password=None, **extra):
        extra.setdefault("papel", Usuario.PROFESSOR)
        extra.setdefault("is_staff", False)
        extra.setdefault("is_superuser", False)
        return self._criar(email, password, **extra)

    def create_superuser(self, email, password, **extra):
        extra.setdefault("papel", Usuario.PROFESSOR)
        extra["is_staff"] = True
        extra["is_superuser"] = True
        return self._criar(email, password, **extra)


class Usuario(AbstractBaseUser, PermissionsMixin):
    ALUNO = "ALUNO"
    PROFESSOR = "PROFESSOR"
    SUGRAD = "SUGRAD"
    PAPEIS = [(ALUNO, "Aluno"), (PROFESSOR, "Professor"), (SUGRAD, "SUGRAD")]

    email = models.EmailField("e-mail", unique=True)
    nome_completo = models.CharField("nome completo", max_length=200)
    cpf = models.CharField("CPF", max_length=11, unique=True, null=True, blank=True,
                           validators=[valida_cpf])
    telefone = models.CharField("telefone", max_length=20, blank=True)
    foto = models.ImageField("foto", upload_to="fotos/", blank=True,
                             validators=[valida_extensao_imagem, valida_tamanho_arquivo])
    papel = models.CharField("papel", max_length=10, choices=PAPEIS, default=PROFESSOR)
    is_coordenador = models.BooleanField("é coordenador", default=False)
    is_active = models.BooleanField("ativo", default=True)
    is_staff = models.BooleanField("acessa o admin", default=False)
    criado_em = models.DateTimeField("criado em", auto_now_add=True)

    objects = GerenciadorUsuario()

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = ["nome_completo", "cpf"]

    class Meta:
        verbose_name = "usuário"
        verbose_name_plural = "usuários"
        ordering = ["nome_completo"]
        constraints = [
            # A conta da SUGRAD é um setor, não uma pessoa, e não tem CPF.
            models.CheckConstraint(
                condition=Q(papel="SUGRAD") | Q(cpf__isnull=False),
                name="cpf_obrigatorio_para_pessoas",
            ),
            # Índice parcial: o banco recusa a segunda conta SUGRAD (spec §5.1).
            models.UniqueConstraint(
                fields=["papel"], condition=Q(papel="SUGRAD"), name="conta_sugrad_unica"
            ),
            models.CheckConstraint(
                condition=Q(is_coordenador=False) | Q(papel="PROFESSOR"),
                name="coordenador_e_professor",
            ),
        ]

    def __str__(self):
        return f"{self.nome_completo} <{self.email}>"
```

`apps/contas/admin.py`:

```python
from django.contrib import admin

from apps.contas.models import Usuario


@admin.register(Usuario)
class UsuarioAdmin(admin.ModelAdmin):
    list_display = ["nome_completo", "email", "papel", "is_coordenador", "is_active"]
    list_filter = ["papel", "is_coordenador", "is_active"]
    search_fields = ["nome_completo", "email", "cpf"]
```

- [ ] **Passo 7: Escrever os testes transversais**

`tests/__init__.py` (vazio), `tests/test_saude.py`:

```python
import pytest


@pytest.mark.django_db
def test_saude_responde_ok(client):
    resposta = client.get("/saude/")
    assert resposta.status_code == 200
    assert resposta.json() == {"estado": "ok"}
```

`tests/test_producao.py`:

```python
import importlib
import os

import pytest
from django.core.exceptions import ImproperlyConfigured


def carrega_settings(**ambiente):
    anterior = dict(os.environ)
    os.environ.update(ambiente)
    try:
        import config.settings

        return importlib.reload(config.settings)
    finally:
        os.environ.clear()
        os.environ.update(anterior)
        import config.settings

        importlib.reload(config.settings)


def test_producao_desliga_debug_e_exige_segredos():
    settings = carrega_settings(
        AMBIENTE="producao", SECRET_KEY="segredo-real", ALLOWED_HOSTS="orientasi.ufsm.br"
    )
    assert settings.DEBUG is False
    assert settings.SECURE_SSL_REDIRECT is True
    assert settings.SESSION_COOKIE_SECURE is True
    assert settings.CSRF_COOKIE_SECURE is True


def test_producao_sem_secret_key_falha_alto():
    with pytest.raises(ImproperlyConfigured):
        carrega_settings(AMBIENTE="producao", SECRET_KEY="", ALLOWED_HOSTS="x")
```

`tests/test_arquitetura.py` — o teste que defende a convenção de `services.py`:

```python
import ast
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parent.parent
APPS = sorted(p for p in (RAIZ / "apps").iterdir() if (p / "apps.py").exists())


def importa(caminho, alvo):
    arvore = ast.parse(caminho.read_text(encoding="utf-8"))
    for no in ast.walk(arvore):
        if isinstance(no, ast.ImportFrom) and no.module and alvo in no.module:
            return True
    return False


@pytest.mark.parametrize("app", APPS, ids=lambda p: p.name)
def test_models_nao_importa_services(app):
    arquivo = app / "models.py"
    if not arquivo.exists():
        pytest.skip(f"{app.name} ainda não tem models.py")
    assert not importa(arquivo, "services"), (
        f"{app.name}/models.py importa services: a regra de negócio deve ficar "
        "na camada de serviço, e o model não pode depender dela."
    )
```

- [ ] **Passo 8: Escrever o `conftest.py`**

```python
import pytest


@pytest.fixture(autouse=True)
def midia_temporaria(settings, tmp_path):
    """Nenhum teste escreve em media/ nem no bucket: cada teste recebe um diretório próprio."""
    settings.MEDIA_ROOT = tmp_path / "media"
    settings.STORAGES = {
        **settings.STORAGES,
        "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    }
```

- [ ] **Passo 9: Escrever o Docker**

`.dockerignore`:

```
.git
.venv
__pycache__
*.pyc
node_modules
media
staticfiles
.pytest_cache
.ruff_cache
docs
```

`Dockerfile`:

```dockerfile
FROM python:3.12-slim AS base
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
# WeasyPrint renderiza via Pango e Cairo: sem estas bibliotecas ele falha já na
# importação, e a falha só apareceria no Bloco E (spec §8.2).
RUN apt-get update && apt-get install -y --no-install-recommends \
      libpango-1.0-0 libpangoft2-1.0-0 libharfbuzz0b libcairo2 \
      libgdk-pixbuf-2.0-0 libjpeg62-turbo zlib1g curl \
 && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .

FROM base AS dev
COPY requirements-dev.txt .
RUN pip install --no-cache-dir -r requirements-dev.txt \
 && playwright install --with-deps chromium
CMD ["python", "manage.py", "runserver", "0.0.0.0:8000"]

FROM base AS prod
RUN python manage.py collectstatic --noinput
CMD ["gunicorn", "config.wsgi:application", "--bind", "0.0.0.0:8000", "--workers", "3"]
```

`docker-compose.yml`:

```yaml
services:
  db:
    image: postgres:16-alpine
    environment:
      POSTGRES_DB: orientasi
      POSTGRES_USER: orientasi
      POSTGRES_PASSWORD: orientasi
    volumes:
      - dados_postgres:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U orientasi"]
      interval: 5s
      timeout: 3s
      retries: 10

  web:
    build:
      context: .
      target: dev
    command: python manage.py runserver 0.0.0.0:8000
    volumes:
      - .:/app
    ports:
      - "8000:8000"
    env_file:
      - .env
    depends_on:
      db:
        condition: service_healthy

volumes:
  dados_postgres:
```

`.env.example`:

```
AMBIENTE=dev
SECRET_KEY=chave-de-desenvolvimento-nao-use-em-producao
DATABASE_URL=postgres://orientasi:orientasi@db:5432/orientasi
ALLOWED_HOSTS=localhost,127.0.0.1
```

- [ ] **Passo 10: Subir o ambiente e migrar**

```bash
cp .env.example .env
docker compose up -d --build
docker compose exec web python manage.py makemigrations contas
docker compose exec web python manage.py migrate
```

Esperado: `docker compose ps` mostra `db` saudável e `web` no ar.

- [ ] **Passo 11: Rodar a suíte e confirmar que passa**

Executar: `docker compose exec web pytest -v`
Esperado: todos os testes de `test_usuario.py`, `test_saude.py`, `test_producao.py` e
`test_arquitetura.py` PASSAM.

Executar também: `docker compose exec web ruff check .` e
`docker compose exec web black --check .` — ambos sem erro.

- [ ] **Passo 12: Commit**

```bash
git add -A
git commit -m "Funda a estrutura do projeto com Docker, Django e o modelo Usuario"
```

---

## Tarefa 2: Celery e Redis

**Arquivos:**
- Criar: `config/celery.py`, `apps/comum/tasks.py`
- Modificar: `config/__init__.py`, `config/settings.py`, `docker-compose.yml`, `.env.example`
- Teste: `tests/test_celery.py`

**Interfaces:**
- Consome: `config.settings` da Tarefa 1.
- Produz: `config.celery.app` (instância Celery), exportada como `config.celery_app`;
  `apps.comum.tasks.somar(a, b)` como tarefa de fumaça.

- [ ] **Passo 1: Escrever o teste (falhando)**

`tests/test_celery.py`:

```python
from apps.comum.tasks import somar


def test_tarefa_executa_em_modo_sincrono(settings):
    settings.CELERY_TASK_ALWAYS_EAGER = True
    assert somar.delay(2, 3).get() == 5


def test_app_celery_descobre_as_tarefas_das_apps():
    from config.celery import app

    assert "apps.comum.tasks.somar" in app.tasks
```

- [ ] **Passo 2: Rodar e confirmar que falha**

Executar: `docker compose exec web pytest tests/test_celery.py -v`
Esperado: FALHA com `ModuleNotFoundError: No module named 'apps.comum.tasks'`.

- [ ] **Passo 3: Configurar o Celery**

`config/celery.py`:

```python
import os

from celery import Celery

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

app = Celery("orientasi")
app.config_from_object("django.conf:settings", namespace="CELERY")
app.autodiscover_tasks()
```

`config/__init__.py`:

```python
from config.celery import app as celery_app

__all__ = ("celery_app",)
```

Acrescentar ao final da parte comum de `config/settings.py` (antes do bloco
`if AMBIENTE`):

```python
CELERY_BROKER_URL = os.environ.get("REDIS_URL", "redis://redis:6379/0")
CELERY_RESULT_BACKEND = os.environ.get("REDIS_URL", "redis://redis:6379/0")
CELERY_TASK_ALWAYS_EAGER = False
CELERY_TASK_TIME_LIMIT = 300
CELERY_TASK_ACKS_LATE = True

EMAIL_BACKEND = os.environ.get(
    "EMAIL_BACKEND", "django.core.mail.backends.console.EmailBackend"
)
EMAIL_HOST = os.environ.get("EMAIL_HOST", "")
EMAIL_PORT = int(os.environ.get("EMAIL_PORT", "587"))
EMAIL_USE_TLS = True
EMAIL_HOST_USER = os.environ.get("EMAIL_HOST_USER", "")
EMAIL_HOST_PASSWORD = os.environ.get("EMAIL_HOST_PASSWORD", "")
DEFAULT_FROM_EMAIL = os.environ.get("DEFAULT_FROM_EMAIL", "nao-responda@orientasi.local")
```

`apps/comum/tasks.py`:

```python
from celery import shared_task


@shared_task
def somar(a, b):
    """Tarefa de fumaça: prova que o worker está processando a fila."""
    return a + b
```

- [ ] **Passo 4: Acrescentar os serviços ao compose**

Em `docker-compose.yml`, adicionar:

```yaml
  redis:
    image: redis:7-alpine
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 5s
      timeout: 3s
      retries: 10

  celery_worker:
    build:
      context: .
      target: dev
    command: celery -A config worker --loglevel=info
    volumes:
      - .:/app
    env_file:
      - .env
    depends_on:
      db:
        condition: service_healthy
      redis:
        condition: service_healthy
```

E no serviço `web`, acrescentar `redis: {condition: service_healthy}` em `depends_on`.

Em `.env.example`, acrescentar:

```
REDIS_URL=redis://redis:6379/0
EMAIL_BACKEND=django.core.mail.backends.console.EmailBackend
DEFAULT_FROM_EMAIL=nao-responda@orientasi.local
```

- [ ] **Passo 5: Rodar os testes e confirmar que passam**

```bash
docker compose up -d --build
docker compose exec web pytest tests/test_celery.py -v
```

Esperado: PASSA.

- [ ] **Passo 6: Verificar o worker de verdade**

```bash
# `import config` e obrigatorio: sem ele este processo cru nao registra config.celery.app,
# e o shared_task liga-se ao app Celery default implicito, que aponta para AMQP.
docker compose exec web python -c "import config; from apps.comum.tasks import somar; print(somar.delay(2, 3).get(timeout=10))"
docker compose logs --tail=20 celery_worker
```

Esperado: imprime `5`, e o log do worker mostra
`Task apps.comum.tasks.somar[...] succeeded`. Este passo é a verificação que o teste
síncrono **não** faz: prova que broker, worker e fila estão realmente conectados.

- [ ] **Passo 7: Commit**

```bash
git add -A
git commit -m "Liga o Celery ao Redis com tarefa de fumaça verificada no worker"
```

---

## Tarefa 3: MinIO e armazenamento de mídia

**Arquivos:**
- Modificar: `config/settings.py`, `docker-compose.yml`, `.env.example`
- Teste: `tests/test_armazenamento.py`

**Interfaces:**
- Consome: `config.settings` das Tarefas 1–2.
- Produz: `STORAGES["default"]` apontando para `storages.backends.s3.S3Storage` fora
  dos testes. Nenhuma interface Python nova.

- [ ] **Passo 1: Escrever o teste (falhando)**

`tests/test_armazenamento.py`:

```python
import importlib
import os


def test_storage_padrao_e_s3_fora_dos_testes():
    anterior = dict(os.environ)
    os.environ.update({"S3_ENDPOINT": "http://minio:9000", "S3_BUCKET": "orientasi"})
    try:
        import config.settings

        settings = importlib.reload(config.settings)
        backend = settings.STORAGES["default"]["BACKEND"]
        assert backend == "storages.backends.s3.S3Storage"
        assert settings.STORAGES["default"]["OPTIONS"]["bucket_name"] == "orientasi"
    finally:
        os.environ.clear()
        os.environ.update(anterior)
        import config.settings

        importlib.reload(config.settings)


def test_fixture_isola_os_testes_do_bucket(settings):
    # A fixture autouse do conftest força FileSystemStorage: nenhum teste toca o MinIO.
    assert settings.STORAGES["default"]["BACKEND"] == (
        "django.core.files.storage.FileSystemStorage"
    )
```

- [ ] **Passo 2: Rodar e confirmar que falha**

Executar: `docker compose exec web pytest tests/test_armazenamento.py -v`
Esperado: FALHA — `test_storage_padrao_e_s3_fora_dos_testes` afirma `S3Storage` mas
encontra `FileSystemStorage`.

- [ ] **Passo 3: Configurar o armazenamento**

Em `config/settings.py`, substituir a definição de `STORAGES` nos dois ramos por uma
definição única, colocada **antes** do `if AMBIENTE`:

```python
# MinIO fala o protocolo S3: dev e produção usam o mesmo backend, mudando apenas
# o endpoint e as credenciais (spec §3.7).
_ARMAZENAMENTO_S3 = {
    "BACKEND": "storages.backends.s3.S3Storage",
    "OPTIONS": {
        "bucket_name": os.environ.get("S3_BUCKET", "orientasi"),
        "endpoint_url": os.environ.get("S3_ENDPOINT") or None,
        "access_key": os.environ.get("S3_ACCESS_KEY", ""),
        "secret_key": os.environ.get("S3_SECRET_KEY", ""),
        "default_acl": None,
        "querystring_auth": True,
        "file_overwrite": False,
    },
}
_ARMAZENAMENTO_LOCAL = {"BACKEND": "django.core.files.storage.FileSystemStorage"}

_padrao = _ARMAZENAMENTO_S3 if os.environ.get("S3_ENDPOINT") else _ARMAZENAMENTO_LOCAL
```

E nos dois ramos do `if AMBIENTE`, trocar a chave `"default"` por `_padrao`, mantendo
a diferença apenas em `"staticfiles"`:

```python
    STORAGES = {"default": _padrao, "staticfiles": {"BACKEND": "..."}}
```

- [ ] **Passo 4: Acrescentar os serviços ao compose**

```yaml
  minio:
    image: minio/minio
    command: server /data --console-address ":9001"
    environment:
      MINIO_ROOT_USER: orientasi
      MINIO_ROOT_PASSWORD: orientasi123
    volumes:
      - dados_minio:/data
    ports:
      - "9000:9000"
      - "9001:9001"
    healthcheck:
      test: ["CMD", "mc", "ready", "local"]
      interval: 5s
      timeout: 3s
      retries: 10

  minio_init:
    image: minio/mc
    depends_on:
      minio:
        condition: service_healthy
    entrypoint: >
      /bin/sh -c "
      mc alias set local http://minio:9000 orientasi orientasi123 &&
      mc mb --ignore-existing local/orientasi &&
      echo 'bucket orientasi pronto'
      "
```

Acrescentar `dados_minio:` à seção `volumes`, e ao `.env.example`:

```
S3_ENDPOINT=http://minio:9000
S3_BUCKET=orientasi
S3_ACCESS_KEY=orientasi
S3_SECRET_KEY=orientasi123
```

- [ ] **Passo 5: Rodar os testes e confirmar que passam**

```bash
docker compose up -d --build
docker compose exec web pytest tests/test_armazenamento.py -v
```

Esperado: PASSA.

- [ ] **Passo 6: Verificar o envio de verdade**

```bash
docker compose exec web python manage.py shell -c "
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
nome = default_storage.save('teste.txt', ContentFile(b'ola'))
print('gravado:', nome, '| conteudo:', default_storage.open(nome).read())
default_storage.delete(nome)
"
```

Esperado: imprime `gravado: teste.txt | conteudo: b'ola'`. Prova que o bucket existe e
aceita escrita — o que o teste unitário, isolado por fixture, não cobre.

- [ ] **Passo 7: Commit**

```bash
git add -A
git commit -m "Aponta a midia para o MinIO pelo backend S3 do django-storages"
```

---

## Tarefa 4: Tailwind v4, DaisyUI, HTMX, Alpine e o layout base

**Arquivos:**
- Criar: `package.json`, `static/css/entrada.css`, `templates/base.html`, `templates/inicio.html`
- Criar: `static/js/htmx.min.js`, `static/js/alpine-focus.min.js`, `static/js/alpine.min.js`
- Modificar: `Dockerfile`, `docker-compose.yml`, `config/urls.py`, `.gitignore`
- Teste: `tests/test_base_template.py`

**Interfaces:**
- Consome: `config.urls` da Tarefa 1.
- Produz: rota nomeada `inicio` em `/`; bloco de template `{% block conteudo %}` e
  `{% block titulo %}` em `base.html`; região `#anuncios` com `aria-live="polite"`,
  destino de todo `hx-swap-oob` de mensagem.

- [ ] **Passo 1: Baixar as bibliotecas para `static/js/`**

```bash
curl -sL -o static/js/htmx.min.js        https://unpkg.com/htmx.org@2.0.4/dist/htmx.min.js
curl -sL -o static/js/alpine-focus.min.js https://unpkg.com/@alpinejs/focus@3.14.8/dist/cdn.min.js
curl -sL -o static/js/alpine.min.js       https://unpkg.com/alpinejs@3.14.8/dist/cdn.min.js
ls -la static/js/
```

O plugin `focus` **precisa** vir antes do núcleo do Alpine: é assim que ele se
registra. A ordem no `base.html` reflete isso.

- [ ] **Passo 2: Criar a configuração do Tailwind**

`package.json`:

```json
{
  "name": "orientasi",
  "private": true,
  "devDependencies": {
    "@tailwindcss/cli": "^4.1.0",
    "tailwindcss": "^4.1.0",
    "daisyui": "^5.0.0"
  },
  "scripts": {
    "build:css": "tailwindcss -i static/css/entrada.css -o static/css/orientasi.css --minify",
    "watch:css": "tailwindcss -i static/css/entrada.css -o static/css/orientasi.css --watch"
  }
}
```

`static/css/entrada.css`:

```css
@import "tailwindcss";

@source "../../templates";
@source "../../apps";

@plugin "daisyui";

@plugin "daisyui/theme" {
  name: "orientasi";
  default: true;
  color-scheme: light;

  --color-base-100: #ffffff;
  --color-base-200: #f5f8fb;
  --color-base-300: #e1e6ec;
  --color-base-content: #16202e;

  --color-primary: #21376b;
  --color-primary-content: #ffffff;
  --color-secondary: #055695;
  --color-secondary-content: #ffffff;
  --color-accent: #38c2c2;
  --color-accent-content: #16202e;

  --color-warning: #d9530e;
  --color-warning-content: #ffffff;

  --radius-box: 0.75rem;
  --radius-field: 0.5rem;
}

@theme {
  --font-display: "Jakarta", system-ui, sans-serif;
  --font-corpo: "Inter", system-ui, -apple-system, sans-serif;
}

/* Alvo de toque mínimo de 44x44px (WCAG 2.1 AA, alvo 2.5.5). Aplicado uma vez
   aqui em vez de repetido em cada componente. */
@layer base {
  button, [role="button"], a.btn, input[type="submit"], select {
    min-height: 2.75rem;
    min-width: 2.75rem;
  }
  [x-cloak] { display: none !important; }
}
```

Acrescentar ao `.gitignore`: `static/css/orientasi.css` (gerado) — já presente desde o
commit inicial; confirmar.

- [ ] **Passo 3: Escrever o teste do layout (falhando)**

`tests/test_base_template.py`:

```python
import pytest


@pytest.mark.django_db
def test_inicio_responde_com_marcos_semanticos(client):
    html = client.get("/").content.decode()
    assert '<html lang="pt-br"' in html
    assert "<main" in html and 'id="conteudo"' in html
    assert "<header" in html and "<nav" in html and "<footer" in html


@pytest.mark.django_db
def test_base_tem_link_para_pular_o_conteudo(client):
    html = client.get("/").content.decode()
    assert 'href="#conteudo"' in html
    assert "Pular para o conteúdo" in html


@pytest.mark.django_db
def test_base_tem_regiao_de_anuncio_para_o_htmx(client):
    html = client.get("/").content.decode()
    assert 'id="anuncios"' in html
    assert 'aria-live="polite"' in html


@pytest.mark.django_db
def test_nao_carrega_recurso_de_cdn(client):
    html = client.get("/").content.decode()
    for proibido in ["unpkg.com", "cdn.jsdelivr", "cdnjs", "fonts.googleapis"]:
        assert proibido not in html, f"O projeto não carrega CDN, e encontrei {proibido}."
```

- [ ] **Passo 4: Rodar e confirmar que falha**

Executar: `docker compose exec web pytest tests/test_base_template.py -v`
Esperado: FALHA com 404 em `/` (a rota ainda não existe).

- [ ] **Passo 5: Escrever os templates**

`templates/base.html`:

```html
{% load static %}<!doctype html>
<html lang="pt-br" data-theme="orientasi">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta name="theme-color" content="#21376b">
  <title>OrientaSI{% block titulo %}{% endblock %}</title>
  <link rel="stylesheet" href="{% static 'css/orientasi.css' %}">
  <script src="{% static 'js/htmx.min.js' %}" defer></script>
  {# O plugin focus registra-se no Alpine e precisa ser avaliado antes do nucleo. #}
  <script src="{% static 'js/alpine-focus.min.js' %}" defer></script>
  <script src="{% static 'js/alpine.min.js' %}" defer></script>
</head>
<body class="min-h-screen bg-base-200 font-corpo text-base-content">

  {# Primeiro elemento focavel da pagina. Invisivel ate receber foco: quem usa
     mouse nunca o ve, quem usa teclado o encontra na primeira tabulacao. #}
  <a href="#conteudo"
     class="sr-only focus:not-sr-only focus:absolute focus:z-50 focus:m-2 focus:rounded
            focus:bg-primary focus:px-4 focus:py-3 focus:text-primary-content">
    Pular para o conteúdo
  </a>

  <header class="bg-base-100 shadow-sm">
    <div class="mx-auto flex max-w-5xl items-center justify-between gap-4 px-4 py-3">
      <a href="{% url 'inicio' %}" class="flex items-center">
        <img src="{% static 'img/orientasi-marca.png' %}" alt="OrientaSI, Sistema de Gestão de TCC"
             class="h-12 w-auto">
      </a>
      <nav aria-label="Principal">
        {% block navegacao %}{% endblock %}
      </nav>
    </div>
  </header>

  {# Regiao de anuncio permanente. Sem ela, uma troca de HTMX e silenciosa para
     leitores de tela: a acao acontece e a pessoa nao recebe sinal algum. Toda
     resposta HTMX de sucesso ou erro escreve aqui via hx-swap-oob. #}
  <div id="anuncios" aria-live="polite" aria-atomic="true" class="sr-only"></div>

  {# tabindex=-1 nao e enfeite: sem ele, Safari e Chrome rolam ate a ancora mas
     nao movem o foco, e a pessoa continua tabulando dentro do cabecalho. #}
  <main id="conteudo" tabindex="-1" class="mx-auto max-w-5xl px-4 py-8">
    {% block conteudo %}{% endblock %}
  </main>

  <footer class="mx-auto max-w-5xl px-4 py-8 text-sm text-base-content/70">
    <p>OrientaSI — Sistema de Gestão de TCC do Curso de Sistemas de Informação.</p>
  </footer>
</body>
</html>
```

`templates/inicio.html`:

```html
{% extends "base.html" %}

{% block titulo %} — Início{% endblock %}

{% block conteudo %}
  <article class="rounded-box bg-base-100 p-8 shadow-sm">
    <h1 class="font-display text-3xl font-bold text-primary">
      Sistema de Gestão de TCC
    </h1>
    <p class="mt-4 max-w-prose">
      O OrientaSI acompanha o trabalho de conclusão de curso do início ao depósito
      final: temas, orientação, bancas, atas e o catálogo público dos trabalhos
      concluídos.
    </p>
    <a href="{% url 'admin:index' %}" class="btn btn-primary mt-6">Entrar</a>
  </article>
{% endblock %}
```

Em `config/urls.py`, acrescentar:

```python
from django.views.generic import TemplateView

urlpatterns = [
    path("", TemplateView.as_view(template_name="inicio.html"), name="inicio"),
    path("admin/", admin.site.urls),
    path("saude/", saude, name="saude"),
]
```

- [ ] **Passo 6: Acrescentar o estágio `css` ao Dockerfile e o serviço de watch**

No topo do `Dockerfile`, antes do estágio `base`:

```dockerfile
FROM node:22-alpine AS css
WORKDIR /build
COPY package.json ./
RUN npm install
COPY static/css/entrada.css ./static/css/entrada.css
COPY templates ./templates
COPY apps ./apps
RUN npx tailwindcss -i static/css/entrada.css -o static/css/orientasi.css --minify
```

E no estágio `prod`, **antes** do `collectstatic`:

```dockerfile
COPY --from=css /build/static/css/orientasi.css /app/static/css/orientasi.css
```

No `docker-compose.yml`, acrescentar o serviço de desenvolvimento:

```yaml
  tailwind:
    image: node:22-alpine
    working_dir: /app
    command: sh -c "npm install && npx tailwindcss -i static/css/entrada.css -o static/css/orientasi.css --watch"
    volumes:
      - .:/app
    profiles:
      - dev
```

- [ ] **Passo 7: Gerar o CSS e rodar os testes**

```bash
docker compose --profile dev up -d
docker compose exec web ls -la static/css/orientasi.css
docker compose exec web pytest tests/test_base_template.py -v
```

Esperado: o CSS existe e todos os testes PASSAM.

- [ ] **Passo 8: Commit**

```bash
git add -A
git commit -m "Monta o layout base com Tailwind, DaisyUI, HTMX e Alpine vendorizados"
```

---

## Tarefa 5: Suíte de acessibilidade

**Arquivos:**
- Modificar: `conftest.py`
- Teste: `tests/test_acessibilidade.py`, `tests/test_toque.py`, `tests/test_responsivo.py`, `tests/test_teclado.py`, `tests/test_pdf.py`

**Interfaces:**
- Consome: a rota `inicio` da Tarefa 4.
- Produz: a fixture `rota` do `conftest.py`, parametrizada sobre a lista `ROTAS`.
  **Toda tarefa que criar uma página pública nova acrescenta sua rota a essa lista** —
  é assim que a suíte cresce sozinha (spec §10.1).

- [ ] **Passo 1: Acrescentar a lista de rotas ao `conftest.py`**

```python
import pytest

# Lista única de rotas submetidas à suíte de acessibilidade, toque, responsividade
# e teclado. Acrescentar aqui é o que submete uma página nova às quatro verificações.
ROTAS = [
    "/",
]


@pytest.fixture(params=ROTAS)
def rota(request):
    return request.param
```

- [ ] **Passo 2: Escrever os testes (falhando)**

`tests/test_acessibilidade.py`:

```python
import pytest
from axe_playwright_python.sync_playwright import Axe

REGRAS = {"runOnly": {"type": "tag", "values": ["wcag2a", "wcag2aa", "wcag21aa"]}}


@pytest.mark.django_db(transaction=True)
def test_pagina_nao_viola_wcag(page, live_server, rota):
    page.goto(f"{live_server.url}{rota}")
    resultados = Axe().run(page, options=REGRAS)
    assert resultados.violations_count == 0, (
        f"{rota} viola {resultados.violations_count} regra(s):\n"
        f"{resultados.generate_report()}"
    )
```

`tests/test_toque.py`:

```python
import pytest

INTERATIVOS = "a, button, input:not([type=hidden]), select, textarea, [role=button]"


@pytest.mark.django_db(transaction=True)
def test_alvos_de_toque_tem_ao_menos_44px(page, live_server, rota):
    page.goto(f"{live_server.url}{rota}")
    pequenos = []
    for elemento in page.query_selector_all(INTERATIVOS):
        if not elemento.is_visible():
            continue
        caixa = elemento.bounding_box()
        if caixa and (caixa["width"] < 44 or caixa["height"] < 44):
            pequenos.append(
                f'{elemento.evaluate("e => e.outerHTML.slice(0, 90)")} '
                f'({caixa["width"]:.0f}x{caixa["height"]:.0f})'
            )
    assert not pequenos, f"Alvos menores que 44x44px em {rota}:\n" + "\n".join(pequenos)
```

`tests/test_responsivo.py`:

```python
import pytest


@pytest.mark.django_db(transaction=True)
def test_sem_rolagem_horizontal_em_360px(page, live_server, rota):
    page.set_viewport_size({"width": 360, "height": 800})
    page.goto(f"{live_server.url}{rota}")
    largura_conteudo = page.evaluate("document.documentElement.scrollWidth")
    largura_janela = page.evaluate("document.documentElement.clientWidth")
    assert largura_conteudo <= largura_janela + 1, (
        f"{rota} rola horizontalmente a 360px: "
        f"conteúdo {largura_conteudo}px em janela de {largura_janela}px."
    )
```

`tests/test_teclado.py`:

```python
import pytest


@pytest.mark.django_db(transaction=True)
def test_primeira_tabulacao_alcanca_o_link_de_pular(page, live_server, rota):
    page.goto(f"{live_server.url}{rota}")
    page.keyboard.press("Tab")
    focado = page.evaluate("document.activeElement.getAttribute('href')")
    assert focado == "#conteudo", (
        f"Em {rota}, a primeira tabulação deveria alcançar o link "
        f'"Pular para o conteúdo", e alcançou {focado!r}.'
    )
```

`tests/test_pdf.py`:

```python
def test_weasyprint_gera_pdf():
    """Trava a regressão do dia em que alguém enxugar as libs do Dockerfile (spec §8.2)."""
    from weasyprint import HTML

    pdf = HTML(string="<p>Ata de defesa</p>").write_pdf()
    assert pdf.startswith(b"%PDF-")
```

- [ ] **Passo 3: Rodar e observar o resultado**

Executar: `docker compose exec web pytest tests/test_acessibilidade.py tests/test_toque.py tests/test_responsivo.py tests/test_teclado.py tests/test_pdf.py -v`

Esperado: os testes **executam**. Se `test_pagina_nao_viola_wcag` ou
`test_alvos_de_toque_tem_ao_menos_44px` falharem, o defeito está no `base.html` da
Tarefa 4 — corrija o template, não o teste. A falha mais provável é contraste
insuficiente no rodapé (`text-base-content/70`): se o axe apontar
`color-contrast`, subir para `/80` resolve.

- [ ] **Passo 4: Corrigir o que a suíte apontar e rodar de novo**

Executar: `docker compose exec web pytest -v`
Esperado: a suíte inteira PASSA.

- [ ] **Passo 5: Commit**

```bash
git add -A
git commit -m "Adiciona a suite de acessibilidade com Playwright e axe-core"
```

---

## Tarefa 6: Perfis e áreas

**Arquivos:**
- Modificar: `apps/contas/models.py`, `apps/contas/admin.py`
- Teste: `apps/contas/tests/test_perfis.py`

**Interfaces:**
- Consome: `Usuario` da Tarefa 1.
- Produz: `apps.contas.models.PerfilAluno` (`usuario`, `matricula`),
  `PerfilProfessor` (`usuario`, `siape`, `areas`), `Area` (`nome`, `descricao`).
  Acessos reversos: `usuario.perfil_aluno` e `usuario.perfil_professor`.

- [ ] **Passo 1: Escrever o teste (falhando)**

`apps/contas/tests/test_perfis.py`:

```python
import pytest
from django.db import IntegrityError, transaction

from apps.contas.models import Area, PerfilAluno, PerfilProfessor, Usuario


@pytest.fixture
def professora(db):
    return Usuario.objects.create_user(
        email="ana@ufsm.br", password="x", nome_completo="Ana", cpf="52998224725"
    )


@pytest.mark.django_db
def test_perfil_professor_guarda_siape_e_areas(professora):
    ia = Area.objects.create(nome="Inteligência Artificial")
    redes = Area.objects.create(nome="Redes")
    perfil = PerfilProfessor.objects.create(usuario=professora, siape="1234567")
    perfil.areas.set([ia, redes])

    assert professora.perfil_professor.siape == "1234567"
    assert set(professora.perfil_professor.areas.all()) == {ia, redes}


@pytest.mark.django_db
def test_matricula_e_unica():
    for email in ["joao@ufsm.br", "maria@ufsm.br"]:
        cpf = "52998224725" if email.startswith("joao") else "16899535009"
        usuario = Usuario.objects.create_user(
            email=email, password="x", nome_completo=email, papel=Usuario.ALUNO, cpf=cpf
        )
        if email.startswith("joao"):
            PerfilAluno.objects.create(usuario=usuario, matricula="201910001")
        else:
            with pytest.raises(IntegrityError), transaction.atomic():
                PerfilAluno.objects.create(usuario=usuario, matricula="201910001")


@pytest.mark.django_db
def test_area_tem_nome_unico():
    Area.objects.create(nome="Redes")
    with pytest.raises(IntegrityError), transaction.atomic():
        Area.objects.create(nome="Redes")
```

- [ ] **Passo 2: Rodar e confirmar que falha**

Executar: `docker compose exec web pytest apps/contas/tests/test_perfis.py -v`
Esperado: FALHA com `ImportError: cannot import name 'Area'`.

- [ ] **Passo 3: Escrever os modelos**

Acrescentar a `apps/contas/models.py`:

```python
class Area(models.Model):
    """Vocabulário controlado de áreas de atuação, mantido pela coordenação.

    Vive em contas e não em projetos porque é a única direção acíclica: projetos
    já dependerá de contas (todo projeto aponta para um Usuario). Spec §5.4.
    """

    nome = models.CharField("nome", max_length=120, unique=True)
    descricao = models.TextField("descrição", blank=True)

    class Meta:
        verbose_name = "área"
        verbose_name_plural = "áreas"
        ordering = ["nome"]

    def __str__(self):
        return self.nome


class PerfilAluno(models.Model):
    usuario = models.OneToOneField(
        Usuario, on_delete=models.CASCADE, related_name="perfil_aluno",
        verbose_name="usuário",
    )
    matricula = models.CharField("matrícula", max_length=20, unique=True)

    class Meta:
        verbose_name = "perfil de aluno"
        verbose_name_plural = "perfis de alunos"

    def __str__(self):
        return f"{self.usuario.nome_completo} ({self.matricula})"


class PerfilProfessor(models.Model):
    usuario = models.OneToOneField(
        Usuario, on_delete=models.CASCADE, related_name="perfil_professor",
        verbose_name="usuário",
    )
    siape = models.CharField("SIAPE", max_length=20, unique=True)
    areas = models.ManyToManyField(Area, blank=True, related_name="professores",
                                   verbose_name="áreas de atuação")

    class Meta:
        verbose_name = "perfil de professor"
        verbose_name_plural = "perfis de professores"

    def __str__(self):
        return f"{self.usuario.nome_completo} (SIAPE {self.siape})"
```

Acrescentar a `apps/contas/admin.py`:

```python
from apps.contas.models import Area, PerfilAluno, PerfilProfessor


@admin.register(Area)
class AreaAdmin(admin.ModelAdmin):
    list_display = ["nome"]
    search_fields = ["nome"]


admin.site.register(PerfilAluno)
admin.site.register(PerfilProfessor)
```

- [ ] **Passo 4: Migrar e rodar os testes**

```bash
docker compose exec web python manage.py makemigrations contas
docker compose exec web python manage.py migrate
docker compose exec web pytest apps/contas/tests/ -v
```

Esperado: PASSA.

- [ ] **Passo 5: Commit**

```bash
git add -A
git commit -m "Adiciona perfis de aluno e professor e o vocabulario de areas"
```

---

## Tarefa 7: Convites — modelo, serviço e envio assíncrono

**Arquivos:**
- Modificar: `apps/contas/models.py`
- Criar: `apps/contas/permissions.py`, `apps/contas/services.py`, `apps/contas/tasks.py`
- Criar: `templates/email/convite.txt`
- Teste: `apps/contas/tests/test_convites.py`

**Interfaces:**
- Consome: `Usuario` (T1), perfis (T6), `apps.comum.tasks` (T2).
- Produz:
  - `apps.contas.permissions.garante(condicao, mensagem)` — levanta `PermissionDenied`.
  - `apps.contas.permissions.pode_convidar(usuario) -> bool`
  - `apps.contas.permissions.pode_promover(usuario) -> bool`
  - `apps.contas.models.Convite` com `esta_valido() -> bool`
  - `apps.contas.services.convidar(email, papel, por) -> Convite`
  - `apps.contas.services.reenviar_convite(convite, por) -> Convite`
  - `apps.contas.tasks.enviar_convite(convite_id, token)`
  - A validade do convite vem de `settings.CONVITE_VALIDADE_DIAS` (uma única
    fonte, lida tanto pelo serviço quanto pelo corpo do e-mail).

- [ ] **Passo 1: Escrever o teste (falhando)**

`apps/contas/tests/test_convites.py`:

```python
import pytest
from django.core import mail
from django.core.exceptions import PermissionDenied, ValidationError
from django.utils import timezone

from apps.contas import services
from apps.contas.models import Convite, Usuario


@pytest.fixture
def coordenadora(db):
    return Usuario.objects.create_user(
        email="coord@ufsm.br", password="x", nome_completo="Coordenadora",
        cpf="52998224725", is_coordenador=True, is_staff=True,
    )


@pytest.fixture
def professor(db):
    return Usuario.objects.create_user(
        email="prof@ufsm.br", password="x", nome_completo="Professor", cpf="16899535009"
    )


# services.convidar enfileira o e-mail em transaction.on_commit, e o pytest-django
# reverte a transacao de cada teste: sem capturar os callbacks, o on_commit nunca
# dispara e mail.outbox fica vazio. A fixture abaixo executa os callbacks pendentes.
@pytest.fixture
def envia_convite(settings, django_capture_on_commit_callbacks):
    settings.CELERY_TASK_ALWAYS_EAGER = True

    def _envia(*args, **kwargs):
        with django_capture_on_commit_callbacks(execute=True):
            return services.convidar(*args, **kwargs)

    return _envia


@pytest.mark.django_db
def test_convidar_grava_o_hash_e_nunca_o_token_em_claro(coordenadora, envia_convite):
    convite = envia_convite("novo@ufsm.br", Usuario.ALUNO, por=coordenadora)

    assert convite.email == "novo@ufsm.br"
    assert convite.usado_em is None
    assert convite.esta_valido()
    assert len(convite.token_hash) == 64
    # O token em claro só existe no corpo do e-mail.
    assert convite.token_hash not in mail.outbox[0].body


@pytest.mark.django_db
def test_convidar_envia_email_com_o_link(coordenadora, envia_convite):
    envia_convite("novo@ufsm.br", Usuario.ALUNO, por=coordenadora)

    assert len(mail.outbox) == 1
    assert "novo@ufsm.br" in mail.outbox[0].to
    assert "/convite/" in mail.outbox[0].body


@pytest.mark.django_db
def test_so_coordenador_convida(professor):
    with pytest.raises(PermissionDenied):
        services.convidar("novo@ufsm.br", Usuario.ALUNO, por=professor)


@pytest.mark.django_db
def test_recusa_convite_para_email_ja_cadastrado(coordenadora, professor):
    with pytest.raises(ValidationError):
        services.convidar(professor.email, Usuario.PROFESSOR, por=coordenadora)


@pytest.mark.django_db
def test_recusa_segundo_convite_ativo_para_o_mesmo_email(coordenadora, envia_convite):
    envia_convite("novo@ufsm.br", Usuario.ALUNO, por=coordenadora)
    with pytest.raises(ValidationError):
        services.convidar("novo@ufsm.br", Usuario.ALUNO, por=coordenadora)


@pytest.mark.django_db
def test_reenviar_invalida_o_convite_anterior(
    coordenadora, envia_convite, django_capture_on_commit_callbacks
):
    primeiro = envia_convite("novo@ufsm.br", Usuario.ALUNO, por=coordenadora)
    hash_antigo = primeiro.token_hash

    with django_capture_on_commit_callbacks(execute=True):
        segundo = services.reenviar_convite(primeiro, por=coordenadora)

    assert segundo.token_hash != hash_antigo
    assert not Convite.objects.filter(token_hash=hash_antigo, usado_em__isnull=True).exists()
    assert len(mail.outbox) == 2


@pytest.mark.django_db
def test_convite_expirado_nao_e_valido(coordenadora, envia_convite):
    convite = envia_convite("novo@ufsm.br", Usuario.ALUNO, por=coordenadora)
    convite.expira_em = timezone.now() - timezone.timedelta(seconds=1)
    convite.save(update_fields=["expira_em"])

    assert not convite.esta_valido()
```

- [ ] **Passo 2: Rodar e confirmar que falha**

Executar: `docker compose exec web pytest apps/contas/tests/test_convites.py -v`
Esperado: FALHA com `ImportError: cannot import name 'services'` ou `'Convite'`.

- [ ] **Passo 3: Escrever o modelo `Convite`**

Acrescentar a `apps/contas/models.py`:

```python
class Convite(models.Model):
    PAPEIS_CONVIDAVEIS = [(Usuario.ALUNO, "Aluno"), (Usuario.PROFESSOR, "Professor")]

    email = models.EmailField("e-mail")
    papel = models.CharField("papel", max_length=10, choices=PAPEIS_CONVIDAVEIS)
    # Guardamos o hash, nunca o token em claro: se o banco vazar, os convites
    # pendentes não são utilizáveis (spec §5.5).
    token_hash = models.CharField("hash do token", max_length=64, unique=True)
    criado_por = models.ForeignKey(
        Usuario, on_delete=models.PROTECT, related_name="convites_enviados",
        verbose_name="criado por",
    )
    criado_em = models.DateTimeField("criado em", auto_now_add=True)
    expira_em = models.DateTimeField("expira em")
    usado_em = models.DateTimeField("usado em", null=True, blank=True)
    usuario_criado = models.OneToOneField(
        Usuario, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="convite_de_origem", verbose_name="usuário criado",
    )

    class Meta:
        verbose_name = "convite"
        verbose_name_plural = "convites"
        ordering = ["-criado_em"]

    def __str__(self):
        return f"Convite para {self.email} ({self.get_papel_display()})"

    def esta_valido(self):
        from django.utils import timezone

        return self.usado_em is None and self.expira_em > timezone.now()
```

- [ ] **Passo 4: Escrever `permissions.py`**

```python
from django.core.exceptions import PermissionDenied

from apps.contas.models import Usuario


def garante(condicao, mensagem):
    if not condicao:
        raise PermissionDenied(mensagem)


def pode_convidar(usuario):
    return bool(usuario and usuario.is_authenticated and usuario.is_coordenador)


def pode_promover(usuario):
    return pode_convidar(usuario)


def e_sugrad(usuario):
    return bool(usuario and usuario.is_authenticated and usuario.papel == Usuario.SUGRAD)
```

- [ ] **Passo 5: Escrever `services.py` e `tasks.py`**

`apps/contas/services.py`:

```python
import hashlib
import secrets

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from apps.contas import permissions
from django.conf import settings

from apps.contas.models import Convite, Usuario


def _hash(token):
    return hashlib.sha256(token.encode()).hexdigest()


@transaction.atomic
def convidar(email, papel, por):
    """Cria o convite e enfileira o e-mail. O token em claro só existe no e-mail."""
    permissions.garante(permissions.pode_convidar(por), "Somente a coordenação envia convites.")

    email = email.strip().lower()
    if Usuario.objects.filter(email=email).exists():
        raise ValidationError(f"Já existe uma conta para {email}.")
    if any(c.esta_valido() for c in Convite.objects.filter(email=email)):
        raise ValidationError(f"Já existe um convite ativo para {email}. Reenvie-o, se preciso.")

    token = secrets.token_urlsafe(32)
    convite = Convite.objects.create(
        email=email,
        papel=papel,
        token_hash=_hash(token),
        criado_por=por,
        expira_em=timezone.now() + timezone.timedelta(days=settings.CONVITE_VALIDADE_DIAS),
    )

    from apps.contas.tasks import enviar_convite

    transaction.on_commit(lambda: enviar_convite.delay(convite.id, token))
    return convite


@transaction.atomic
def reenviar_convite(convite, por):
    """Invalida o convite anterior e emite outro: um link por vez, sempre."""
    permissions.garante(permissions.pode_convidar(por), "Somente a coordenação envia convites.")
    if convite.usado_em is not None:
        raise ValidationError("Este convite já foi utilizado.")

    convite.expira_em = timezone.now()
    convite.save(update_fields=["expira_em"])
    return convidar(convite.email, convite.papel, por=por)
```

`apps/contas/tasks.py`:

```python
from celery import shared_task
from django.conf import settings
from django.core.mail import send_mail
from django.template.loader import render_to_string
from django.urls import reverse


@shared_task(bind=True, max_retries=3, default_retry_delay=60, retry_backoff=True)
def enviar_convite(self, convite_id, token):
    from apps.contas.models import Convite

    convite = Convite.objects.get(pk=convite_id)
    caminho = reverse("contas:aceitar_convite", kwargs={"token": token})
    corpo = render_to_string(
        "email/convite.txt",
        {
            "convite": convite,
            "link": f"{settings.URL_BASE}{caminho}",
            "validade_dias": settings.CONVITE_VALIDADE_DIAS,
        },
    )
    try:
        send_mail(
            subject="OrientaSI — convite de cadastro",
            message=corpo,
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[convite.email],
        )
    except Exception as erro:  # noqa: BLE001 — repetimos qualquer falha de entrega
        raise self.retry(exc=erro) from erro
```

Acrescentar a `config/settings.py`, junto das demais constantes do projeto:

```python
URL_BASE = os.environ.get("URL_BASE", "http://localhost:8000")
CONVITE_VALIDADE_DIAS = 7
```

E ao `.env.example`: `URL_BASE=http://localhost:8000`

`templates/email/convite.txt`:

```
Olá,

Você foi convidado(a) a se cadastrar no OrientaSI, o sistema de gestão de TCC do
Curso de Sistemas de Informação, como {{ convite.get_papel_display|lower }}.

Para concluir seu cadastro, acesse:

{{ link }}

Este link vale por {{ validade_dias }} dias e pode ser usado uma única vez.

Se você não esperava este convite, ignore esta mensagem.

OrientaSI — Sistema de Gestão de TCC
```

- [ ] **Passo 6: Registrar a rota nomeada usada pela task**

A task chama `reverse("contas:aceitar_convite")`, que a Tarefa 8 implementa. Para que
esta tarefa seja testável isoladamente, criar já `apps/contas/urls.py`:

```python
from django.urls import path

from apps.contas import views

app_name = "contas"

urlpatterns = [
    path("convite/<str:token>/", views.aceitar_convite, name="aceitar_convite"),
]
```

E `apps/contas/views.py` com a view mínima, que a Tarefa 8 substitui:

```python
from django.http import HttpResponse


def aceitar_convite(request, token):
    return HttpResponse("Formulário de cadastro — implementado na Tarefa 8.")
```

Em `config/urls.py`, acrescentar: `path("", include("apps.contas.urls"))` (importando
`include` de `django.urls`).

- [ ] **Passo 7: Migrar e rodar os testes**

```bash
docker compose exec web python manage.py makemigrations contas
docker compose exec web python manage.py migrate
docker compose exec web pytest apps/contas/tests/test_convites.py -v
```

Esperado: PASSA.

- [ ] **Passo 8: Commit**

```bash
git add -A
git commit -m "Cria convites com token em hash e envio assincrono por Celery"
```

---

## Tarefa 8: Aceitar o convite e criar a conta

**Arquivos:**
- Modificar: `apps/contas/services.py`, `apps/contas/views.py`
- Criar: `apps/contas/forms.py`, `templates/contas/aceitar_convite.html`, `templates/contas/convite_invalido.html`
- Modificar: `conftest.py` (acrescentar a rota à lista `ROTAS`)
- Teste: `apps/contas/tests/test_aceitar_convite.py`

**Interfaces:**
- Consome: `services.convidar` e `Convite` (T7); perfis (T6).
- Produz: `apps.contas.services.aceitar_convite(token, dados) -> Usuario`, onde `dados`
  é um dicionário com `nome_completo`, `cpf`, `telefone`, `senha`, `foto` (opcional) e
  — conforme o papel — `matricula` ou `siape`.
  `apps.contas.forms.FormularioAlunoConvidado` e `FormularioProfessorConvidado`.

- [ ] **Passo 1: Escrever o teste (falhando)**

`apps/contas/tests/test_aceitar_convite.py`:

```python
import hashlib

import pytest
from django.core.exceptions import ValidationError
from django.utils import timezone

from apps.contas import services
from apps.contas.models import Convite, Usuario


@pytest.fixture
def coordenadora(db):
    return Usuario.objects.create_user(
        email="coord@ufsm.br", password="x", nome_completo="Coordenadora",
        cpf="52998224725", is_coordenador=True, is_staff=True,
    )


def cria_convite(coordenadora, papel, email="novo@ufsm.br"):
    """Cria o convite direto no banco para termos o token em claro no teste."""
    token = "token-de-teste-previsivel"
    convite = Convite.objects.create(
        email=email, papel=papel,
        token_hash=hashlib.sha256(token.encode()).hexdigest(),
        criado_por=coordenadora,
        expira_em=timezone.now() + timezone.timedelta(days=7),
    )
    return convite, token


DADOS_ALUNO = {
    "nome_completo": "João Silva",
    "cpf": "16899535009",
    "telefone": "55999990000",
    "senha": "senha-bem-forte-123",
    "matricula": "201910001",
}


@pytest.mark.django_db
def test_aceitar_cria_usuario_e_perfil(coordenadora):
    convite, token = cria_convite(coordenadora, Usuario.ALUNO)

    usuario = services.aceitar_convite(token, DADOS_ALUNO)

    assert usuario.email == "novo@ufsm.br"
    assert usuario.papel == Usuario.ALUNO
    assert usuario.check_password("senha-bem-forte-123")
    assert usuario.perfil_aluno.matricula == "201910001"

    convite.refresh_from_db()
    assert convite.usado_em is not None
    assert convite.usuario_criado == usuario


@pytest.mark.django_db
def test_aceitar_cria_perfil_de_professor(coordenadora):
    convite, token = cria_convite(coordenadora, Usuario.PROFESSOR)
    dados = {**DADOS_ALUNO, "siape": "1234567"}
    del dados["matricula"]

    usuario = services.aceitar_convite(token, dados)

    assert usuario.papel == Usuario.PROFESSOR
    assert usuario.perfil_professor.siape == "1234567"


@pytest.mark.django_db
def test_token_invalido_expirado_e_usado_dao_a_mesma_mensagem(coordenadora):
    convite, token = cria_convite(coordenadora, Usuario.ALUNO)
    services.aceitar_convite(token, DADOS_ALUNO)

    mensagens = []
    for tentativa in ["token-que-nao-existe", token]:
        with pytest.raises(ValidationError) as erro:
            services.aceitar_convite(tentativa, DADOS_ALUNO)
        mensagens.append(str(erro.value))

    assert mensagens[0] == mensagens[1], (
        "Token inexistente e token já usado devem produzir a mesma mensagem: "
        "a diferença entre eles não é informação que o solicitante precise ter."
    )


@pytest.mark.django_db
def test_convite_expirado_e_recusado(coordenadora):
    convite, token = cria_convite(coordenadora, Usuario.ALUNO)
    convite.expira_em = timezone.now() - timezone.timedelta(seconds=1)
    convite.save(update_fields=["expira_em"])

    with pytest.raises(ValidationError):
        services.aceitar_convite(token, DADOS_ALUNO)


@pytest.mark.django_db
def test_falha_no_perfil_nao_deixa_usuario_orfao(coordenadora):
    """A transação é atômica: matrícula duplicada não pode deixar um Usuario solto."""
    primeiro, token_um = cria_convite(coordenadora, Usuario.ALUNO, "um@ufsm.br")
    services.aceitar_convite(token_um, DADOS_ALUNO)

    segundo = Convite.objects.create(
        email="dois@ufsm.br", papel=Usuario.ALUNO,
        token_hash=hashlib.sha256(b"outro-token").hexdigest(),
        criado_por=coordenadora,
        expira_em=timezone.now() + timezone.timedelta(days=7),
    )
    dados = {**DADOS_ALUNO, "cpf": "11144477735"}  # matrícula continua repetida

    with pytest.raises(Exception):
        services.aceitar_convite("outro-token", dados)

    assert not Usuario.objects.filter(email="dois@ufsm.br").exists()
```

- [ ] **Passo 2: Rodar e confirmar que falha**

Executar: `docker compose exec web pytest apps/contas/tests/test_aceitar_convite.py -v`
Esperado: FALHA com `AttributeError: module 'apps.contas.services' has no attribute 'aceitar_convite'`.

- [ ] **Passo 3: Escrever o serviço**

Acrescentar a `apps/contas/services.py`:

```python
MENSAGEM_CONVITE_INVALIDO = "Convite inválido, expirado ou já utilizado."


def busca_convite_valido(token):
    """Devolve o convite válido ou levanta a mensagem genérica.

    Token inexistente, expirado e já usado produzem a MESMA mensagem: distingui-los
    entregaria ao solicitante informação que ele não precisa ter (spec §6.2).
    """
    convite = Convite.objects.filter(token_hash=_hash(token)).first()
    if convite is None or not convite.esta_valido():
        raise ValidationError(MENSAGEM_CONVITE_INVALIDO)
    return convite


@transaction.atomic
def aceitar_convite(token, dados):
    from apps.contas.models import PerfilAluno, PerfilProfessor

    convite = busca_convite_valido(token)

    usuario = Usuario.objects.create_user(
        email=convite.email,
        password=dados["senha"],
        nome_completo=dados["nome_completo"],
        cpf=dados["cpf"],
        telefone=dados.get("telefone", ""),
        papel=convite.papel,
    )
    if dados.get("foto"):
        usuario.foto = dados["foto"]
        usuario.save(update_fields=["foto"])

    if convite.papel == Usuario.ALUNO:
        PerfilAluno.objects.create(usuario=usuario, matricula=dados["matricula"])
    else:
        PerfilProfessor.objects.create(usuario=usuario, siape=dados["siape"])

    convite.usado_em = timezone.now()
    convite.usuario_criado = usuario
    convite.save(update_fields=["usado_em", "usuario_criado"])
    return usuario
```

- [ ] **Passo 4: Escrever os formulários**

`apps/contas/forms.py`:

```python
from django import forms
from django.contrib.auth.password_validation import validate_password

from apps.comum.validators import valida_extensao_imagem, valida_tamanho_arquivo
from apps.contas.validators import valida_cpf


class FormularioConvidado(forms.Form):
    """Campos comuns a aluno e professor no aceite do convite."""

    nome_completo = forms.CharField(label="Nome completo", max_length=200)
    cpf = forms.CharField(label="CPF", max_length=14, validators=[],
                          help_text="Somente números.")
    telefone = forms.CharField(label="Telefone", max_length=20, required=False)
    foto = forms.ImageField(label="Foto", required=False,
                            validators=[valida_extensao_imagem, valida_tamanho_arquivo])
    senha = forms.CharField(label="Senha", widget=forms.PasswordInput, strip=False)
    senha_confirmacao = forms.CharField(label="Confirme a senha",
                                        widget=forms.PasswordInput, strip=False)

    def clean_cpf(self):
        cpf = "".join(c for c in self.cleaned_data["cpf"] if c.isdigit())
        valida_cpf(cpf)
        return cpf

    def clean(self):
        limpos = super().clean()
        senha, confirmacao = limpos.get("senha"), limpos.get("senha_confirmacao")
        if senha and confirmacao and senha != confirmacao:
            self.add_error("senha_confirmacao", "As senhas não conferem.")
        if senha:
            validate_password(senha)
        return limpos


class FormularioAlunoConvidado(FormularioConvidado):
    matricula = forms.CharField(label="Matrícula", max_length=20)


class FormularioProfessorConvidado(FormularioConvidado):
    siape = forms.CharField(label="SIAPE", max_length=20)
```

- [ ] **Passo 5: Escrever a view e os templates**

`apps/contas/views.py` (substituindo a view mínima da Tarefa 7):

```python
from django.contrib import messages
from django.contrib.auth import login
from django.core.exceptions import ValidationError
from django.shortcuts import redirect, render

from apps.contas import services
from apps.contas.forms import FormularioAlunoConvidado, FormularioProfessorConvidado
from apps.contas.models import Usuario


def aceitar_convite(request, token):
    try:
        convite = services.busca_convite_valido(token)
    except ValidationError as erro:
        return render(request, "contas/convite_invalido.html", {"mensagem": erro.messages[0]},
                      status=404)

    Formulario = (
        FormularioAlunoConvidado if convite.papel == Usuario.ALUNO
        else FormularioProfessorConvidado
    )
    formulario = Formulario(request.POST or None, request.FILES or None)

    if request.method == "POST" and formulario.is_valid():
        try:
            usuario = services.aceitar_convite(token, formulario.cleaned_data)
        except ValidationError as erro:
            formulario.add_error(None, erro.messages[0])
        else:
            login(request, usuario)
            messages.success(request, "Cadastro concluído. Bem-vindo(a) ao OrientaSI.")
            return redirect("inicio")

    return render(request, "contas/aceitar_convite.html",
                  {"formulario": formulario, "convite": convite})
```

`templates/contas/aceitar_convite.html`:

```html
{% extends "base.html" %}

{% block titulo %} — Concluir cadastro{% endblock %}

{% block conteudo %}
  <article class="mx-auto max-w-xl rounded-box bg-base-100 p-6 shadow-sm">
    <h1 class="font-display text-2xl font-bold text-primary">Concluir cadastro</h1>
    <p class="mt-2">
      Convite para <strong>{{ convite.email }}</strong>
      como {{ convite.get_papel_display|lower }}.
    </p>

    <form method="post" enctype="multipart/form-data" class="mt-6 space-y-4" novalidate>
      {% csrf_token %}

      {% if formulario.non_field_errors %}
        <div role="alert" class="alert alert-error">
          {% for erro in formulario.non_field_errors %}<p>{{ erro }}</p>{% endfor %}
        </div>
      {% endif %}

      {% for campo in formulario %}
        <div class="form-control">
          <label class="label" for="{{ campo.id_for_label }}">
            <span class="label-text">
              {{ campo.label }}{% if campo.field.required %} <span aria-hidden="true">*</span>
              <span class="sr-only">(obrigatório)</span>{% endif %}
            </span>
          </label>
          {{ campo }}
          {% if campo.help_text %}
            <p id="ajuda-{{ campo.name }}" class="mt-1 text-sm text-base-content/80">
              {{ campo.help_text }}
            </p>
          {% endif %}
          {% for erro in campo.errors %}
            <p role="alert" class="mt-1 text-sm text-error">{{ erro }}</p>
          {% endfor %}
        </div>
      {% endfor %}

      <button type="submit" class="btn btn-primary w-full">Concluir cadastro</button>
    </form>
  </article>
{% endblock %}
```

`templates/contas/convite_invalido.html`:

```html
{% extends "base.html" %}

{% block titulo %} — Convite inválido{% endblock %}

{% block conteudo %}
  <article class="mx-auto max-w-xl rounded-box bg-base-100 p-6 shadow-sm">
    <h1 class="font-display text-2xl font-bold text-primary">Convite inválido</h1>
    <p class="mt-4">{{ mensagem }}</p>
    <p class="mt-2">Peça à coordenação do curso o reenvio do convite.</p>
    <a href="{% url 'inicio' %}" class="btn btn-primary mt-6">Voltar ao início</a>
  </article>
{% endblock %}
```

Para que os campos do formulário recebam as classes do DaisyUI, acrescentar ao final
de `apps/contas/forms.py`:

```python
CLASSES = {
    forms.TextInput: "input input-bordered w-full",
    forms.EmailInput: "input input-bordered w-full",
    forms.PasswordInput: "input input-bordered w-full",
    forms.ClearableFileInput: "file-input file-input-bordered w-full",
}


def aplica_estilo(formulario):
    for campo in formulario.fields.values():
        classe = CLASSES.get(type(campo.widget))
        if classe:
            campo.widget.attrs.setdefault("class", classe)
```

E chamá-la no `__init__` de `FormularioConvidado`:

```python
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        aplica_estilo(self)
```

- [ ] **Passo 6: Acrescentar a rota à lista da suíte de acessibilidade**

Em `conftest.py`, a página de convite precisa de um convite existente para responder
200. Trocar a lista fixa por uma fixture que semeia o convite:

```python
import hashlib

import pytest
from django.utils import timezone

ROTAS = ["/", "/convite/rota-para-teste-de-acessibilidade/"]


@pytest.fixture
def convite_das_rotas(db):
    """A rota de convite da suíte precisa de um convite válido para responder 200.

    NÃO é autouse: se fosse, o usuário que ela cria colidiria em CPF e e-mail com as
    fixtures de apps/contas/tests/, e a suíte inteira quebraria por IntegrityError.
    Só quem pede `rota` recebe esta semeadura.
    """
    from apps.contas.models import Convite, Usuario

    coordenadora = Usuario.objects.create_user(
        email="coord-das-rotas@ufsm.br", password="x", nome_completo="Coordenação",
        cpf="39053344705", is_coordenador=True, is_staff=True,
    )
    Convite.objects.create(
        email="convidado-fixture@ufsm.br",
        papel=Usuario.ALUNO,
        token_hash=hashlib.sha256(b"rota-para-teste-de-acessibilidade").hexdigest(),
        criado_por=coordenadora,
        expira_em=timezone.now() + timezone.timedelta(days=7),
    )


@pytest.fixture(params=ROTAS)
def rota(request, convite_das_rotas):
    return request.param
```

A fixture `midia_temporaria` da Tarefa 1 permanece no arquivo, inalterada: este passo
acrescenta, não substitui.

- [ ] **Passo 7: Rodar a suíte inteira**

Executar: `docker compose exec web pytest -v`
Esperado: tudo PASSA, incluindo acessibilidade, toque, responsividade e teclado na
página nova de convite. Se o axe apontar `label` ou `form-field-multiple-labels`,
o defeito está no template — corrija o HTML, não o teste.

- [ ] **Passo 8: Commit**

```bash
git add -A
git commit -m "Permite concluir o cadastro pelo link do convite"
```

---

## Tarefa 9: Login, logout e recuperação de senha

**Arquivos:**
- Modificar: `config/urls.py`, `config/settings.py`, `templates/base.html`
- Criar: `templates/registration/login.html`, `templates/registration/password_reset_form.html`, `templates/registration/password_reset_done.html`, `templates/registration/password_reset_confirm.html`, `templates/registration/password_reset_complete.html`, `templates/registration/password_reset_email.html`
- Modificar: `conftest.py`
- Teste: `apps/contas/tests/test_autenticacao.py`

**Interfaces:**
- Consome: `Usuario` (T1), `base.html` (T4).
- Produz: rotas nomeadas `login`, `logout`, `password_reset`, `password_reset_done`,
  `password_reset_confirm`, `password_reset_complete`; `settings.LOGIN_URL`,
  `LOGIN_REDIRECT_URL`, `LOGOUT_REDIRECT_URL`.

- [ ] **Passo 1: Escrever o teste (falhando)**

`apps/contas/tests/test_autenticacao.py`:

```python
import pytest
from django.core import mail
from django.urls import reverse

from apps.contas.models import Usuario


@pytest.fixture
def professora(db):
    return Usuario.objects.create_user(
        email="ana@ufsm.br", password="senha-bem-forte-123", nome_completo="Ana",
        cpf="52998224725",
    )


@pytest.mark.django_db
def test_login_com_email_e_senha(client, professora):
    resposta = client.post(
        reverse("login"), {"username": "ana@ufsm.br", "password": "senha-bem-forte-123"}
    )
    assert resposta.status_code == 302
    assert client.session.get("_auth_user_id") == str(professora.pk)


@pytest.mark.django_db
def test_login_recusa_senha_errada(client, professora):
    resposta = client.post(reverse("login"), {"username": "ana@ufsm.br", "password": "errada"})
    assert resposta.status_code == 200
    assert "_auth_user_id" not in client.session


@pytest.mark.django_db
def test_logout_encerra_a_sessao(client, professora):
    client.force_login(professora)
    client.post(reverse("logout"))
    assert "_auth_user_id" not in client.session


@pytest.mark.django_db
def test_recuperacao_de_senha_envia_email(client, professora):
    resposta = client.post(reverse("password_reset"), {"email": "ana@ufsm.br"})
    assert resposta.status_code == 302
    assert len(mail.outbox) == 1
    assert "ana@ufsm.br" in mail.outbox[0].to
```

- [ ] **Passo 2: Rodar e confirmar que falha**

Executar: `docker compose exec web pytest apps/contas/tests/test_autenticacao.py -v`
Esperado: FALHA com `NoReverseMatch: Reverse for 'login' not found`.

- [ ] **Passo 3: Registrar as rotas de autenticação**

Em `config/urls.py`, acrescentar `path("contas/", include("django.contrib.auth.urls"))`.

Em `config/settings.py`, acrescentar:

```python
LOGIN_URL = "/contas/login/"
LOGIN_REDIRECT_URL = "/"
LOGOUT_REDIRECT_URL = "/"
```

- [ ] **Passo 4: Escrever os templates de autenticação**

`templates/registration/login.html`:

```html
{% extends "base.html" %}

{% block titulo %} — Entrar{% endblock %}

{% block conteudo %}
  <article class="mx-auto max-w-md rounded-box bg-base-100 p-6 shadow-sm">
    <h1 class="font-display text-2xl font-bold text-primary">Entrar</h1>

    <form method="post" class="mt-6 space-y-4" novalidate>
      {% csrf_token %}

      {% if form.non_field_errors %}
        <div role="alert" class="alert alert-error">
          {% for erro in form.non_field_errors %}<p>{{ erro }}</p>{% endfor %}
        </div>
      {% endif %}

      <div class="form-control">
        <label class="label" for="{{ form.username.id_for_label }}">
          <span class="label-text">E-mail</span>
        </label>
        <input type="email" name="username" id="{{ form.username.id_for_label }}"
               autocomplete="username" required class="input input-bordered w-full">
      </div>

      <div class="form-control">
        <label class="label" for="{{ form.password.id_for_label }}">
          <span class="label-text">Senha</span>
        </label>
        <input type="password" name="password" id="{{ form.password.id_for_label }}"
               autocomplete="current-password" required class="input input-bordered w-full">
      </div>

      <button type="submit" class="btn btn-primary w-full">Entrar</button>
    </form>

    <a href="{% url 'password_reset' %}" class="link mt-4 inline-block">Esqueci minha senha</a>
  </article>
{% endblock %}
```

Os quatro templates de recuperação seguem o mesmo padrão: `{% extends "base.html" %}`,
um `<h1>` dentro de `<article>`, o formulário com `{% csrf_token %}` e rótulos
associados por `for`/`id`. `password_reset_form.html` renderiza `form.email`;
`password_reset_confirm.html` renderiza `form.new_password1` e `form.new_password2`;
`password_reset_done.html` e `password_reset_complete.html` exibem só um parágrafo de
confirmação e um link para `{% url 'login' %}`.

`templates/registration/password_reset_email.html`:

```
Olá,

Recebemos um pedido de redefinição de senha para sua conta no OrientaSI.

Acesse o endereço abaixo para escolher uma nova senha:

{{ protocol }}://{{ domain }}{% url 'password_reset_confirm' uidb64=uid token=token %}

Se não foi você quem pediu, ignore esta mensagem: sua senha continua a mesma.

OrientaSI — Sistema de Gestão de TCC
```

- [ ] **Passo 5: Acrescentar a navegação ao `base.html`**

Substituir o bloco `{% block navegacao %}{% endblock %}` por:

```html
{% block navegacao %}
  <ul class="flex items-center gap-2">
    {% if user.is_authenticated %}
      <li><span class="px-2">{{ user.nome_completo }}</span></li>
      <li>
        <form method="post" action="{% url 'logout' %}">
          {% csrf_token %}
          <button type="submit" class="btn btn-ghost">Sair</button>
        </form>
      </li>
    {% else %}
      <li><a href="{% url 'login' %}" class="btn btn-primary">Entrar</a></li>
    {% endif %}
  </ul>
{% endblock %}
```

E, em `templates/inicio.html`, trocar `{% url 'admin:index' %}` por `{% url 'login' %}`.

- [ ] **Passo 6: Acrescentar as rotas à suíte**

Em `conftest.py`, `ROTAS` passa a:

```python
ROTAS = [
    "/",
    "/convite/rota-para-teste-de-acessibilidade/",
    "/contas/login/",
    "/contas/password_reset/",
]
```

- [ ] **Passo 7: Rodar a suíte inteira**

Executar: `docker compose exec web pytest -v`
Esperado: tudo PASSA.

- [ ] **Passo 8: Commit**

```bash
git add -A
git commit -m "Adiciona login, logout e recuperacao de senha"
```

---

## Tarefa 10: Painel de perfil

**Arquivos:**
- Modificar: `apps/contas/views.py`, `apps/contas/urls.py`, `apps/contas/forms.py`, `apps/contas/services.py`
- Criar: `templates/contas/perfil.html`
- Teste: `apps/contas/tests/test_perfil_view.py`

**Interfaces:**
- Consome: `PerfilProfessor`, `Area` (T6); `login` (T9).
- Produz: rota nomeada `contas:perfil`;
  `apps.contas.services.atualiza_perfil(usuario, telefone, areas=None, foto=None)`;
  `apps.contas.forms.FormularioPerfilProfessor`.

- [ ] **Passo 1: Escrever o teste (falhando)**

`apps/contas/tests/test_perfil_view.py`:

```python
import pytest
from django.urls import reverse

from apps.contas.models import Area, PerfilProfessor, Usuario


@pytest.fixture
def professora(db):
    usuario = Usuario.objects.create_user(
        email="ana@ufsm.br", password="senha-bem-forte-123", nome_completo="Ana",
        cpf="52998224725",
    )
    PerfilProfessor.objects.create(usuario=usuario, siape="1234567")
    return usuario


@pytest.mark.django_db
def test_perfil_exige_autenticacao(client):
    resposta = client.get(reverse("contas:perfil"))
    assert resposta.status_code == 302
    assert "/contas/login/" in resposta.url


@pytest.mark.django_db
def test_professor_seleciona_suas_areas(client, professora):
    ia = Area.objects.create(nome="Inteligência Artificial")
    redes = Area.objects.create(nome="Redes")
    client.force_login(professora)

    resposta = client.post(
        reverse("contas:perfil"),
        {"telefone": "55999990000", "areas": [ia.pk, redes.pk]},
    )

    assert resposta.status_code == 302
    professora.refresh_from_db()
    assert set(professora.perfil_professor.areas.all()) == {ia, redes}
    assert professora.telefone == "55999990000"


@pytest.mark.django_db
def test_aluno_nao_ve_campo_de_areas(client, db):
    aluno = Usuario.objects.create_user(
        email="joao@ufsm.br", password="senha-bem-forte-123", nome_completo="João",
        cpf="16899535009", papel=Usuario.ALUNO,
    )
    client.force_login(aluno)
    html = client.get(reverse("contas:perfil")).content.decode()
    assert "areas" not in html
```

- [ ] **Passo 2: Rodar e confirmar que falha**

Executar: `docker compose exec web pytest apps/contas/tests/test_perfil_view.py -v`
Esperado: FALHA com `NoReverseMatch: Reverse for 'perfil' not found`.

- [ ] **Passo 3: Escrever o serviço, o formulário e a view**

Acrescentar a `apps/contas/services.py`:

```python
@transaction.atomic
def atualiza_perfil(usuario, telefone, areas=None, foto=None):
    """Atualiza os dados que a própria pessoa mantém sobre si."""
    usuario.telefone = telefone
    campos = ["telefone"]
    if foto:
        usuario.foto = foto
        campos.append("foto")
    usuario.save(update_fields=campos)

    if areas is not None and usuario.papel == Usuario.PROFESSOR:
        usuario.perfil_professor.areas.set(areas)
    return usuario
```

Acrescentar a `apps/contas/forms.py`:

```python
from apps.contas.models import Area


class FormularioPerfil(forms.Form):
    telefone = forms.CharField(label="Telefone", max_length=20, required=False)
    foto = forms.ImageField(label="Foto", required=False,
                            validators=[valida_extensao_imagem, valida_tamanho_arquivo])

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        aplica_estilo(self)


class FormularioPerfilProfessor(FormularioPerfil):
    areas = forms.ModelMultipleChoiceField(
        label="Áreas de atuação",
        queryset=Area.objects.all(),
        required=False,
        widget=forms.CheckboxSelectMultiple,
    )
```

Acrescentar a `apps/contas/views.py`:

```python
from django.contrib.auth.decorators import login_required

from apps.contas.forms import FormularioPerfil, FormularioPerfilProfessor


@login_required
def perfil(request):
    e_professor = request.user.papel == Usuario.PROFESSOR
    Formulario = FormularioPerfilProfessor if e_professor else FormularioPerfil

    if request.method == "POST":
        formulario = Formulario(request.POST, request.FILES)
        if formulario.is_valid():
            services.atualiza_perfil(
                request.user,
                telefone=formulario.cleaned_data["telefone"],
                areas=formulario.cleaned_data.get("areas"),
                foto=formulario.cleaned_data.get("foto"),
            )
            messages.success(request, "Perfil atualizado.")
            return redirect("contas:perfil")
    else:
        inicial = {"telefone": request.user.telefone}
        if e_professor:
            inicial["areas"] = request.user.perfil_professor.areas.all()
        formulario = Formulario(initial=inicial)

    return render(request, "contas/perfil.html", {"formulario": formulario})
```

Em `apps/contas/urls.py`, acrescentar:

```python
    path("perfil/", views.perfil, name="perfil"),
```

- [ ] **Passo 4: Escrever o template**

`templates/contas/perfil.html`:

```html
{% extends "base.html" %}

{% block titulo %} — Meu perfil{% endblock %}

{% block conteudo %}
  <article class="mx-auto max-w-xl rounded-box bg-base-100 p-6 shadow-sm">
    <h1 class="font-display text-2xl font-bold text-primary">Meu perfil</h1>
    <p class="mt-2">{{ user.nome_completo }} — {{ user.email }}</p>

    <form method="post" enctype="multipart/form-data" class="mt-6 space-y-4" novalidate>
      {% csrf_token %}

      {% for campo in formulario %}
        {% if campo.name == "areas" %}
          <fieldset class="form-control">
            <legend class="label-text mb-2">{{ campo.label }}</legend>
            {{ campo }}
            {% for erro in campo.errors %}
              <p role="alert" class="mt-1 text-sm text-error">{{ erro }}</p>
            {% endfor %}
          </fieldset>
        {% else %}
          <div class="form-control">
            <label class="label" for="{{ campo.id_for_label }}">
              <span class="label-text">{{ campo.label }}</span>
            </label>
            {{ campo }}
            {% for erro in campo.errors %}
              <p role="alert" class="mt-1 text-sm text-error">{{ erro }}</p>
            {% endfor %}
          </div>
        {% endif %}
      {% endfor %}

      <button type="submit" class="btn btn-primary">Salvar</button>
    </form>
  </article>
{% endblock %}
```

O grupo de caixas de seleção vai dentro de `<fieldset>` com `<legend>`: sem isso o
axe aponta que os controles não têm rótulo de grupo, e um leitor de tela anuncia as
opções sem dizer a que pergunta elas respondem.

- [ ] **Passo 5: Rodar os testes**

Executar: `docker compose exec web pytest apps/contas/tests/ -v`
Esperado: PASSA.

- [ ] **Passo 6: Commit**

```bash
git add -A
git commit -m "Adiciona o painel de perfil com selecao de areas do professor"
```

---

## Tarefa 11: Coordenação — promover, revogar e o painel

**Arquivos:**
- Modificar: `apps/contas/services.py`, `apps/contas/views.py`, `apps/contas/urls.py`, `apps/contas/forms.py`
- Criar: `templates/contas/painel_coordenacao.html`, `templates/contas/_lista_convites.html`
- Modificar: `conftest.py`
- Teste: `apps/contas/tests/test_coordenacao.py`

**Interfaces:**
- Consome: `services.convidar`, `permissions` (T7).
- Produz: `apps.contas.services.LIMITE_COORDENADORES = 4`;
  `promover_a_coordenador(usuario, por) -> Usuario`;
  `revogar_coordenacao(usuario, por) -> Usuario`; rota nomeada `contas:painel`.

- [ ] **Passo 1: Escrever o teste (falhando)**

`apps/contas/tests/test_coordenacao.py`:

```python
import pytest
from django.core.exceptions import PermissionDenied, ValidationError

from apps.contas import services
from apps.contas.models import Usuario

CPFS = ["52998224725", "16899535009", "11144477735", "12345678909", "98765432100", "39053344705"]


def cria_professor(indice, coordenador=False):
    return Usuario.objects.create_user(
        email=f"prof{indice}@ufsm.br", password="x", nome_completo=f"Professor {indice}",
        cpf=CPFS[indice], is_coordenador=coordenador, is_staff=coordenador,
    )


@pytest.mark.django_db
def test_promover_marca_coordenador_e_staff():
    coordenadora = cria_professor(0, coordenador=True)
    alvo = cria_professor(1)

    services.promover_a_coordenador(alvo, por=coordenadora)

    alvo.refresh_from_db()
    assert alvo.is_coordenador is True
    assert alvo.is_staff is True


@pytest.mark.django_db
def test_quinta_promocao_e_recusada():
    coordenadores = [cria_professor(i, coordenador=True) for i in range(4)]
    quinto = cria_professor(4)

    with pytest.raises(ValidationError) as erro:
        services.promover_a_coordenador(quinto, por=coordenadores[0])

    assert "4" in str(erro.value)
    quinto.refresh_from_db()
    assert quinto.is_coordenador is False


@pytest.mark.django_db
def test_aluno_nao_pode_ser_promovido():
    coordenadora = cria_professor(0, coordenador=True)
    aluno = Usuario.objects.create_user(
        email="joao@ufsm.br", password="x", nome_completo="João",
        cpf=CPFS[1], papel=Usuario.ALUNO,
    )

    with pytest.raises(ValidationError):
        services.promover_a_coordenador(aluno, por=coordenadora)


@pytest.mark.django_db
def test_ultimo_coordenador_nao_pode_ser_revogado():
    unica = cria_professor(0, coordenador=True)

    with pytest.raises(ValidationError) as erro:
        services.revogar_coordenacao(unica, por=unica)

    assert "outro" in str(erro.value).lower()
    unica.refresh_from_db()
    assert unica.is_coordenador is True


@pytest.mark.django_db
def test_revogar_funciona_havendo_outro_coordenador():
    primeira = cria_professor(0, coordenador=True)
    segunda = cria_professor(1, coordenador=True)

    services.revogar_coordenacao(segunda, por=primeira)

    segunda.refresh_from_db()
    assert segunda.is_coordenador is False
    assert segunda.is_staff is False


@pytest.mark.django_db
def test_professor_comum_nao_promove():
    comum = cria_professor(0)
    alvo = cria_professor(1)

    with pytest.raises(PermissionDenied):
        services.promover_a_coordenador(alvo, por=comum)
```

- [ ] **Passo 2: Rodar e confirmar que falha**

Executar: `docker compose exec web pytest apps/contas/tests/test_coordenacao.py -v`
Esperado: FALHA com `AttributeError: module 'apps.contas.services' has no attribute 'promover_a_coordenador'`.

- [ ] **Passo 3: Escrever os serviços**

Acrescentar a `apps/contas/services.py`:

```python
LIMITE_COORDENADORES = 4


@transaction.atomic
def promover_a_coordenador(usuario, por):
    """Aplica o teto de coordenadores sob bloqueio de linha.

    O select_for_update não é decoração: promover é um UPDATE de uma linha que passa
    a integrar o próprio conjunto travado, de modo que duas promoções simultâneas se
    serializam e a segunda relê a contagem já atualizada. Sem ele, dois cliques
    concorrentes ultrapassam o limite (spec §6.3).
    """
    permissions.garante(permissions.pode_promover(por), "Somente a coordenação promove.")

    if usuario.papel != Usuario.PROFESSOR:
        raise ValidationError("Somente professores podem ser coordenadores.")
    if usuario.is_coordenador:
        raise ValidationError(f"{usuario.nome_completo} já é coordenador(a).")

    atuais = list(Usuario.objects.select_for_update().filter(is_coordenador=True))
    if len(atuais) >= LIMITE_COORDENADORES:
        raise ValidationError(
            f"O sistema admite no máximo {LIMITE_COORDENADORES} coordenadores. "
            "Revogue a coordenação de alguém antes de nomear outra pessoa."
        )

    usuario.is_coordenador = True
    usuario.is_staff = True
    usuario.save(update_fields=["is_coordenador", "is_staff"])
    return usuario


@transaction.atomic
def revogar_coordenacao(usuario, por):
    permissions.garante(permissions.pode_promover(por), "Somente a coordenação revoga.")

    if not usuario.is_coordenador:
        raise ValidationError(f"{usuario.nome_completo} não é coordenador(a).")

    atuais = list(Usuario.objects.select_for_update().filter(is_coordenador=True))
    if len(atuais) <= 1:
        raise ValidationError(
            "Este é o último coordenador do sistema. Nomeie outro antes de revogar "
            "esta coordenação."
        )

    usuario.is_coordenador = False
    usuario.is_staff = False
    usuario.save(update_fields=["is_coordenador", "is_staff"])
    return usuario
```

- [ ] **Passo 4: Escrever o painel**

Acrescentar a `apps/contas/forms.py`:

```python
class FormularioConvite(forms.Form):
    email = forms.EmailField(label="E-mail")
    papel = forms.ChoiceField(
        label="Papel",
        choices=[(Usuario.ALUNO, "Aluno"), (Usuario.PROFESSOR, "Professor")],
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        aplica_estilo(self)
        self.fields["papel"].widget.attrs.setdefault("class", "select select-bordered w-full")
```

Isso exige `from apps.contas.models import Area, Usuario` no topo de `forms.py`.

Acrescentar a `apps/contas/views.py`:

```python
from django.core.exceptions import PermissionDenied

from apps.contas import permissions
from apps.contas.forms import FormularioConvite
from apps.contas.models import Convite


@login_required
def painel(request):
    if not permissions.pode_convidar(request.user):
        raise PermissionDenied("Esta área é exclusiva da coordenação.")

    formulario = FormularioConvite(request.POST or None)
    if request.method == "POST" and formulario.is_valid():
        try:
            services.convidar(
                formulario.cleaned_data["email"], formulario.cleaned_data["papel"],
                por=request.user,
            )
        except ValidationError as erro:
            formulario.add_error("email", erro.messages[0])
        else:
            messages.success(request, "Convite enviado.")
            return redirect("contas:painel")

    return render(request, "contas/painel_coordenacao.html", {
        "formulario": formulario,
        "convites": Convite.objects.select_related("criado_por")[:50],
        "coordenadores": Usuario.objects.filter(is_coordenador=True),
        "limite": services.LIMITE_COORDENADORES,
    })
```

Em `apps/contas/urls.py`, acrescentar `path("painel/", views.painel, name="painel")`.

`templates/contas/painel_coordenacao.html`:

```html
{% extends "base.html" %}

{% block titulo %} — Coordenação{% endblock %}

{% block conteudo %}
  <h1 class="font-display text-2xl font-bold text-primary">Painel da coordenação</h1>

  <section aria-labelledby="titulo-convidar" class="mt-6 rounded-box bg-base-100 p-6 shadow-sm">
    <h2 id="titulo-convidar" class="font-display text-xl font-semibold">Convidar</h2>
    <form method="post" class="mt-4 space-y-4" novalidate>
      {% csrf_token %}
      {% for campo in formulario %}
        <div class="form-control">
          <label class="label" for="{{ campo.id_for_label }}">
            <span class="label-text">{{ campo.label }}</span>
          </label>
          {{ campo }}
          {% for erro in campo.errors %}
            <p role="alert" class="mt-1 text-sm text-error">{{ erro }}</p>
          {% endfor %}
        </div>
      {% endfor %}
      <button type="submit" class="btn btn-primary">Enviar convite</button>
    </form>
  </section>

  <section aria-labelledby="titulo-coordenadores"
           class="mt-6 rounded-box bg-base-100 p-6 shadow-sm">
    <h2 id="titulo-coordenadores" class="font-display text-xl font-semibold">
      Coordenadores ({{ coordenadores|length }} de {{ limite }})
    </h2>
    <ul class="mt-4 space-y-2">
      {% for pessoa in coordenadores %}
        <li>{{ pessoa.nome_completo }} — {{ pessoa.email }}</li>
      {% endfor %}
    </ul>
  </section>

  <section aria-labelledby="titulo-convites" class="mt-6 rounded-box bg-base-100 p-6 shadow-sm">
    <h2 id="titulo-convites" class="font-display text-xl font-semibold">Convites enviados</h2>
    <div class="mt-4 overflow-x-auto">
      <table class="table">
        <caption class="sr-only">Convites enviados, do mais recente ao mais antigo</caption>
        <thead>
          <tr>
            <th scope="col">E-mail</th>
            <th scope="col">Papel</th>
            <th scope="col">Situação</th>
          </tr>
        </thead>
        <tbody>
          {% for convite in convites %}
            <tr>
              <td>{{ convite.email }}</td>
              <td>{{ convite.get_papel_display }}</td>
              <td>
                {% if convite.usado_em %}Aceito
                {% elif convite.esta_valido %}Pendente
                {% else %}Expirado{% endif %}
              </td>
            </tr>
          {% empty %}
            <tr><td colspan="3">Nenhum convite enviado ainda.</td></tr>
          {% endfor %}
        </tbody>
      </table>
    </div>
  </section>
{% endblock %}
```

A tabela vai dentro de um contêiner com `overflow-x: auto` para não forçar rolagem
horizontal na página a 360px — é isso que `test_responsivo.py` verifica.

- [ ] **Passo 5: Escrever o teste da view do painel**

Acrescentar a `apps/contas/tests/test_coordenacao.py`:

```python
from django.urls import reverse


@pytest.mark.django_db
def test_painel_recusa_quem_nao_e_coordenador(client):
    comum = cria_professor(0)
    client.force_login(comum)
    assert client.get(reverse("contas:painel")).status_code == 403


@pytest.mark.django_db
def test_painel_envia_convite(client, settings, django_capture_on_commit_callbacks):
    settings.CELERY_TASK_ALWAYS_EAGER = True
    coordenadora = cria_professor(0, coordenador=True)
    client.force_login(coordenadora)

    with django_capture_on_commit_callbacks(execute=True):
        resposta = client.post(
            reverse("contas:painel"), {"email": "novo@ufsm.br", "papel": Usuario.PROFESSOR}
        )

    assert resposta.status_code == 302
    assert Usuario.objects.filter(email="novo@ufsm.br").count() == 0
    from apps.contas.models import Convite

    assert Convite.objects.filter(email="novo@ufsm.br").exists()
```

- [ ] **Passo 6: Rodar os testes**

Executar: `docker compose exec web pytest apps/contas/tests/ -v`
Esperado: PASSA.

- [ ] **Passo 7: Commit**

```bash
git add -A
git commit -m "Aplica o teto de 4 coordenadores e a trava do ultimo coordenador"
```

---

## Tarefa 12: Comando `semear_sistema`

**Arquivos:**
- Criar: `apps/contas/management/__init__.py`, `apps/contas/management/commands/__init__.py`, `apps/contas/management/commands/semear_sistema.py`
- Teste: `apps/contas/tests/test_semear.py`

**Interfaces:**
- Consome: `Usuario` (T1).
- Produz: o comando `semear_sistema`, com as opções `--email-coordenador`,
  `--nome-coordenador`, `--cpf-coordenador` e `--email-sugrad`.

- [ ] **Passo 1: Escrever o teste (falhando)**

`apps/contas/tests/test_semear.py`:

```python
import pytest
from django.core.management import call_command

from apps.contas.models import Usuario

ARGUMENTOS = [
    "--email-coordenador", "coord@ufsm.br",
    "--nome-coordenador", "Coordenação do Curso",
    "--cpf-coordenador", "52998224725",
    "--email-sugrad", "sugrad@ufsm.br",
]


@pytest.mark.django_db
def test_semear_cria_sugrad_e_coordenador():
    call_command("semear_sistema", *ARGUMENTOS)

    coordenadora = Usuario.objects.get(email="coord@ufsm.br")
    assert coordenadora.is_coordenador is True
    assert coordenadora.is_staff is True
    assert coordenadora.papel == Usuario.PROFESSOR

    sugrad = Usuario.objects.get(email="sugrad@ufsm.br")
    assert sugrad.papel == Usuario.SUGRAD
    assert sugrad.cpf is None


@pytest.mark.django_db
def test_semear_e_idempotente():
    call_command("semear_sistema", *ARGUMENTOS)
    call_command("semear_sistema", *ARGUMENTOS)

    assert Usuario.objects.filter(email="coord@ufsm.br").count() == 1
    assert Usuario.objects.filter(papel=Usuario.SUGRAD).count() == 1


@pytest.mark.django_db
def test_semear_nao_rebaixa_quem_ja_e_coordenador():
    call_command("semear_sistema", *ARGUMENTOS)
    outra = Usuario.objects.create_user(
        email="outra@ufsm.br", password="x", nome_completo="Outra",
        cpf="16899535009", is_coordenador=True, is_staff=True,
    )

    call_command("semear_sistema", *ARGUMENTOS)

    outra.refresh_from_db()
    assert outra.is_coordenador is True
```

- [ ] **Passo 2: Rodar e confirmar que falha**

Executar: `docker compose exec web pytest apps/contas/tests/test_semear.py -v`
Esperado: FALHA com `CommandError: Unknown command: 'semear_sistema'`.

- [ ] **Passo 3: Escrever o comando**

`apps/contas/management/commands/semear_sistema.py`:

```python
import secrets

from django.core.management.base import BaseCommand
from django.db import transaction

from apps.contas.models import Usuario


class Command(BaseCommand):
    help = (
        "Cria a conta única da SUGRAD e o primeiro coordenador. Resolve o "
        "ovo-e-galinha de 'o coordenador envia os convites'. É idempotente."
    )

    def add_arguments(self, parser):
        parser.add_argument("--email-coordenador", required=True)
        parser.add_argument("--nome-coordenador", required=True)
        parser.add_argument("--cpf-coordenador", required=True)
        parser.add_argument("--email-sugrad", required=True)

    @transaction.atomic
    def handle(self, *args, **opcoes):
        sugrad, criada = Usuario.objects.get_or_create(
            papel=Usuario.SUGRAD,
            defaults={
                "email": opcoes["email_sugrad"],
                "nome_completo": "SUGRAD",
                "cpf": None,
                "password": "",
            },
        )
        if criada:
            senha = secrets.token_urlsafe(16)
            sugrad.set_password(senha)
            sugrad.save(update_fields=["password"])
            self.stdout.write(self.style.SUCCESS(f"Conta SUGRAD criada: {sugrad.email}"))
            self.stdout.write(f"Senha inicial da SUGRAD: {senha}")
            self.stdout.write("Anote-a agora: ela não será exibida de novo.")
        else:
            self.stdout.write(f"Conta SUGRAD já existe: {sugrad.email}")

        coordenadora, criada = Usuario.objects.get_or_create(
            email=opcoes["email_coordenador"],
            defaults={
                "nome_completo": opcoes["nome_coordenador"],
                "cpf": opcoes["cpf_coordenador"],
                "papel": Usuario.PROFESSOR,
            },
        )
        if criada:
            senha = secrets.token_urlsafe(16)
            coordenadora.set_password(senha)
            coordenadora.save(update_fields=["password"])
            self.stdout.write(f"Senha inicial da coordenação: {senha}")

        if not coordenadora.is_coordenador:
            coordenadora.is_coordenador = True
            coordenadora.is_staff = True
            coordenadora.save(update_fields=["is_coordenador", "is_staff"])
            self.stdout.write(
                self.style.SUCCESS(f"{coordenadora.email} agora é coordenador(a).")
            )
        else:
            self.stdout.write(f"{coordenadora.email} já era coordenador(a).")
```

- [ ] **Passo 4: Rodar os testes**

Executar: `docker compose exec web pytest apps/contas/tests/test_semear.py -v`
Esperado: PASSA.

- [ ] **Passo 5: Commit**

```bash
git add -A
git commit -m "Adiciona o comando semear_sistema para a conta SUGRAD e o primeiro coordenador"
```

---

## Tarefa 13: Atualizar o `CLAUDE.md`

**Arquivos:**
- Modificar: `CLAUDE.md`
- Criar: `README.md`
- Teste: `tests/test_documentacao.py`

**Interfaces:**
- Consome: a estrutura consolidada nas Tarefas 1–12.
- Produz: nenhuma interface de código.

- [ ] **Passo 1: Escrever o teste (falhando)**

`tests/test_documentacao.py`:

```python
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
CLAUDE = (RAIZ / "CLAUDE.md").read_text(encoding="utf-8")


def test_claude_md_nao_tem_markdown_escapado():
    """O arquivo veio de uma exportação que escapou o markdown: \\#\\# e \\*\\*."""
    for escapado in ["\\#", "\\*", "\\`"]:
        assert escapado not in CLAUDE, (
            f"CLAUDE.md contém markdown escapado ({escapado}), que renderiza a "
            "barra invertida à mostra."
        )


def test_claude_md_nomeia_as_apps_em_portugues():
    for app in ["apps/contas", "apps/projetos", "apps/bancas", "apps/documentos"]:
        assert app in CLAUDE, f"CLAUDE.md deve nomear {app}."
    for antiga in ["apps/accounts", "apps/projects", "apps/boards", "apps/documents"]:
        assert antiga not in CLAUDE, f"CLAUDE.md ainda cita o nome antigo {antiga}."


def test_claude_md_nao_manda_copiar_css_de_outro_projeto():
    assert "IntegraSI" not in CLAUDE
    assert "DaisyUI" in CLAUDE


def test_claude_md_registra_os_comandos_reais():
    for comando in ["docker compose up -d", "docker compose exec web pytest",
                    "semear_sistema"]:
        assert comando in CLAUDE
```

- [ ] **Passo 2: Rodar e confirmar que falha**

Executar: `docker compose exec web pytest tests/test_documentacao.py -v`
Esperado: FALHA nos quatro testes — o arquivo atual tem markdown escapado, nomeia as
apps em inglês, cita o projeto de referência pelo nome e não menciona
`semear_sistema`.

- [ ] **Passo 3: Reescrever o `CLAUDE.md`**

Reescrever o arquivo inteiro, sem barras invertidas de escape, preservando as seções
existentes e aplicando estas mudanças:

1. **Remover todo escape de markdown** — `\#\#` vira `##`, `\*\*` vira `**`.
2. **Seção "Stack Tecnológica & UI/UX"** — substituir a linha sobre copiar o CSS do
   projeto de referência por:
   `**CSS & Identidade Visual:** Tailwind v4 + DaisyUI, com tema próprio construído
   sobre as cores institucionais (marinho #21376B, azul #055695, ciano #38C2C2,
   laranja #D9530E). Flowbite não é usado: aparência vem do DaisyUI, comportamento
   vem do Alpine.js.`
3. **Nova seção "Estrutura de Apps"**, com os nomes reais: `apps/contas`,
   `apps/projetos`, `apps/bancas`, `apps/documentos`, `apps/comum`, e a nota de que
   todo identificador de código é em português enquanto a interface também o é.
4. **Seção de comandos** — acrescentar
   `docker compose exec web python manage.py semear_sistema --email-coordenador ... --nome-coordenador ... --cpf-coordenador ... --email-sugrad ...`
   e `docker compose --profile dev up -d` (que inclui o container do Tailwind).
5. **Regra 3 (Professores Externos)** — acrescentar a nota de que o fluxo de token é
   especificado no Bloco D e não existe na Fase 1.
6. **Nova seção "Fases"**, apontando para `docs/superpowers/specs/` e listando os
   blocos A–H, com A marcado como concluído.

- [ ] **Passo 4: Escrever o `README.md`**

```markdown
# OrientaSI

Sistema de gestão de TCC do Curso de Sistemas de Informação.

## Como subir o ambiente

```bash
cp .env.example .env
docker compose --profile dev up -d --build
docker compose exec web python manage.py migrate
docker compose exec web python manage.py semear_sistema \
  --email-coordenador coordenacao@ufsm.br \
  --nome-coordenador "Coordenação do Curso" \
  --cpf-coordenador 00000000000 \
  --email-sugrad sugrad@ufsm.br
```

O sistema fica em http://localhost:8000 e o console do MinIO em
http://localhost:9001.

## Testes

```bash
docker compose exec web pytest
docker compose exec web ruff check .
docker compose exec web black --check .
```

A suíte inclui verificação automática de acessibilidade (WCAG 2.1 AA) com
Playwright e axe-core, alvos de toque, responsividade e navegação por teclado.

## Documentação

- Contexto e convenções: `CLAUDE.md`
- Especificações: `docs/superpowers/specs/`
- Planos de implementação: `docs/superpowers/plans/`
```

- [ ] **Passo 5: Rodar a suíte inteira**

Executar: `docker compose exec web pytest -v`
Esperado: tudo PASSA, inclusive `tests/test_documentacao.py`.

- [ ] **Passo 6: Verificar os critérios de aceitação do spec §13**

Percorrer os 13 critérios do spec, um a um, a partir de um clone limpo:

```bash
docker compose down -v
docker compose --profile dev up -d --build
docker compose exec web python manage.py migrate
docker compose exec web pytest
docker compose exec web ruff check .
```

Esperado: todos os 13 critérios verificáveis. Registrar no commit qualquer um que
não seja atendido.

- [ ] **Passo 7: Commit**

```bash
git add -A
git commit -m "Atualiza o CLAUDE.md com as decisoes da Fase 1 e adiciona o README"
```

---

## Ao concluir

Com as 13 tarefas concluídas, a Fase 1 (Bloco A) está entregue. O próximo ciclo é o
**Bloco B — Mural de temas e alocação**, que precisa de uma decisão pendente antes de
começar: o `inicio.pdf` diz que a alocação de orientadores é feita "por desempenho
escolar", e o sistema não tem de onde ler essa nota. Levante essa questão no
brainstorming do Bloco B, antes de modelar `Candidatura`.
