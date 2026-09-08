import importlib
import os
from types import SimpleNamespace

import pytest
from django.core.exceptions import ImproperlyConfigured


def carrega_settings(**ambiente):
    """Recarrega config.settings sob um ambiente diferente e devolve uma cópia.

    A cópia é necessária porque o bloco `finally` restaura o ambiente original
    e recarrega o mesmo módulo de novo (para não vazar estado para outros
    testes): se devolvêssemos o módulo em si, esse segundo reload sobrescreveria
    os valores antes mesmo de o chamador conseguir inspecioná-los.
    """
    anterior = dict(os.environ)
    os.environ.update(ambiente)
    try:
        import config.settings

        importlib.reload(config.settings)
        return SimpleNamespace(**vars(config.settings))
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
