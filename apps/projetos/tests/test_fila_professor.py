"""Testes da fila do professor (T9, spec §5.2 e §5.3): aceitar e recusar
manifestações de interesse — o outro lado da candidatura que a T8 registrou.

`aceitar_opcao` cria o `Projeto` (revalidando a vaga dentro da própria
transação, via `criar_projeto_sob_limite`, T5) e cancela as demais opções da
candidatura; `recusar_opcao` marca a opção como `RECUSADA`, com justificativa
obrigatória, e avança a cascata (`avancar_cascata`, T8) para a opção
seguinte, enfileirando `enviar_recusa` (T8) por `transaction.on_commit`.

Os testes que disparam e-mail usam `django_capture_on_commit_callbacks`
(mesmo padrão de test_candidatura.py): `transaction.on_commit` não dispara
sozinho sob pytest-django. Os testes de VIEW não usam esse mecanismo — o
cliente de teste roda dentro da transação do próprio teste, que nunca comita,
então `transaction.on_commit` nunca dispara de qualquer forma (nenhum destes
testes afirma nada sobre `mail.outbox`).
"""

import pytest
from django.contrib.auth.models import AnonymousUser
from django.core import mail
from django.core.exceptions import PermissionDenied, ValidationError
from django.urls import reverse

from apps.comum.semestre import semestre_vigente
from apps.contas.models import Area, PerfilAluno, PerfilProfessor, Usuario
from apps.contas.validators import _digito
from apps.projetos import permissions, services
from apps.projetos.models import Candidatura, OpcaoCandidatura, Projeto

ANO_VIGENTE, PERIODO_VIGENTE = semestre_vigente()


# CPFs sintéticos com dígito verificador válido — faixa própria (700000000+),
# para não colidir com as faixas já usadas por test_vagas.py (500000000+),
# test_concorrencia.py (600000000+) e test_candidatura.py (900000000+). A
# colisão não importaria de qualquer forma (cada teste roda numa transação
# revertida ao final), mas manter faixas distintas facilita achar de qual
# suíte um CPF veio ao ler uma falha.
def _gera_cpf(indice):
    base = f"{700000000 + indice:09d}"
    d1 = _digito(base, 10)
    d2 = _digito(base + str(d1), 11)
    return base + str(d1) + str(d2)


def _cria_professor(indice, nome):
    usuario = Usuario.objects.create_user(
        email=f"professor.fila{indice}@ufsm.br",
        password="x",
        nome_completo=nome,
        cpf=_gera_cpf(indice),
    )
    return PerfilProfessor.objects.create(usuario=usuario, siape=f"FILA{indice}")


def _cria_aluno(indice, nome="Aluno Fila"):
    usuario = Usuario.objects.create_user(
        email=f"aluno.fila{indice}@ufsm.br",
        password="x",
        nome_completo=nome,
        papel=Usuario.ALUNO,
        cpf=_gera_cpf(indice),
    )
    return PerfilAluno.objects.create(usuario=usuario, matricula=f"2026FILA{indice:03d}")


@pytest.fixture
def area(db):
    return Area.objects.create(nome="Engenharia de Software")


@pytest.fixture
def tres_professores(area):
    # Índices 1-3: faixa reservada aos professores principais do teste.
    return [_cria_professor(indice, f"Professor Fila {indice}") for indice in range(1, 4)]


@pytest.fixture
def aluno(db):
    # Índice 50: faixa reservada ao aluno principal, longe da dos professores.
    return _cria_aluno(50)


@pytest.fixture
def candidatura_em_curso(settings, django_capture_on_commit_callbacks, tres_professores, aluno):
    """Candidatura registrada (T8) com as três opções: a opção 1, para
    `tres_professores[0]`, nasce `ENVIADA` — é ela que os testes de aceitar
    e recusar exercitam. `mail.outbox` é limpo depois: o e-mail da primeira
    manifestação (disparado por `registrar_candidatura`) não é o que estes
    testes medem."""
    settings.CELERY_TASK_ALWAYS_EAGER = True
    opcoes = [(professor, None) for professor in tres_professores]
    with django_capture_on_commit_callbacks(execute=True):
        candidatura = services.registrar_candidatura(aluno, opcoes)
    mail.outbox.clear()
    return candidatura


