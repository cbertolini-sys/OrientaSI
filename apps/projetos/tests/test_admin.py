"""Prova de que o admin fecha o caminho mais acessível para o achado da
revisão 1 da Tarefa 4: trocar o professor de um Tema já existente deixaria
OpcaoCandidatura antigas apontando para um tema cujo professor não bate mais
com o `professor` gravado na opção — exatamente o que a trigger
`valida_tema_do_professor_da_opcao` (migrations/0002_...) protege, mas ela só
observa INSERT/UPDATE de OpcaoCandidatura, não de Tema.
"""

import pytest
from django.urls import reverse

from apps.contas.models import Area, PerfilProfessor, Usuario
from apps.projetos.models import Tema


@pytest.fixture
def superusuario(db):
    return Usuario.objects.create_superuser(
        email="admin@ufsm.br", password="x", nome_completo="Admin", cpf="12345678909"
    )


@pytest.fixture
def professor(db):
    usuario = Usuario.objects.create_user(
        email="orientador@ufsm.br", password="x", nome_completo="Orientador", cpf="52998224725"
    )
    return PerfilProfessor.objects.create(usuario=usuario, siape="1234567")


@pytest.fixture
def professor2(db):
    usuario = Usuario.objects.create_user(
        email="orientador2@ufsm.br",
        password="x",
        nome_completo="Orientador Dois",
        cpf="93541134780",
    )
    return PerfilProfessor.objects.create(usuario=usuario, siape="7654321")


@pytest.fixture
def area(db):
    return Area.objects.create(nome="Área de Teste Padrão")


@pytest.mark.django_db
def test_admin_nao_permite_trocar_o_professor_na_edicao_de_um_tema(
    client, superusuario, professor, professor2, area
):
    tema = Tema.objects.create(
        professor=professor, area=area, titulo="Título original", descricao="Descrição original."
    )
    client.force_login(superusuario)

    url = reverse("admin:projetos_tema_change", args=[tema.pk])
    resposta = client.post(
        url,
        {
            "professor": professor2.pk,
            "area": area.pk,
            "titulo": "Título alterado",
            "descricao": tema.descricao,
            "ativo": "on",
        },
        follow=True,
    )

    assert resposta.status_code == 200
    tema.refresh_from_db()
    # O POST foi processado de verdade (o título mudou — não foi um erro de
    # validação genérico barrando o formulário inteiro), mas `professor`,
    # somente-leitura na edição, permanece o original.
    assert tema.titulo == "Título alterado"
    assert tema.professor == professor


@pytest.mark.django_db
def test_admin_permite_escolher_o_professor_na_criacao_de_um_tema(
    client, superusuario, professor, area
):
    """Contraprova: a trava é só na EDIÇÃO. Criar um Tema continua livre para
    escolher qualquer professor — não há opções dependentes ainda para
    contradizer."""
    client.force_login(superusuario)

    url = reverse("admin:projetos_tema_add")
    resposta = client.post(
        url,
        {
            "professor": professor.pk,
            "area": area.pk,
            "titulo": "Tema novo",
            "descricao": "Descrição do tema novo.",
            "ativo": "on",
        },
        follow=True,
    )

    assert resposta.status_code == 200
    tema = Tema.objects.get(titulo="Tema novo")
    assert tema.professor == professor
