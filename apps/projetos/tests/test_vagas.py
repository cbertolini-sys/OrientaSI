"""Testes de `apps/projetos/services.py`: contagem e limite de vagas de
orientação (spec §3.5 e §3.6), sem concorrência — a prova de travamento sob
concorrência real está em `test_concorrencia.py`, separada de propósito.
"""

import pytest
from django.core.exceptions import ValidationError

from apps.comum.semestre import semestre_vigente
from apps.contas.models import Area, PerfilAluno, PerfilProfessor, Usuario
from apps.contas.validators import _digito
from apps.projetos import services
from apps.projetos.models import LimiteOrientacao, Projeto, Tema

ANO_VIGENTE, PERIODO_VIGENTE = semestre_vigente()
ANO_ANTERIOR = ANO_VIGENTE - 1


def _gera_cpf(indice):
    base = f"{500000000 + indice:09d}"
    d1 = _digito(base, 10)
    d2 = _digito(base + str(d1), 11)
    return base + str(d1) + str(d2)


@pytest.fixture
def professor(db):
    usuario = Usuario.objects.create_user(
        email="orientador.vagas@ufsm.br",
        password="x",
        nome_completo="Orientador Vagas",
        cpf=_gera_cpf(0),
    )
    return PerfilProfessor.objects.create(usuario=usuario, siape="9990001")


@pytest.fixture
def coordenador(db):
    return Usuario.objects.create_user(
        email="coordenador.vagas@ufsm.br",
        password="x",
        nome_completo="Coordenadora Vagas",
        cpf=_gera_cpf(1),
        is_coordenador=True,
        is_staff=True,
    )


@pytest.fixture
def area(db):
    return Area.objects.create(nome="Área de Teste Padrão")


@pytest.fixture
def tema(professor, area):
    tema = Tema.objects.create(
        professor=professor, titulo="Tema", descricao="Descrição do tema."
    )
    tema.areas.set([area])
    return tema


def _cria_perfil_aluno(indice):
    usuario = Usuario.objects.create_user(
        email=f"aluno.vagas{indice}@ufsm.br",
        password="x",
        nome_completo=f"Aluno Vagas {indice}",
        papel=Usuario.ALUNO,
        cpf=_gera_cpf(10 + indice),
    )
    return PerfilAluno.objects.create(usuario=usuario, matricula=f"20260{indice:05d}")


def _cria_projeto(perfil_aluno, professor, tema, etapa, ano, periodo):
    return Projeto.objects.create(
        aluno=perfil_aluno.usuario,
        orientador=professor.usuario,
        tema=tema,
        etapa=etapa,
        status=Projeto.EM_ANDAMENTO,
        ano=ano,
        periodo=periodo,
    )


@pytest.mark.django_db
def test_vagas_ocupadas_conta_so_semestre_vigente(professor, tema):
    """Decisão 3.5 do spec: um projeto de semestre anterior, mesmo em
    andamento, não pesa na contagem do semestre vigente — o custo aceito e
    registrado no spec é justamente este."""
    aluno_antigo = _cria_perfil_aluno(1)
    aluno_atual = _cria_perfil_aluno(2)
    _cria_projeto(aluno_antigo, professor, tema, Projeto.TCC_I, ANO_ANTERIOR, PERIODO_VIGENTE)
    _cria_projeto(aluno_atual, professor, tema, Projeto.TCC_I, ANO_VIGENTE, PERIODO_VIGENTE)

    assert services.vagas_ocupadas(professor, Projeto.TCC_I, ANO_VIGENTE, PERIODO_VIGENTE) == 1


