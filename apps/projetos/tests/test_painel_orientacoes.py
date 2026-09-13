"""Testes do painel da coordenação para ajuste de orientações (T12, spec §6 e
§10 critérios 10-12): troca de orientador (`services.trocar_orientador`) e
limites elevados de vaga (`services.conceder_limite`/`revogar_limite`).

`trocar_orientador` revalida a vaga do professor NOVO com a MESMA disciplina
de travamento de `criar_projeto_sob_limite` (T5) — a prova de concorrência
mora em `test_concorrencia.py`, junto das demais provas de travamento deste
app, não aqui (mesma separação que `test_vagas.py` já documenta: "sem
concorrência — a prova de travamento sob concorrência real está em
test_concorrencia.py").
"""

import pytest
from django.contrib.auth.models import AnonymousUser
from django.core.exceptions import PermissionDenied, ValidationError
from django.urls import reverse

from apps.comum.semestre import semestre_vigente
from apps.contas.models import PerfilAluno, PerfilProfessor, Usuario
from apps.contas.validators import _digito
from apps.projetos import permissions, services
from apps.projetos.models import LimiteOrientacao, Projeto

ANO_VIGENTE, PERIODO_VIGENTE = semestre_vigente()
ANO_ANTERIOR = ANO_VIGENTE - 1


# CPFs sintéticos com dígito verificador válido — faixa própria (330000000+),
# distinta das já usadas por test_vagas.py (500000000+), test_concorrencia.py
# (600000000+), test_fila_professor.py (700000000+), test_prazo.py
# (800000000+) e test_candidatura.py/test_tela_candidatura.py (900000000+/
# 950000000+). A colisão não importaria de qualquer forma (cada teste roda
# numa transação revertida ao final), mas manter faixas distintas facilita
# achar de qual suíte um CPF veio ao ler uma falha.
def _gera_cpf(indice):
    base = f"{330000000 + indice:09d}"
    d1 = _digito(base, 10)
    d2 = _digito(base + str(d1), 11)
    return base + str(d1) + str(d2)


def _cria_professor(indice, nome):
    usuario = Usuario.objects.create_user(
        email=f"professor.painel{indice}@ufsm.br",
        password="x",
        nome_completo=nome,
        cpf=_gera_cpf(indice),
    )
    return PerfilProfessor.objects.create(usuario=usuario, siape=f"PAINEL{indice}")


def _cria_aluno(indice, nome="Aluno Painel"):
    usuario = Usuario.objects.create_user(
        email=f"aluno.painel{indice}@ufsm.br",
        password="x",
        nome_completo=nome,
        papel=Usuario.ALUNO,
        cpf=_gera_cpf(indice),
    )
    return PerfilAluno.objects.create(usuario=usuario, matricula=f"2026PAINEL{indice:03d}")


def _cria_projeto(aluno_usuario, professor, ano, periodo, etapa=Projeto.TCC_I, tema=None):
    return Projeto.objects.create(
        aluno=aluno_usuario,
        orientador=professor.usuario,
        tema=tema,
        etapa=etapa,
        status=Projeto.EM_ANDAMENTO,
        ano=ano,
        periodo=periodo,
    )


@pytest.fixture
def coordenador(db):
    return Usuario.objects.create_user(
        email="coordenador.painel@ufsm.br",
        password="x",
        nome_completo="Coordenadora Painel",
        cpf=_gera_cpf(1),
        is_coordenador=True,
        is_staff=True,
    )


@pytest.fixture
def professor_novo(db):
    # Índice 2: o professor PARA quem os projetos são trocados / a quem se
    # concede limite, na maioria dos testes.
    return _cria_professor(2, "Professor Novo Painel")


@pytest.fixture
def professor_antigo(db):
    # Índice 3: o orientador ATUAL do projeto, antes da troca.
    return _cria_professor(3, "Professor Antigo Painel")


@pytest.fixture
def aluno(db):
    return _cria_aluno(50)


