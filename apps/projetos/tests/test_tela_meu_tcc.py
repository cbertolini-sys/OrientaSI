import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse

from apps.contas.models import PerfilAluno, PerfilProfessor, Usuario
from apps.contas.validators import _digito
from apps.projetos.models import Projeto, Submissao


def _cpf_valido(base_int):
    base = f"{base_int:09d}"
    d1 = _digito(base, 10)
    d2 = _digito(base + str(d1), 11)
    return base + str(d1) + str(d2)


def _arquivo(nome):
    return SimpleUploadedFile(nome, b"conteudo")


@pytest.fixture
def aluno(db):
    usuario = Usuario.objects.create_user(
        email="aluno.meutcc@ufsm.br",
        password="x",
        nome_completo="Aluno Meu TCC",
        papel=Usuario.ALUNO,
        cpf=_cpf_valido(950000010),
    )
    PerfilAluno.objects.create(usuario=usuario, matricula="2026MTC0001")
    return usuario


@pytest.fixture
def professor(db):
    usuario = Usuario.objects.create_user(
        email="professor.meutcc@ufsm.br",
        password="x",
        nome_completo="Professor Meu TCC",
        cpf=_cpf_valido(950000011),
    )
    PerfilProfessor.objects.create(usuario=usuario, siape="9500011")
    return usuario


@pytest.fixture
def projeto(db, aluno, professor):
    return Projeto.objects.create(
        aluno=aluno, orientador=professor, etapa=Projeto.TCC_I, ano=2026, periodo=2
    )


@pytest.mark.django_db
def test_meu_tcc_sem_projeto_mostra_estado_vazio(client, aluno):
    client.force_login(aluno)
    resposta = client.get(reverse("projetos:meu_tcc"))
    assert resposta.status_code == 200
    assert "ainda não tem uma orientação em andamento" in resposta.content.decode()


@pytest.mark.django_db
def test_meu_tcc_com_projeto_mostra_formulario_de_envio(client, aluno, projeto):
    client.force_login(aluno)
    resposta = client.get(reverse("projetos:meu_tcc"))
    assert resposta.status_code == 200
    assert 'enctype="multipart/form-data"' in resposta.content.decode()


@pytest.mark.django_db
def test_meu_tcc_envia_submissao_pela_tela(client, aluno, projeto):
    client.force_login(aluno)
    resposta = client.post(
        reverse("projetos:meu_tcc"),
        {"pdf": _arquivo("trabalho.pdf"), "editavel": _arquivo("trabalho.docx")},
    )
    assert resposta.status_code == 302
    assert Submissao.objects.filter(projeto=projeto).exists()


@pytest.mark.django_db
def test_meu_tcc_reenvio_incrementa_versao_na_tela(client, aluno, projeto):
    client.force_login(aluno)
    client.post(
        reverse("projetos:meu_tcc"),
        {"pdf": _arquivo("v1.pdf"), "editavel": _arquivo("v1.docx")},
    )
    client.post(
        reverse("projetos:meu_tcc"),
        {"pdf": _arquivo("v2.pdf"), "editavel": _arquivo("v2.docx")},
    )
    submissao = Submissao.objects.get(projeto=projeto)
    assert submissao.versao == 2


@pytest.mark.django_db
def test_meu_tcc_envio_sem_editavel_e_recusado_pelo_formulario(client, aluno, projeto):
    client.force_login(aluno)
    resposta = client.post(reverse("projetos:meu_tcc"), {"pdf": _arquivo("trabalho.pdf")})
    assert resposta.status_code == 200
    assert not Submissao.objects.filter(projeto=projeto).exists()


@pytest.mark.django_db
def test_meu_tcc_recusa_professor_com_403(client, professor):
    client.force_login(professor)
    resposta = client.get(reverse("projetos:meu_tcc"))
    assert resposta.status_code == 403


@pytest.mark.django_db
def test_meu_tcc_recusa_papel_aluno_sem_perfil_com_403_nao_500(client):
    usuario_sem_perfil = Usuario.objects.create_user(
        email="sem.perfil.meutcc@ufsm.br",
        password="x",
        nome_completo="Sem Perfil Meu TCC",
        papel=Usuario.ALUNO,
        cpf=_cpf_valido(950000012),
    )
    client.force_login(usuario_sem_perfil)
    resposta = client.get(reverse("projetos:meu_tcc"))
    assert resposta.status_code == 403


@pytest.mark.django_db
def test_meu_tcc_mostra_correcoes_pendentes_e_botao_de_termo(client):
    from apps.bancas.models import ItemCorrecao

    aluno_usuario = Usuario.objects.create_user(
        email="aluno.meutccii.correcoes@ufsm.br",
        password="x",
        nome_completo="Aluno Meu TCC II Correções",
        papel=Usuario.ALUNO,
        cpf=_cpf_valido(950000020),
    )
    PerfilAluno.objects.create(usuario=aluno_usuario, matricula="2026MTC0020")
    professor_usuario = Usuario.objects.create_user(
        email="professor.meutccii.correcoes@ufsm.br",
        password="x",
        nome_completo="Professor Meu TCC II Correções",
        cpf=_cpf_valido(950000021),
    )
    PerfilProfessor.objects.create(usuario=professor_usuario, siape="9500021")
    projeto_tcc_ii = Projeto.objects.create(
        aluno=aluno_usuario,
        orientador=professor_usuario,
        etapa=Projeto.TCC_II,
        status=Projeto.APROVADO_COM_RESSALVAS,
        ano=2026,
        periodo=2,
    )
    ItemCorrecao.objects.create(projeto=projeto_tcc_ii, descricao="Ajustar a introdução.")

    client.force_login(aluno_usuario)
    resposta = client.get(reverse("projetos:meu_tcc"))
    conteudo = resposta.content.decode()
    assert "Ajustar a introdução." in conteudo
    assert "Assinar termo de aceite de publicação" in conteudo


@pytest.mark.django_db
def test_meu_tcc_assinar_termo_cria_a_linha(client):
    from apps.projetos.models import TermoPublicacao

    aluno_usuario = Usuario.objects.create_user(
        email="aluno.meutccii.termo@ufsm.br",
        password="x",
        nome_completo="Aluno Meu TCC II Termo",
        papel=Usuario.ALUNO,
        cpf=_cpf_valido(950000022),
    )
    PerfilAluno.objects.create(usuario=aluno_usuario, matricula="2026MTC0022")
    professor_usuario = Usuario.objects.create_user(
        email="professor.meutccii.termo@ufsm.br",
        password="x",
        nome_completo="Professor Meu TCC II Termo",
        cpf=_cpf_valido(950000023),
    )
    PerfilProfessor.objects.create(usuario=professor_usuario, siape="9500023")
    projeto_tcc_ii = Projeto.objects.create(
        aluno=aluno_usuario,
        orientador=professor_usuario,
        etapa=Projeto.TCC_II,
        status=Projeto.APROVADO_COM_RESSALVAS,
        ano=2026,
        periodo=2,
    )

    client.force_login(aluno_usuario)
    resposta = client.post(reverse("projetos:meu_tcc"), {"acao": "assinar_termo"})
    assert resposta.status_code == 302
    assert TermoPublicacao.objects.filter(projeto=projeto_tcc_ii).exists()