@pytest.fixture
def opcao1(candidatura_em_curso):
    return candidatura_em_curso.opcoes.get(ordem=1)


@pytest.fixture
def recusa(settings, django_capture_on_commit_callbacks):
    """Chama `services.recusar_opcao` capturando os callbacks de
    `transaction.on_commit`, para os testes que precisam medir o e-mail de
    recusa (T8, `enviar_recusa`) ou o da próxima manifestação (`avancar_cascata`)."""
    settings.CELERY_TASK_ALWAYS_EAGER = True

    def _recusa(*args, **kwargs):
        with django_capture_on_commit_callbacks(execute=True):
            return services.recusar_opcao(*args, **kwargs)

    return _recusa


# --------------------------------------------------------------------------
# permissions.pode_responder_opcao
# --------------------------------------------------------------------------


@pytest.mark.django_db
def test_pode_responder_opcao_e_verdadeiro_para_o_professor_dono(opcao1, tres_professores):
    assert permissions.pode_responder_opcao(tres_professores[0].usuario, opcao1) is True


@pytest.mark.django_db
def test_pode_responder_opcao_e_falso_para_outro_professor(opcao1, tres_professores):
    assert permissions.pode_responder_opcao(tres_professores[1].usuario, opcao1) is False


@pytest.mark.django_db
def test_pode_responder_opcao_e_falso_para_aluno(opcao1, aluno):
    assert permissions.pode_responder_opcao(aluno.usuario, opcao1) is False


@pytest.mark.django_db
def test_pode_responder_opcao_e_falso_para_usuario_anonimo(opcao1):
    assert permissions.pode_responder_opcao(AnonymousUser(), opcao1) is False


# --------------------------------------------------------------------------
# services.aceitar_opcao
# --------------------------------------------------------------------------


@pytest.mark.django_db
def test_aceitar_opcao_cria_projeto_e_cancela_as_demais(
    candidatura_em_curso, opcao1, tres_professores, aluno
):
    projeto = services.aceitar_opcao(opcao1, por=tres_professores[0].usuario)

    assert isinstance(projeto, Projeto)
    assert projeto.aluno == aluno.usuario
    assert projeto.orientador == tres_professores[0].usuario
    assert projeto.etapa == Projeto.TCC_I
    assert projeto.status == Projeto.EM_ANDAMENTO

    candidatura_em_curso.refresh_from_db()
    assert candidatura_em_curso.status == Candidatura.ACEITA

    opcao1.refresh_from_db()
    assert opcao1.situacao == OpcaoCandidatura.ACEITA
    assert opcao1.respondida_em is not None

    opcao2, opcao3 = candidatura_em_curso.opcoes.filter(ordem__in=[2, 3]).order_by("ordem")
    assert opcao2.situacao == OpcaoCandidatura.CANCELADA
    assert opcao3.situacao == OpcaoCandidatura.CANCELADA


@pytest.mark.django_db
def test_aceitar_opcao_revalida_vaga_dentro_da_transacao(
    candidatura_em_curso, opcao1, tres_professores, aluno
):
    """spec §5.3: 'o e-mail que o professor recebeu pode ter dias, e as
    vagas podem ter enchido nesse meio-tempo'. `registrar_candidatura` já
    validou a vaga na hora do registro (T8); este teste enche as vagas do
    professor DEPOIS — simulando essa passagem de tempo — e prova que
    `aceitar_opcao` revalida por conta própria, sem confiar na checagem
    antiga."""
    professor = tres_professores[0]
    for indice in range(60, 63):
        services.criar_projeto_sob_limite(_cria_aluno(indice), professor, None, Projeto.TCC_I)

    with pytest.raises(ValidationError) as excinfo:
        services.aceitar_opcao(opcao1, por=professor.usuario)

    assert professor.usuario.nome_completo in excinfo.value.messages[0]
    candidatura_em_curso.refresh_from_db()
    assert candidatura_em_curso.status == Candidatura.EM_CURSO
    opcao1.refresh_from_db()
    assert opcao1.situacao == OpcaoCandidatura.ENVIADA
    assert not Projeto.objects.filter(aluno=aluno.usuario).exists()


