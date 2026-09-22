"""Testes de `services.registrar_resultado` (Bloco D, spec §5.1)."""

import pytest
from django.core.exceptions import PermissionDenied, ValidationError
from django.utils import timezone

from apps.bancas import services
from apps.bancas.models import Banca
from apps.contas.models import PerfilAluno, PerfilProfessor, Usuario
from apps.contas.validators import _digito
from apps.projetos.models import Projeto, Submissao


def _cpf(indice):
    base = f"{630000000 + indice:09d}"
    d1 = _digito(base, 10)
    d2 = _digito(base + str(d1), 11)
    return base + str(d1) + str(d2)


def _professor(indice, nome):
    usuario = Usuario.objects.create_user(
        email=f"professor.resultado.{indice}@ufsm.br",
        password="x",
        nome_completo=nome,
        cpf=_cpf(indice),
    )
    return PerfilProfessor.objects.create(usuario=usuario, siape=f"RESULT{indice:03d}")


@pytest.fixture
def orientador(db):
    return _professor(1, "Orientador Resultado")


@pytest.fixture
def banca_agendada(db, orientador):
    aluno = Usuario.objects.create_user(
        email="aluno.resultado@ufsm.br",
        password="x",
        nome_completo="Aluno Resultado",
        papel=Usuario.ALUNO,
        cpf=_cpf(2),
    )
    PerfilAluno.objects.create(usuario=aluno, matricula="2026RESULT01")
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
    membro1 = _professor(3, "Membro Resultado Um")
    membro2 = _professor(4, "Membro Resultado Dois")
    return services.agendar_banca(
        projeto,
        data_hora=timezone.now(),
        local="Sala 1",
        membros=[{"professor": membro1}, {"professor": membro2}],
        por=orientador.usuario,
    )


@pytest.mark.django_db
def test_registrar_resultado_aprovado_com_ressalvas(banca_agendada, orientador):
    services.registrar_resultado(
        banca_agendada,
        nota=8.5,
        resultado=Projeto.APROVADO_COM_RESSALVAS,
        comentario="Boa apresentação, ajustar a conclusão.",
        por=orientador.usuario,
    )
    banca_agendada.refresh_from_db()
    assert banca_agendada.status == Banca.REALIZADA
    assert str(banca_agendada.nota) == "8.5"
    banca_agendada.projeto.refresh_from_db()
    assert banca_agendada.projeto.status == Projeto.APROVADO_COM_RESSALVAS


@pytest.mark.django_db
def test_registrar_resultado_reprovado(banca_agendada, orientador):
    services.registrar_resultado(
        banca_agendada,
        nota=3.0,
        resultado=Projeto.REPROVADO,
        comentario="Não atendeu aos critérios mínimos.",
        por=orientador.usuario,
    )
    banca_agendada.projeto.refresh_from_db()
    assert banca_agendada.projeto.status == Projeto.REPROVADO


@pytest.mark.django_db
def test_registrar_resultado_recusa_quem_nao_e_o_orientador(banca_agendada):
    outro = Usuario.objects.create_user(
        email="outro.resultado@ufsm.br", password="x", nome_completo="Outro Resultado", cpf=_cpf(5)
    )
    with pytest.raises(PermissionDenied):
        services.registrar_resultado(
            banca_agendada,
            nota=7.0,
            resultado=Projeto.APROVADO_COM_RESSALVAS,
            comentario="",
            por=outro,
        )


@pytest.mark.django_db
def test_registrar_resultado_recusa_valor_fora_da_whitelist(banca_agendada, orientador):
    """ACHADO M2 da auditoria (2026-09-22): antes, `resultado` era gravado
    direto em `Projeto.status` sem checagem nenhuma na camada de serviço —
    só o formulário restringia os valores possíveis (`Banca.resultado` tem
    `choices`, mas `choices` não é trava de banco). Um chamador de serviço
    que não passasse pelo formulário conseguia jogar o projeto em qualquer
    string de até 22 caracteres, inclusive `CONCLUIDO` — pulando a banca, a
    ata e a SUGRAD inteiras."""
    with pytest.raises(ValidationError):
        services.registrar_resultado(
            banca_agendada,
            nota=10.0,
            resultado=Projeto.CONCLUIDO,
            comentario="",
            por=orientador.usuario,
        )
    banca_agendada.refresh_from_db()
    assert banca_agendada.status == Banca.AGENDADA
    banca_agendada.projeto.refresh_from_db()
    assert banca_agendada.projeto.status == Projeto.AGUARDANDO_DEFESA


@pytest.mark.django_db
def test_registrar_resultado_recusa_quando_projeto_nao_esta_aguardando_defesa(
    banca_agendada, orientador
):
    """ACHADO M2: a função confiava só em `banca.status == AGENDADA` como
    proxy do status do projeto. Este teste força a assimetria diretamente
    (sem passar por outro serviço) para provar que a checagem nova é quem
    barra, não alguma trava vizinha."""
    banca_agendada.projeto.status = Projeto.EM_ANDAMENTO
    banca_agendada.projeto.save(update_fields=["status"])
    with pytest.raises(ValidationError):
        services.registrar_resultado(
            banca_agendada,
            nota=8.0,
            resultado=Projeto.APROVADO_COM_RESSALVAS,
            comentario="",
            por=orientador.usuario,
        )


@pytest.mark.django_db
def test_registrar_resultado_recusa_duas_vezes(banca_agendada, orientador):
    services.registrar_resultado(
        banca_agendada,
        nota=8.0,
        resultado=Projeto.APROVADO_COM_RESSALVAS,
        comentario="Ok.",
        por=orientador.usuario,
    )
    with pytest.raises(ValidationError):
        services.registrar_resultado(
            banca_agendada,
            nota=9.0,
            resultado=Projeto.APROVADO_COM_RESSALVAS,
            comentario="De novo.",
            por=orientador.usuario,
        )
