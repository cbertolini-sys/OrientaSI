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
from django.core.exceptions import PermissionDenied, ValidationError
from django.urls import reverse

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
def test_painel_nao_lista_professor_inativo_como_candidato(client):
    """Achado da revisão 1: sem filtrar `is_active`, um professor desativado
    apareceria como promovível — uma linha que fecha antes de a lacuna
    existir de verdade (hoje não há tela de desativação, mas o campo já
    existe no model)."""
    coordenadora = cria_professor(0, coordenador=True)
    inativo = cria_professor(1)
    inativo.is_active = False
    inativo.save(update_fields=["is_active"])
    client.force_login(coordenadora)

    html = client.get(reverse("contas:painel")).content.decode()

    assert inativo.nome_completo not in html


@pytest.mark.django_db
def test_painel_nao_lista_coordenador_inativo(client):
    coordenadora = cria_professor(0, coordenador=True)
    outra = cria_professor(1, coordenador=True)
    outra.is_active = False
    outra.save(update_fields=["is_active"])
    client.force_login(coordenadora)

    html = client.get(reverse("contas:painel")).content.decode()

    assert outra.nome_completo not in html


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
