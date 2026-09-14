import pytest
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import IntegrityError

from apps.comum.validators import valida_extensao_editavel, valida_extensao_pdf
from apps.contas.models import PerfilAluno, PerfilProfessor, Usuario
from apps.projetos.models import Projeto, Submissao


def _arquivo(nome, conteudo=b"conteudo"):
    return SimpleUploadedFile(nome, conteudo)


def test_valida_extensao_pdf_aceita_pdf():
    valida_extensao_pdf(_arquivo("trabalho.pdf"))  # não levanta


def test_valida_extensao_pdf_recusa_docx():
    with pytest.raises(ValidationError):
        valida_extensao_pdf(_arquivo("trabalho.docx"))


def test_valida_extensao_editavel_aceita_docx():
    valida_extensao_editavel(_arquivo("trabalho.docx"))  # não levanta


def test_valida_extensao_editavel_recusa_pdf():
    with pytest.raises(ValidationError):
        valida_extensao_editavel(_arquivo("trabalho.pdf"))


def _cpf_valido(base_int):
    """Gera um CPF sintético com dígitos verificadores válidos, a partir de
    um inteiro de 9 dígitos — mesmo algoritmo de `apps/contas/validators.py`.
    Índices acima de 950000000 para não colidir com faixas já usadas por
    outras suítes de `apps/projetos/tests/`."""
    from apps.contas.validators import _digito

    base = f"{base_int:09d}"
    d1 = _digito(base, 10)
    d2 = _digito(base + str(d1), 11)
    return base + str(d1) + str(d2)


@pytest.fixture
def projeto_em_andamento(db):
    aluno_usuario = Usuario.objects.create_user(
        email="aluno.submissao@ufsm.br",
        password="x",
        nome_completo="Aluno Submissão",
        papel=Usuario.ALUNO,
        cpf=_cpf_valido(950000001),
    )
    PerfilAluno.objects.create(usuario=aluno_usuario, matricula="2026SUB0001")
    professor_usuario = Usuario.objects.create_user(
        email="professor.submissao@ufsm.br",
        password="x",
        nome_completo="Professor Submissão",
        cpf=_cpf_valido(950000002),
    )
    PerfilProfessor.objects.create(usuario=professor_usuario, siape="9500001")
    return Projeto.objects.create(
        aluno=aluno_usuario,
        orientador=professor_usuario,
        etapa=Projeto.TCC_I,
        ano=2026,
        periodo=2,
    )


@pytest.mark.django_db
def test_submissao_uma_por_projeto(projeto_em_andamento):
    Submissao.objects.create(
        projeto=projeto_em_andamento,
        pdf=_arquivo("v1.pdf"),
        editavel=_arquivo("v1.docx"),
    )
    with pytest.raises(IntegrityError):  # UniqueConstraint implícito do OneToOneField
        Submissao.objects.create(
            projeto=projeto_em_andamento,
            pdf=_arquivo("v2.pdf"),
            editavel=_arquivo("v2.docx"),
        )


@pytest.mark.django_db
def test_submissao_nasce_com_versao_um(projeto_em_andamento):
    submissao = Submissao.objects.create(
        projeto=projeto_em_andamento,
        pdf=_arquivo("v1.pdf"),
        editavel=_arquivo("v1.docx"),
    )
    assert submissao.versao == 1
