import pytest
from django.core.exceptions import ImproperlyConfigured
from django.core.management import call_command
from django.core.management.base import SystemCheckError
from django.test import override_settings

from conftest import AMBIENTE_PRODUCAO, carrega_settings

# Configurações que `manage.py check --deploy` inspeciona e que o bloco de
# produção do config/settings.py define. Enumeradas para que
# `test_check_deploy_nao_aponta_avisos` possa aplicá-las com `override_settings`
# sobre a sessão de teste (que roda com AMBIENTE=dev): recarregar o módulo
# `config.settings` NÃO atualiza o `django.conf.settings` já materializado.
CONFIGURACOES_DO_DEPLOY = [
    "DEBUG",
    "SECRET_KEY",
    "ALLOWED_HOSTS",
    "SECURE_SSL_REDIRECT",
    "SECURE_PROXY_SSL_HEADER",
    "SESSION_COOKIE_SECURE",
    "CSRF_COOKIE_SECURE",
    "SECURE_HSTS_SECONDS",
    "SECURE_HSTS_INCLUDE_SUBDOMAINS",
    "SECURE_HSTS_PRELOAD",
    "SECURE_CONTENT_TYPE_NOSNIFF",
    "MIDDLEWARE",
]


def test_producao_desliga_debug_e_exige_segredos():
    settings = carrega_settings(**AMBIENTE_PRODUCAO)
    assert settings.DEBUG is False
    assert settings.SECURE_SSL_REDIRECT is True
    assert settings.SESSION_COOKIE_SECURE is True
    assert settings.CSRF_COOKIE_SECURE is True


def test_producao_sem_secret_key_falha_alto():
    with pytest.raises(ImproperlyConfigured):
        carrega_settings(**{**AMBIENTE_PRODUCAO, "SECRET_KEY": ""})


@pytest.mark.parametrize("variavel", sorted(AMBIENTE_PRODUCAO.keys() - {"AMBIENTE"}))
def test_producao_impoe_todas_as_variaveis_sem_padrao_seguro(variavel):
    """A spec §3.7 justifica o arquivo único de settings com "impor os valores
    em vez de lê-los", mas só `SECRET_KEY` e `ALLOWED_HOSTS` passavam por
    `obrigatorio()` (achado da revisão final). As outras cinco falham em
    SILÊNCIO: sem `URL_BASE`, todo convite sai com link para
    `http://localhost:8000`; sem `EMAIL_BACKEND`, os convites vão para o
    console do Gunicorn; sem as credenciais do S3, o upload não autentica."""
    with pytest.raises(ImproperlyConfigured) as erro:
        carrega_settings(**{**AMBIENTE_PRODUCAO, variavel: ""})
    assert variavel in str(erro.value)


def test_producao_confia_no_cabecalho_de_proxy_para_reconhecer_https():
    """Sem `SECURE_PROXY_SSL_HEADER`, o Gunicorn atrás de um proxy (que termina
    o TLS e repassa em HTTP) enxerga `request.is_secure()` False: o
    `SECURE_SSL_REDIRECT` redireciona para HTTPS em laço infinito, e o
    `{{ protocol }}` de registration/password_reset_email.html monta o link de
    recuperação com `http://`."""
    settings = carrega_settings(**AMBIENTE_PRODUCAO)
    assert settings.SECURE_PROXY_SSL_HEADER == ("HTTP_X_FORWARDED_PROTO", "https")


def test_check_deploy_nao_aponta_avisos(monkeypatch):
    """`manage.py check --deploy` com AMBIENTE=producao, item que a spec §10.1
    nomeia e que a implementação não tinha (achado da revisão final).

    `fail_level="WARNING"` é o que dá dente ao teste: sem ele, `check` só
    falharia em ERROR, e todos os avisos de segurança do Django (W004-W022 —
    HSTS ausente, cookie sem `Secure`, `DEBUG` ligado) passariam
    despercebidos. Trava a regressão do dia em que alguém remover uma
    configuração de segurança do bloco de produção."""
    # `DJANGO_ALLOW_ASYNC_UNSAFE` é ligado pelo conftest.py quando a sessão
    # inclui testes de Playwright, e o `check --deploy` acusa (async.E001) a
    # presença dessa variável — corretamente, aliás: ela desliga uma proteção
    # do Django e não deve existir em produção. Só que é artefato da SUÍTE,
    # não do bloco de produção que este teste inspeciona: nada em
    # config/settings.py nem no Dockerfile a define. Removê-la aqui é o que
    # mantém o teste medindo os settings, e não o ambiente do pytest — sem
    # isto, o resultado dependeria de a sessão ter ou não testes de navegador.
    monkeypatch.delenv("DJANGO_ALLOW_ASYNC_UNSAFE", raising=False)
    producao = carrega_settings(**AMBIENTE_PRODUCAO)
    aplicadas = {nome: getattr(producao, nome) for nome in CONFIGURACOES_DO_DEPLOY}
    with override_settings(**aplicadas):
        try:
            call_command("check", deploy=True, fail_level="WARNING")
        except SystemCheckError as erro:
            pytest.fail(
                "manage.py check --deploy apontou problemas com o bloco de "
                f"produção do config/settings.py:\n{erro}"
            )
