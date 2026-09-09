import hashlib
import os

import pytest
from django.utils import timezone


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

    Preservação de valores pré-existentes: a variável só é definida se ainda
    não estiver presente. Um valor vindo de fora (ex.: CI com `DJANGO_ALLOW_ASYNC_UNSAFE=""`)
    é preservado — a string vazia é lida pelo Django como falso, sendo portanto
    a maneira de forçar a proteção ligada sem ser sobrescrita por este hook.
    """
    if any("page" in item.fixturenames for item in items):
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
    "/convite/rota-para-teste-de-acessibilidade/",
    "/contas/login/",
    "/contas/password_reset/",
    # done/complete são páginas estáticas (sem formulário, sem estado) —
    # cobertura de graça, sem precisar de fixture nenhuma. password_reset_confirm
    # fica de fora: exige um uidb64/token real e válido, que só existe depois de
    # um fluxo de recuperação de senha de verdade (ver
    # apps/contas/tests/test_autenticacao.py,
    # test_fluxo_completo_de_recuperacao_de_senha_ate_novo_login).
    "/contas/password_reset/concluido/",
    "/contas/reset/concluido/",
]


@pytest.fixture
def convite_das_rotas(db):
    """A rota de convite da suíte precisa de um convite válido para responder 200.

    NÃO é autouse: se fosse, o usuário que ela cria colidiria em CPF e e-mail com as
    fixtures de apps/contas/tests/, e a suíte inteira quebraria por IntegrityError.
    Só quem pede `rota` recebe esta semeadura.
    """
    from apps.contas.models import Convite, Usuario

    coordenadora = Usuario.objects.create_user(
        email="coord-das-rotas@ufsm.br",
        password="x",
        nome_completo="Coordenação",
        cpf="39053344705",
        is_coordenador=True,
        is_staff=True,
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


# Seletor presente só na página certa de cada rota, usado por
# tests/test_rotas.py para provar que uma rota quebrada (ex.: caiu para 404
# porque a fixture parou de semear o convite, ou o token mudou) reprova a
# suíte em vez de continuar verde medindo a página de erro por engano.
SELETOR_POR_ROTA = {
    "/": "h1",
    "/convite/rota-para-teste-de-acessibilidade/": "form",
    "/contas/login/": "form",
    "/contas/password_reset/": "form",
    "/contas/password_reset/concluido/": "h1",
    "/contas/reset/concluido/": "h1",
}


@pytest.fixture
def seletor_da_rota(rota):
    return SELETOR_POR_ROTA[rota]