@pytest.fixture
def projeto(professor_antigo, aluno):
    return _cria_projeto(aluno.usuario, professor_antigo, ANO_VIGENTE, PERIODO_VIGENTE)


# --------------------------------------------------------------------------
# permissions.pode_ajustar_orientacao / permissions.pode_conceder_limite
# --------------------------------------------------------------------------


@pytest.mark.django_db
def test_pode_ajustar_orientacao_e_verdadeiro_para_coordenador(coordenador):
    assert permissions.pode_ajustar_orientacao(coordenador) is True


@pytest.mark.django_db
def test_pode_ajustar_orientacao_e_falso_para_professor_comum(professor_antigo):
    assert permissions.pode_ajustar_orientacao(professor_antigo.usuario) is False


def test_pode_ajustar_orientacao_e_falso_para_usuario_anonimo():
    assert permissions.pode_ajustar_orientacao(AnonymousUser()) is False


@pytest.mark.django_db
def test_pode_conceder_limite_e_verdadeiro_para_coordenador(coordenador):
    assert permissions.pode_conceder_limite(coordenador) is True


@pytest.mark.django_db
def test_pode_conceder_limite_e_falso_para_professor_comum(professor_antigo):
    assert permissions.pode_conceder_limite(professor_antigo.usuario) is False


# --------------------------------------------------------------------------
# services.trocar_orientador
# --------------------------------------------------------------------------


@pytest.mark.django_db
def test_trocar_orientador_troca_quando_ha_vaga(projeto, professor_novo, coordenador):
    resultado = services.trocar_orientador(projeto, professor_novo, por=coordenador)

    assert resultado.pk == projeto.pk
    assert resultado.orientador == professor_novo.usuario
    projeto.refresh_from_db()
    assert projeto.orientador == professor_novo.usuario


@pytest.mark.django_db
def test_trocar_orientador_recusa_quando_professor_novo_esta_lotado(
    projeto, professor_novo, coordenador
):
    for indice in range(60, 63):
        _cria_projeto(_cria_aluno(indice).usuario, professor_novo, ANO_VIGENTE, PERIODO_VIGENTE)

    with pytest.raises(ValidationError) as excinfo:
        services.trocar_orientador(projeto, professor_novo, por=coordenador)

    mensagem = excinfo.value.messages[0]
    assert professor_novo.usuario.nome_completo in mensagem
    assert "3 de 3" in mensagem
    projeto.refresh_from_db()
    assert projeto.orientador != professor_novo.usuario


@pytest.mark.django_db
def test_trocar_orientador_usa_semestre_do_projeto_nao_o_vigente(professor_antigo, professor_novo):
    """A revalidação de vaga tem que olhar `projeto.ano`/`projeto.periodo` —
    o carimbo do semestre em que o projeto NASCEU — e nunca
    `semestre_vigente()`. Este teste é construído para DISCRIMINAR as duas
    implementações: `professor_novo` está LOTADO no semestre ANTERIOR (o do
    projeto sendo trocado) e tem vaga de sobra no semestre VIGENTE. Uma
    implementação que revalidasse contra `semestre_vigente()` (o defeito que
    esta tarefa existe para não introduzir) aprovaria a troca por engano —
    só a implementação certa, que olha o semestre do projeto, recusa.
    """
    aluno_do_projeto_antigo = _cria_aluno(70)
    projeto_de_semestre_anterior = _cria_projeto(
        aluno_do_projeto_antigo.usuario, professor_antigo, ANO_ANTERIOR, PERIODO_VIGENTE
    )
    for indice in range(71, 74):
        _cria_projeto(_cria_aluno(indice).usuario, professor_novo, ANO_ANTERIOR, PERIODO_VIGENTE)
    # `professor_novo` está de vagas livres no semestre VIGENTE — se a
    # revalidação (por engano) olhasse para cá, a troca passaria.
    assert services.vagas_ocupadas(professor_novo, Projeto.TCC_I, ANO_VIGENTE, PERIODO_VIGENTE) == 0

    with pytest.raises(ValidationError) as excinfo:
        services.trocar_orientador(
            projeto_de_semestre_anterior,
            professor_novo,
            por=Usuario.objects.create_user(
                email="coordenador.semestre.painel@ufsm.br",
                password="x",
                nome_completo="Coordenadora Semestre Painel",
                cpf=_gera_cpf(75),
                is_coordenador=True,
                is_staff=True,
            ),
        )

    assert "3 de 3" in excinfo.value.messages[0]
    projeto_de_semestre_anterior.refresh_from_db()
    assert projeto_de_semestre_anterior.orientador == professor_antigo.usuario


