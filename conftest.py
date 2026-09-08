import os

import pytest


def pytest_collection_modifyitems(session, config, items):
    """Liga DJANGO_ALLOW_ASYNC_UNSAFE só quando a sessão inclui algum teste que
    usa `page` (Playwright) — e só uma vez, na coleta, antes de qualquer
    fixture rodar.

    O driver síncrono do Playwright roda seu loop de eventos com um greenlet
    cooperativo na MESMA thread do teste, em vez de numa thread separada:
    `loop.run_until_complete` fica suspenso sempre que esse greenlet devolve o
    controle ao teste. O detector "chamada de banco em contexto async" do
    Django (`django.utils.asyncio.async_unsafe`) enxerga esse loop suspenso e
    conclui, errado, que há um event loop rodando na thread — e barra a
    criação do banco de teste (`SynchronousOnlyOperation`) mesmo sem nenhuma
    concorrência real: greenlets nunca executam dois ao mesmo tempo, então o
    acesso síncrono ao banco nos testes com `page` + `live_server` nunca
    corre risco de reentrância. `DJANGO_ALLOW_ASYNC_UNSAFE` é o escape hatch
    que o próprio Django documenta para exatamente este tipo de falso
    positivo do detector.

    Por que na coleta, e não numa fixture por teste (tentamos primeiro): o
    banco de teste é criado uma única vez por sessão (`django_db_setup`,
    fixture de escopo de sessão do pytest-django), na primeira vez que
    qualquer teste marcado `@pytest.mark.django_db` pede acesso ao banco — e
    a ordem de setup entre esse fixture interno e os fixtures de Playwright
    (`page`/`browser`/`playwright`, também de sessão inteira) não é garantida
    pelo pytest. Confirmamos isso na prática: uma fixture `autouse` que ligava
    a variável só quando `"page" in request.fixturenames` ainda deixava o
    `SynchronousOnlyOperation` estourar, porque a checagem do Django corria
    antes dela. Ligar a variável na coleta — antes de qualquer fixture — evita
    essa corrida por completo. O custo é que a variável fica ligada para a
    sessão inteira, não só para os testes de navegador; o ganho sobre o estado
    anterior (sempre ligada, mesmo sem nenhum teste de navegador na sessão) é
    que uma sessão sem nenhum `page` (ex.: `pytest tests/test_saude.py`,
    `pytest apps/`) nunca liga a variável.
    """
    if any("page" in item.fixturenames for item in items):
        os.environ["DJANGO_ALLOW_ASYNC_UNSAFE"] = "true"


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
