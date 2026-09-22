"""Testes dos dois caminhos a partir de `Projeto.REPROVADO` (Bloco D, spec
§3.6) e do filtro ampliado de `orientandos_atuais` (spec §3.7)."""

import pytest
from django.core.exceptions import PermissionDenied, ValidationError

from apps.comum.semestre import semestre_vigente
from apps.contas.models import PerfilAluno, PerfilProfessor, Usuario
from apps.contas.validators import _digito
from apps.projetos import services
from apps.projetos.models import Projeto


def _cpf(indice):
    base = f"{640000000 + indice:09d}"
    d1 = _digito(base, 10)
    d2 = _digito(base + str(d1), 11)
    return base + str(d1) + str(d2)


def _professor(indice, nome):
    usuario = Usuario.objects.create_user(
        email=f"professor.reprovacao.{indice}@ufsm.br",
        password="x",
        nome_completo=nome,
        cpf=_cpf(indice),
    )
    return PerfilProfessor.objects.create(usuario=usuario, siape=f"REPROV{indice:03d}")


def _aluno(indice, nome):
    usuario = Usuario.objects.create_user(
        email=f"aluno.reprovacao.{indice}@ufsm.br",
        password="x",
        nome_completo=nome,
        papel=Usuario.ALUNO,
        cpf=_cpf(indice),
    )
    PerfilAluno.objects.create(usuario=usuario, matricula=f"2026REPROV{indice:02d}")
    return usuario


@pytest.fixture
def orientador(db):
    return _professor(1, "Orientador Reprovação")


@pytest.fixture
def projeto_reprovado(db, orientador):
    ano, periodo = semestre_vigente()
    aluno = _aluno(2, "Aluno Reprovado")
    return Projeto.objects.create(
        aluno=aluno,
        orientador=orientador.usuario,
        etapa=Projeto.TCC_I,
        status=Projeto.REPROVADO,
        ano=ano,
        periodo=periodo,
    )


@pytest.mark.django_db
def test_reabrir_projeto_volta_para_em_andamento(projeto_reprovado, orientador):
    services.reabrir_projeto(projeto_reprovado, por=orientador.usuario)
    projeto_reprovado.refresh_from_db()
    assert projeto_reprovado.status == Projeto.EM_ANDAMENTO


@pytest.mark.django_db
def test_reabrir_projeto_recusa_quem_nao_e_o_orientador(projeto_reprovado):
    outro = Usuario.objects.create_user(
        email="outro.reabrir@ufsm.br", password="x", nome_completo="Outro Reabrir", cpf=_cpf(3)
    )
    with pytest.raises(PermissionDenied):
        services.reabrir_projeto(projeto_reprovado, por=outro)


@pytest.mark.django_db
def test_reabrir_projeto_recusa_fora_de_reprovado(projeto_reprovado, orientador):
    projeto_reprovado.status = Projeto.EM_ANDAMENTO
    projeto_reprovado.save()
    with pytest.raises(ValidationError):
        services.reabrir_projeto(projeto_reprovado, por=orientador.usuario)


@pytest.mark.django_db
def test_cancelar_projeto_marca_cancelado(projeto_reprovado, orientador):
    services.cancelar_projeto(projeto_reprovado, por=orientador.usuario)
    projeto_reprovado.refresh_from_db()
    assert projeto_reprovado.status == Projeto.CANCELADO


@pytest.mark.django_db
def test_cancelar_projeto_recusa_quem_nao_e_o_orientador(projeto_reprovado):
    outro = Usuario.objects.create_user(
        email="outro.cancelarprojeto@ufsm.br",
        password="x",
        nome_completo="Outro Cancelar Projeto",
        cpf=_cpf(4),
    )
    with pytest.raises(PermissionDenied):
        services.cancelar_projeto(projeto_reprovado, por=outro)


@pytest.mark.django_db
def test_reabrir_projeto_view_duas_vezes_nao_da_500(client, projeto_reprovado, orientador):
    """ACHADO H7 da auditoria (2026-09-22): a view não capturava o
    `ValidationError` de um duplo clique — a segunda chamada batia num
    projeto que já não está mais `REPROVADO` e vazava como 500."""
    client.force_login(orientador.usuario)
    primeira = client.post(f"/orientacoes/{projeto_reprovado.pk}/reabrir/")
    segunda = client.post(f"/orientacoes/{projeto_reprovado.pk}/reabrir/")
    assert primeira.status_code == 302
    assert segunda.status_code == 302


@pytest.mark.django_db
def test_cancelar_projeto_view_duas_vezes_nao_da_500(client, projeto_reprovado, orientador):
    """ACHADO H7: mesma razão de `test_reabrir_projeto_view_duas_vezes_nao_da_500`."""
    client.force_login(orientador.usuario)
    primeira = client.post(f"/orientacoes/{projeto_reprovado.pk}/cancelar/")
    segunda = client.post(f"/orientacoes/{projeto_reprovado.pk}/cancelar/")
    assert primeira.status_code == 302
    assert segunda.status_code == 302