@pytest.mark.django_db
def test_aceitar_opcao_ja_respondida_e_recusado(candidatura_em_curso, opcao1, tres_professores):
    services.aceitar_opcao(opcao1, por=tres_professores[0].usuario)

    with pytest.raises(ValidationError):
        services.aceitar_opcao(opcao1, por=tres_professores[0].usuario)


@pytest.mark.django_db
def test_aceitar_opcao_de_outro_professor_e_recusado_com_permissiondenied(opcao1, tres_professores):
    with pytest.raises(PermissionDenied):
        services.aceitar_opcao(opcao1, por=tres_professores[1].usuario)
    opcao1.refresh_from_db()
    assert opcao1.situacao == OpcaoCandidatura.ENVIADA


@pytest.mark.django_db
def test_aceitar_opcao_depois_do_aluno_cancelar_e_recusado(
    candidatura_em_curso, opcao1, tres_professores, aluno
):
    services.cancelar_candidatura(candidatura_em_curso, por=aluno.usuario)

    with pytest.raises(ValidationError):
        services.aceitar_opcao(opcao1, por=tres_professores[0].usuario)

    assert not Projeto.objects.filter(aluno=aluno.usuario).exists()


# --------------------------------------------------------------------------
# services.recusar_opcao
# --------------------------------------------------------------------------


@pytest.mark.django_db
def test_recusar_opcao_sem_justificativa_e_recusado(opcao1, tres_professores):
    with pytest.raises(ValidationError):
        services.recusar_opcao(opcao1, por=tres_professores[0].usuario, justificativa="")

    with pytest.raises(ValidationError):
        services.recusar_opcao(opcao1, por=tres_professores[0].usuario, justificativa="   ")

    opcao1.refresh_from_db()
    assert opcao1.situacao == OpcaoCandidatura.ENVIADA


@pytest.mark.django_db
def test_recusar_opcao_marca_recusada_com_justificativa(
    recusa, candidatura_em_curso, opcao1, tres_professores
):
    candidatura_atualizada = recusa(
        opcao1, por=tres_professores[0].usuario, justificativa="Fora da minha área."
    )

    opcao1.refresh_from_db()
    assert opcao1.situacao == OpcaoCandidatura.RECUSADA
    assert opcao1.justificativa == "Fora da minha área."
    assert opcao1.respondida_em is not None

    # `avancar_cascata` devolve a candidatura JÁ avançada (Importante 2 da
    # rodada de correção 2 da T8, apps/projetos/services.py:506-517): é o
    # RETORNO de `recusar_opcao` que precisa refletir isso, não o objeto que
    # a fixture `candidatura_em_curso` tinha em mãos antes da chamada.
    assert candidatura_atualizada.opcao_atual == 2
    assert candidatura_atualizada.status == Candidatura.EM_CURSO


@pytest.mark.django_db
def test_recusar_opcao_avanca_a_cascata_e_notifica_o_proximo_professor(
    recusa, candidatura_em_curso, opcao1, tres_professores
):
    recusa(opcao1, por=tres_professores[0].usuario, justificativa="Fora da minha área.")

    opcao2 = candidatura_em_curso.opcoes.get(ordem=2)
    assert opcao2.situacao == OpcaoCandidatura.ENVIADA
    assert opcao2.prazo is not None

    # Dois e-mails: a nova manifestação (avancar_cascata → _enviar_opcao,
    # T8) para o professor 2, e o aviso de recusa (enviar_recusa, T8) para o
    # aluno — o acréscimo do controlador que esta tarefa fecha (T8 criou a
    # tarefa e o template, mas nenhum serviço a chamava até aqui).
    assert len(mail.outbox) == 2
    destinatarios = {mensagem.to[0] for mensagem in mail.outbox}
    assert tres_professores[1].usuario.email in destinatarios
    assert candidatura_em_curso.aluno.usuario.email in destinatarios

    email_de_recusa = next(
        m for m in mail.outbox if m.to == [candidatura_em_curso.aluno.usuario.email]
    )
    assert "Fora da minha área." in email_de_recusa.body


