"""Discriminação da navegação de `templates/base.html` (rodada de correção 1
da Tarefa 12, Importante).

As cinco suítes transversais (`tests/test_acessibilidade.py`, `test_toque.py`,
`test_responsivo.py`, `test_teclado.py`, `test_rotas.py`) medem contraste, alvo
de toque, estrutura semântica e ausência de rolagem — nunca CONTEÚDO: nenhuma
delas afirma que um link existe, ou para quem. A revisão desta rodada mutou
`base.html` de duas formas — removendo o guarda `{% if user.perfil_aluno %}`
do link "Minha candidatura" (passaria a aparecer para professores e
coordenadores) e removendo por completo o `<li>` de "Painel de orientações"
(exatamente o defeito que o acréscimo de escopo da T12 existe para fechar) —
e rodou a suíte inteira as duas vezes: `535 passed, 6 skipped`, zero falhas.
Este arquivo é o teste que faltava.

Renderiza `/` (a `TemplateView` pública de `config/urls.py`, que estende
`base.html` e não exige autenticação) para cada uma das cinco personas do
brief da rodada de correção, e afirma presença/ausência de cada `href` do
bloco `navegacao` — pelo atributo COMPLETO (`href="/temas/"`, não só
`/temas/`), porque `/temas/` é uma substring de `/temas/meus/` e `/painel/`
é uma substring de `/painel/orientacoes/`: checar a substring sem as aspas
daria falso positivo para "mural" sempre que só "meus temas" estivesse
presente, e para "painel da coordenação" sempre que só "painel de
orientações" estivesse presente.
"""

import pytest

from apps.contas.models import PerfilAluno, PerfilProfessor, Usuario
from apps.contas.validators import _digito


# CPFs sintéticos com dígito verificador válido — faixa própria (200000000+),
# distinta das faixas já usadas pelas suítes de apps/projetos/tests/ e
# apps/contas/tests/ (ver, por exemplo, o comentário de
# apps/projetos/tests/test_painel_orientacoes.py sobre por que manter faixas
# distintas facilita achar de qual suíte um CPF veio).
def _gera_cpf(indice):
    base = f"{200000000 + indice:09d}"
    d1 = _digito(base, 10)
    d2 = _digito(base + str(d1), 11)
    return base + str(d1) + str(d2)


# Os hrefs exatos que o bloco `navegacao` de base.html pode emitir, com as
# aspas — ver a docstring do módulo sobre por que a substring sem aspas não
# discrimina "/temas/" de "/temas/meus/" nem "/painel/" de
# "/painel/orientacoes/".
HREF_ENTRAR = 'href="/contas/login/"'
HREF_MURAL = 'href="/temas/"'
HREF_MEUS_TEMAS = 'href="/temas/meus/"'
HREF_ORIENTACOES = 'href="/orientacoes/"'
HREF_CANDIDATURA = 'href="/candidatura/"'
HREF_PERFIL = 'href="/perfil/"'
HREF_PAINEL_COORDENACAO = 'href="/painel/"'
HREF_PAINEL_ORIENTACOES = 'href="/painel/orientacoes/"'

TODOS_OS_HREFS_AUTENTICADOS = [
    HREF_MURAL,
    HREF_MEUS_TEMAS,
    HREF_ORIENTACOES,
    HREF_CANDIDATURA,
    HREF_PERFIL,
    HREF_PAINEL_COORDENACAO,
    HREF_PAINEL_ORIENTACOES,
]


def _extrai_navegacao(html):
    """Isola o conteúdo de `<nav aria-label="Principal">...</nav>` (o bloco
    `{% block navegacao %}` de base.html) do resto da página.

    Necessário porque `templates/inicio.html` (a página usada aqui, "/") tem
    seu PRÓPRIO botão "Entrar" no corpo do conteúdo
    (`<a href="{% url 'login' %}" class="btn btn-primary mt-6">Entrar</a>`),
    fora da navegação e sem nenhuma condição de autenticação — sem isolar a
    `<nav>`, o teste do persona anônimo passaria por acidente (o único hrefs
    que ele checa É o de login) mas os quatro testes autenticados
    reprovariam a checagem de AUSÊNCIA de `href="/contas/login/"`, porque
    esse href está no corpo da página, não na navegação, e continua lá
    também para quem está logado.
    """
    inicio = html.index('<nav aria-label="Principal">')
    fim = html.index("</nav>", inicio)
    return html[inicio:fim]


