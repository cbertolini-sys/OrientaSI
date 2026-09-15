import pytest
from django.db import IntegrityError, transaction

from apps.contas.models import Area, PerfilAluno, PerfilProfessor, Usuario
from apps.projetos.models import Candidatura, LimiteOrientacao, OpcaoCandidatura, Projeto, Tema


@pytest.fixture
def professor(db):
    usuario = Usuario.objects.create_user(
        email="orientador@ufsm.br", password="x", nome_completo="Orientador", cpf="52998224725"
    )
    return PerfilProfessor.objects.create(usuario=usuario, siape="1234567")


@pytest.fixture
def area(db):
    return Area.objects.create(nome="Área de Teste Padrão")


@pytest.fixture
def aluno(db):
    return Usuario.objects.create_user(
        email="aluno@ufsm.br",
        password="x",
        nome_completo="Aluno",
        papel=Usuario.ALUNO,
        cpf="11144477735",
    )


@pytest.fixture
def coordenador(db):
    return Usuario.objects.create_user(
        email="coordenador@ufsm.br",
        password="x",
        nome_completo="Coordenador",
        cpf="16899535009",
        is_coordenador=True,
        is_staff=True,
    )


@pytest.fixture
def perfil_aluno(aluno):
    return PerfilAluno.objects.create(usuario=aluno, matricula="2021000001")


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
def tema(professor, area):
    return Tema.objects.create(
        professor=professor,
        area=area,
        titulo="Tema do professor",
        descricao="Descrição do tema.",
    )


@pytest.fixture
def tema_de_outro_professor(professor2, area):
    return Tema.objects.create(
        professor=professor2,
        area=area,
        titulo="Tema de outro professor",
        descricao="Descrição de outro tema.",
    )


@pytest.mark.django_db
def test_tema_exige_professor(area):
    with pytest.raises(IntegrityError), transaction.atomic():
        Tema.objects.create(
            professor=None, area=area, titulo="Título", descricao="Descrição do tema."
        )


@pytest.mark.django_db
def test_tema_exige_area(professor):
    with pytest.raises(IntegrityError), transaction.atomic():
        Tema.objects.create(
            professor=professor, area=None, titulo="Título", descricao="Descrição do tema."
        )


@pytest.mark.django_db
def test_projeto_recusa_dois_ativos_do_mesmo_aluno_na_mesma_etapa(aluno, professor):
    Projeto.objects.create(
        aluno=aluno,
        orientador=professor.usuario,
        etapa=Projeto.TCC_I,
        status=Projeto.EM_ANDAMENTO,
        ano=2026,
        periodo=1,
    )
    with pytest.raises(IntegrityError), transaction.atomic():
        Projeto.objects.create(
            aluno=aluno,
            orientador=professor.usuario,
            etapa=Projeto.TCC_I,
            status=Projeto.EM_ANDAMENTO,
            ano=2026,
            periodo=1,
        )


@pytest.mark.django_db
def test_projeto_concluido_nao_bloqueia_um_novo_ativo_na_mesma_etapa(aluno, professor):
    """A trava é sobre projeto ATIVO, não sobre o par (aluno, etapa) para sempre:
    um TCC I concluído não pode impedir que o aluno inicie outro (ex.: reprovado
    numa etapa anterior e reiniciando). Sem esta cobertura, uma trava implementada
    como UniqueConstraint incondicional passaria despercebida no teste acima."""
    Projeto.objects.create(
        aluno=aluno,
        orientador=professor.usuario,
        etapa=Projeto.TCC_I,
        status=Projeto.CONCLUIDO,
        ano=2025,
        periodo=2,
    )
    Projeto.objects.create(
        aluno=aluno,
        orientador=professor.usuario,
        etapa=Projeto.TCC_I,
        status=Projeto.EM_ANDAMENTO,
        ano=2026,
        periodo=1,
    )
    assert Projeto.objects.filter(aluno=aluno, etapa=Projeto.TCC_I).count() == 2