@pytest.mark.django_db
def test_recusar_opcao_ja_respondida_e_recusado(
    recusa, candidatura_em_curso, opcao1, tres_professores
):
    recusa(opcao1, por=tres_professores[0].usuario, justificativa="Fora da minha área.")

    with pytest.raises(ValidationError):
        services.recusar_opcao(opcao1, por=tres_professores[0].usuario, justificativa="De novo.")


@pytest.mark.django_db
def test_recusar_opcao_de_outro_professor_e_recusado_com_permissiondenied(opcao1, tres_professores):
    with pytest.raises(PermissionDenied):
        services.recusar_opcao(opcao1, por=tres_professores[1].usuario, justificativa="Não é meu.")
    opcao1.refresh_from_db()
    assert opcao1.situacao == OpcaoCandidatura.ENVIADA


@pytest.mark.django_db
def test_recusar_opcao_depois_do_aluno_cancelar_e_recusado(
    candidatura_em_curso, opcao1, tres_professores, aluno
):
    services.cancelar_candidatura(candidatura_em_curso, por=aluno.usuario)

    with pytest.raises(ValidationError):
        services.recusar_opcao(
            opcao1, por=tres_professores[0].usuario, justificativa="Tarde demais."
        )


# --------------------------------------------------------------------------
# view projetos:orientacoes
# --------------------------------------------------------------------------


@pytest.mark.django_db
def test_orientacoes_exige_autenticacao(client):
    resposta = client.get(reverse("projetos:orientacoes"))
    assert resposta.status_code == 302
    assert "/contas/login/" in resposta.url


@pytest.mark.django_db
def test_orientacoes_recusa_aluno_com_403(client, aluno):
    client.force_login(aluno.usuario)
    resposta = client.get(reverse("projetos:orientacoes"))
    assert resposta.status_code == 403


@pytest.mark.django_db
def test_orientacoes_recusa_professor_sem_perfil_com_403_nao_500(client):
    """O mesmo defeito que `apps/contas/views.py::perfil` já teve na Fase 1,
    e que `apps/projetos/views.py::meus_temas` já evita (T6): papel
    PROFESSOR sem `PerfilProfessor` não pode derrubar a página com 500."""
    usuario = Usuario.objects.create_user(
        email="coord.sem.perfil.fila@ufsm.br",
        password="x",
        nome_completo="Coordenação Sem Perfil Fila",
        cpf=_gera_cpf(90),
        is_coordenador=True,
        is_staff=True,
    )
    client.force_login(usuario)
    resposta = client.get(reverse("projetos:orientacoes"))
    assert resposta.status_code == 403


@pytest.mark.django_db
def test_orientacoes_lista_as_pendentes_do_professor_autenticado(
    client, candidatura_em_curso, opcao1, tres_professores
):
    client.force_login(tres_professores[0].usuario)

    html = client.get(reverse("projetos:orientacoes")).content.decode()

    assert candidatura_em_curso.aluno.usuario.nome_completo in html


@pytest.mark.django_db
def test_orientacoes_nao_lista_pendente_de_outro_professor(
    client, candidatura_em_curso, tres_professores
):
    client.force_login(tres_professores[1].usuario)

    html = client.get(reverse("projetos:orientacoes")).content.decode()

    assert candidatura_em_curso.aluno.usuario.nome_completo not in html


