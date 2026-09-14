import pytest
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import IntegrityError

from apps.comum.validators import valida_extensao_editavel, valida_extensao_pdf
from apps.contas.models import PerfilAluno, PerfilProfessor, Usuario
from apps.projetos import permissions, services
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


@pytest.fixture
def projeto_tcc_ii_com_ressalvas(db):
    aluno_usuario = Usuario.objects.create_user(
        email="aluno.submissao.tccii@ufsm.br",
        password="x",
        nome_completo="Aluno Submissão TCC II",
        papel=Usuario.ALUNO,
        cpf=_cpf_valido(950000006),
    )
    PerfilAluno.objects.create(usuario=aluno_usuario, matricula="2026SUB0006")
    professor_usuario = Usuario.objects.create_user(
        email="professor.submissao.tccii@ufsm.br",
        password="x",
        nome_completo="Professor Submissão TCC II",
        cpf=_cpf_valido(950000007),
    )
    PerfilProfessor.objects.create(usuario=professor_usuario, siape="9500007")
    return Projeto.objects.create(
        aluno=aluno_usuario,
        orientador=professor_usuario,
        etapa=Projeto.TCC_II,
        status=Projeto.APROVADO_COM_RESSALVAS,
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


@pytest.mark.django_db
def test_projeto_ativo_do_aluno_encontra_em_andamento(projeto_em_andamento):
    encontrado = services.projeto_ativo_do_aluno(projeto_em_andamento.aluno, Projeto.TCC_I)
    assert encontrado == projeto_em_andamento


@pytest.mark.django_db
def test_projeto_ativo_do_aluno_ignora_concluido(projeto_em_andamento):
    projeto_em_andamento.status = Projeto.CONCLUIDO
    projeto_em_andamento.save(update_fields=["status"])
    assert services.projeto_ativo_do_aluno(projeto_em_andamento.aluno, Projeto.TCC_I) is None


@pytest.mark.django_db
def test_projeto_ativo_do_aluno_sem_projeto_devolve_none(db):
    aluno = Usuario.objects.create_user(
        email="aluno.sem.projeto@ufsm.br",
        password="x",
        nome_completo="Aluno Sem Projeto",
        papel=Usuario.ALUNO,
        cpf=_cpf_valido(950000003),
    )
    assert services.projeto_ativo_do_aluno(aluno, Projeto.TCC_I) is None


@pytest.mark.django_db
def test_pode_enviar_submissao_e_o_dono_do_projeto(projeto_em_andamento):
    assert permissions.pode_enviar_submissao(projeto_em_andamento.aluno, projeto_em_andamento)


@pytest.mark.django_db
def test_pode_enviar_submissao_recusa_quem_nao_e_dono(projeto_em_andamento):
    outro = Usuario.objects.create_user(
        email="outro.aluno.submissao@ufsm.br",
        password="x",
        nome_completo="Outro Aluno",
        papel=Usuario.ALUNO,
        cpf=_cpf_valido(950000004),
    )
    assert not permissions.pode_enviar_submissao(outro, projeto_em_andamento)


@pytest.mark.django_db
def test_enviar_submissao_cria_na_primeira_vez(projeto_em_andamento):
    submissao = services.enviar_submissao(
        projeto_em_andamento,
        por=projeto_em_andamento.aluno,
        pdf=_arquivo("v1.pdf"),
        editavel=_arquivo("v1.docx"),
    )
    assert submissao.versao == 1
    assert submissao.projeto == projeto_em_andamento


@pytest.mark.django_db
def test_enviar_submissao_reenvio_atualiza_e_incrementa_versao(projeto_em_andamento):
    primeira = services.enviar_submissao(
        projeto_em_andamento,
        por=projeto_em_andamento.aluno,
        pdf=_arquivo("v1.pdf"),
        editavel=_arquivo("v1.docx"),
    )
    segunda = services.enviar_submissao(
        projeto_em_andamento,
        por=projeto_em_andamento.aluno,
        pdf=_arquivo("v2.pdf"),
        editavel=_arquivo("v2.docx"),
    )
    assert segunda.pk == primeira.pk
    assert segunda.versao == 2
    # `Submissao` já está importado no topo do arquivo (Tarefa 1, Passo 5).
    assert Submissao.objects.filter(projeto=projeto_em_andamento).count() == 1


@pytest.mark.django_db
def test_enviar_submissao_recusa_quem_nao_e_dono(projeto_em_andamento):
    outro = Usuario.objects.create_user(
        email="outro.aluno.enviar@ufsm.br",
        password="x",
        nome_completo="Outro Aluno Enviar",
        papel=Usuario.ALUNO,
        cpf=_cpf_valido(950000005),
    )
    with pytest.raises(PermissionDenied):
        services.enviar_submissao(
            projeto_em_andamento, por=outro, pdf=_arquivo("v1.pdf"), editavel=_arquivo("v1.docx")
        )


@pytest.mark.django_db
def test_enviar_submissao_recusa_fora_de_em_andamento(projeto_em_andamento):
    """Mutação obrigatória (Global Constraints): hoje nenhum outro status é
    alcançável em produção (o Bloco D ainda não existe), mas este teste cria
    o `Projeto` DIRETAMENTE com outro status, sem depender do Bloco D — a
    checagem precisa de prova mesmo sendo hoje inalcançável pelo fluxo real
    (spec §5.1)."""
    projeto_em_andamento.status = Projeto.AGUARDANDO_DEFESA
    projeto_em_andamento.save(update_fields=["status"])
    with pytest.raises(ValidationError):
        services.enviar_submissao(
            projeto_em_andamento,
            por=projeto_em_andamento.aluno,
            pdf=_arquivo("v1.pdf"),
            editavel=_arquivo("v1.docx"),
        )


@pytest.mark.django_db
def test_enviar_submissao_aceita_reenvio_em_aprovado_com_ressalvas_para_tcc_ii(
    projeto_tcc_ii_com_ressalvas,
):
    submissao = services.enviar_submissao(
        projeto_tcc_ii_com_ressalvas,
        por=projeto_tcc_ii_com_ressalvas.aluno,
        pdf=_arquivo("corrigido.pdf"),
        editavel=_arquivo("corrigido.docx"),
    )
    assert submissao.versao == 1


@pytest.mark.django_db
def test_enviar_submissao_recusa_tcc_ii_fora_dos_status_permitidos(projeto_tcc_ii_com_ressalvas):
    """Mutação obrigatória: prova que a exceção é específica de
    `APROVADO_COM_RESSALVAS`, não "qualquer status" para TCC_II."""
    projeto_tcc_ii_com_ressalvas.status = Projeto.AGUARDANDO_DEFESA
    projeto_tcc_ii_com_ressalvas.save(update_fields=["status"])
    with pytest.raises(ValidationError):
        services.enviar_submissao(
            projeto_tcc_ii_com_ressalvas,
            por=projeto_tcc_ii_com_ressalvas.aluno,
            pdf=_arquivo("v1.pdf"),
            editavel=_arquivo("v1.docx"),
        )
