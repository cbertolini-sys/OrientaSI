"""Testes da tela do aluno (T11, spec §6: "/candidatura/ | aluno | montar,
acompanhar e cancelar") — a primeira tela do lado do aluno sobre o motor de
candidatura que as Tarefas 8-10 construíram do lado do serviço.

Cobertura pedida pelo Passo 1 do brief: o aluno monta a candidatura
escolhendo até três alvos (Temas) em ordem; a tela mostra em qual opção a
cascata está e a justificativa das recusas já recebidas; cancelar funciona;
professor não acessa a tela do aluno.

Os testes que precisam medir e-mail usam `django_capture_on_commit_callbacks`
(mesmo padrão de test_candidatura.py e test_fila_professor.py):
`transaction.on_commit` não dispara sozinho sob pytest-django. Os demais
testes de view não usam esse mecanismo — o cliente de teste roda dentro da
transação do próprio teste, que nunca comita.
"""

import pytest
from django.contrib.auth.models import AnonymousUser
from django.core import mail
from django.urls import reverse

from apps.comum.semestre import semestre_vigente
from apps.contas.models import Area, PerfilAluno, PerfilProfessor, Usuario
from apps.contas.validators import _digito
from apps.projetos import permissions, services
from apps.projetos.models import Candidatura, OpcaoCandidatura, Projeto, Tema

ANO_VIGENTE, PERIODO_VIGENTE = semestre_vigente()


# CPFs sintéticos com dígito verificador válido — faixa própria (950000000+),
# para não colidir com as faixas já usadas por test_vagas.py (500000000+),
# test_concorrencia.py (600000000+), test_fila_professor.py (700000000+) e
# test_candidatura.py (900000000+).
def _gera_cpf(indice):
    base = f"{950000000 + indice:09d}"
    d1 = _digito(base, 10)
    d2 = _digito(base + str(d1), 11)
    return base + str(d1) + str(d2)


def _cria_professor(indice, nome):
    usuario = Usuario.objects.create_user(
        email=f"professor.tela{indice}@ufsm.br",
        password="x",
        nome_completo=nome,
        cpf=_gera_cpf(indice),
    )
    return PerfilProfessor.objects.create(usuario=usuario, siape=f"TELA{indice}")


def _cria_aluno(indice, nome="Aluno Tela"):
    usuario = Usuario.objects.create_user(
        email=f"aluno.tela{indice}@ufsm.br",
        password="x",
        nome_completo=nome,
        papel=Usuario.ALUNO,
        cpf=_gera_cpf(indice),
    )
    return PerfilAluno.objects.create(usuario=usuario, matricula=f"2026TELA{indice:03d}")


@pytest.fixture
def area(db):
    return Area.objects.create(nome="Engenharia de Software")


@pytest.fixture
def tres_professores(area):
    professores = [_cria_professor(indice, f"Professor Tela {indice}") for indice in range(1, 4)]
    for professor in professores:
        professor.areas.add(area)
    return professores


@pytest.fixture
def tres_temas(area, tres_professores):
    return [
        Tema.objects.create(
            professor=professor,
            area=area,
            titulo=f"Tema Tela {indice}",
            descricao=f"Descrição do tema tela {indice}.",
        )
        for indice, professor in enumerate(tres_professores, start=1)
    ]


@pytest.fixture
def aluno(db):
    return _cria_aluno(50)


@pytest.fixture
def candidatura_em_curso(settings, django_capture_on_commit_callbacks, tres_temas, aluno):
    """Candidatura registrada com as três opções, na ORDEM de `tres_temas`
    (opção 1 -> tres_temas[0], etc.) — a opção 1 nasce ENVIADA. `mail.outbox`
    é limpo depois: o e-mail da primeira manifestação não é o que a maioria
    destes testes mede."""
    settings.CELERY_TASK_ALWAYS_EAGER = True
    opcoes = [(tema.professor, tema) for tema in tres_temas]
    with django_capture_on_commit_callbacks(execute=True):
        candidatura = services.registrar_candidatura(aluno, opcoes)
    mail.outbox.clear()
    return candidatura


# --------------------------------------------------------------------------
# permissions.pode_montar_candidatura
# --------------------------------------------------------------------------


@pytest.mark.django_db
def test_pode_montar_candidatura_e_verdadeiro_para_aluno(aluno):
    assert permissions.pode_montar_candidatura(aluno.usuario) is True