@pytest.mark.django_db
def test_trocar_orientador_por_professor_comum_e_recusado_com_permissiondenied(
    projeto, professor_novo, professor_antigo
):
    with pytest.raises(PermissionDenied):
        services.trocar_orientador(projeto, professor_novo, por=professor_antigo.usuario)

    projeto.refresh_from_db()
    assert projeto.orientador == professor_antigo.usuario


# --------------------------------------------------------------------------
# services.conceder_limite
# --------------------------------------------------------------------------


@pytest.mark.django_db
def test_conceder_limite_registra_justificativa_e_autor(professor_novo, coordenador):
    limite = services.conceder_limite(
        professor_novo, Projeto.TCC_I, 5, "Sobrecarga temporária autorizada.", por=coordenador
    )

    assert isinstance(limite, LimiteOrientacao)
    assert limite.professor == professor_novo
    assert limite.etapa == Projeto.TCC_I
    assert (limite.ano, limite.periodo) == (ANO_VIGENTE, PERIODO_VIGENTE)
    assert limite.limite == 5
    assert limite.justificativa == "Sobrecarga temporária autorizada."
    assert limite.autorizado_por == coordenador


@pytest.mark.django_db
def test_conceder_limite_com_justificativa_com_espacos_e_gravada_sem_eles(
    professor_novo, coordenador
):
    limite = services.conceder_limite(
        professor_novo, Projeto.TCC_I, 5, "  Justificativa com espaços.  ", por=coordenador
    )
    assert limite.justificativa == "Justificativa com espaços."


@pytest.mark.django_db
def test_conceder_limite_sem_justificativa_e_recusado(professor_novo, coordenador):
    with pytest.raises(ValidationError):
        services.conceder_limite(professor_novo, Projeto.TCC_I, 5, "", por=coordenador)
    with pytest.raises(ValidationError):
        services.conceder_limite(professor_novo, Projeto.TCC_I, 5, "   ", por=coordenador)

    assert not LimiteOrientacao.objects.filter(professor=professor_novo).exists()


@pytest.mark.django_db
@pytest.mark.parametrize("limite_recusado", [1, 2, 3])
def test_conceder_limite_igual_ou_menor_que_o_padrao_e_recusado(
    limite_recusado, professor_novo, coordenador
):
    with pytest.raises(ValidationError) as excinfo:
        services.conceder_limite(
            professor_novo, Projeto.TCC_I, limite_recusado, "Justificativa.", por=coordenador
        )

    assert str(services.LIMITE_PADRAO_VAGAS) in excinfo.value.messages[0]
    assert not LimiteOrientacao.objects.filter(professor=professor_novo).exists()


@pytest.mark.django_db
def test_conceder_limite_maior_que_o_padrao_e_aceito(professor_novo, coordenador):
    limite = services.conceder_limite(
        professor_novo,
        Projeto.TCC_I,
        services.LIMITE_PADRAO_VAGAS + 1,
        "Justificativa.",
        por=coordenador,
    )
    assert limite.limite == services.LIMITE_PADRAO_VAGAS + 1


