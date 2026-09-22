"""Testes de `services.gerar_ata` (Bloco E, spec §5.2)."""

import pytest
from django.utils import timezone

from apps.bancas.models import Banca
from apps.contas.models import PerfilAluno, PerfilProfessor, Usuario
from apps.contas.validators import _digito
from apps.documentos import services
from apps.documentos.models import RevisaoSUGRAD
from apps.projetos.models import Projeto


def _cpf(indice):
    base = f"{720000000 + indice:09d}"
    d1 = _digito(base, 10)
    d2 = _digito(base + str(d1), 11)
    return base + str(d1) + str(d2)


def _cria_projeto_aprovado(indice_aluno, indice_professor):
    aluno = Usuario.objects.create_user(
        email=f"aluno.gerarata.{indice_aluno}@ufsm.br",
        password="x",
        nome_completo=f"Aluno Gerar Ata {indice_aluno}",
        papel=Usuario.ALUNO,
        cpf=_cpf(indice_aluno),
    )
    PerfilAluno.objects.create(usuario=aluno, matricula=f"2026GERAR{indice_aluno:02d}")
    professor = Usuario.objects.create_user(
        email=f"professor.gerarata.{indice_professor}@ufsm.br",
        password="x",
        nome_completo=f"Professor Gerar Ata {indice_professor}",
        cpf=_cpf(indice_professor),
    )
    PerfilProfessor.objects.create(usuario=professor, siape=f"GERAR{indice_professor:03d}")
    projeto = Projeto.objects.create(
        aluno=aluno,
        orientador=professor,
        etapa=Projeto.TCC_I,
        status=Projeto.APROVADO,
        ano=2026,
        periodo=1,
    )
    Banca.objects.create(
        projeto=projeto,
        data_hora=timezone.now(),
        local="Sala 1",
        status=Banca.REALIZADA,
        nota=8.5,
        resultado=Projeto.APROVADO_COM_RESSALVAS,
        comentario="Boa apresentação.",
    )
    return projeto


@pytest.mark.django_db
def test_gerar_ata_cria_ata_com_pdf_valido():
    projeto = _cria_projeto_aprovado(1, 2)
    ata = services.gerar_ata(projeto)
    assert ata.pdf.name
    with ata.pdf.open("rb") as arquivo:
        conteudo = arquivo.read()
    assert conteudo.startswith(b"%PDF-")


@pytest.mark.django_db
def test_gerar_ata_cria_revisao_pendente():
    projeto = _cria_projeto_aprovado(3, 4)
    ata = services.gerar_ata(projeto)
    assert ata.revisao.status == RevisaoSUGRAD.PENDENTE


@pytest.mark.django_db
def test_gerar_ata_numeracao_sequencial_no_mesmo_ano():
    projeto1 = _cria_projeto_aprovado(5, 6)
    projeto2 = _cria_projeto_aprovado(7, 8)
    ata1 = services.gerar_ata(projeto1)
    ata2 = services.gerar_ata(projeto2)
    ano_atual = ata1.gerada_em.year
    numero1 = int(ata1.numero.split("/")[0])
    numero2 = int(ata2.numero.split("/")[0])
    assert ata1.numero.endswith(f"/{ano_atual}")
    assert numero2 == numero1 + 1


@pytest.mark.django_db
def test_gerar_ata_converte_colisao_de_numero_em_validationerror(monkeypatch):
    """ACHADO M1 da auditoria (2026-09-22): `Ata.numero` tem `unique=True`
    como retaguarda contra a corrida documentada de `count()+1` (custo
    aceito, spec §4.1) — antes desta trava, a colisão era gravada em
    silêncio (dois documentos oficiais com o mesmo número); agora vira
    `IntegrityError`, traduzido para `ValidationError` (achado M-2 da
    re-auditoria: a tradução agora inspeciona `constraint_name`, mesmo
    padrão de `agendar_banca`/`criar_tcc_ii_automatico`, em vez de assumir
    que todo `IntegrityError` daqui é a colisão de número). Reproduz a
    colisão sem depender de threads: força o `count()` do segundo
    `gerar_ata` a repetir o mesmo resultado do primeiro."""
    from django.core.exceptions import ValidationError

    projeto1 = _cria_projeto_aprovado(11, 12)
    projeto2 = _cria_projeto_aprovado(13, 14)
    services.gerar_ata(projeto1)

    # Força a MESMA colisão que a corrida real produziria: o próximo
    # `count()+1` de `gerar_ata` calcula o número que já foi usado.
    monkeypatch.setattr(
        services.Ata.objects, "filter", lambda **kwargs: services.Ata.objects.none()
    )
    with pytest.raises(ValidationError):
        services.gerar_ata(projeto2)


@pytest.mark.django_db
def test_gerar_ata_usa_a_banca_nao_cancelada():
    projeto = _cria_projeto_aprovado(9, 10)
    banca_cancelada = Banca.objects.create(
        projeto=projeto,
        data_hora=timezone.now(),
        local="Sala Cancelada",
        status=Banca.CANCELADA,
    )
    ata = services.gerar_ata(projeto)
    assert ata.banca_id != banca_cancelada.id
    assert ata.banca.status == Banca.REALIZADA