@pytest.mark.django_db
def test_pode_montar_candidatura_e_falso_para_professor(tres_professores):
    assert permissions.pode_montar_candidatura(tres_professores[0].usuario) is False


def test_pode_montar_candidatura_e_falso_para_usuario_anonimo():
    assert permissions.pode_montar_candidatura(AnonymousUser()) is False


@pytest.mark.django_db
def test_pode_montar_candidatura_e_falso_para_papel_aluno_sem_perfil(db):
    """Mesma classe de defeito que `pode_criar_tema`/`pode_responder_opcao`
    evitam para professor: papel ALUNO não implica `PerfilAluno` existente
    (nada cria o perfil automaticamente). A checagem tem que ser por
    EXISTÊNCIA do perfil (`hasattr`), não por `usuario.papel`."""
    usuario = Usuario.objects.create_user(
        email="aluno.sem.perfil.tela@ufsm.br",
        password="x",
        nome_completo="Aluno Sem Perfil Tela",
        papel=Usuario.ALUNO,
        cpf=_gera_cpf(91),
    )
    assert permissions.pode_montar_candidatura(usuario) is False


# --------------------------------------------------------------------------
# view projetos:candidatura — portão de acesso
# --------------------------------------------------------------------------


@pytest.mark.django_db
def test_candidatura_exige_autenticacao(client):
    resposta = client.get(reverse("projetos:candidatura"))
    assert resposta.status_code == 302
    assert "/contas/login/" in resposta.url


@pytest.mark.django_db
def test_candidatura_recusa_professor_com_403(client, tres_professores):
    client.force_login(tres_professores[0].usuario)
    resposta = client.get(reverse("projetos:candidatura"))
    assert resposta.status_code == 403


@pytest.mark.django_db
def test_candidatura_recusa_papel_aluno_sem_perfil_com_403_nao_500(client, db):
    """O mesmo defeito que `apps/contas/views.py::perfil` já teve na Fase 1,
    e que `apps/projetos/views.py::meus_temas`/`orientacoes` já evitam para
    professor sem perfil: papel ALUNO sem `PerfilAluno` não pode derrubar a
    página com 500."""
    usuario = Usuario.objects.create_user(
        email="aluno.sem.perfil.tela.view@ufsm.br",
        password="x",
        nome_completo="Aluno Sem Perfil Tela View",
        papel=Usuario.ALUNO,
        cpf=_gera_cpf(92),
    )
    client.force_login(usuario)
    resposta = client.get(reverse("projetos:candidatura"))
    assert resposta.status_code == 403


# --------------------------------------------------------------------------
# view projetos:candidatura — montar (GET sem candidatura em curso)
# --------------------------------------------------------------------------


@pytest.mark.django_db
def test_candidatura_mostra_formulario_quando_nao_ha_candidatura_em_curso(
    client, aluno, tres_temas
):
    client.force_login(aluno.usuario)

    html = client.get(reverse("projetos:candidatura")).content.decode()

    assert tres_temas[0].titulo in html
    assert "Enviar candidatura" in html


@pytest.mark.django_db
def test_candidatura_so_lista_temas_ativos_no_formulario(client, aluno, tres_temas):
    tema_inativo = Tema.objects.create(
        professor=tres_temas[0].professor,
        area=tres_temas[0].area,
        titulo="Tema Tela Inativo",
        descricao="Descrição do tema inativo.",
        ativo=False,
    )
    client.force_login(aluno.usuario)

    html = client.get(reverse("projetos:candidatura")).content.decode()

    assert tema_inativo.titulo not in html


@pytest.mark.django_db
def test_candidatura_encerrada_nao_bloqueia_nova_montagem(client, aluno, tres_temas):
    """`Candidatura.Meta.constraints` só impede uma segunda `EM_CURSO`
    simultânea — uma já `CANCELADA` não deveria travar a tela em modo
    "acompanhar" para sempre. Prova que o filtro `status=EM_CURSO` da view
    discrimina de verdade (e não só "a candidatura mais recente do aluno")."""
    Candidatura.objects.create(
        aluno=aluno, status=Candidatura.CANCELADA, ano=ANO_VIGENTE, periodo=PERIODO_VIGENTE
    )
    client.force_login(aluno.usuario)

    html = client.get(reverse("projetos:candidatura")).content.decode()

    assert "Enviar candidatura" in html
    assert "Cancelar candidatura" not in html


