"""Testes das duas regras de negócio inegociáveis da coordenação (CLAUDE.md,
seção "Regras de Negócio Inegociáveis", item 2) — teto de 4 coordenadores e
trava do último coordenador — e da view `contas:painel`, que é a única porta
de entrada do sistema para essas duas regras (convidar, promover, revogar).

Os seis primeiros testes (serviço) reproduzem exatamente o roteiro do brief
da Tarefa 11: escritos antes de `services.promover_a_coordenador` e
`services.revogar_coordenacao` existirem, para provar via RED que o teste
falha pela ausência do serviço, não por outro motivo.
"""

import pytest
from django.core import mail
from django.core.exceptions import PermissionDenied, ValidationError
from django.urls import reverse
from django.utils import timezone

from apps.contas import services
from apps.contas.models import Convite, Usuario
from apps.contas.validators import _digito

CPFS = ["52998224725", "16899535009", "11144477735", "12345678909", "98765432100", "39053344705"]


def cria_professor(indice, coordenador=False):
    return Usuario.objects.create_user(
        email=f"prof{indice}@ufsm.br",
        password="x",
        nome_completo=f"Professor {indice}",
        cpf=CPFS[indice],
        is_coordenador=coordenador,
        is_staff=coordenador,
    )


def _gera_cpf(indice):
    """Gera um CPF com dígitos verificadores válidos para qualquer índice,
    reusando o mesmo algoritmo de `apps.contas.validators.valida_cpf` (a
    função `_digito`, exposta ali para os próprios testes do validador).

    Os testes de view/acessibilidade abaixo precisam de mais professores do
    que a lista fixa `CPFS` (pensada só para os seis testes de serviço do
    brief) cobre, sem arriscar colisão com ela — daí gerar em vez de
    hardcodar mais uma lista.
    """
    base = f"{200000000 + indice:09d}"
    d1 = _digito(base, 10)
    d2 = _digito(base + str(d1), 11)
    return base + str(d1) + str(d2)


def cria_professor_gerado(indice, nome=None, coordenador=False):
    return Usuario.objects.create_user(
        email=f"gerado{indice}@ufsm.br",
        password="x",
        nome_completo=nome or f"Professor Gerado {indice}",
        cpf=_gera_cpf(indice),
        is_coordenador=coordenador,
        is_staff=coordenador,
    )


# --- Passo 1: serviços (roteiro do brief) -----------------------------------


@pytest.mark.django_db
def test_promover_marca_coordenador_e_staff():
    coordenadora = cria_professor(0, coordenador=True)
    alvo = cria_professor(1)

    services.promover_a_coordenador(alvo, por=coordenadora)

    alvo.refresh_from_db()
    assert alvo.is_coordenador is True
    assert alvo.is_staff is True


@pytest.mark.django_db
def test_quinta_promocao_e_recusada():
    coordenadores = [cria_professor(i, coordenador=True) for i in range(4)]
    quinto = cria_professor(4)

    with pytest.raises(ValidationError) as erro:
        services.promover_a_coordenador(quinto, por=coordenadores[0])

    assert "4" in str(erro.value)
    quinto.refresh_from_db()
    assert quinto.is_coordenador is False


@pytest.mark.django_db
def test_aluno_nao_pode_ser_promovido():
    coordenadora = cria_professor(0, coordenador=True)
    aluno = Usuario.objects.create_user(
        email="joao@ufsm.br",
        password="x",
        nome_completo="João",
        cpf=CPFS[1],
        papel=Usuario.ALUNO,
    )

    with pytest.raises(ValidationError):
        services.promover_a_coordenador(aluno, por=coordenadora)


@pytest.mark.django_db
def test_ultimo_coordenador_nao_pode_ser_revogado():
    unica = cria_professor(0, coordenador=True)

    with pytest.raises(ValidationError) as erro:
        services.revogar_coordenacao(unica, por=unica)

    assert "outro" in str(erro.value).lower()
    unica.refresh_from_db()
    assert unica.is_coordenador is True


@pytest.mark.django_db
def test_revogar_funciona_havendo_outro_coordenador():
    primeira = cria_professor(0, coordenador=True)
    segunda = cria_professor(1, coordenador=True)

    services.revogar_coordenacao(segunda, por=primeira)

    segunda.refresh_from_db()
    assert segunda.is_coordenador is False
    assert segunda.is_staff is False