@pytest.mark.django_db
def test_conceder_limite_recusa_quando_ja_existe_para_a_mesma_chave(professor_novo, coordenador):
    original = services.conceder_limite(
        professor_novo, Projeto.TCC_I, 4, "Primeira autorização.", por=coordenador
    )

    with pytest.raises(ValidationError) as excinfo:
        services.conceder_limite(
            professor_novo, Projeto.TCC_I, 6, "Segunda tentativa.", por=coordenador
        )

    assert "revogue" in excinfo.value.messages[0].lower()
    original.refresh_from_db()
    assert original.limite == 4  # a linha original não foi sobrescrita
    quantidade = LimiteOrientacao.objects.filter(
        professor=professor_novo, etapa=Projeto.TCC_I
    ).count()
    assert quantidade == 1


@pytest.mark.django_db
def test_conceder_limite_converte_erro_de_integridade_em_validationerror(
    monkeypatch, professor_novo, coordenador
):
    """Rede de segurança contra a corrida da ambiguidade 1 do controlador da
    T12: duas concessões simultâneas para a MESMA chave (professor, etapa,
    ano, periodo) não podem deixar um `IntegrityError` cru atravessar até a
    view — mesmo padrão de
    `test_candidatura.py::
    test_registrar_converte_erro_de_integridade_do_banco_em_validationerror`
    e `test_vagas.py::
    test_criar_projeto_sob_limite_converte_erro_de_integridade_em_validationerror`:
    engana a checagem amigável (`monkeypatch`, devolvendo "não existe
    autorização para esta chave") para simular a janela entre a leitura e o
    INSERT, com a linha concorrente já gravada de antemão.
    """
    LimiteOrientacao.objects.create(
        professor=professor_novo,
        etapa=Projeto.TCC_I,
        ano=ANO_VIGENTE,
        periodo=PERIODO_VIGENTE,
        limite=4,
        justificativa="Autorização concorrente.",
        autorizado_por=coordenador,
    )
    monkeypatch.setattr(services, "_possui_limite_para_chave", lambda *a, **k: False)

    with pytest.raises(ValidationError) as excinfo:
        services.conceder_limite(
            professor_novo, Projeto.TCC_I, 6, "Segunda tentativa.", por=coordenador
        )

    assert "revogue" in excinfo.value.messages[0].lower()
    quantidade = LimiteOrientacao.objects.filter(
        professor=professor_novo, etapa=Projeto.TCC_I
    ).count()
    assert quantidade == 1


@pytest.mark.django_db
def test_conceder_limite_por_professor_comum_e_recusado_com_permissiondenied(
    professor_novo, professor_antigo
):
    with pytest.raises(PermissionDenied):
        services.conceder_limite(
            professor_novo, Projeto.TCC_I, 5, "Justificativa.", por=professor_antigo.usuario
        )
    assert not LimiteOrientacao.objects.filter(professor=professor_novo).exists()


# --------------------------------------------------------------------------
# services.revogar_limite
# --------------------------------------------------------------------------


@pytest.mark.django_db
def test_revogar_limite_nao_desfaz_projetos_e_trava_proximo_aceite(professor_novo, coordenador):
    limite = LimiteOrientacao.objects.create(
        professor=professor_novo,
        etapa=Projeto.TCC_I,
        ano=ANO_VIGENTE,
        periodo=PERIODO_VIGENTE,
        limite=4,
        justificativa="Sobrecarga temporária autorizada.",
        autorizado_por=coordenador,
    )
    for indice in range(80, 84):
        services.criar_projeto_sob_limite(_cria_aluno(indice), professor_novo, None, Projeto.TCC_I)
    assert Projeto.objects.filter(orientador=professor_novo.usuario).count() == 4

    services.revogar_limite(limite, por=coordenador)

    assert not LimiteOrientacao.objects.filter(pk=limite.pk).exists()
    # Os 4 projetos já criados continuam intactos — revogar não desfaz nada.
    assert Projeto.objects.filter(orientador=professor_novo.usuario).count() == 4

    quinto_aluno = _cria_aluno(84)
    with pytest.raises(ValidationError):
        services.criar_projeto_sob_limite(quinto_aluno, professor_novo, None, Projeto.TCC_I)
    assert Projeto.objects.filter(orientador=professor_novo.usuario).count() == 4