@pytest.mark.django_db
def test_vagas_ocupadas_conta_separadamente_por_etapa(professor, tema):
    """`vagas_ocupadas` recebe `etapa` como parâmetro explícito porque o teto
    do CLAUDE.md é por etapa (3 em TCC I e 3 em TCC II, não 3 no total) — um
    projeto de TCC II não pode contar contra o limite de TCC I."""
    aluno_tcc1 = _cria_perfil_aluno(3)
    aluno_tcc2 = _cria_perfil_aluno(4)
    _cria_projeto(aluno_tcc1, professor, tema, Projeto.TCC_I, ANO_VIGENTE, PERIODO_VIGENTE)
    _cria_projeto(aluno_tcc2, professor, tema, Projeto.TCC_II, ANO_VIGENTE, PERIODO_VIGENTE)

    assert services.vagas_ocupadas(professor, Projeto.TCC_I, ANO_VIGENTE, PERIODO_VIGENTE) == 1
    assert services.vagas_ocupadas(professor, Projeto.TCC_II, ANO_VIGENTE, PERIODO_VIGENTE) == 1


@pytest.mark.django_db
def test_limite_do_professor_padrao_e_tres(professor):
    """Sem nenhuma autorização da coordenação, o teto é o padrão do CLAUDE.md."""
    limite = services.limite_do_professor(professor, Projeto.TCC_I, ANO_VIGENTE, PERIODO_VIGENTE)
    assert limite == 3
    assert limite == services.LIMITE_PADRAO_VAGAS


@pytest.mark.django_db
def test_limite_do_professor_respeita_limite_elevado(professor, coordenador):
    """Decisão 3.6: a coordenação pode elevar o teto de um professor, para uma
    etapa e semestre específicos."""
    LimiteOrientacao.objects.create(
        professor=professor,
        etapa=Projeto.TCC_I,
        ano=ANO_VIGENTE,
        periodo=PERIODO_VIGENTE,
        limite=5,
        justificativa="Sobrecarga temporária autorizada.",
        autorizado_por=coordenador,
    )

    assert services.limite_do_professor(professor, Projeto.TCC_I, ANO_VIGENTE, PERIODO_VIGENTE) == 5
    # A autorização vale só para a etapa e o semestre gravados (spec §3.6): TCC
    # II do mesmo professor, no mesmo semestre, continua no padrão.
    assert (
        services.limite_do_professor(professor, Projeto.TCC_II, ANO_VIGENTE, PERIODO_VIGENTE) == 3
    )


@pytest.mark.django_db
def test_limite_revogado_nao_desfaz_projetos_mas_trava_proximo(professor, coordenador, tema):
    """Spec §3.6: revogar a autorização não desfaz orientações já aceitas —
    aqui simulado apagando a `LimiteOrientacao` diretamente, já que
    `revogar_limite` é interface de uma tarefa posterior (T9) — só trava o
    próximo aceite. Os quatro projetos abaixo foram aceitos sob um limite de 4
    elevado pela coordenação; a autorização é então removida."""
    limite = LimiteOrientacao.objects.create(
        professor=professor,
        etapa=Projeto.TCC_I,
        ano=ANO_VIGENTE,
        periodo=PERIODO_VIGENTE,
        limite=4,
        justificativa="Sobrecarga temporária autorizada.",
        autorizado_por=coordenador,
    )
    for indice in range(5, 9):
        _cria_projeto(
            _cria_perfil_aluno(indice), professor, tema, Projeto.TCC_I, ANO_VIGENTE, PERIODO_VIGENTE
        )
    assert services.vagas_ocupadas(professor, Projeto.TCC_I, ANO_VIGENTE, PERIODO_VIGENTE) == 4

    limite.delete()

    # Os quatro projetos continuam de pé.
    assert services.vagas_ocupadas(professor, Projeto.TCC_I, ANO_VIGENTE, PERIODO_VIGENTE) == 4
    # Mas o teto voltou ao padrão, então o próximo aceite é recusado.
    assert services.limite_do_professor(professor, Projeto.TCC_I, ANO_VIGENTE, PERIODO_VIGENTE) == 3
    proximo_aluno = _cria_perfil_aluno(9)
    with pytest.raises(ValidationError):
        services.criar_projeto_sob_limite(proximo_aluno, professor, tema, Projeto.TCC_I)