# --------------------------------------------------------------------------
# view projetos:candidatura — montar (POST)
# --------------------------------------------------------------------------


@pytest.mark.django_db
def test_aluno_monta_candidatura_com_tres_opcoes_em_ordem(client, aluno, tres_temas):
    client.force_login(aluno.usuario)

    resposta = client.post(
        reverse("projetos:candidatura"),
        {
            "opcao_1": tres_temas[2].pk,
            "opcao_2": tres_temas[0].pk,
            "opcao_3": tres_temas[1].pk,
        },
    )

    assert resposta.status_code == 302
    candidatura = Candidatura.objects.get(aluno=aluno)
    assert candidatura.status == Candidatura.EM_CURSO
    opcao1, opcao2, opcao3 = candidatura.opcoes.order_by("ordem")
    assert opcao1.tema == tres_temas[2]
    assert opcao1.professor == tres_temas[2].professor
    assert opcao2.tema == tres_temas[0]
    assert opcao3.tema == tres_temas[1]


@pytest.mark.django_db
def test_aluno_monta_candidatura_so_com_a_primeira_opcao(client, aluno, tres_temas):
    client.force_login(aluno.usuario)

    resposta = client.post(reverse("projetos:candidatura"), {"opcao_1": tres_temas[0].pk})

    assert resposta.status_code == 302
    candidatura = Candidatura.objects.get(aluno=aluno)
    assert candidatura.opcoes.count() == 1


@pytest.mark.django_db
def test_aluno_monta_candidatura_dispara_email_para_o_primeiro_professor(
    client, settings, django_capture_on_commit_callbacks, aluno, tres_temas
):
    settings.CELERY_TASK_ALWAYS_EAGER = True
    client.force_login(aluno.usuario)

    with django_capture_on_commit_callbacks(execute=True):
        resposta = client.post(reverse("projetos:candidatura"), {"opcao_1": tres_temas[0].pk})

    assert resposta.status_code == 302
    assert len(mail.outbox) == 1
    assert mail.outbox[0].to == [tres_temas[0].professor.usuario.email]


@pytest.mark.django_db
def test_candidatura_sem_nenhuma_opcao_e_recusada(client, aluno, tres_temas):
    client.force_login(aluno.usuario)

    resposta = client.post(reverse("projetos:candidatura"), {})

    assert resposta.status_code == 200
    assert not Candidatura.objects.filter(aluno=aluno).exists()


@pytest.mark.django_db
def test_candidatura_com_buraco_entre_opcoes_e_recusada(client, aluno, tres_temas):
    """`clean()` de `FormularioCandidatura` recusa `opcao_3` preenchido sem
    `opcao_2` — comprimir silenciosamente reescreveria a prioridade
    declarada pelo aluno."""
    client.force_login(aluno.usuario)

    resposta = client.post(
        reverse("projetos:candidatura"),
        {"opcao_1": tres_temas[0].pk, "opcao_3": tres_temas[1].pk},
    )

    assert resposta.status_code == 200
    assert "Preencha a 2ª opção" in resposta.content.decode()
    assert not Candidatura.objects.filter(aluno=aluno).exists()


@pytest.mark.django_db
def test_candidatura_com_professor_repetido_e_recusada_pelo_formulario(
    client, area, tres_professores, tres_temas, aluno
):
    """Dois Temas do MESMO professor em opções diferentes — checagem
    amigável do formulário (`FormularioCandidatura.clean`), antes mesmo de
    chegar em `services.registrar_candidatura`."""
    segundo_tema_do_professor_1 = Tema.objects.create(
        professor=tres_professores[0],
        area=area,
        titulo="Segundo Tema do Professor 1",
        descricao="Outro tema do mesmo professor.",
    )
    client.force_login(aluno.usuario)

    resposta = client.post(
        reverse("projetos:candidatura"),
        {"opcao_1": tres_temas[0].pk, "opcao_2": segundo_tema_do_professor_1.pk},
    )

    assert resposta.status_code == 200
    assert "professor só pode aparecer uma vez" in resposta.content.decode()
    assert not Candidatura.objects.filter(aluno=aluno).exists()