@pytest.mark.django_db
def test_revogar_limite_por_professor_comum_e_recusado_com_permissiondenied(
    professor_novo, professor_antigo, coordenador
):
    limite = LimiteOrientacao.objects.create(
        professor=professor_novo,
        etapa=Projeto.TCC_I,
        ano=ANO_VIGENTE,
        periodo=PERIODO_VIGENTE,
        limite=4,
        justificativa="Sobrecarga temporária autorizada.",
        autorizado_por=coordenador,
    )

    with pytest.raises(PermissionDenied):
        services.revogar_limite(limite, por=professor_antigo.usuario)

    assert LimiteOrientacao.objects.filter(pk=limite.pk).exists()


# --------------------------------------------------------------------------
# view projetos:painel_orientacoes
# --------------------------------------------------------------------------


@pytest.mark.django_db
def test_painel_orientacoes_exige_autenticacao(client):
    resposta = client.get(reverse("projetos:painel_orientacoes"))
    assert resposta.status_code == 302
    assert "/contas/login/" in resposta.url


@pytest.mark.django_db
def test_painel_orientacoes_recusa_professor_comum_com_403(client, professor_antigo):
    client.force_login(professor_antigo.usuario)
    resposta = client.get(reverse("projetos:painel_orientacoes"))
    assert resposta.status_code == 403


@pytest.mark.django_db
def test_painel_orientacoes_recusa_aluno_com_403(client, aluno):
    client.force_login(aluno.usuario)
    resposta = client.get(reverse("projetos:painel_orientacoes"))
    assert resposta.status_code == 403


@pytest.mark.django_db
def test_painel_orientacoes_lista_projetos_e_limites(client, coordenador, projeto, professor_novo):
    limite = LimiteOrientacao.objects.create(
        professor=professor_novo,
        etapa=Projeto.TCC_I,
        ano=ANO_VIGENTE,
        periodo=PERIODO_VIGENTE,
        limite=4,
        justificativa="Sobrecarga temporária autorizada.",
        autorizado_por=coordenador,
    )
    client.force_login(coordenador)

    html = client.get(reverse("projetos:painel_orientacoes")).content.decode()

    assert projeto.aluno.nome_completo in html
    assert projeto.orientador.nome_completo in html
    assert professor_novo.usuario.nome_completo in html
    assert limite.justificativa in html


@pytest.mark.django_db
def test_painel_orientacoes_concede_limite_pela_tela(client, coordenador, professor_novo):
    client.force_login(coordenador)

    resposta = client.post(
        reverse("projetos:painel_orientacoes"),
        {
            "professor": professor_novo.pk,
            "etapa": Projeto.TCC_I,
            "limite": 5,
            "justificativa": "Sobrecarga temporária autorizada.",
        },
    )

    assert resposta.status_code == 302
    limite = LimiteOrientacao.objects.get(professor=professor_novo, etapa=Projeto.TCC_I)
    assert limite.limite == 5
    assert limite.autorizado_por == coordenador


@pytest.mark.django_db
def test_painel_orientacoes_concede_limite_invalido_mostra_erro_sem_criar(
    client, coordenador, professor_novo
):
    client.force_login(coordenador)

    resposta = client.post(
        reverse("projetos:painel_orientacoes"),
        {
            "professor": professor_novo.pk,
            "etapa": Projeto.TCC_I,
            "limite": 3,
            "justificativa": "Justificativa.",
        },
    )

    assert resposta.status_code == 200
    assert not LimiteOrientacao.objects.filter(professor=professor_novo).exists()


# --------------------------------------------------------------------------
# view projetos:trocar_orientador
# --------------------------------------------------------------------------


@pytest.mark.django_db
def test_trocar_orientador_view_exige_autenticacao(client, projeto):
    resposta = client.post(reverse("projetos:trocar_orientador", args=[projeto.pk]))
    assert resposta.status_code == 302
    assert "/contas/login/" in resposta.url