@pytest.mark.django_db
def test_professor_comum_nao_promove():
    comum = cria_professor(0)
    alvo = cria_professor(1)

    with pytest.raises(PermissionDenied):
        services.promover_a_coordenador(alvo, por=comum)


# --- Regra não coberta literalmente pelo brief, mas exigida pela -----------
# --- autorrevisão: a trava do último coordenador precisa valer tanto -------
# --- quando o alvo é o próprio solicitante quanto quando é outra pessoa. ---


@pytest.mark.django_db
def test_trava_do_ultimo_coordenador_vale_para_auto_revogacao_e_para_outra_pessoa():
    """A trava depende só da contagem que resultaria da revogação, não de
    quem é o alvo: com dois coordenadores, uma pode revogar a outra (alvo é
    outra pessoa) e sobra um só; a partir daí, mesmo essa pessoa que sobrou
    tentando revogar A SI MESMA (alvo é o próprio solicitante) é recusada.
    Um único teste, em sequência, cobre as duas formas do mesmo alvo real:
    "ia sobrar zero coordenadores"."""
    primeira = cria_professor(0, coordenador=True)
    segunda = cria_professor(1, coordenador=True)

    # Alvo é outra pessoa: permitido, ainda resta um coordenador depois.
    services.revogar_coordenacao(segunda, por=primeira)
    segunda.refresh_from_db()
    assert segunda.is_coordenador is False

    # Agora só resta "primeira": alvo é o próprio solicitante, recusado.
    with pytest.raises(ValidationError) as erro:
        services.revogar_coordenacao(primeira, por=primeira)
    assert "outro" in str(erro.value).lower()
    primeira.refresh_from_db()
    assert primeira.is_coordenador is True


# --- Passo 5 do brief: a view do painel -------------------------------------


@pytest.mark.django_db
def test_painel_recusa_quem_nao_e_coordenador(client):
    comum = cria_professor(0)
    client.force_login(comum)
    assert client.get(reverse("contas:painel")).status_code == 403


@pytest.mark.django_db
def test_painel_recusa_anonimo_redirecionando_ao_login(client):
    resposta = client.get(reverse("contas:painel"))
    assert resposta.status_code == 302
    assert "/contas/login/" in resposta.url


@pytest.mark.django_db
def test_painel_envia_convite(client, settings, django_capture_on_commit_callbacks):
    settings.CELERY_TASK_ALWAYS_EAGER = True
    coordenadora = cria_professor(0, coordenador=True)
    client.force_login(coordenadora)

    with django_capture_on_commit_callbacks(execute=True):
        resposta = client.post(
            reverse("contas:painel"), {"email": "novo@ufsm.br", "papel": Usuario.PROFESSOR}
        )

    assert resposta.status_code == 302
    assert Usuario.objects.filter(email="novo@ufsm.br").count() == 0
    assert Convite.objects.filter(email="novo@ufsm.br").exists()


@pytest.mark.django_db
def test_painel_lista_coordenadores_e_candidatos_a_promocao(client):
    coordenadora = cria_professor(0, coordenador=True)
    candidato = cria_professor(1)
    client.force_login(coordenadora)

    html = client.get(reverse("contas:painel")).content.decode()

    assert coordenadora.nome_completo in html
    assert candidato.nome_completo in html


@pytest.mark.django_db
def test_painel_nao_oferece_promover_para_professor_inativo(client):
    """Achado da revisão 1, ainda válido depois da refatoração em duas
    colunas (o usuário pediu "Professores" como lista única, dobrando as
    antigas seções "Coordenadores"/"Promover a coordenador(a)"): o professor
    desativado agora APARECE na lista — é um professor de verdade, e a
    coordenação precisa vê-lo para agir sobre a conta — mas sem o botão
    "Promover a coordenador(a)", que levaria a uma ação que o serviço já
    recusa (`test_promover_recusa_alvo_com_conta_desativada`)."""
    coordenadora = cria_professor(0, coordenador=True)
    inativo = cria_professor(1)
    inativo.is_active = False
    inativo.save(update_fields=["is_active"])
    client.force_login(coordenadora)

    html = client.get(reverse("contas:painel")).content.decode()

    assert inativo.nome_completo in html
    assert f"Promover a coordenador(a): {inativo.nome_completo}" not in html