@pytest.mark.django_db
def test_candidatura_repassa_erro_de_vaga_do_servico_como_erro_de_formulario(
    client, aluno, tres_temas
):
    """`services.registrar_candidatura` recusa um professor sem vaga (spec
    §5.1) — a view precisa mostrar essa `ValidationError` como erro do
    formulário, em vez de deixá-la propagar como 500, e sem criar a
    `Candidatura`."""
    professor = tres_temas[0].professor
    for indice in range(60, 63):
        services.criar_projeto_sob_limite(_cria_aluno(indice), professor, None, Projeto.TCC_I)
    client.force_login(aluno.usuario)

    resposta = client.post(reverse("projetos:candidatura"), {"opcao_1": tres_temas[0].pk})

    assert resposta.status_code == 200
    assert "vagas ocupadas" in resposta.content.decode()
    assert not Candidatura.objects.filter(aluno=aluno).exists()


@pytest.mark.django_db
def test_candidatura_com_tema_inativo_e_recusada_pelo_formulario_nao_pelo_servico(
    client, aluno, tres_temas
):
    """`ModelChoiceField.queryset` só lista Temas `ativo=True`
    (`FormularioCandidatura`) — um `pk` de tema inativo submetido de
    qualquer forma (ex.: formulário adulterado) é recusado como opção
    INVÁLIDA do próprio campo, sem chegar ao serviço.

    A mensagem afirmada é a de "escolha inválida" do PRÓPRIO
    `ModelChoiceField` ("Sua escolha não é uma das disponíveis."), não a
    mensagem de `services.registrar_candidatura` para tema inativo ("não
    está mais ativo...") — as duas produzem o mesmo status 200 sem
    `Candidatura` criada, então checar só o status/ausência de candidatura
    NÃO prova que é o FORMULÁRIO quem recusou: `services.registrar_candidatura`
    também rejeita tema inativo, e absorveria uma remoção do filtro do
    queryset sem que nenhum teste baseado só em estado final percebesse —
    confirmado retirando `ativo=True` do queryset dos três campos e rodando
    esta suíte: só esta versão do teste (checando a mensagem) reprova; a
    versão anterior (só status/ausência de candidatura) continuava passando."""
    tema_inativo = Tema.objects.create(
        professor=tres_temas[0].professor,
        area=tres_temas[0].area,
        titulo="Tema Tela Inativo Submetido",
        descricao="Descrição.",
        ativo=False,
    )
    client.force_login(aluno.usuario)

    resposta = client.post(reverse("projetos:candidatura"), {"opcao_1": tema_inativo.pk})

    assert resposta.status_code == 200
    assert not Candidatura.objects.filter(aluno=aluno).exists()
    assert "não é uma das disponíveis" in resposta.content.decode()


# --------------------------------------------------------------------------
# view projetos:candidatura — acompanhar (GET com candidatura em curso)
# --------------------------------------------------------------------------


@pytest.mark.django_db
def test_candidatura_acompanhar_mostra_opcao_atual_da_cascata(client, candidatura_em_curso, aluno):
    client.force_login(aluno.usuario)

    html = client.get(reverse("projetos:candidatura")).content.decode()

    assert "1ª opção de até três" in html
    assert "Cancelar candidatura" in html
    assert "Enviar candidatura" not in html


@pytest.mark.django_db
def test_candidatura_acompanhar_mostra_opcao_atual_apos_avancar(
    client,
    settings,
    django_capture_on_commit_callbacks,
    candidatura_em_curso,
    aluno,
    tres_temas,
):
    opcao1 = candidatura_em_curso.opcoes.get(ordem=1)
    settings.CELERY_TASK_ALWAYS_EAGER = True
    with django_capture_on_commit_callbacks(execute=True):
        services.recusar_opcao(
            opcao1, por=tres_temas[0].professor.usuario, justificativa="Fora da minha área."
        )
    client.force_login(aluno.usuario)

    html = client.get(reverse("projetos:candidatura")).content.decode()

    assert "2ª opção de até três" in html


@pytest.mark.django_db
def test_candidatura_acompanhar_mostra_justificativa_de_recusa(
    client,
    settings,
    django_capture_on_commit_callbacks,
    candidatura_em_curso,
    aluno,
    tres_temas,
):
    opcao1 = candidatura_em_curso.opcoes.get(ordem=1)
    settings.CELERY_TASK_ALWAYS_EAGER = True
    with django_capture_on_commit_callbacks(execute=True):
        services.recusar_opcao(
            opcao1,
            por=tres_temas[0].professor.usuario,
            justificativa="Fora da minha área de pesquisa.",
        )
    client.force_login(aluno.usuario)

    html = client.get(reverse("projetos:candidatura")).content.decode()

    assert "Fora da minha área de pesquisa." in html
    assert "Justificativa da recusa" in html


