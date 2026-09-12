"""Testes de temas (T6, com a rodada de correção 1): `apps/projetos/permissions.py`,
`apps/projetos/services.py::criar_tema/editar_tema/desativar_tema` e as views
`projetos:meus_temas`/`projetos:editar_tema`/`projetos:desativar_tema` — o painel
em que o professor cadastra, edita e desativa os temas que oferece.

Cobertura pedida pelo Passo 1 do brief original: professor cria tema numa área que
declarou; tema fora das áreas dele é recusado com mensagem nomeando a área; aluno
não cria tema (`PermissionDenied`); desativar tira do mural e preserva as
candidaturas que o referenciam.

Acrescido na rodada de correção 1: `criar_tema` recusa um professor publicando em
nome de outro (Importante 1 — achado do revisor, reproduzido com
`test_professor_nao_cria_tema_em_nome_de_outro`); a checagem de posse mora em
`permissions.py` (Importante 2); `editar_tema` (acréscimo de escopo — spec §2 e
§6, ausente do plano original); e os Menores M2 (mensagem de área discrimina de
verdade), M4 (403, não 500, para quem tenta desativar sem `PerfilProfessor`) e M5
(o ramo "tema inativo" do template tem teste).
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
def test_tema_fora_das_areas_do_professor_e_recusado_nomeando_a_area(professor, area, outra_area):
    """M2 (rodada de correção 1): a fixture `professor` declara `area` (não
    `outra_area`), e o professor tenta publicar em `outra_area` — um cenário
    que discrimina de verdade. Sem `professor.areas.add(area)`, `outra_area`
    seria a ÚNICA `Area` do banco, e uma implementação que nomeasse a área
    errada na mensagem passaria do mesmo jeito."""
    professor.areas.add(area)

    with pytest.raises(ValidationError) as excinfo:
        services.criar_tema(
            professor=professor,
            area=outra_area,
            titulo="Tema fora de área",
            descricao="Descrição qualquer.",
            por=professor.usuario,
        )

    mensagem = str(excinfo.value)
    assert outra_area.nome in mensagem
    assert area.nome not in mensagem
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


@pytest.mark.django_db
def test_professor_nao_cria_tema_em_nome_de_outro(professor, outro_professor, area):
    """Importante 1 (rodada de correção 1): antes desta correção,
    `pode_criar_tema(por)` só perguntava "por é UM professor?", sem ligar
    `por` ao `professor` alvo — o professor A conseguia criar um `Tema` cujo
    dono gravado era o professor B. Reproduz literalmente o que o revisor
    exercitou: "A conseguiu criar tema para B? True"."""
    professor.areas.add(area)

    with pytest.raises(PermissionDenied):
        services.criar_tema(
            professor=professor,
            area=area,
            titulo="Tema em nome alheio",
            descricao="Descrição qualquer.",
            por=outro_professor.usuario,
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
def test_desativar_tema_de_outro_professor_recebe_404_nao_403(
    client, professor, outro_professor, area
):
    """404, e não 403, de propósito (rodada de correção 2 da T6).

    A view escopa o lookup ao professor autenticado
    (`get_object_or_404(Tema, pk=..., professor=...)`), então tema alheio e
    tema inexistente respondem os DOIS 404. Distinguir os dois casos —
    403 para "existe mas não é seu", 404 para "não existe" — transformava a
    URL num oráculo de existência: com pk sequencial, um professor podia
    descobrir quantos temas existem sem descobrir de quem são. O que isso
    entregava a mais que o mural (que lista só os ATIVOS) era exatamente a
    contagem dos DESATIVADOS alheios.

    O 403 não sumiu da tela: continua para quem não passa no portão de PAPEL
    (aluno, ou PROFESSOR sem `PerfilProfessor` — ver o teste seguinte). A
    troca é só entre 403 e 404 para quem É professor e mira um tema que não
    é seu."""
    professor.areas.add(area)
    tema = Tema.objects.create(
        professor=professor, area=area, titulo="Tema", descricao="Descrição do tema."
    )
    client.force_login(outro_professor.usuario)

    resposta = client.post(reverse("projetos:desativar_tema", args=[tema.pk]))

    assert resposta.status_code == 404
    tema.refresh_from_db()
    assert tema.ativo is True


@pytest.mark.django_db
def test_desativar_tema_inexistente_e_alheio_respondem_o_mesmo_status(
    client, professor, outro_professor, area
):
    """O oráculo só está fechado se os dois casos forem INDISTINGUÍVEIS.

    Os testes acima afirmam 404 para tema alheio; este afirma que um pk que
    não existe responde o MESMO, medido na mesma execução. Sem esta
    comparação, uma regressão que devolvesse 403 para alheio e 404 para
    inexistente reabriria o oráculo sem derrubar nenhum dos outros testes."""
    professor.areas.add(area)
    tema = Tema.objects.create(
        professor=professor, area=area, titulo="Tema", descricao="Descrição do tema."
    )
    client.force_login(outro_professor.usuario)

    alheio = client.post(reverse("projetos:desativar_tema", args=[tema.pk]))
    inexistente = client.post(reverse("projetos:desativar_tema", args=[tema.pk + 10_000]))

    assert alheio.status_code == inexistente.status_code == 404


@pytest.mark.django_db
def test_desativar_tema_por_usuario_sem_perfil_recebe_403_nao_500(client, professor, area):
    """M4 (rodada de correção 1): `hasattr(por, "perfil_professor")` em
    `permissions.pode_desativar_tema` é o que evita `RelatedObjectDoesNotExist`
    (500) — mesma classe de defeito que `/perfil/` teve na Fase 1, agora sem
    nenhum teste travando especificamente a VIEW de desativar (só a unitária
    de serviço, `test_outro_professor_nao_desativa_tema_alheio`, que nunca
    passa um `por` sem perfil algum)."""
    professor.areas.add(area)
    tema = Tema.objects.create(
        professor=professor, area=area, titulo="Tema", descricao="Descrição do tema."
    )
    usuario_sem_perfil = Usuario.objects.create_user(
        email="sem.perfil.desativa@ufsm.br",
        password="x",
        nome_completo="Sem Perfil Desativa",
        cpf="39053344705",
    )
    client.force_login(usuario_sem_perfil)

    resposta = client.post(reverse("projetos:desativar_tema", args=[tema.pk]))

    assert resposta.status_code == 403
    tema.refresh_from_db()
    assert tema.ativo is True


@pytest.mark.django_db
def test_tela_marca_tema_inativo_e_esconde_o_botao_desativar(client, professor, area):
    """M5 (rodada de correção 1): cobre o ramo `{% if not tema.ativo %}`
    (badge "Inativo") e a ausência do formulário de "Desativar" para um tema
    já desativado — só a variante "ativo" tinha teste até aqui."""
    professor.areas.add(area)
    tema = Tema.objects.create(
        professor=professor,
        area=area,
        titulo="Tema Inativo",
        descricao="Descrição.",
        ativo=False,
    )
    client.force_login(professor.usuario)

    html = client.get(reverse("projetos:meus_temas")).content.decode()

    assert "Inativo" in html
    assert f'action="{reverse("projetos:desativar_tema", args=[tema.pk])}"' not in html
    # "Editar" continua disponível para tema inativo (spec §2/§6 não
    # condicionam a edição ao estado do tema).
    assert f'href="{reverse("projetos:editar_tema", args=[tema.pk])}"' in html


# --- services.editar_tema (acréscimo de escopo, rodada de correção 1) ------


@pytest.mark.django_db
def test_pode_editar_tema_e_verdadeiro_so_para_o_dono(professor, outro_professor, area):
    professor.areas.add(area)
    tema = Tema.objects.create(
        professor=professor, area=area, titulo="Tema", descricao="Descrição."
    )
    assert permissions.pode_editar_tema(professor.usuario, tema) is True
    assert permissions.pode_editar_tema(outro_professor.usuario, tema) is False


@pytest.mark.django_db
def test_dono_edita_tema(professor, area, outra_area):
    professor.areas.add(area)
    professor.areas.add(outra_area)
    tema = Tema.objects.create(
        professor=professor, area=area, titulo="Título original", descricao="Descrição original."
    )

    editado = services.editar_tema(
        tema,
        area=outra_area,
        titulo="Título novo",
        descricao="Descrição nova.",
        por=professor.usuario,
    )

    assert editado.pk == tema.pk
    tema.refresh_from_db()
    assert tema.titulo == "Título novo"
    assert tema.descricao == "Descrição nova."
    assert tema.area == outra_area


@pytest.mark.django_db
def test_outro_professor_nao_edita_tema_alheio(professor, outro_professor, area):
    professor.areas.add(area)
    tema = Tema.objects.create(
        professor=professor, area=area, titulo="Título", descricao="Descrição."
    )

    with pytest.raises(PermissionDenied):
        services.editar_tema(
            tema,
            area=area,
            titulo="Título adulterado",
            descricao="Descrição adulterada.",
            por=outro_professor.usuario,
        )

    tema.refresh_from_db()
    assert tema.titulo == "Título"


@pytest.mark.django_db
def test_editar_tema_recusa_area_fora_das_declaradas_nomeando_a_area(professor, area, outra_area):
    professor.areas.add(area)
    tema = Tema.objects.create(
        professor=professor, area=area, titulo="Título", descricao="Descrição."
    )

    with pytest.raises(ValidationError) as excinfo:
        services.editar_tema(
            tema,
            area=outra_area,
            titulo="Título",
            descricao="Descrição.",
            por=professor.usuario,
        )

    mensagem = str(excinfo.value)
    assert outra_area.nome in mensagem
    assert area.nome not in mensagem
    tema.refresh_from_db()
    assert tema.area == area


@pytest.mark.django_db
def test_editar_tema_permite_mesmo_com_candidatura(professor, area, perfil_aluno):
    """O spec (§2, §6) concede a edição sem condicioná-la ao estado das
    candidaturas — ver a lacuna registrada na docstring de `editar_tema` e no
    spec §4.1: isto NÃO decide se é seguro, só prova que nada no código
    impede."""
    professor.areas.add(area)
    tema = Tema.objects.create(
        professor=professor, area=area, titulo="Título", descricao="Descrição."
    )
    ano, periodo = semestre_vigente()
    candidatura = Candidatura.objects.create(aluno=perfil_aluno, ano=ano, periodo=periodo)
    OpcaoCandidatura.objects.create(
        candidatura=candidatura, ordem=1, professor=professor, tema=tema
    )

    services.editar_tema(
        tema, area=area, titulo="Título editado", descricao="Descrição.", por=professor.usuario
    )

    tema.refresh_from_db()
    assert tema.titulo == "Título editado"


# --- view projetos:editar_tema ----------------------------------------------


@pytest.mark.django_db
def test_editar_tema_exige_autenticacao(client, professor, area):
    professor.areas.add(area)
    tema = Tema.objects.create(
        professor=professor, area=area, titulo="Título", descricao="Descrição."
    )
    resposta = client.get(reverse("projetos:editar_tema", args=[tema.pk]))
    assert resposta.status_code == 302
    assert "/contas/login/" in resposta.url


@pytest.mark.django_db
def test_editar_tema_get_preenche_os_valores_atuais(client, professor, area):
    professor.areas.add(area)
    tema = Tema.objects.create(
        professor=professor, area=area, titulo="Título atual", descricao="Descrição atual."
    )
    client.force_login(professor.usuario)

    html = client.get(reverse("projetos:editar_tema", args=[tema.pk])).content.decode()

    assert 'value="Título atual"' in html
    assert "Descrição atual." in html
    assert f'value="{area.pk}" selected' in html


@pytest.mark.django_db
def test_dono_edita_tema_pela_tela(client, professor, area, outra_area):
    professor.areas.add(area)
    professor.areas.add(outra_area)
    tema = Tema.objects.create(
        professor=professor, area=area, titulo="Título antigo", descricao="Descrição antiga."
    )
    client.force_login(professor.usuario)

    resposta = client.post(
        reverse("projetos:editar_tema", args=[tema.pk]),
        {"titulo": "Título novo", "descricao": "Descrição nova.", "area": outra_area.pk},
    )

    assert resposta.status_code == 302
    tema.refresh_from_db()
    assert tema.titulo == "Título novo"
    assert tema.descricao == "Descrição nova."
    assert tema.area == outra_area

    # A tela reflete o valor editado (critério do brief): a lista em
    # /temas/meus/ mostra o título novo, não mais o antigo.
    html = client.get(reverse("projetos:meus_temas")).content.decode()
    assert "Título novo" in html
    assert "Título antigo" not in html


@pytest.mark.django_db
def test_outro_professor_nao_edita_tema_alheio_pela_tela(client, professor, outro_professor, area):
    """404, e não 403 — mesmo motivo de
    `test_desativar_tema_de_outro_professor_recebe_404_nao_403`: o lookup é
    escopado ao professor autenticado, então "não é seu" e "não existe" são
    indistinguíveis de fora (rodada de correção 2 da T6)."""
    professor.areas.add(area)
    tema = Tema.objects.create(
        professor=professor, area=area, titulo="Título", descricao="Descrição."
    )
    client.force_login(outro_professor.usuario)

    resposta = client.get(reverse("projetos:editar_tema", args=[tema.pk]))
    assert resposta.status_code == 404

    resposta = client.post(
        reverse("projetos:editar_tema", args=[tema.pk]),
        {"titulo": "Adulterado", "descricao": "Adulterado.", "area": area.pk},
    )
    assert resposta.status_code == 404
    tema.refresh_from_db()
    assert tema.titulo == "Título"

    inexistente = client.get(reverse("projetos:editar_tema", args=[tema.pk + 10_000]))
    assert inexistente.status_code == resposta.status_code == 404


@pytest.mark.django_db
def test_editar_tema_view_recusa_area_fora_das_declaradas(client, professor, outra_area):
    tema_area = Area.objects.create(nome="Área do Tema")
    professor.areas.add(tema_area)
    tema = Tema.objects.create(
        professor=professor, area=tema_area, titulo="Título", descricao="Descrição."
    )
    client.force_login(professor.usuario)

    resposta = client.post(
        reverse("projetos:editar_tema", args=[tema.pk]),
        {"titulo": "Título", "descricao": "Descrição.", "area": outra_area.pk},
    )

    assert resposta.status_code == 200
    assert "Faça uma escolha válida" in resposta.content.decode()
    tema.refresh_from_db()
    assert tema.area == tema_area