@pytest.mark.django_db
def test_criar_projeto_sob_limite_cria_quando_ha_vaga(professor, tema):
    perfil_aluno = _cria_perfil_aluno(20)

    projeto = services.criar_projeto_sob_limite(perfil_aluno, professor, tema, Projeto.TCC_I)

    assert projeto.pk is not None
    assert projeto.aluno == perfil_aluno.usuario
    assert projeto.orientador == professor.usuario
    assert projeto.tema == tema
    assert projeto.etapa == Projeto.TCC_I
    assert projeto.status == Projeto.EM_ANDAMENTO
    assert (projeto.ano, projeto.periodo) == (ANO_VIGENTE, PERIODO_VIGENTE)


@pytest.mark.django_db
def test_criar_projeto_sob_limite_recusa_quando_lotado(professor, tema):
    for indice in range(30, 33):
        _cria_projeto(
            _cria_perfil_aluno(indice),
            professor,
            tema,
            Projeto.TCC_I,
            ANO_VIGENTE,
            PERIODO_VIGENTE,
        )
    perfil_aluno = _cria_perfil_aluno(33)

    with pytest.raises(ValidationError) as excinfo:
        services.criar_projeto_sob_limite(perfil_aluno, professor, tema, Projeto.TCC_I)

    mensagem = excinfo.value.messages[0]
    assert professor.usuario.nome_completo in mensagem
    assert "3 de 3" in mensagem
    # A mensagem diz o que fazer, não só que falhou (instrução permanente do bloco).
    assert "coordenação" in mensagem
    # Rótulo de exibição ("TCC I"), não o valor bruto do choice ("TCC_I") —
    # achado da rodada de correção 1 (Menor 3).
    assert "TCC I" in mensagem
    assert "TCC_I" not in mensagem
    assert Projeto.objects.filter(orientador=professor.usuario, etapa=Projeto.TCC_I).count() == 3


@pytest.mark.django_db
def test_criar_projeto_sob_limite_cria_quarto_projeto_sob_limite_elevado(
    professor, coordenador, tema
):
    """Teste de integração (achado da rodada de correção 1, Menor 5): até aqui
    `limite_do_professor` era provado isolado, e `criar_projeto_sob_limite` só
    com o limite padrão — o elo entre os dois (o serviço LENDO o
    `LimiteOrientacao` dentro da trava e deixando passar o aceite que o
    padrão recusaria) nunca era exercitado por nenhum teste."""
    LimiteOrientacao.objects.create(
        professor=professor,
        etapa=Projeto.TCC_I,
        ano=ANO_VIGENTE,
        periodo=PERIODO_VIGENTE,
        limite=4,
        justificativa="Sobrecarga temporária autorizada.",
        autorizado_por=coordenador,
    )
    for indice in range(40, 43):
        _cria_projeto(
            _cria_perfil_aluno(indice), professor, tema, Projeto.TCC_I, ANO_VIGENTE, PERIODO_VIGENTE
        )

    quarto_aluno = _cria_perfil_aluno(43)
    quarto_projeto = services.criar_projeto_sob_limite(quarto_aluno, professor, tema, Projeto.TCC_I)
    assert quarto_projeto.pk is not None
    assert Projeto.objects.filter(orientador=professor.usuario, etapa=Projeto.TCC_I).count() == 4

    quinto_aluno = _cria_perfil_aluno(44)
    with pytest.raises(ValidationError) as excinfo:
        services.criar_projeto_sob_limite(quinto_aluno, professor, tema, Projeto.TCC_I)
    assert "4 de 4" in excinfo.value.messages[0]


