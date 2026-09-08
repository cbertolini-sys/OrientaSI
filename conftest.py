import os

import pytest

# O driver síncrono do Playwright (usado pela fixture `page` de pytest-playwright)
# roda seu loop de eventos com um greenlet cooperativo na MESMA thread do teste, em
# vez de numa thread separada: `loop.run_until_complete` fica suspenso sempre que
# esse greenlet devolve o controle ao teste. O detector "chamada de banco em
# contexto async" do Django (`django.utils.asyncio.async_unsafe`) enxerga esse loop
# suspenso e conclui, errado, que há um event loop rodando na thread — e barra a
# criação do banco de teste (`SynchronousOnlyOperation`) mesmo sem nenhuma
# concorrência real: greenlets nunca executam dois ao mesmo tempo, então o acesso
# síncrono ao banco nos testes com `page` + `live_server` nunca corre risco de
# reentrância. `DJANGO_ALLOW_ASYNC_UNSAFE` é o escape hatch que o próprio Django
# documenta para exatamente este tipo de falso positivo do detector.
os.environ.setdefault("DJANGO_ALLOW_ASYNC_UNSAFE", "true")


@pytest.fixture(autouse=True)
def midia_temporaria(settings, tmp_path):
    """Nenhum teste escreve em media/ nem no bucket: cada teste recebe um diretório próprio."""
    settings.MEDIA_ROOT = tmp_path / "media"
    settings.STORAGES = {
        **settings.STORAGES,
        "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    }


# Lista única de rotas submetidas à suíte de acessibilidade, toque, responsividade
# e teclado (tests/test_acessibilidade.py, test_toque.py, test_responsivo.py,
# test_teclado.py). Acrescentar uma rota aqui é o que submete uma página nova às
# quatro verificações de uma vez — toda tarefa que criar uma página pública nova
# acrescenta sua rota a esta lista (spec §10.1).
ROTAS = [
    "/",
]


@pytest.fixture(params=ROTAS)
def rota(request):
    return request.param