@pytest.mark.django_db
def test_trocar_orientador_view_exige_post(client, coordenador, projeto):
    client.force_login(coordenador)
    resposta = client.get(reverse("projetos:trocar_orientador", args=[projeto.pk]))
    assert resposta.status_code == 405


@pytest.mark.django_db
def test_trocar_orientador_view_recusa_professor_comum_com_403(client, professor_antigo, projeto):
    client.force_login(professor_antigo.usuario)
    resposta = client.post(reverse("projetos:trocar_orientador", args=[projeto.pk]))
    assert resposta.status_code == 403


@pytest.mark.django_db
def test_trocar_orientador_view_projeto_inexistente_recebe_404(client, coordenador, projeto):
    client.force_login(coordenador)
    resposta = client.post(reverse("projetos:trocar_orientador", args=[projeto.pk + 9999]))
    assert resposta.status_code == 404


@pytest.mark.django_db
def test_trocar_orientador_view_troca_pela_tela(client, coordenador, projeto, professor_novo):
    client.force_login(coordenador)

    resposta = client.post(
        reverse("projetos:trocar_orientador", args=[projeto.pk]),
        {"novo_orientador": professor_novo.pk},
    )

    assert resposta.status_code == 302
    projeto.refresh_from_db()
    assert projeto.orientador == professor_novo.usuario


@pytest.mark.django_db
def test_trocar_orientador_view_recusa_quando_lotado_nao_derruba_com_500(
    client, coordenador, projeto, professor_novo
):
    for indice in range(90, 93):
        _cria_projeto(_cria_aluno(indice).usuario, professor_novo, ANO_VIGENTE, PERIODO_VIGENTE)
    client.force_login(coordenador)

    resposta = client.post(
        reverse("projetos:trocar_orientador", args=[projeto.pk]),
        {"novo_orientador": professor_novo.pk},
    )

    assert resposta.status_code == 302  # nunca 500
    projeto.refresh_from_db()
    assert projeto.orientador != professor_novo.usuario


# --------------------------------------------------------------------------
# view projetos:revogar_limite
# --------------------------------------------------------------------------


@pytest.fixture
def limite(professor_novo, coordenador):
    return LimiteOrientacao.objects.create(
        professor=professor_novo,
        etapa=Projeto.TCC_I,
        ano=ANO_VIGENTE,
        periodo=PERIODO_VIGENTE,
        limite=4,
        justificativa="Sobrecarga temporária autorizada.",
        autorizado_por=coordenador,
    )


@pytest.mark.django_db
def test_revogar_limite_view_exige_autenticacao(client, limite):
    resposta = client.post(reverse("projetos:revogar_limite", args=[limite.pk]))
    assert resposta.status_code == 302
    assert "/contas/login/" in resposta.url


@pytest.mark.django_db
def test_revogar_limite_view_exige_post(client, coordenador, limite):
    client.force_login(coordenador)
    resposta = client.get(reverse("projetos:revogar_limite", args=[limite.pk]))
    assert resposta.status_code == 405


@pytest.mark.django_db
def test_revogar_limite_view_recusa_professor_comum_com_403(client, professor_antigo, limite):
    client.force_login(professor_antigo.usuario)
    resposta = client.post(reverse("projetos:revogar_limite", args=[limite.pk]))
    assert resposta.status_code == 403


@pytest.mark.django_db
def test_revogar_limite_view_limite_inexistente_recebe_404(client, coordenador, limite):
    client.force_login(coordenador)
    resposta = client.post(reverse("projetos:revogar_limite", args=[limite.pk + 9999]))
    assert resposta.status_code == 404


@pytest.mark.django_db
def test_revogar_limite_view_revoga_pela_tela(client, coordenador, limite):
    client.force_login(coordenador)

    resposta = client.post(reverse("projetos:revogar_limite", args=[limite.pk]))

    assert resposta.status_code == 302
    assert not LimiteOrientacao.objects.filter(pk=limite.pk).exists()