@pytest.mark.django_db
def test_painel_lista_coordenador_inativo_marcado_como_tal(client):
    """SUBSTITUI `test_painel_nao_lista_coordenador_inativo` (T11), que
    afirmava o contrário — a decisão que ele codificava é o defeito corrigido
    na revisão final, não uma regra que se possa preservar.

    A tela escondia o coordenador desativado enquanto `services` contava
    todo `is_coordenador=True`: com quatro coordenadores e um desativado, o
    painel anunciava "Coordenadores (3 de 4)", oferecia promoções, e o
    serviço as recusava pelo teto. Decidido que coordenador inativo OCUPA
    vaga (ver `services.coordenadores`), a tela precisa mostrá-lo — inclusive
    para que a vaga possa ser liberada por ali, com "Revogar coordenação"."""
    coordenadora = cria_professor(0, coordenador=True)
    outra = cria_professor(1, coordenador=True)
    outra.is_active = False
    outra.save(update_fields=["is_active"])
    client.force_login(coordenadora)

    html = client.get(reverse("contas:painel")).content.decode()

    assert outra.nome_completo in html
    assert "Conta desativada" in html


@pytest.mark.django_db
def test_contagem_exibida_no_painel_e_a_mesma_que_o_servico_aplica(client):
    """A regressão inteira do achado, em um teste: quatro coordenadores, um
    deles desativado. O painel precisa anunciar "4 de 4" — não "3 de 4" —
    porque é 4 o número que `promover_a_coordenador` vai aplicar ao recusar a
    quinta promoção logo abaixo."""
    coordenadores = [cria_professor_gerado(i, coordenador=True) for i in range(4)]
    coordenadores[3].is_active = False
    coordenadores[3].save(update_fields=["is_active"])
    quinto = cria_professor_gerado(4)
    client.force_login(coordenadores[0])

    html = client.get(reverse("contas:painel")).content.decode()
    assert f"Coordenadores ({services.LIMITE_COORDENADORES} de " in html

    with pytest.raises(ValidationError):
        services.promover_a_coordenador(quinto, por=coordenadores[0])


@pytest.mark.django_db
def test_promover_recusa_alvo_com_conta_desativada():
    """A recusa é do SERVIÇO, não da lista exibida (CLAUDE.md, regra 4): a
    view filtrava `is_active` para montar os candidatos, mas nada impedia
    postar o `usuario_id` de um professor desativado direto na rota de
    promoção."""
    coordenadora = cria_professor(0, coordenador=True)
    inativo = cria_professor(1)
    inativo.is_active = False
    inativo.save(update_fields=["is_active"])

    with pytest.raises(ValidationError) as erro:
        services.promover_a_coordenador(inativo, por=coordenadora)

    assert "desativada" in str(erro.value)
    inativo.refresh_from_db()
    assert inativo.is_coordenador is False


@pytest.mark.django_db
def test_promover_via_painel_recusa_alvo_desativado_postado_direto(client):
    coordenadora = cria_professor(0, coordenador=True)
    inativo = cria_professor(1)
    inativo.is_active = False
    inativo.save(update_fields=["is_active"])
    client.force_login(coordenadora)

    resposta = client.post(reverse("contas:promover"), {"usuario_id": inativo.pk}, follow=True)

    mensagens = [str(m) for m in resposta.context["messages"]]
    assert any("desativada" in m for m in mensagens)
    inativo.refresh_from_db()
    assert inativo.is_coordenador is False


@pytest.mark.django_db
def test_candidatos_a_coordenacao_exclui_inativos_e_coordenadores():
    """O complemento exato de quem `promover_a_coordenador` aceita: a lista
    que o painel oferece não pode conter ninguém que o serviço vá recusar."""
    coordenadora = cria_professor(0, coordenador=True)
    promovivel = cria_professor(1)
    inativo = cria_professor(2)
    inativo.is_active = False
    inativo.save(update_fields=["is_active"])
    aluno = Usuario.objects.create_user(
        email="aluno-candidato@ufsm.br",
        password="x",
        nome_completo="Aluno",
        cpf=CPFS[3],
        papel=Usuario.ALUNO,
    )

    candidatos = list(services.candidatos_a_coordenacao())

    assert promovivel in candidatos
    assert coordenadora not in candidatos
    assert inativo not in candidatos
    assert aluno not in candidatos


# --- Interface de promover, no painel (lacuna do brief) ---------------------


