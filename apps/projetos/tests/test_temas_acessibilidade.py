"""`/temas/<id>/editar/` é rota nova da rodada de correção 1 da T6 (acréscimo de
escopo: edição de tema, spec §2 e §6) — e por ter um `<id>` de banco de dados na
própria URL, não cabe na fábrica estática de `conftest.py::ROTAS` (mesmo motivo
pelo qual `/contas/reset/<uidb64>/<token>/` fica de fora dali: precisa de um
registro real, criado a cada teste, cujo pk não é previsível antes de existir).

Segue o mesmo padrão de `apps/contas/tests/test_coordenacao_acessibilidade.py`
para o mesmo problema (ali, o estado "confirmação aberta" de `/painel/`, que
também não é alcançável pela fábrica estática de `ROTAS`): fixture própria,
âncora de identidade própria (URL final + `<h1>`), e o Axe rodado nas mesmas
duas larguras e com as mesmas regras da suíte oficial (`REGRAS_AXE`,
`LARGURAS_TESTADAS`, ambas de `conftest.py`).

`/temas/meus/` (a tela de listagem) já está em `ROTAS` desde a Tarefa 6 e
continua coberta pelas quatro suítes transversais sem nenhuma mudança aqui —
a variante POPULADA dela (com o link "Editar" e o badge "Inativo") é o Menor 1
da revisão desta rodada, explicitamente adiado para a Tarefa 7 (que já mexe em
`conftest.py`), não fechado nesta suíte.
"""

import pytest
from axe_playwright_python.sync_playwright import Axe

from apps.contas.models import Area, PerfilProfessor, Usuario
from apps.projetos.models import Tema
from conftest import LARGURAS_TESTADAS, REGRAS_AXE

CPF_PROFESSOR = "52998224725"


@pytest.fixture
def professor_com_tema(db):
    usuario = Usuario.objects.create_user(
        email="professor-editar-tema@ufsm.br",
        password="x",
        nome_completo="Professor Editar Tema",
        cpf=CPF_PROFESSOR,
    )
    perfil = PerfilProfessor.objects.create(usuario=usuario, siape="2000002")
    area = Area.objects.create(nome="Área do Tema a Editar")
    perfil.areas.add(area)
    tema = Tema.objects.create(
        professor=perfil,
        area=area,
        titulo="Tema a Editar",
        descricao="Descrição do tema a editar, para a tela de edição não ficar vazia.",
    )
    return usuario, tema


@pytest.fixture
def pagina_autenticada(autentica_no_navegador, professor_com_tema):
    usuario, _tema = professor_com_tema
    return autentica_no_navegador(usuario)


def _confirma_que_esta_editando_o_tema(page, live_server, tema):
    """Âncora de identidade: mesmo risco que a fixture `rota` (conftest.py)
    neutraliza para as rotas estáticas — sem isto, um redirecionamento para
    o login (autenticação não pegou) ou um 404/403 servido com HTML próprio
    deixaria este teste medir a página errada."""
    url_esperada = f"{live_server.url}/temas/{tema.pk}/editar/"
    assert page.url == url_esperada, (
        f"/temas/{tema.pk}/editar/ deveria terminar a navegação em {url_esperada!r}, e a "
        f"URL final foi {page.url!r} — provável redirecionamento para o login (autenticação "
        "não pegou) ou erro servido no lugar da tela."
    )
    assert "Editar tema" in page.inner_text(
        "h1"
    ), f"esperava <h1> com 'Editar tema', e o texto foi {page.inner_text('h1')!r}."


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize("largura", LARGURAS_TESTADAS)
def test_editar_tema_nao_viola_wcag(pagina_autenticada, live_server, professor_com_tema, largura):
    _usuario, tema = professor_com_tema
    pagina_autenticada.set_viewport_size({"width": largura, "height": 800})
    pagina_autenticada.goto(f"{live_server.url}/temas/{tema.pk}/editar/")
    _confirma_que_esta_editando_o_tema(pagina_autenticada, live_server, tema)

    resultados = Axe().run(pagina_autenticada, options=REGRAS_AXE)
    assert resultados.violations_count == 0, (
        f"/temas/{tema.pk}/editar/ a {largura}px viola {resultados.violations_count} "
        f"regra(s) WCAG 2.1 A/AA:\n{resultados.generate_report()}"
    )
