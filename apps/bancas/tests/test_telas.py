"""Testes HTTP das telas de `apps/bancas` (Bloco D, spec §7). Lookup
escopado ao orientador — dono alheio e pk inexistente respondem os DOIS com
404, nunca 403 (mesmo padrão de `editar_tema`/`desativar_tema`, Bloco B)."""

import pytest
from django.utils import timezone

from apps.bancas import services
from apps.bancas.models import Banca
from apps.contas.models import PerfilAluno, PerfilProfessor, Usuario
from apps.contas.validators import _digito
from apps.projetos.models import Projeto, Submissao


def _cpf(indice):
    base = f"{670000000 + indice:09d}"
    d1 = _digito(base, 10)
    d2 = _digito(base + str(d1), 11)
    return base + str(d1) + str(d2)


def _professor(indice, nome):
    usuario = Usuario.objects.create_user(
        email=f"professor.tela.{indice}@ufsm.br",
        password="x",
        nome_completo=nome,
        cpf=_cpf(indice),
    )
    return PerfilProfessor.objects.create(usuario=usuario, siape=f"TELA{indice:03d}")


@pytest.fixture
def cenario(db):
    orientador = _professor(1, "Orientador Tela")
    aluno = Usuario.objects.create_user(
        email="aluno.tela@ufsm.br",
        password="x",
        nome_completo="Aluno Tela",
        papel=Usuario.ALUNO,
        cpf=_cpf(2),
    )
    PerfilAluno.objects.create(usuario=aluno, matricula="2026TELA0001")
    projeto = Projeto.objects.create(
        aluno=aluno,
        orientador=orientador.usuario,
        etapa=Projeto.TCC_I,
        status=Projeto.EM_ANDAMENTO,
        ano=2026,
        periodo=1,
    )
    Submissao.objects.create(
        projeto=projeto, pdf="submissoes/v1.pdf", editavel="submissoes/v1.docx"
    )
    membro1 = _professor(3, "Membro Tela Um")
    membro2 = _professor(4, "Membro Tela Dois")
    return {
        "orientador": orientador,
        "projeto": projeto,
        "membro1": membro1,
        "membro2": membro2,
    }


@pytest.mark.django_db
def test_agendar_get_mostra_formulario(client, cenario):
    client.force_login(cenario["orientador"].usuario)
    resposta = client.get(f"/bancas/agendar/{cenario['projeto'].pk}/")
    assert resposta.status_code == 200


@pytest.mark.django_db
def test_agendar_post_cria_banca_e_redireciona(client, cenario):
    client.force_login(cenario["orientador"].usuario)
    resposta = client.post(
        f"/bancas/agendar/{cenario['projeto'].pk}/",
        {
            "data_hora": "2026-12-01T14:00",
            "local": "Sala 9",
            "membro_1_professor": cenario["membro1"].pk,
            "membro_1_externo": "",
            "membro_2_professor": cenario["membro2"].pk,
            "membro_2_externo": "",
        },
    )
    assert resposta.status_code == 302
    assert Banca.objects.filter(projeto=cenario["projeto"]).exists()


@pytest.mark.django_db
def test_agendar_recusa_projeto_alheio_com_404(client, cenario):
    outro_professor = _professor(5, "Outro Professor Tela")
    client.force_login(outro_professor.usuario)
    resposta = client.get(f"/bancas/agendar/{cenario['projeto'].pk}/")
    assert resposta.status_code == 404


@pytest.mark.django_db
def test_cancelar_recusa_banca_alheia_com_404(client, cenario):
    banca = services.agendar_banca(
        cenario["projeto"],
        data_hora=timezone.now(),
        local="Sala 1",
        membros=[{"professor": cenario["membro1"]}, {"professor": cenario["membro2"]}],
        por=cenario["orientador"].usuario,
    )
    outro_professor = _professor(6, "Outro Professor Cancelar")
    client.force_login(outro_professor.usuario)
    resposta = client.post(f"/bancas/{banca.pk}/cancelar/")
    assert resposta.status_code == 404


@pytest.mark.django_db
def test_cancelar_duas_vezes_nao_da_500(client, cenario):
    """ACHADO H7 da auditoria (2026-09-22): a view não capturava o
    `ValidationError` de um duplo clique/reenvio — a segunda chamada batia
    num estado já cancelado e a view deixava o erro subir como 500. Prova
    por mutação: remover o `try/except` da view faz este teste reprovar
    com um 500 na segunda chamada."""
    banca = services.agendar_banca(
        cenario["projeto"],
        data_hora=timezone.now(),
        local="Sala 1",
        membros=[{"professor": cenario["membro1"]}, {"professor": cenario["membro2"]}],
        por=cenario["orientador"].usuario,
    )
    client.force_login(cenario["orientador"].usuario)
    primeira = client.post(f"/bancas/{banca.pk}/cancelar/")
    segunda = client.post(f"/bancas/{banca.pk}/cancelar/")
    assert primeira.status_code == 302
    assert segunda.status_code == 302


@pytest.mark.django_db
def test_resultado_post_registra_e_redireciona(client, cenario):
    banca = services.agendar_banca(
        cenario["projeto"],
        data_hora=timezone.now(),
        local="Sala 1",
        membros=[{"professor": cenario["membro1"]}, {"professor": cenario["membro2"]}],
        por=cenario["orientador"].usuario,
    )
    client.force_login(cenario["orientador"].usuario)
    resposta = client.post(
        f"/bancas/{banca.pk}/resultado/",
        {"nota": "8.0", "resultado": Projeto.APROVADO_COM_RESSALVAS, "comentario": "Ok."},
    )
    assert resposta.status_code == 302
    banca.refresh_from_db()
    assert banca.status == Banca.REALIZADA