@pytest.mark.django_db
def test_promover_via_painel_promove_e_redireciona(client):
    coordenadora = cria_professor(0, coordenador=True)
    alvo = cria_professor(1)
    client.force_login(coordenadora)

    resposta = client.post(reverse("contas:promover"), {"usuario_id": alvo.pk})

    assert resposta.status_code == 302
    alvo.refresh_from_db()
    assert alvo.is_coordenador is True


@pytest.mark.django_db
def test_promover_via_painel_mostra_mensagem_clara_no_teto(client):
    coordenadores = [cria_professor_gerado(i, coordenador=True) for i in range(4)]
    quinto = cria_professor_gerado(4)
    client.force_login(coordenadores[0])

    resposta = client.post(reverse("contas:promover"), {"usuario_id": quinto.pk}, follow=True)

    mensagens = [str(m) for m in resposta.context["messages"]]
    assert any("4" in m and ("revogue" in m.lower() or "máximo" in m.lower()) for m in mensagens)
    quinto.refresh_from_db()
    assert quinto.is_coordenador is False


@pytest.mark.django_db
def test_promover_via_painel_recusa_quem_nao_e_coordenador(client):
    comum = cria_professor(0)
    alvo = cria_professor(1)
    client.force_login(comum)

    resposta = client.post(reverse("contas:promover"), {"usuario_id": alvo.pk})

    assert resposta.status_code == 403
    alvo.refresh_from_db()
    assert alvo.is_coordenador is False


@pytest.mark.django_db
def test_promover_via_painel_exige_post(client):
    coordenadora = cria_professor(0, coordenador=True)
    client.force_login(coordenadora)
    assert client.get(reverse("contas:promover")).status_code == 405


@pytest.mark.django_db
def test_promover_via_painel_usuario_inexistente_da_404(client):
    coordenadora = cria_professor(0, coordenador=True)
    client.force_login(coordenadora)
    assert client.post(reverse("contas:promover"), {"usuario_id": 999999}).status_code == 404


@pytest.mark.django_db
def test_promover_via_painel_recusa_antes_de_buscar_alvo_inexistente(client):
    """Regressão da revisão 1: a permissão precisa ser conferida ANTES do
    lookup do `usuario_id`. Sem essa ordem, um `usuario_id` inexistente
    responderia 404 mesmo para quem não tem permissão nenhuma — e um
    professor comum poderia enumerar contas comparando 403 (id existe) com
    404 (id não existe). Aqui, um id que nem existe deve dar 403 do mesmo
    jeito, porque a permissão é checada primeiro."""
    comum = cria_professor(0)
    client.force_login(comum)
    assert client.post(reverse("contas:promover"), {"usuario_id": 999999}).status_code == 403


# --- Interface de revogar, no painel (lacuna do brief) ----------------------


@pytest.mark.django_db
def test_revogar_via_painel_revoga_e_redireciona(client):
    primeira = cria_professor(0, coordenador=True)
    segunda = cria_professor(1, coordenador=True)
    client.force_login(primeira)

    resposta = client.post(reverse("contas:revogar"), {"usuario_id": segunda.pk})

    assert resposta.status_code == 302
    segunda.refresh_from_db()
    assert segunda.is_coordenador is False


@pytest.mark.django_db
def test_revogar_via_painel_mostra_mensagem_clara_no_ultimo(client):
    unica = cria_professor(0, coordenador=True)
    client.force_login(unica)

    resposta = client.post(reverse("contas:revogar"), {"usuario_id": unica.pk}, follow=True)

    mensagens = [str(m) for m in resposta.context["messages"]]
    assert any("outro" in m.lower() for m in mensagens)
    unica.refresh_from_db()
    assert unica.is_coordenador is True


@pytest.mark.django_db
def test_revogar_via_painel_recusa_quem_nao_e_coordenador(client):
    comum = cria_professor(0)
    alvo = cria_professor(1, coordenador=True)
    client.force_login(comum)

    resposta = client.post(reverse("contas:revogar"), {"usuario_id": alvo.pk})

    assert resposta.status_code == 403
    alvo.refresh_from_db()
    assert alvo.is_coordenador is True


@pytest.mark.django_db
def test_revogar_via_painel_exige_post(client):
    coordenadora = cria_professor(0, coordenador=True)
    client.force_login(coordenadora)
    assert client.get(reverse("contas:revogar")).status_code == 405