@pytest.mark.django_db
def test_criar_projeto_sob_limite_converte_erro_de_integridade_em_validationerror(professor, tema):
    """Rodada de correção 1 da T11 (Importante da revisão, achado real): um
    aluno já `EM_ANDAMENTO` com `professor` não pode ganhar um SEGUNDO
    `Projeto` ativo na mesma etapa — nem mesmo com um SEGUNDO professor que
    tem vaga de sobra. Sem esta tradução, o `INSERT` batia no
    `UniqueConstraint` "projeto_ativo_unico_por_aluno_e_etapa"
    (`apps/projetos/models.py::Projeto.Meta`) e o `IntegrityError` cru
    atravessava até `aceitar_opcao_view` — 500 para um professor que não fez
    nada de errado. `registrar_candidatura` já tem uma checagem amigável
    para o caso comum (`services._possui_projeto_ativo`,
    `test_candidatura.py::test_registrar_com_projeto_ativo_e_recusado`);
    este teste prova a REDE DE SEGURANÇA, chamando `criar_projeto_sob_limite`
    diretamente, sem passar pela checagem amigável — o mesmo padrão de
    `test_registrar_converte_erro_de_integridade_do_banco_em_validationerror`
    (`test_candidatura.py`), que prova a rede equivalente para `Candidatura`.
    """
    perfil_aluno = _cria_perfil_aluno(50)
    services.criar_projeto_sob_limite(perfil_aluno, professor, tema, Projeto.TCC_I)

    outro_professor = PerfilProfessor.objects.create(
        usuario=Usuario.objects.create_user(
            email="outro.orientador.vagas@ufsm.br",
            password="x",
            nome_completo="Outro Orientador Vagas",
            cpf=_gera_cpf(2),
        ),
        siape="9990002",
    )

    with pytest.raises(ValidationError) as excinfo:
        services.criar_projeto_sob_limite(perfil_aluno, outro_professor, None, Projeto.TCC_I)

    assert perfil_aluno.usuario.nome_completo in excinfo.value.messages[0]
    # Continua existindo exatamente UM Projeto ativo do aluno nesta etapa —
    # a tentativa recusada não deixou lixo parcial para trás.
    assert Projeto.objects.filter(aluno=perfil_aluno.usuario, etapa=Projeto.TCC_I).count() == 1


@pytest.mark.django_db
def test_mesmo_tema_aceita_mais_de_um_aluno(professor, tema):
    """Decisão explícita do usuário: "o mesmo tema poderá ser associado a
    mais de um aluno". NÃO existe teto por tema — o único limite é o do
    PROFESSOR (aqui, 2 de 3 ocupadas ao final, ainda com folga).

    Este teste PINA essa decisão: uma tentativa anterior de `Tema.vagas`
    (teto por tema) foi revertida por confundir mais do que ajudar, e
    reintroduzi-la derrubaria este teste em vez de passar despercebida."""
    primeiro = services.criar_projeto_sob_limite(
        _cria_perfil_aluno(60), professor, tema, Projeto.TCC_I
    )
    segundo = services.criar_projeto_sob_limite(
        _cria_perfil_aluno(61), professor, tema, Projeto.TCC_I
    )

    assert primeiro.tema_id == tema.pk
    assert segundo.tema_id == tema.pk
    assert Projeto.objects.filter(tema=tema).count() == 2


@pytest.mark.django_db
def test_desativar_tema_permitido_mesmo_com_aluno_ja_associado(professor, tema):
    """Outra metade da mesma decisão do usuário: o tema pode ser
    "desativado pelo professor uma vez que algum aluno já tenha escolhido
    ele". Desativar tira do mural sem apagar nada — o `Projeto` do aluno
    continua de pé, intacto."""
    projeto = services.criar_projeto_sob_limite(
        _cria_perfil_aluno(62), professor, tema, Projeto.TCC_I
    )

    services.desativar_tema(tema, por=professor.usuario)

    tema.refresh_from_db()
    projeto.refresh_from_db()
    assert tema.ativo is False
    assert projeto.tema_id == tema.pk
    assert projeto.status == Projeto.EM_ANDAMENTO
