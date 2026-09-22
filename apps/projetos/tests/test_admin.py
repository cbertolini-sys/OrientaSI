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
        professor=professor, titulo="Título original", descricao="Descrição original."
    )
    tema.areas.set([area])
    client.force_login(superusuario)

    url = reverse("admin:projetos_tema_change", args=[tema.pk])
    resposta = client.post(
        url,
        {
            "professor": professor2.pk,
            "areas": [area.pk],
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
            "areas": [area.pk],
            "titulo": "Tema novo",
            "descricao": "Descrição do tema novo.",
            "ativo": "on",
        },
        follow=True,
    )

    assert resposta.status_code == 200
    tema = Tema.objects.get(titulo="Tema novo")
    assert tema.professor == professor


@pytest.mark.django_db
def test_admin_nao_permite_criar_projeto_direto(client, superusuario, professor, area):
    """ACHADO L9 da auditoria (2026-09-22): criar um `Projeto` pelo admin
    fura `LIMITE_PADRAO_VAGAS` (só `criar_projeto_sob_limite` conta vagas).
    Prova por mutação: remover `has_add_permission` de `ProjetoAdmin` faz
    este teste reprovar (a tela de adicionar passaria a existir, 200)."""
    client.force_login(superusuario)
    resposta = client.get(reverse("admin:projetos_projeto_add"))
    assert resposta.status_code == 403


@pytest.mark.django_db
def test_admin_nao_permite_trocar_status_na_edicao_de_um_projeto(
    client, superusuario, professor, area
):
    """ACHADO L9: editar `status`/`etapa` pelo admin pula toda a máquina de
    estados (banca, ata, checklist do TCC II).

    O POST inclui `status`/`etapa` com valores DIFERENTES dos atuais, de
    propósito (achado da revisão de código desta mesma correção): sem isso,
    a prova por mutação era mascarada — remover as duas de `readonly_fields`
    faz `status`/`etapa` virarem campos OBRIGATÓRIOS do formulário (nenhum
    tem `blank=True` no model), e como o POST original não os enviava, o
    formulário reprovava por "campo obrigatório" mesmo sem a proteção —
    coincidindo com a asserção `status == EM_ANDAMENTO`, mas pelo motivo
    ERRADO. Com `status`/`etapa` presentes no POST, a mutação (remover
    `readonly_fields`) aceita os valores novos e o status muda de verdade;
    com a proteção no lugar, os dois são ignorados (campos somente-leitura
    não fazem parte do formulário) e a gravação segue normal com os OUTROS
    campos — daí o `assert "errornote" not in ...`, mesmo padrão do teste
    irmão de H3 (`test_admin_nao_permite_promover_coordenador_direto_na_edicao`)."""
    from apps.contas.models import PerfilAluno
    from apps.contas.validators import _digito
    from apps.projetos.models import Projeto

    def cpf(indice):
        base = f"{640000000 + indice:09d}"
        d1 = _digito(base, 10)
        d2 = _digito(base + str(d1), 11)
        return base + str(d1) + str(d2)

    aluno = Usuario.objects.create_user(
        email="aluno.admin.projeto@ufsm.br",
        password="x",
        nome_completo="Aluno Admin Projeto",
        papel=Usuario.ALUNO,
        cpf=cpf(1),
    )
    PerfilAluno.objects.create(usuario=aluno, matricula="2026ADMINPROJ1")
    projeto = Projeto.objects.create(
        aluno=aluno,
        orientador=professor.usuario,
        etapa=Projeto.TCC_I,
        status=Projeto.EM_ANDAMENTO,
        ano=2026,
        periodo=1,
    )
    client.force_login(superusuario)
    url = reverse("admin:projetos_projeto_change", args=[projeto.pk])
    resposta = client.post(
        url,
        {
            "aluno": aluno.pk,
            "orientador": professor.usuario_id,
            "ano": 2026,
            "periodo": 1,
            "coorientador_externo": "",
            # Tentativa hostil: valores DIFERENTES dos atuais, só possíveis
            # de vingar se `readonly_fields` não estiver protegendo os dois.
            "status": Projeto.CONCLUIDO,
            "etapa": Projeto.TCC_II,
        },
        follow=True,
    )
    assert resposta.status_code == 200
    assert "errornote" not in resposta.content.decode()
    projeto.refresh_from_db()
    assert projeto.status == Projeto.EM_ANDAMENTO
    assert projeto.etapa == Projeto.TCC_I