@pytest.mark.django_db
def test_candidatura_acompanhar_nao_mostra_justificativa_para_opcao_sem_recusa(
    client, candidatura_em_curso, aluno
):
    client.force_login(aluno.usuario)

    html = client.get(reverse("projetos:candidatura")).content.decode()

    assert "Justificativa da recusa" not in html


@pytest.mark.django_db
def test_candidatura_acompanhar_de_outro_aluno_nao_vaza(client, candidatura_em_curso, tres_temas):
    """A view lê `request.user.perfil_aluno.candidaturas`, escopado ao
    próprio usuário autenticado — outro aluno, mesmo logado, nunca vê a
    candidatura alheia; ele só veria a SUA PRÓPRIA (aqui, nenhuma, então cai
    no formulário de montar)."""
    outro_aluno = _cria_aluno(55, "Outro Aluno Tela")
    client.force_login(outro_aluno.usuario)

    html = client.get(reverse("projetos:candidatura")).content.decode()

    assert "Enviar candidatura" in html
    # `matricula`, não `nome_completo`: o cabeçalho da própria página mostra
    # "Outro Aluno Tela" (usuário autenticado), que CONTÉM "Aluno Tela" como
    # substring — uma asserção sobre o nome daria falso positivo. A
    # matrícula do aluno da candidatura alheia não aparece em lugar nenhum
    # do HTML se a candidatura de fato não vazou.
    assert candidatura_em_curso.aluno.matricula not in html


# --------------------------------------------------------------------------
# view projetos:cancelar_candidatura
# --------------------------------------------------------------------------


@pytest.mark.django_db
def test_aluno_cancela_candidatura_pela_tela(client, candidatura_em_curso, aluno):
    client.force_login(aluno.usuario)

    resposta = client.post(reverse("projetos:cancelar_candidatura", args=[candidatura_em_curso.pk]))

    assert resposta.status_code == 302
    candidatura_em_curso.refresh_from_db()
    assert candidatura_em_curso.status == Candidatura.CANCELADA
    opcao1 = candidatura_em_curso.opcoes.get(ordem=1)
    assert opcao1.situacao == OpcaoCandidatura.CANCELADA


@pytest.mark.django_db
def test_cancelar_candidatura_exige_post(client, candidatura_em_curso, aluno):
    client.force_login(aluno.usuario)

    resposta = client.get(reverse("projetos:cancelar_candidatura", args=[candidatura_em_curso.pk]))

    assert resposta.status_code == 405
    candidatura_em_curso.refresh_from_db()
    assert candidatura_em_curso.status == Candidatura.EM_CURSO


@pytest.mark.django_db
def test_cancelar_candidatura_de_outro_aluno_recebe_404_nao_403(client, candidatura_em_curso):
    """Mesmo padrão de `test_aceitar_opcao_de_outro_professor_recebe_404_nao_403`
    (test_fila_professor.py): a view escopa o lookup ao aluno autenticado —
    candidatura alheia e candidatura inexistente respondem os DOIS com 404,
    sem abrir um oráculo de existência sobre candidaturas de outros alunos."""
    outro_aluno = _cria_aluno(56, "Outro Aluno Cancela")
    client.force_login(outro_aluno.usuario)

    resposta_alheia = client.post(
        reverse("projetos:cancelar_candidatura", args=[candidatura_em_curso.pk])
    )
    resposta_inexistente = client.post(
        reverse("projetos:cancelar_candidatura", args=[candidatura_em_curso.pk + 9999])
    )

    assert resposta_alheia.status_code == resposta_inexistente.status_code == 404
    candidatura_em_curso.refresh_from_db()
    assert candidatura_em_curso.status == Candidatura.EM_CURSO


@pytest.mark.django_db
def test_cancelar_candidatura_ja_encerrada_mostra_erro_sem_500(client, candidatura_em_curso, aluno):
    client.force_login(aluno.usuario)
    client.post(reverse("projetos:cancelar_candidatura", args=[candidatura_em_curso.pk]))

    resposta = client.post(reverse("projetos:cancelar_candidatura", args=[candidatura_em_curso.pk]))

    assert resposta.status_code == 302
    candidatura_em_curso.refresh_from_db()
    assert candidatura_em_curso.status == Candidatura.CANCELADA