@pytest.mark.django_db
@pytest.mark.parametrize("limite", [3, 2, 0])
def test_limite_orientacao_recusa_limite_igual_ou_menor_que_tres(professor, coordenador, limite):
    with pytest.raises(IntegrityError), transaction.atomic():
        LimiteOrientacao.objects.create(
            professor=professor,
            etapa=Projeto.TCC_I,
            ano=2026,
            periodo=1,
            limite=limite,
            justificativa="Justificativa qualquer.",
            autorizado_por=coordenador,
        )


@pytest.mark.django_db
def test_limite_orientacao_recusa_duplicata_de_professor_etapa_ano_e_periodo(
    professor, coordenador
):
    LimiteOrientacao.objects.create(
        professor=professor,
        etapa=Projeto.TCC_I,
        ano=2026,
        periodo=1,
        limite=4,
        justificativa="Primeira concessão.",
        autorizado_por=coordenador,
    )
    with pytest.raises(IntegrityError), transaction.atomic():
        LimiteOrientacao.objects.create(
            professor=professor,
            etapa=Projeto.TCC_I,
            ano=2026,
            periodo=1,
            limite=5,
            justificativa="Segunda concessão, mesma chave.",
            autorizado_por=coordenador,
        )


@pytest.mark.django_db
def test_candidatura_recusa_duas_em_curso_do_mesmo_aluno(perfil_aluno):
    Candidatura.objects.create(
        aluno=perfil_aluno, status=Candidatura.EM_CURSO, opcao_atual=1, ano=2026, periodo=1
    )
    with pytest.raises(IntegrityError), transaction.atomic():
        Candidatura.objects.create(
            aluno=perfil_aluno, status=Candidatura.EM_CURSO, opcao_atual=1, ano=2026, periodo=1
        )


@pytest.mark.django_db
def test_candidatura_cancelada_nao_bloqueia_nova_em_curso_do_mesmo_aluno(perfil_aluno):
    """A trava é sobre EM_CURSO, não sobre o aluno para sempre: um pedido já
    encerrado (cancelado, aceito ou esgotado) não pode impedir um novo. Sem
    esta cobertura, uma trava implementada como UniqueConstraint incondicional
    sobre `aluno` passaria despercebida no teste acima."""
    Candidatura.objects.create(
        aluno=perfil_aluno, status=Candidatura.CANCELADA, opcao_atual=1, ano=2025, periodo=2
    )
    Candidatura.objects.create(
        aluno=perfil_aluno, status=Candidatura.EM_CURSO, opcao_atual=1, ano=2026, periodo=1
    )
    assert Candidatura.objects.filter(aluno=perfil_aluno).count() == 2


@pytest.mark.django_db
def test_opcao_recusa_ordem_duplicada_na_mesma_candidatura(perfil_aluno, professor):
    candidatura = Candidatura.objects.create(
        aluno=perfil_aluno, status=Candidatura.EM_CURSO, opcao_atual=1, ano=2026, periodo=1
    )
    OpcaoCandidatura.objects.create(candidatura=candidatura, ordem=1, professor=professor)
    with pytest.raises(IntegrityError), transaction.atomic():
        OpcaoCandidatura.objects.create(candidatura=candidatura, ordem=1, professor=professor)


@pytest.mark.django_db
def test_opcao_permite_mesma_ordem_em_candidaturas_diferentes(perfil_aluno, professor):
    """A trava é por candidatura, não sobre `ordem` isolada: duas candidaturas
    diferentes podem cada uma ter sua própria opção de ordem 1. Sem esta
    cobertura, uma trava implementada como unique=True direto no campo
    `ordem` (em vez de UniqueConstraint em [candidatura, ordem]) passaria
    despercebida no teste acima."""
    candidatura1 = Candidatura.objects.create(
        aluno=perfil_aluno, status=Candidatura.CANCELADA, opcao_atual=1, ano=2025, periodo=2
    )
    candidatura2 = Candidatura.objects.create(
        aluno=perfil_aluno, status=Candidatura.EM_CURSO, opcao_atual=1, ano=2026, periodo=1
    )
    OpcaoCandidatura.objects.create(candidatura=candidatura1, ordem=1, professor=professor)
    OpcaoCandidatura.objects.create(candidatura=candidatura2, ordem=1, professor=professor)
    assert OpcaoCandidatura.objects.filter(ordem=1).count() == 2