def _assert_presentes_e_ausentes(html, presentes, ausentes):
    navegacao = _extrai_navegacao(html)
    for href in presentes:
        assert href in navegacao, f"esperava {href} na navegação, e não apareceu"
    for href in ausentes:
        assert href not in navegacao, f"não esperava {href} na navegação, e apareceu"


@pytest.mark.django_db
def test_navegacao_anonimo_so_mostra_entrar(client):
    html = client.get("/").content.decode()

    _assert_presentes_e_ausentes(
        html, presentes=[HREF_ENTRAR], ausentes=TODOS_OS_HREFS_AUTENTICADOS
    )


@pytest.mark.django_db
def test_navegacao_aluno(client):
    usuario = Usuario.objects.create_user(
        email="aluno.nav@ufsm.br",
        password="x",
        nome_completo="Aluno Navegação",
        papel=Usuario.ALUNO,
        cpf=_gera_cpf(0),
    )
    PerfilAluno.objects.create(usuario=usuario, matricula="2026NAV0001")
    client.force_login(usuario)

    html = client.get("/").content.decode()

    _assert_presentes_e_ausentes(
        html,
        presentes=[HREF_CANDIDATURA, HREF_PERFIL, HREF_MURAL],
        ausentes=[
            HREF_MEUS_TEMAS,
            HREF_ORIENTACOES,
            HREF_PAINEL_COORDENACAO,
            HREF_PAINEL_ORIENTACOES,
            HREF_ENTRAR,
        ],
    )


@pytest.mark.django_db
def test_navegacao_professor_comum(client):
    usuario = Usuario.objects.create_user(
        email="professor.nav@ufsm.br",
        password="x",
        nome_completo="Professor Navegação",
        cpf=_gera_cpf(1),
    )
    PerfilProfessor.objects.create(usuario=usuario, siape="NAV0001")
    client.force_login(usuario)

    html = client.get("/").content.decode()

    _assert_presentes_e_ausentes(
        html,
        presentes=[HREF_ORIENTACOES, HREF_MEUS_TEMAS, HREF_MURAL, HREF_PERFIL],
        ausentes=[
            HREF_CANDIDATURA,
            HREF_PAINEL_COORDENACAO,
            HREF_PAINEL_ORIENTACOES,
            HREF_ENTRAR,
        ],
    )


@pytest.mark.django_db
def test_navegacao_coordenador_sem_perfil_professor(client):
    usuario = Usuario.objects.create_user(
        email="coordenador.nav@ufsm.br",
        password="x",
        nome_completo="Coordenador Navegação",
        cpf=_gera_cpf(2),
        is_coordenador=True,
        is_staff=True,
    )
    client.force_login(usuario)

    html = client.get("/").content.decode()

    _assert_presentes_e_ausentes(
        html,
        presentes=[HREF_PAINEL_COORDENACAO, HREF_PAINEL_ORIENTACOES, HREF_PERFIL, HREF_MURAL],
        ausentes=[HREF_ORIENTACOES, HREF_MEUS_TEMAS, HREF_CANDIDATURA, HREF_ENTRAR],
    )


@pytest.mark.django_db
def test_navegacao_coordenador_que_tambem_e_professor(client):
    usuario = Usuario.objects.create_user(
        email="coordenador.professor.nav@ufsm.br",
        password="x",
        nome_completo="Coordenador Professor Navegação",
        cpf=_gera_cpf(3),
        is_coordenador=True,
        is_staff=True,
    )
    PerfilProfessor.objects.create(usuario=usuario, siape="NAV0002")
    client.force_login(usuario)

    html = client.get("/").content.decode()

    _assert_presentes_e_ausentes(
        html,
        presentes=[
            HREF_PAINEL_COORDENACAO,
            HREF_PAINEL_ORIENTACOES,
            HREF_MEUS_TEMAS,
            HREF_ORIENTACOES,
            HREF_MURAL,
            HREF_PERFIL,
        ],
        ausentes=[HREF_CANDIDATURA, HREF_ENTRAR],
    )
