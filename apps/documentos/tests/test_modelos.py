"""Testes de modelo do Bloco E (spec §4): `Ata`/`RevisaoSUGRAD` e o vínculo
`OneToOneField` entre elas."""

import pytest
from django.db import IntegrityError
from django.utils import timezone

from apps.bancas.models import Banca
from apps.contas.models import PerfilAluno, PerfilProfessor, Usuario
from apps.contas.validators import _digito
from apps.documentos.models import Ata, RevisaoSUGRAD
from apps.projetos.models import Projeto


def _cpf(indice):
    """CPF sintético com dígitos verificadores válidos, faixa 700000000+ —
    livre (conferida por grep) para os testes de `apps/documentos/`."""
    base = f"{700000000 + indice:09d}"
    d1 = _digito(base, 10)
    d2 = _digito(base + str(d1), 11)
    return base + str(d1) + str(d2)


@pytest.fixture
def projeto_aprovado(db):
    aluno = Usuario.objects.create_user(
        email="aluno.ata.modelo@ufsm.br",
        password="x",
        nome_completo="Aluno Ata Modelo",
        papel=Usuario.ALUNO,
        cpf=_cpf(1),
    )
    PerfilAluno.objects.create(usuario=aluno, matricula="2026ATA001")
    professor = Usuario.objects.create_user(
        email="professor.ata.modelo@ufsm.br",
        password="x",
        nome_completo="Professor Ata Modelo",
        cpf=_cpf(2),
    )
    PerfilProfessor.objects.create(usuario=professor, siape="ATA0001")
    projeto = Projeto.objects.create(
        aluno=aluno,
        orientador=professor,
        etapa=Projeto.TCC_I,
        status=Projeto.APROVADO,
        ano=2026,
        periodo=1,
    )
    banca = Banca.objects.create(
        projeto=projeto,
        data_hora=timezone.now(),
        local="Sala 1",
        status=Banca.REALIZADA,
        nota=8.5,
        resultado=Projeto.APROVADO_COM_RESSALVAS,
    )
    return projeto, banca


@pytest.mark.django_db
def test_ata_criada_com_revisao_pendente(projeto_aprovado):
    projeto, banca = projeto_aprovado
    ata = Ata.objects.create(projeto=projeto, banca=banca, numero="001/2026")
    revisao = RevisaoSUGRAD.objects.create(ata=ata)
    assert revisao.status == RevisaoSUGRAD.PENDENTE
    assert revisao.comentario == ""
    assert revisao.decidida_em is None


@pytest.mark.django_db
def test_ata_numero_e_unico(projeto_aprovado):
    """ACHADO M1 da auditoria (2026-09-22): antes não havia NENHUMA trava
    de banco contra dois documentos oficiais com o mesmo número — a
    colisão sob concorrência (custo aceito, spec §4.1) ou sob deleção pelo
    admin (`count()` não é monotônico) era gravada em silêncio. Prova por
    mutação: reverter `Ata.numero` para `unique=False` faz este teste
    reprovar (a segunda criação teria sucesso em vez de levantar)."""
    projeto, banca = projeto_aprovado
    Ata.objects.create(projeto=projeto, banca=banca, numero="003/2026")
    with pytest.raises(IntegrityError):
        Ata.objects.create(projeto=projeto, banca=banca, numero="003/2026")


@pytest.mark.django_db
def test_ata_str_inclui_numero(projeto_aprovado):
    projeto, banca = projeto_aprovado
    ata = Ata.objects.create(projeto=projeto, banca=banca, numero="002/2026")
    assert "002/2026" in str(ata)


def test_revisao_sugrad_tem_tres_status():
    assert RevisaoSUGRAD.PENDENTE == "PENDENTE"
    assert RevisaoSUGRAD.APROVADA == "APROVADA"
    assert RevisaoSUGRAD.DEVOLVIDA == "DEVOLVIDA"