@pytest.mark.django_db
@pytest.mark.parametrize("ordem", [0, 4])
def test_opcao_recusa_ordem_fora_do_intervalo_um_a_tres(perfil_aluno, professor, ordem):
    candidatura = Candidatura.objects.create(
        aluno=perfil_aluno, status=Candidatura.EM_CURSO, opcao_atual=1, ano=2026, periodo=1
    )
    with pytest.raises(IntegrityError), transaction.atomic():
        OpcaoCandidatura.objects.create(candidatura=candidatura, ordem=ordem, professor=professor)


@pytest.mark.django_db
def test_opcao_recusa_tema_de_outro_professor(perfil_aluno, professor, tema_de_outro_professor):
    """A opção aponta para `professor`, mas o `tema` pertence a outro professor
    (`tema_de_outro_professor` foi criado com `professor2`) — a linha
    contradiz a si mesma: o aluno estaria se candidatando ao tema de um
    professor e à orientação de outro na mesma opção."""
    candidatura = Candidatura.objects.create(
        aluno=perfil_aluno, status=Candidatura.EM_CURSO, opcao_atual=1, ano=2026, periodo=1
    )
    with pytest.raises(IntegrityError), transaction.atomic():
        OpcaoCandidatura.objects.create(
            candidatura=candidatura, ordem=1, professor=professor, tema=tema_de_outro_professor
        )


@pytest.mark.django_db
def test_opcao_aceita_tema_nulo(perfil_aluno, professor):
    """Caso válido: `tema` nulo é "aberto a temas" — o aluno pede o professor
    sem escolher um tema publicado por ele."""
    candidatura = Candidatura.objects.create(
        aluno=perfil_aluno, status=Candidatura.EM_CURSO, opcao_atual=1, ano=2026, periodo=1
    )
    opcao = OpcaoCandidatura.objects.create(
        candidatura=candidatura, ordem=1, professor=professor, tema=None
    )
    assert opcao.tema is None


@pytest.mark.django_db
def test_opcao_aceita_tema_do_mesmo_professor(perfil_aluno, professor, tema):
    """Caso válido: `tema` pertence ao mesmo `professor` da opção."""
    candidatura = Candidatura.objects.create(
        aluno=perfil_aluno, status=Candidatura.EM_CURSO, opcao_atual=1, ano=2026, periodo=1
    )
    opcao = OpcaoCandidatura.objects.create(
        candidatura=candidatura, ordem=1, professor=professor, tema=tema
    )
    assert opcao.tema == tema


@pytest.mark.django_db
def test_opcao_aceita_ordem_maxima(perfil_aluno, professor):
    """Caso válido no teto do intervalo: `ordem=3` é a terceira e última opção
    permitida. Sem este teste, um CheckConstraint sobre-restritivo (por
    exemplo `ordem__lte=2`, escrito por engano) passaria despercebido —
    `test_opcao_recusa_ordem_fora_do_intervalo_um_a_tres` só exercita valores
    inválidos (0 e 4), e os demais testes positivos só usam `ordem=1`."""
    candidatura = Candidatura.objects.create(
        aluno=perfil_aluno, status=Candidatura.EM_CURSO, opcao_atual=3, ano=2026, periodo=1
    )
    opcao = OpcaoCandidatura.objects.create(candidatura=candidatura, ordem=3, professor=professor)
    assert opcao.ordem == 3