@pytest.mark.django_db
def test_revogar_via_painel_recusa_antes_de_buscar_alvo_inexistente(client):
    """Mesma regressão de `test_promover_via_painel_recusa_antes_de_buscar_alvo_inexistente`,
    para `revogar`: permissão checada antes do lookup, então um id
    inexistente também dá 403 para quem não tem permissão — nunca 404."""
    comum = cria_professor(0)
    client.force_login(comum)
    assert client.post(reverse("contas:revogar"), {"usuario_id": 999999}).status_code == 403


# --- Reenvio de convite pelo painel (a porta que faltava) ------------------


def _convite_pendente(coordenadora, email="pendente@ufsm.br", token_hash="a" * 64):
    return Convite.objects.create(
        email=email,
        papel=Usuario.ALUNO,
        token_hash=token_hash,
        criado_por=coordenadora,
        expira_em=timezone.now() + timezone.timedelta(days=7),
    )


@pytest.mark.django_db
def test_painel_oferece_reenvio_para_convite_pendente(client):
    """`services.reenviar_convite` existia desde a T7, com quatro testes, e
    nenhuma URL, view ou botão o alcançava (achado da revisão final)."""
    coordenadora = cria_professor(0, coordenador=True)
    _convite_pendente(coordenadora)
    client.force_login(coordenadora)

    html = client.get(reverse("contas:painel")).content.decode()

    assert reverse("contas:reenviar") in html
    assert "Reenviar convite" in html


@pytest.mark.django_db
def test_painel_nao_oferece_reenvio_para_convite_ja_aceito(client):
    """`reenviar_convite` recusa convite utilizado: oferecer o botão ali seria
    oferecer uma ação que só produz mensagem de erro."""
    coordenadora = cria_professor(0, coordenador=True)
    convite = _convite_pendente(coordenadora)
    convite.usado_em = timezone.now()
    convite.save(update_fields=["usado_em"])
    client.force_login(coordenadora)

    html = client.get(reverse("contas:painel")).content.decode()

    assert "Reenviar convite" not in html


@pytest.mark.django_db
def test_reenviar_via_painel_expira_o_anterior_e_manda_outro_email(
    client, settings, django_capture_on_commit_callbacks
):
    settings.CELERY_TASK_ALWAYS_EAGER = True
    coordenadora = cria_professor(0, coordenador=True)
    convite = _convite_pendente(coordenadora)
    client.force_login(coordenadora)

    with django_capture_on_commit_callbacks(execute=True):
        resposta = client.post(reverse("contas:reenviar"), {"convite_id": convite.pk})

    assert resposta.status_code == 302
    convite.refresh_from_db()
    assert not convite.esta_valido()
    novo = Convite.objects.filter(email=convite.email).exclude(pk=convite.pk).get()
    assert novo.esta_valido()
    assert len(mail.outbox) == 1
    assert convite.email in mail.outbox[0].to


@pytest.mark.django_db
def test_reenviar_via_painel_recusa_convite_ja_utilizado(client):
    coordenadora = cria_professor(0, coordenador=True)
    convite = _convite_pendente(coordenadora)
    convite.usado_em = timezone.now()
    convite.save(update_fields=["usado_em"])
    client.force_login(coordenadora)

    resposta = client.post(reverse("contas:reenviar"), {"convite_id": convite.pk}, follow=True)

    mensagens = [str(m) for m in resposta.context["messages"]]
    assert any("utilizado" in m for m in mensagens)


@pytest.mark.django_db
def test_reenviar_via_painel_recusa_quem_nao_e_coordenador(client):
    coordenadora = cria_professor(0, coordenador=True)
    comum = cria_professor(1)
    convite = _convite_pendente(coordenadora)
    client.force_login(comum)

    assert client.post(reverse("contas:reenviar"), {"convite_id": convite.pk}).status_code == 403


@pytest.mark.django_db
def test_reenviar_via_painel_exige_post(client):
    coordenadora = cria_professor(0, coordenador=True)
    client.force_login(coordenadora)
    assert client.get(reverse("contas:reenviar")).status_code == 405


@pytest.mark.django_db
def test_reenviar_via_painel_recusa_antes_de_buscar_convite_inexistente(client):
    """Mesma ordem de `promover`/`revogar`: permissão antes do lookup, para
    que a resposta não distinga um `convite_id` existente de um inexistente."""
    comum = cria_professor(0)
    client.force_login(comum)
    assert client.post(reverse("contas:reenviar"), {"convite_id": 999999}).status_code == 403


