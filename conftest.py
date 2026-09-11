import hashlib
import importlib
import os
from collections.abc import Callable
from dataclasses import dataclass
from types import SimpleNamespace

import pytest
from django.conf import settings
from django.test import Client
from django.utils import timezone


def carrega_settings(**ambiente):
    """Recarrega config.settings sob um ambiente diferente e devolve uma cópia.

    A cópia é necessária porque o bloco `finally` restaura o ambiente original
    e recarrega o mesmo módulo de novo (para não vazar estado para outros
    testes): se devolvêssemos o módulo em si, esse segundo reload sobrescreveria
    os valores antes mesmo de o chamador conseguir inspecioná-los.

    Vive no conftest desde a onda final: `tests/test_producao.py` e
    `tests/test_armazenamento.py` precisam do mesmo mecanismo (o segundo
    passou a exercitar o ramo de fallback do armazenamento), e uma segunda
    cópia da função divergiria como as três cópias de suíte de acessibilidade
    já divergiram.
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


# Ambiente mínimo que o bloco de produção do config/settings.py aceita: todas
# as variáveis que ele impõe via `obrigatorio()`. Qualquer teste que carregue
# os settings com AMBIENTE=producao parte daqui e sobrescreve o que lhe
# interessa — assim, acrescentar uma variável imposta atualiza todos os
# testes de produção de uma vez, em vez de quebrá-los um a um.
AMBIENTE_PRODUCAO = {
    "AMBIENTE": "producao",
    # Chave longa de propósito: `manage.py check --deploy` (W009) reprova
    # SECRET_KEY com menos de 50 caracteres ou pouca entropia.
    "SECRET_KEY": "chave-de-producao-fake-para-teste-com-mais-de-cinquenta-caracteres",
    "ALLOWED_HOSTS": "orientasi.ufsm.br",
    "URL_BASE": "https://orientasi.ufsm.br",
    "EMAIL_BACKEND": "django.core.mail.backends.smtp.EmailBackend",
    "EMAIL_HOST": "smtp.ufsm.br",
    "S3_ACCESS_KEY": "chave-de-acesso",
    "S3_SECRET_KEY": "chave-secreta",
}


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


# Regras do axe-core (WCAG 2.1 A/AA), larguras e seletor de alvos interativos
# usados por toda suíte de acessibilidade/toque baseada em Playwright — tanto
# a suíte global sobre rotas anônimas (tests/test_acessibilidade.py,
# test_toque.py) quanto qualquer suíte de rota autenticada (a partir da T10,
# ver `autentica_no_navegador` abaixo). Centralizados aqui (revisão 1 da T10)
# para não haver uma segunda cópia por tarefa: antes desta extração,
# apps/contas/tests/test_perfil_acessibilidade.py duplicava as três
# constantes de tests/test_acessibilidade.py e tests/test_toque.py.
REGRAS_AXE = {"runOnly": {"type": "tag", "values": ["wcag2a", "wcag2aa", "wcag21aa"]}}
LARGURAS_TESTADAS = [1280, 360]
SELETOR_INTERATIVOS = (
    "a, button, input:not([type=hidden]), select, textarea, summary, "
    "[tabindex]:not([tabindex='-1']), "
    "[role=button], [role=link], [role=checkbox], [role=tab], [role=menuitem]"
)


@pytest.fixture
def autentica_no_navegador(page, live_server):
    """Fábrica: devolve uma função que autentica `page` (Playwright) como o
    `Usuario` que ela recebe.

    Extraída para cá na revisão 1 da T10: `/perfil/` foi a primeira rota
    autenticada do projeto, e sua suíte de acessibilidade
    (`apps/contas/tests/test_perfil_acessibilidade.py`) precisava navegar já
    logada — as quatro suítes globais (`tests/test_acessibilidade.py` e
    companhia) navegam sempre anônimas, então não serviam. Qualquer suíte de
    acessibilidade de uma rota autenticada futura (T11 em diante) deve reusar
    esta fábrica em vez de reimplementar login + injeção de cookie.

    Mecanismo: `django.test.Client().force_login(usuario)` grava a sessão
    diretamente no banco de teste, sem passar pelo formulário de login; o
    cookie de sessão resultante (`settings.SESSION_COOKIE_NAME`) é injetado
    no contexto do Playwright, para que a navegação real do navegador chegue
    com a sessão já aberta.
    """

    def _autentica(usuario):
        cliente = Client()
        cliente.force_login(usuario)
        cookie = cliente.cookies[settings.SESSION_COOKIE_NAME]
        page.context.add_cookies(
            [{"name": settings.SESSION_COOKIE_NAME, "value": cookie.value, "url": live_server.url}]
        )
        return page

    return _autentica


@dataclass(frozen=True)
class Rota:
    """Uma rota submetida às quatro verificações transversais.

    `fabrica_usuario` é o que permite cobrir tela autenticada sem duplicar a suíte:
    quando presente, a fixture `rota` autentica no navegador antes de medir. `h1`,
    junto com a própria URL final, é a âncora de identidade (confira a fixture `rota`
    abaixo) — sem ela, uma rota quebrada passa medindo a tela de login, defeito que
    este projeto já teve duas vezes: uma na própria fixture `rota` (ver linha ~340,
    corrigida para igualdade exata `page.url == url_esperada`) e outra em
    `apps/contas/tests/test_coordenacao_acessibilidade.py::_confirma_que_esta_no_painel`
    (cuja suíte duplicada nasceu exatamente deste problema antes desta generalização).
    """

    caminho: str
    seletor: str
    fabrica_usuario: Callable | None = None
    h1: str | None = None
    # Só preenchido quando duas Rotas compartilham `caminho` (ex.: /perfil/ como
    # professor e como aluno, HTML genuinamente diferente na mesma URL) — desambigua
    # o id que `ids=lambda r: ...` (fixture `rota`, abaixo) gera para o pytest, que do
    # contrário colidiria (duas entradas "/perfil/" seriam indistinguíveis nos
    # relatórios e no -k).
    persona: str | None = None


def cria_professor_para_rotas():
    """Fábrica da variante professor de `/perfil/`: professor com `PerfilProfessor`
    e ao menos uma `Area` cadastrada, para a suíte medir a variante do formulário
    que traz o `<fieldset>`/`<legend>` do grupo de áreas.

    A área criada é também ASSOCIADA ao professor (`perfil.areas.add`, T6):
    sem isso, o professor desta fábrica não declara nenhuma área de atuação, e
    `/temas/meus/` (T6) — cujo campo `area` só lista as áreas que o professor
    declarou — mediria um `<select>` vazio, uma página degenerada em vez da
    tela real."""
    from apps.contas.models import Area, PerfilProfessor, Usuario

    usuario = Usuario.objects.create_user(
        email="professor-das-rotas@ufsm.br",
        password="x",
        nome_completo="Professor das Rotas",
        cpf="98765432100",
    )
    perfil = PerfilProfessor.objects.create(usuario=usuario, siape="1000001")
    area = Area.objects.create(nome="Área das Rotas")
    perfil.areas.add(area)
    return usuario


def cria_coordenador_para_rotas():
    """Fábrica de `/painel/`: professor promovido a coordenador (ver
    apps/contas/tests/test_coordenacao_acessibilidade.py)."""
    from apps.contas.models import Usuario

    return Usuario.objects.create_user(
        email="coordenador-das-rotas@ufsm.br",
        password="x",
        nome_completo="Coordenador das Rotas",
        cpf="12345678909",
        is_coordenador=True,
        is_staff=True,
    )


def cria_aluno_para_rotas():
    """Fábrica da variante aluno de `/perfil/` — o HTML difere de verdade da
    variante professor (sem o `<fieldset>`/`<legend>` do grupo de áreas), por isso
    as duas entram em `ROTAS` separadamente. Também serve às telas autenticadas de
    aluno que as tarefas seguintes do Bloco B (candidatura, mural) vão acrescentar."""
    from apps.contas.models import PerfilAluno, Usuario

    usuario = Usuario.objects.create_user(
        email="aluno-das-rotas@ufsm.br",
        password="x",
        nome_completo="Aluno das Rotas",
        cpf="11144477735",
        papel=Usuario.ALUNO,
    )
    PerfilAluno.objects.create(usuario=usuario, matricula="202399999")
    return usuario


# Lista única de rotas submetidas à suíte de acessibilidade, toque, responsividade
# e teclado (tests/test_acessibilidade.py, test_toque.py, test_responsivo.py,
# test_teclado.py). Acrescentar uma rota aqui é o que submete uma página nova às
# quatro verificações de uma vez — toda tarefa que criar uma página nova (pública
# ou autenticada, via `fabrica_usuario`) acrescenta sua rota a esta lista (spec §10.1).
ROTAS = [
    Rota("/", "h1"),
    Rota("/convite/rota-para-teste-de-acessibilidade/", "form"),
    Rota("/contas/login/", "form"),
    Rota("/contas/password_reset/", "form"),
    # done/complete são páginas estáticas (sem formulário, sem estado) —
    # cobertura de graça, sem precisar de fixture nenhuma. password_reset_confirm
    # fica de fora: exige um uidb64/token real e válido, que só existe depois de
    # um fluxo de recuperação de senha de verdade (ver
    # apps/contas/tests/test_autenticacao.py,
    # test_fluxo_completo_de_recuperacao_de_senha_ate_novo_login).
    Rota("/contas/password_reset/concluido/", "h1"),
    Rota("/contas/reset/concluido/", "h1"),
    # As rotas abaixo substituem as suítes que viviam inteiras em
    # apps/contas/tests/test_perfil_acessibilidade.py (removido) e
    # test_coordenacao_acessibilidade.py (T1 do Bloco B): eram cópias dos
    # mesmos cinco corpos de teste desta suíte, só que autenticadas na mão.
    # /perfil/ entra duas vezes: o HTML da variante professor (com o
    # <fieldset>/<legend> do grupo de áreas) difere de verdade do da variante
    # aluno, então uma cobertura só varreria metade das personas de verdade.
    Rota(
        "/perfil/",
        "form",
        fabrica_usuario=cria_professor_para_rotas,
        h1="Meu perfil",
        persona="professor",
    ),
    Rota(
        "/perfil/",
        "form",
        fabrica_usuario=cria_aluno_para_rotas,
        h1="Meu perfil",
        persona="aluno",
    ),
    Rota(
        "/painel/",
        "form",
        fabrica_usuario=cria_coordenador_para_rotas,
        h1="Painel da coordenação",
    ),
    Rota("/temas/meus/", "form", fabrica_usuario=cria_professor_para_rotas, h1="Meus temas"),
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


@pytest.fixture(params=ROTAS, ids=lambda r: f"{r.caminho}[{r.persona}]" if r.persona else r.caminho)
def rota(request, convite_das_rotas, page, live_server, autentica_no_navegador):
    """Devolve a rota já aberta no navegador, autenticada quando ela exige.

    A checagem de âncora roda uma única vez aqui, no viewport padrão — ela prova qual
    página está aberta, não como ela se comporta em cada largura. São duas asserções,
    nesta ordem, ambas antes de qualquer outra verificação (restricoes-globais.md): a
    URL final tem que ser exatamente a URL pedida (pega redirecionamento para o login
    que a autenticação não conseguiu evitar) e o texto do `<h1>` tem que bater com o
    esperado (pega a página errada que por acaso responde na mesma URL, ex.: um 404
    customizado). Os testes de toque e responsividade mudam a largura e chamam
    `page.reload()` por conta própria: se a fixture recarregasse, a largura que o
    teste definiu se perderia.

    A comparação de URL é **igualdade exata** com `live_server.url + r.caminho`, não
    `str.endswith(r.caminho)`: `login_required` redireciona para
    `/contas/login/?next=/painel/`, e essa URL também *termina* em `/painel/` — o
    parâmetro `next` reproduz o caminho pedido no fim da string. Um `endswith` passaria
    por engano exatamente no caso que existe para pegar (confirmado quebrando de
    propósito na Tarefa 1, revisão 1 — ver relatório).
    """
    r = request.param
    if r.fabrica_usuario is not None:
        autentica_no_navegador(r.fabrica_usuario())
    page.goto(f"{live_server.url}{r.caminho}")
    if r.h1:
        url_esperada = f"{live_server.url}{r.caminho}"
        assert page.url == url_esperada, (
            f"{r.caminho} deveria terminar a navegação em {url_esperada!r}, e a URL final foi "
            f"{page.url!r} — provável redirecionamento para o login (autenticação não pegou)."
        )
        texto = page.inner_text("h1")
        assert r.h1 in texto, (
            f"{r.caminho} deveria mostrar <h1> com {r.h1!r}, e mostrou {texto!r}. "
            "A suíte pode estar medindo a página errada (ex.: um redirecionamento "
            "para o login que a autenticação não pegou)."
        )
    return r