@pytest.mark.django_db
def test_orientandos_atuais_inclui_aguardando_defesa_e_reprovado(orientador):
    ano, periodo = semestre_vigente()
    aluno_aguardando = _aluno(5, "Aluno Aguardando Defesa")
    Projeto.objects.create(
        aluno=aluno_aguardando,
        orientador=orientador.usuario,
        etapa=Projeto.TCC_I,
        status=Projeto.AGUARDANDO_DEFESA,
        ano=ano,
        periodo=periodo,
    )
    aluno_reprovado = _aluno(6, "Aluno Reprovado Dois")
    Projeto.objects.create(
        aluno=aluno_reprovado,
        orientador=orientador.usuario,
        etapa=Projeto.TCC_I,
        status=Projeto.REPROVADO,
        ano=ano,
        periodo=periodo,
    )
    resultado = {p.aluno_id for p in services.orientandos_atuais(orientador)}
    assert aluno_aguardando.id in resultado
    assert aluno_reprovado.id in resultado


@pytest.mark.django_db
def test_orientandos_atuais_exclui_cancelado(orientador):
    ano, periodo = semestre_vigente()
    aluno_cancelado = _aluno(7, "Aluno Cancelado")
    Projeto.objects.create(
        aluno=aluno_cancelado,
        orientador=orientador.usuario,
        etapa=Projeto.TCC_I,
        status=Projeto.CANCELADO,
        ano=ano,
        periodo=periodo,
    )
    resultado = {p.aluno_id for p in services.orientandos_atuais(orientador)}
    assert aluno_cancelado.id not in resultado


@pytest.mark.django_db
def test_orientacoes_view_projeto_reaberto_oferece_agendar_banca_nao_reabrir(
    client, orientador
):
    """ACHADO H-1 da re-auditoria (2026-09-22): o achado C1 corrigiu a
    constraint de banco para permitir uma banca NOVA depois de
    `reabrir_projeto`, mas o template `orientacoes.html` continuava
    mostrando o card do projeto REABERTO (`EM_ANDAMENTO`) como se ele ainda
    estivesse `REPROVADO` — `projeto.banca_ativa` aponta para a banca
    REALIZADA antiga (histórico), e o ramo `{% elif projeto.banca_ativa %}`
    não checava `projeto.status`, capturando também o estado reaberto. O
    fix de C1 ficava inalcançável pela tela: sem o link "Agendar banca",
    só "Reabrir projeto"/"Cancelar definitivamente" — clicar "Reabrir"
    de novo batia na `ValidationError` de status. Prova por mutação:
    remover `and projeto.status == "REPROVADO"` do template faz este teste
    reprovar (o botão errado apareceria)."""
    from django.utils import timezone

    from apps.bancas import services as bancas_services

    aluno = _aluno(8, "Aluno Reaberto View")
    from apps.projetos.models import Submissao

    projeto = Projeto.objects.create(
        aluno=aluno,
        orientador=orientador.usuario,
        etapa=Projeto.TCC_I,
        status=Projeto.EM_ANDAMENTO,
        ano=2026,
        periodo=1,
    )
    Submissao.objects.create(
        projeto=projeto, pdf="submissoes/reaberto.pdf", editavel="submissoes/reaberto.docx"
    )
    membro1 = Usuario.objects.create_user(
        email="membro1.reaberto@ufsm.br", password="x", nome_completo="Membro Um", cpf=_cpf(9)
    )
    perfil_membro1 = PerfilProfessor.objects.create(usuario=membro1, siape="REABERTO01")
    membro2 = Usuario.objects.create_user(
        email="membro2.reaberto@ufsm.br", password="x", nome_completo="Membro Dois", cpf=_cpf(10)
    )
    perfil_membro2 = PerfilProfessor.objects.create(usuario=membro2, siape="REABERTO02")

    banca = bancas_services.agendar_banca(
        projeto,
        data_hora=timezone.now(),
        local="Sala 1",
        membros=[{"professor": perfil_membro1}, {"professor": perfil_membro2}],
        por=orientador.usuario,
    )
    bancas_services.registrar_resultado(
        banca, nota=4.0, resultado=Projeto.REPROVADO, comentario="Não convenceu.",
        por=orientador.usuario,
    )
    services.reabrir_projeto(projeto, por=orientador.usuario)

    client.force_login(orientador.usuario)
    html = client.get("/orientacoes/").content.decode()

    assert "Agendar banca" in html
    assert "Reabrir projeto" not in html
    assert "Cancelar definitivamente" not in html
