"""Testes de `/orientacoes/` mostrando as ações de cada estado do Bloco D
(spec §7): agendar (EM_ANDAMENTO com submissão), editar/cancelar/registrar
resultado (AGUARDANDO_DEFESA), reabrir/cancelar (REPROVADO)."""

import pytest
from django.utils import timezone

from apps.comum.semestre import semestre_vigente
from apps.contas.models import PerfilAluno, PerfilProfessor, Usuario
from apps.contas.validators import _digito
from apps.projetos.models import Projeto, Submissao


def _cpf(indice):
    base = f"{680000000 + indice:09d}"
    d1 = _digito(base, 10)
    d2 = _digito(base + str(d1), 11)
    return base + str(d1) + str(d2)


def _professor(indice, nome):
    usuario = Usuario.objects.create_user(
        email=f"professor.orientacoesbancas.{indice}@ufsm.br",
        password="x",
        nome_completo=nome,
        cpf=_cpf(indice),
    )
    return PerfilProfessor.objects.create(usuario=usuario, siape=f"ORIB{indice:03d}")


def _aluno(indice, nome):
    usuario = Usuario.objects.create_user(
        email=f"aluno.orientacoesbancas.{indice}@ufsm.br",
        password="x",
        nome_completo=nome,
        papel=Usuario.ALUNO,
        cpf=_cpf(indice),
    )
    PerfilAluno.objects.create(usuario=usuario, matricula=f"2026ORIB{indice:03d}")
    return usuario


@pytest.mark.django_db
def test_orientacoes_mostra_agendar_banca_para_em_andamento_com_submissao(client):
    orientador = _professor(1, "Orientador Agendar Link")
    aluno = _aluno(2, "Aluno Agendar Link")
    ano, periodo = semestre_vigente()
    projeto = Projeto.objects.create(
        aluno=aluno,
        orientador=orientador.usuario,
        etapa=Projeto.TCC_I,
        status=Projeto.EM_ANDAMENTO,
        ano=ano,
        periodo=periodo,
    )
    Submissao.objects.create(
        projeto=projeto, pdf="submissoes/v1.pdf", editavel="submissoes/v1.docx"
    )
    client.force_login(orientador.usuario)
    resposta = client.get("/orientacoes/")
    assert f"/bancas/agendar/{projeto.pk}/" in resposta.content.decode()


@pytest.mark.django_db
def test_orientacoes_mostra_acoes_de_aguardando_defesa(client):
    orientador = _professor(3, "Orientador Aguardando Link")
    aluno = _aluno(4, "Aluno Aguardando Link")
    ano, periodo = semestre_vigente()
    projeto = Projeto.objects.create(
        aluno=aluno,
        orientador=orientador.usuario,
        etapa=Projeto.TCC_I,
        status=Projeto.EM_ANDAMENTO,
        ano=ano,
        periodo=periodo,
    )
    Submissao.objects.create(
        projeto=projeto, pdf="submissoes/v1.pdf", editavel="submissoes/v1.docx"
    )
    membro1 = _professor(5, "Membro Aguardando Um")
    membro2 = _professor(6, "Membro Aguardando Dois")
    from apps.bancas import services as banca_services

    banca = banca_services.agendar_banca(
        projeto,
        data_hora=timezone.now(),
        local="Sala 7",
        membros=[{"professor": membro1}, {"professor": membro2}],
        por=orientador.usuario,
    )
    client.force_login(orientador.usuario)
    conteudo = client.get("/orientacoes/").content.decode()
    assert f"/bancas/{banca.pk}/editar/" in conteudo
    assert f"/bancas/{banca.pk}/cancelar/" in conteudo
    assert f"/bancas/{banca.pk}/resultado/" in conteudo


@pytest.mark.django_db
def test_orientacoes_mostra_reabrir_e_cancelar_para_reprovado(client):
    """Um `Projeto` `REPROVADO` de verdade sempre tem uma `Banca` `REALIZADA`
    por trás (`registrar_resultado` é o único jeito de chegar a REPROVADO) —
    o teste passa pelo fluxo real, não só seta `status=REPROVADO` direto,
    porque `orientacoes.html` usa `projeto.banca_ativa` para decidir esse
    ramo, e sem uma `Banca` de verdade `banca_ativa` fica `None`."""
    orientador = _professor(7, "Orientador Reprovado Link")
    aluno = _aluno(8, "Aluno Reprovado Link")
    ano, periodo = semestre_vigente()
    projeto = Projeto.objects.create(
        aluno=aluno,
        orientador=orientador.usuario,
        etapa=Projeto.TCC_I,
        status=Projeto.EM_ANDAMENTO,
        ano=ano,
        periodo=periodo,
    )
    Submissao.objects.create(
        projeto=projeto, pdf="submissoes/v1.pdf", editavel="submissoes/v1.docx"
    )
    membro1 = _professor(14, "Membro Reprovado Um")
    membro2 = _professor(15, "Membro Reprovado Dois")
    from apps.bancas import services as banca_services

    banca = banca_services.agendar_banca(
        projeto,
        data_hora=timezone.now(),
        local="Sala 8",
        membros=[{"professor": membro1}, {"professor": membro2}],
        por=orientador.usuario,
    )
    banca_services.registrar_resultado(
        banca,
        nota=3.0,
        resultado=Projeto.REPROVADO,
        comentario="Não atendeu aos critérios.",
        por=orientador.usuario,
    )
    client.force_login(orientador.usuario)
    conteudo = client.get("/orientacoes/").content.decode()
    assert f"/orientacoes/{projeto.pk}/reabrir/" in conteudo
    assert f"/orientacoes/{projeto.pk}/cancelar/" in conteudo


@pytest.mark.django_db
def test_reabrir_projeto_view_redireciona(client):
    orientador = _professor(9, "Orientador Reabrir View")
    aluno = _aluno(10, "Aluno Reabrir View")
    projeto = Projeto.objects.create(
        aluno=aluno,
        orientador=orientador.usuario,
        etapa=Projeto.TCC_I,
        status=Projeto.REPROVADO,
        ano=2026,
        periodo=1,
    )
    client.force_login(orientador.usuario)
    resposta = client.post(f"/orientacoes/{projeto.pk}/reabrir/")
    assert resposta.status_code == 302
    projeto.refresh_from_db()
    assert projeto.status == Projeto.EM_ANDAMENTO


@pytest.mark.django_db
def test_cancelar_projeto_view_recusa_projeto_alheio_com_404(client):
    orientador = _professor(11, "Orientador Cancelar View")
    outro = _professor(12, "Outro Professor Cancelar View")
    aluno = _aluno(13, "Aluno Cancelar View")
    projeto = Projeto.objects.create(
        aluno=aluno,
        orientador=orientador.usuario,
        etapa=Projeto.TCC_I,
        status=Projeto.REPROVADO,
        ano=2026,
        periodo=1,
    )
    client.force_login(outro.usuario)
    resposta = client.post(f"/orientacoes/{projeto.pk}/cancelar/")
    assert resposta.status_code == 404