@pytest.mark.django_db
def test_reenviar_via_painel_com_convite_inexistente_da_404(client):
    coordenadora = cria_professor(0, coordenador=True)
    client.force_login(coordenadora)
    assert client.post(reverse("contas:reenviar"), {"convite_id": 999999}).status_code == 404


# --- Painel em duas colunas: "Professores" e "Alunos" (refatoração --------
# --- posterior, pedido explícito do usuário) -------------------------------


def _cria_aluno(indice, nome=None):
    """Fábrica de aluno para os testes de `alunos_sem_tcc_ii_concluido`
    abaixo. Faixa de CPF própria (200000050+), livre da faixa 200000000-4
    que `_gera_cpf`/`cria_professor_gerado`, acima, já usam neste arquivo."""
    from apps.contas.models import PerfilAluno

    usuario = Usuario.objects.create_user(
        email=f"aluno-painel-{indice}@ufsm.br",
        password="x",
        nome_completo=nome or f"Aluno Painel {indice}",
        papel=Usuario.ALUNO,
        cpf=_gera_cpf(50 + indice),
    )
    PerfilAluno.objects.create(usuario=usuario, matricula=f"2026PAINEL{indice:02d}")
    return usuario


def _cria_orientador(indice):
    from apps.contas.models import PerfilProfessor

    orientador = cria_professor_gerado(90 + indice, nome=f"Orientador Painel {indice}")
    PerfilProfessor.objects.create(usuario=orientador, siape=f"PAINEL{indice:03d}")
    return orientador


def _cria_projeto(aluno, etapa, status, orientador):
    from apps.projetos.models import Projeto

    return Projeto.objects.create(
        aluno=aluno, orientador=orientador, etapa=etapa, status=status, ano=2026, periodo=1
    )


@pytest.mark.django_db
def test_professores_para_painel_inclui_inativo_e_exclui_aluno():
    coordenadora = cria_professor(0, coordenador=True)
    comum = cria_professor(1)
    comum.is_active = False
    comum.save(update_fields=["is_active"])
    aluno = _cria_aluno(0)

    professores = list(services.professores_para_painel())

    assert coordenadora in professores
    assert comum in professores
    assert aluno not in professores


@pytest.mark.django_db
def test_alunos_sem_tcc_ii_concluido_exclui_quem_concluiu():
    """Mutação obrigatória (CLAUDE.md, disciplina de testes): a diferença
    entre "concluiu" e "não concluiu" é o único ponto que este teste prova —
    remover o `exclude(...)` de `alunos_sem_tcc_ii_concluido` faz este teste
    reprovar (verificado nesta revisão)."""
    from apps.projetos.models import Projeto

    orientador = _cria_orientador(0)
    concluiu = _cria_aluno(1, "Aluno Concluiu TCC II")
    _cria_projeto(concluiu, Projeto.TCC_II, Projeto.CONCLUIDO, orientador)

    em_andamento = _cria_aluno(2, "Aluno TCC II Em Andamento")
    _cria_projeto(em_andamento, Projeto.TCC_II, Projeto.EM_ANDAMENTO, orientador)

    sem_projeto_nenhum = _cria_aluno(3, "Aluno Sem Projeto")

    pendentes = list(services.alunos_sem_tcc_ii_concluido())

    assert concluiu not in pendentes
    assert em_andamento in pendentes
    assert sem_projeto_nenhum in pendentes


@pytest.mark.django_db
def test_painel_lista_professores_e_alunos_pendentes(client):
    coordenadora = cria_professor(0, coordenador=True)
    aluno = _cria_aluno(4, "Aluno Pendente Painel")
    client.force_login(coordenadora)

    html = client.get(reverse("contas:painel")).content.decode()

    assert "Professores" in html
    assert "Alunos" in html
    assert coordenadora.nome_completo in html
    assert aluno.nome_completo in html


@pytest.mark.django_db
def test_painel_nao_lista_aluno_que_concluiu_tcc_ii(client):
    from apps.projetos.models import Projeto

    coordenadora = cria_professor(0, coordenador=True)
    orientador = _cria_orientador(1)
    concluiu = _cria_aluno(5, "Aluno Concluiu Painel")
    _cria_projeto(concluiu, Projeto.TCC_II, Projeto.CONCLUIDO, orientador)
    client.force_login(coordenadora)

    html = client.get(reverse("contas:painel")).content.decode()

    assert concluiu.nome_completo not in html
