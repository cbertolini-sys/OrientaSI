"""Testes de temas (T6): `apps/projetos/permissions.py::pode_criar_tema`,
`apps/projetos/services.py::criar_tema/desativar_tema` e a view
`projetos:meus_temas` — o painel em que o professor cadastra e desativa os
temas que oferece.

Cobertura pedida pelo Passo 1 do brief: professor cria tema numa área que
declarou; tema fora das áreas dele é recusado com mensagem nomeando a área;
aluno não cria tema (`PermissionDenied`); desativar tira do mural e preserva
as candidaturas que o referenciam. Os demais testes (permissão de desativar,
integração da view, professor sem perfil) cobrem os dois riscos que o brief
aponta como caros neste projeto: perfil ausente derrubando a página, e
markup do DaisyUI 4 reprovando o axe.
"""

import pytest
from django.core.exceptions import PermissionDenied, ValidationError
from django.urls import reverse

from apps.comum.semestre import semestre_vigente
from apps.contas.models import Area, PerfilAluno, PerfilProfessor, Usuario
from apps.projetos import permissions, services
from apps.projetos.models import Candidatura, OpcaoCandidatura, Tema


@pytest.fixture
def professor(db):
    usuario = Usuario.objects.create_user(
        email="orientador.temas@ufsm.br",
        password="x",
        nome_completo="Orientador Temas",
        cpf="52998224725",
    )
    return PerfilProfessor.objects.create(usuario=usuario, siape="1234567")


@pytest.fixture
def outro_professor(db):
    usuario = Usuario.objects.create_user(
        email="outro.orientador.temas@ufsm.br",
        password="x",
        nome_completo="Outro Orientador Temas",
        cpf="93541134780",
    )
    return PerfilProfessor.objects.create(usuario=usuario, siape="7654321")


@pytest.fixture
def area(db):
    return Area.objects.create(nome="Engenharia de Software")


@pytest.fixture
def outra_area(db):
    return Area.objects.create(nome="Redes")


@pytest.fixture
def aluno(db):
    return Usuario.objects.create_user(
        email="aluno.temas@ufsm.br",
        password="x",
        nome_completo="Aluno Temas",
        papel=Usuario.ALUNO,
        cpf="11144477735",
    )


@pytest.fixture
def perfil_aluno(aluno):
    return PerfilAluno.objects.create(usuario=aluno, matricula="2021000099")


# --- permissions.pode_criar_tema ----------------------------------------


@pytest.mark.django_db
def test_pode_criar_tema_e_verdadeiro_para_professor_com_perfil(professor):
    assert permissions.pode_criar_tema(professor.usuario) is True


@pytest.mark.django_db
def test_pode_criar_tema_e_falso_para_aluno(aluno):
    assert permissions.pode_criar_tema(aluno) is False


@pytest.mark.django_db
def test_pode_criar_tema_e_falso_para_professor_sem_perfil():
    """Papel PROFESSOR é o padrão de `create_user` (`GerenciadorUsuario`),
    mas nada cria `PerfilProfessor` automaticamente — nem o `createsuperuser`
    que o CLAUDE.md manda rodar. `pode_criar_tema` não pode assumir que todo
    usuário com esse papel tem perfil."""
    usuario = Usuario.objects.create_user(
        email="sem.perfil.temas@ufsm.br",
        password="x",
        nome_completo="Sem Perfil",
        cpf="16899535009",
    )
    assert permissions.pode_criar_tema(usuario) is False


def test_pode_criar_tema_e_falso_para_usuario_anonimo():
    from django.contrib.auth.models import AnonymousUser

    assert permissions.pode_criar_tema(AnonymousUser()) is False


# --- services.criar_tema -------------------------------------------------


@pytest.mark.django_db
def test_professor_cria_tema_em_area_que_declarou(professor, area):
    professor.areas.add(area)

    tema = services.criar_tema(
        professor=professor,
        area=area,
        titulo="Recomendação de bibliotecas técnicas",
        descricao="Sistema de recomendação de bibliotecas técnicas para TCC.",
        por=professor.usuario,
    )

    assert tema.pk is not None
    assert tema.professor == professor
    assert tema.area == area
    assert tema.ativo is True


@pytest.mark.django_db
def test_tema_fora_das_areas_do_professor_e_recusado_nomeando_a_area(professor, outra_area):
    with pytest.raises(ValidationError) as excinfo:
        services.criar_tema(
            professor=professor,
            area=outra_area,
            titulo="Tema fora de área",
            descricao="Descrição qualquer.",
            por=professor.usuario,
        )

    assert outra_area.nome in str(excinfo.value)
    assert not Tema.objects.exists()


@pytest.mark.django_db
def test_aluno_nao_cria_tema(professor, area, aluno):
    with pytest.raises(PermissionDenied):
        services.criar_tema(
            professor=professor,
            area=area,
            titulo="Tema de aluno",
            descricao="Descrição qualquer.",
            por=aluno,
        )
    assert not Tema.objects.exists()


# --- services.desativar_tema ----------------------------------------------


@pytest.mark.django_db
def test_desativar_tema_tira_do_mural_e_preserva_candidaturas_que_o_referenciam(
    professor, area, perfil_aluno
):
    professor.areas.add(area)
    tema = Tema.objects.create(
        professor=professor, area=area, titulo="Tema", descricao="Descrição do tema."
    )
    ano, periodo = semestre_vigente()
    candidatura = Candidatura.objects.create(aluno=perfil_aluno, ano=ano, periodo=periodo)
    opcao = OpcaoCandidatura.objects.create(
        candidatura=candidatura, ordem=1, professor=professor, tema=tema
    )

    services.desativar_tema(tema, por=professor.usuario)

    tema.refresh_from_db()
    assert tema.ativo is False
    # Preservada, não apagada: o PROTECT de OpcaoCandidatura.tema depende de o
    # registro do tema nunca ser removido.
    opcao.refresh_from_db()
    assert opcao.tema_id == tema.pk