@pytest.mark.django_db
def test_professor_aceita_opcao_pela_tela(
    client, candidatura_em_curso, opcao1, tres_professores, aluno
):
    client.force_login(tres_professores[0].usuario)

    resposta = client.post(reverse("projetos:aceitar_opcao", args=[opcao1.pk]))

    assert resposta.status_code == 302
    assert Projeto.objects.filter(
        aluno=aluno.usuario, orientador=tres_professores[0].usuario
    ).exists()


@pytest.mark.django_db
def test_aceitar_opcao_exige_post(client, opcao1, tres_professores):
    client.force_login(tres_professores[0].usuario)

    resposta = client.get(reverse("projetos:aceitar_opcao", args=[opcao1.pk]))

    assert resposta.status_code == 405


@pytest.mark.django_db
def test_aceitar_opcao_de_outro_professor_recebe_404_nao_403(client, opcao1, tres_professores):
    """Mesmo padrão de
    test_temas.py::test_desativar_tema_de_outro_professor_recebe_404_nao_403:
    a view escopa o lookup ao professor autenticado
    (`get_object_or_404(OpcaoCandidatura, pk=..., professor=...)`), então
    opção alheia e opção inexistente respondem os DOIS 404 — sem isso, a
    URL vira um oráculo de existência sobre manifestações de outros
    professores."""
    client.force_login(tres_professores[1].usuario)

    resposta = client.post(reverse("projetos:aceitar_opcao", args=[opcao1.pk]))

    assert resposta.status_code == 404
    opcao1.refresh_from_db()
    assert opcao1.situacao == OpcaoCandidatura.ENVIADA


@pytest.mark.django_db
def test_aceitar_opcao_inexistente_e_alheia_respondem_o_mesmo_status(
    client, opcao1, tres_professores
):
    client.force_login(tres_professores[1].usuario)

    resposta_alheia = client.post(reverse("projetos:aceitar_opcao", args=[opcao1.pk]))
    resposta_inexistente = client.post(reverse("projetos:aceitar_opcao", args=[opcao1.pk + 9999]))

    assert resposta_alheia.status_code == resposta_inexistente.status_code == 404


@pytest.mark.django_db
def test_professor_recusa_opcao_pela_tela(client, candidatura_em_curso, opcao1, tres_professores):
    client.force_login(tres_professores[0].usuario)

    resposta = client.post(
        reverse("projetos:recusar_opcao", args=[opcao1.pk]),
        {"justificativa": "Fora da minha área."},
    )

    assert resposta.status_code == 302
    opcao1.refresh_from_db()
    assert opcao1.situacao == OpcaoCandidatura.RECUSADA
    assert opcao1.justificativa == "Fora da minha área."


@pytest.mark.django_db
def test_recusar_opcao_exige_post(client, opcao1, tres_professores):
    client.force_login(tres_professores[0].usuario)

    resposta = client.get(reverse("projetos:recusar_opcao", args=[opcao1.pk]))

    assert resposta.status_code == 405


@pytest.mark.django_db
def test_recusar_opcao_pela_tela_sem_justificativa_nao_recusa(client, opcao1, tres_professores):
    client.force_login(tres_professores[0].usuario)

    resposta = client.post(
        reverse("projetos:recusar_opcao", args=[opcao1.pk]), {"justificativa": ""}
    )

    assert resposta.status_code == 302
    opcao1.refresh_from_db()
    assert opcao1.situacao == OpcaoCandidatura.ENVIADA


@pytest.mark.django_db
def test_recusar_opcao_de_outro_professor_recebe_404_nao_403(client, opcao1, tres_professores):
    client.force_login(tres_professores[1].usuario)

    resposta = client.post(
        reverse("projetos:recusar_opcao", args=[opcao1.pk]), {"justificativa": "Não é meu."}
    )

    assert resposta.status_code == 404
    opcao1.refresh_from_db()
    assert opcao1.situacao == OpcaoCandidatura.ENVIADA