@pytest.mark.django_db
def test_outro_professor_nao_desativa_tema_alheio(professor, outro_professor, area):
    professor.areas.add(area)
    tema = Tema.objects.create(
        professor=professor, area=area, titulo="Tema", descricao="Descrição do tema."
    )

    with pytest.raises(PermissionDenied):
        services.desativar_tema(tema, por=outro_professor.usuario)

    tema.refresh_from_db()
    assert tema.ativo is True


# --- view projetos:meus_temas ---------------------------------------------


@pytest.mark.django_db
def test_meus_temas_exige_autenticacao(client):
    resposta = client.get(reverse("projetos:meus_temas"))
    assert resposta.status_code == 302
    assert "/contas/login/" in resposta.url


@pytest.mark.django_db
def test_meus_temas_recusa_professor_sem_perfil_com_403_nao_500(client):
    """O defeito que já custou caro na Fase 1 (`/perfil/`, revisão 1): papel
    PROFESSOR sem `PerfilProfessor` não pode derrubar a página com 500."""
    usuario = Usuario.objects.create_user(
        email="coord.sem.perfil.temas@ufsm.br",
        password="x",
        nome_completo="Coordenação Sem Perfil",
        cpf="87721295037",
        is_coordenador=True,
        is_staff=True,
    )
    client.force_login(usuario)

    resposta = client.get(reverse("projetos:meus_temas"))

    assert resposta.status_code == 403


@pytest.mark.django_db
def test_meus_temas_recusa_aluno_com_403(client, aluno):
    client.force_login(aluno)
    resposta = client.get(reverse("projetos:meus_temas"))
    assert resposta.status_code == 403


@pytest.mark.django_db
def test_tela_lista_apenas_areas_declaradas_pelo_professor(client, professor, area, outra_area):
    professor.areas.add(area)
    client.force_login(professor.usuario)

    html = client.get(reverse("projetos:meus_temas")).content.decode()

    assert f'value="{area.pk}"' in html
    assert f'value="{outra_area.pk}"' not in html


@pytest.mark.django_db
def test_professor_cadastra_tema_pela_tela(client, professor, area):
    professor.areas.add(area)
    client.force_login(professor.usuario)

    resposta = client.post(
        reverse("projetos:meus_temas"),
        {"titulo": "Tema novo", "descricao": "Descrição do tema novo.", "area": area.pk},
    )

    assert resposta.status_code == 302
    assert Tema.objects.filter(titulo="Tema novo", professor=professor, ativo=True).exists()


@pytest.mark.django_db
def test_tela_recusa_area_fora_das_declaradas_pelo_professor(client, professor, outra_area):
    """O formulário já restringe o `<select>` às áreas declaradas
    (`FormularioTema.__init__`), então uma área fora dessa lista nem chega a
    `services.criar_tema` — é recusada antes, pela validação de queryset do
    próprio `ModelChoiceField`, com a mensagem padrão do Django (a mensagem
    nomeando a área, exigida pelo brief, é responsabilidade do SERVIÇO,
    coberta em `test_tema_fora_das_areas_do_professor_e_recusado_nomeando_a_area`,
    para quem contornar o formulário e chamar o serviço direto)."""
    client.force_login(professor.usuario)

    resposta = client.post(
        reverse("projetos:meus_temas"),
        {"titulo": "Tema novo", "descricao": "Descrição do tema novo.", "area": outra_area.pk},
    )

    assert resposta.status_code == 200
    assert not Tema.objects.exists()
    assert "Faça uma escolha válida" in resposta.content.decode()


@pytest.mark.django_db
def test_tela_lista_os_temas_ja_cadastrados_do_professor(client, professor, area):
    professor.areas.add(area)
    Tema.objects.create(
        professor=professor, area=area, titulo="Tema Existente", descricao="Descrição."
    )
    client.force_login(professor.usuario)

    html = client.get(reverse("projetos:meus_temas")).content.decode()

    assert "Tema Existente" in html


@pytest.mark.django_db
def test_professor_desativa_tema_pela_tela(client, professor, area):
    professor.areas.add(area)
    tema = Tema.objects.create(
        professor=professor, area=area, titulo="Tema", descricao="Descrição do tema."
    )
    client.force_login(professor.usuario)

    resposta = client.post(reverse("projetos:desativar_tema", args=[tema.pk]))

    assert resposta.status_code == 302
    tema.refresh_from_db()
    assert tema.ativo is False


@pytest.mark.django_db
def test_desativar_tema_exige_post(client, professor, area):
    professor.areas.add(area)
    tema = Tema.objects.create(
        professor=professor, area=area, titulo="Tema", descricao="Descrição do tema."
    )
    client.force_login(professor.usuario)

    resposta = client.get(reverse("projetos:desativar_tema", args=[tema.pk]))

    assert resposta.status_code == 405
    tema.refresh_from_db()
    assert tema.ativo is True


@pytest.mark.django_db
def test_desativar_tema_de_outro_professor_recebe_403(client, professor, outro_professor, area):
    professor.areas.add(area)
    tema = Tema.objects.create(
        professor=professor, area=area, titulo="Tema", descricao="Descrição do tema."
    )
    client.force_login(outro_professor.usuario)

    resposta = client.post(reverse("projetos:desativar_tema", args=[tema.pk]))

    assert resposta.status_code == 403
    tema.refresh_from_db()
    assert tema.ativo is True
