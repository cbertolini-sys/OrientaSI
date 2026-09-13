"""Testes de `apps/projetos/services.py`: `registrar_candidatura` e a
cascata de opções (T8, spec §5.1 e §5.2) — o motor por trás do mural (T7):
o aluno registra até três opções ordenadas e o sistema aciona uma de cada
vez, só disparando e-mail para a opção da vez.

Os testes que disparam e-mail usam `django_capture_on_commit_callbacks`
(como em `apps/contas/tests/test_convites.py`): `transaction.on_commit` não
dispara sozinho sob pytest-django, porque cada teste roda dentro de uma
transação que o pytest-django reverte ao final — sem capturar os callbacks,
`mail.outbox` fica vazio mesmo com o serviço certo.
"""

import pytest
from django.core import mail
from django.core.exceptions import PermissionDenied, ValidationError

from apps.comum.semestre import semestre_vigente
from apps.contas.models import Area, PerfilAluno, PerfilProfessor, Usuario
from apps.contas.validators import _digito
from apps.projetos import services, tasks
from apps.projetos.models import Candidatura, OpcaoCandidatura, Projeto, Tema

ANO_VIGENTE, PERIODO_VIGENTE = semestre_vigente()


# CPFs sintéticos com dígito verificador válido — mesmo mecanismo de
# apps/projetos/tests/test_vagas.py, com uma faixa própria (900000000+) para
# não colidir com os índices usados por outras suítes (o que não importaria
# de qualquer forma: cada teste roda numa transação revertida ao final, então
# a colidência só teria efeito DENTRO do mesmo teste).
def _gera_cpf(indice):
    base = f"{900000000 + indice:09d}"
    d1 = _digito(base, 10)
    d2 = _digito(base + str(d1), 11)
    return base + str(d1) + str(d2)


def _cria_professor(indice, nome):
    usuario = Usuario.objects.create_user(
        email=f"professor.cand{indice}@ufsm.br",
        password="x",
        nome_completo=nome,
        cpf=_gera_cpf(indice),
    )
    return PerfilProfessor.objects.create(usuario=usuario, siape=f"CAND{indice}")


def _cria_aluno(indice, nome="Aluno Candidatura"):
    usuario = Usuario.objects.create_user(
        email=f"aluno.cand{indice}@ufsm.br",
        password="x",
        nome_completo=nome,
        papel=Usuario.ALUNO,
        cpf=_gera_cpf(indice),
    )
    return PerfilAluno.objects.create(usuario=usuario, matricula=f"2026CAND{indice:03d}")


@pytest.fixture
def area(db):
    return Area.objects.create(nome="Engenharia de Software")


@pytest.fixture
def tres_professores(area):
    # Índices 1-3: faixa reservada a professores "principais" do teste.
    return [_cria_professor(indice, f"Professor {indice}") for indice in range(1, 4)]


@pytest.fixture
def aluno(db):
    # Índice 50: faixa reservada ao aluno principal, longe da dos professores.
    return _cria_aluno(50)


@pytest.fixture
def registra(settings, django_capture_on_commit_callbacks):
    """Chama `services.registrar_candidatura` capturando os callbacks de
    `transaction.on_commit`, para os testes que precisam medir o e-mail
    disparado."""
    settings.CELERY_TASK_ALWAYS_EAGER = True

    def _registra(*args, **kwargs):
        with django_capture_on_commit_callbacks(execute=True):
            return services.registrar_candidatura(*args, **kwargs)

    return _registra


@pytest.fixture
def avanca(settings, django_capture_on_commit_callbacks):
    settings.CELERY_TASK_ALWAYS_EAGER = True

    def _avanca(*args, **kwargs):
        with django_capture_on_commit_callbacks(execute=True):
            return services.avancar_cascata(*args, **kwargs)

    return _avanca


# --------------------------------------------------------------------------
# registrar_candidatura
# --------------------------------------------------------------------------


@pytest.mark.django_db
def test_registrar_com_tres_opcoes_envia_email_so_para_a_primeira(
    registra, tres_professores, aluno
):
    opcoes = [(professor, None) for professor in tres_professores]

    candidatura = registra(aluno, opcoes)

    assert candidatura.aluno == aluno
    assert candidatura.status == Candidatura.EM_CURSO
    assert candidatura.opcao_atual == 1

    opcao1, opcao2, opcao3 = candidatura.opcoes.order_by("ordem")
    assert opcao1.professor == tres_professores[0]
    assert opcao1.situacao == OpcaoCandidatura.ENVIADA
    assert opcao1.enviada_em is not None
    assert opcao1.prazo is not None
    # As duas seguintes ainda não foram acionadas — é isto que "uma de cada
    # vez" significa (spec §5.2): a cascata não dispara as três de uma vez.
    assert opcao2.situacao == OpcaoCandidatura.AGUARDANDO
    assert opcao2.enviada_em is None
    assert opcao3.situacao == OpcaoCandidatura.AGUARDANDO

    assert len(mail.outbox) == 1
    assert mail.outbox[0].to == [tres_professores[0].usuario.email]


@pytest.mark.django_db
def test_registrar_com_professor_no_limite_e_recusado_nomeando_o_professor(tres_professores, aluno):
    """spec §5.1: aceitar a opção e deixá-la falhar no aceite desperdiça o
    tempo das duas pessoas — por isso o registro já recusa um alvo sem vaga,
    nomeando o professor na mensagem."""
    professor_cheio = tres_professores[0]
    for indice in range(60, 63):
        services.criar_projeto_sob_limite(_cria_aluno(indice), professor_cheio, None, Projeto.TCC_I)
    assert (
        services.vagas_ocupadas(professor_cheio, Projeto.TCC_I, ANO_VIGENTE, PERIODO_VIGENTE) == 3
    )

    with pytest.raises(ValidationError) as excinfo:
        services.registrar_candidatura(aluno, [(professor_cheio, None)])

    assert professor_cheio.usuario.nome_completo in excinfo.value.messages[0]
    # Nada foi gravado: a recusa acontece antes de criar a Candidatura.
    assert not Candidatura.objects.filter(aluno=aluno).exists()


@pytest.mark.django_db
def test_registrar_com_aluno_ja_em_curso_e_recusado(registra, tres_professores, aluno):
    registra(aluno, [(tres_professores[0], None)])

    with pytest.raises(ValidationError):
        services.registrar_candidatura(aluno, [(tres_professores[1], None)])

    # A candidatura original continua sendo a única EM_CURSO.
    assert Candidatura.objects.filter(aluno=aluno, status=Candidatura.EM_CURSO).count() == 1


@pytest.mark.django_db
def test_registrar_converte_erro_de_integridade_do_banco_em_validationerror(
    monkeypatch, tres_professores, aluno
):
    """Ambiguidade 3 do controlador: duas submissões simultâneas do mesmo
    aluno passam as duas pela checagem amigável em Python antes de qualquer
    uma delas commitar — e só o `UniqueConstraint` do banco (rede de
    segurança) intercepta a segunda. Simula a corrida forçando a checagem
    amigável a mentir (`monkeypatch`, devolvendo "sem candidatura em curso"
    mesmo já havendo uma) para provar que o `IntegrityError` que sobra é
    convertido em `ValidationError` — nunca um 500 na cara do aluno."""
    Candidatura.objects.create(aluno=aluno, ano=ANO_VIGENTE, periodo=PERIODO_VIGENTE)
    monkeypatch.setattr(services, "_possui_candidatura_em_curso", lambda aluno: False)

    with pytest.raises(ValidationError) as excinfo:
        services.registrar_candidatura(aluno, [(tres_professores[0], None)])

    assert "candidatura em curso" in excinfo.value.messages[0].lower()
    # Continua existindo exatamente uma candidatura EM_CURSO — a segunda
    # tentativa não deixou lixo parcial (opções órfãs, etc.) para trás.
    assert Candidatura.objects.filter(aluno=aluno, status=Candidatura.EM_CURSO).count() == 1


@pytest.mark.django_db
def test_registrar_tema_que_nao_pertence_ao_professor_da_opcao_e_recusado(
    tres_professores, aluno, area
):
    """A trigger `valida_tema_do_professor_da_opcao` (migração 0002) recusaria
    este INSERT de qualquer forma — mas com um IntegrityError cru do banco.
    Este teste cobra a mensagem legível que `registrar_candidatura` deve dar
    ANTES de chegar lá."""
    tema_do_professor_2 = Tema.objects.create(
        professor=tres_professores[1],
        area=area,
        titulo="Tema do professor 2",
        descricao="Descrição.",
    )

    with pytest.raises(ValidationError) as excinfo:
        services.registrar_candidatura(aluno, [(tres_professores[0], tema_do_professor_2)])

    assert "Tema do professor 2" in excinfo.value.messages[0]
    assert not Candidatura.objects.filter(aluno=aluno).exists()


@pytest.mark.django_db
def test_registrar_sem_nenhuma_opcao_e_recusado(aluno):
    with pytest.raises(ValidationError):
        services.registrar_candidatura(aluno, [])


@pytest.mark.django_db
def test_registrar_com_mais_de_tres_opcoes_e_recusado(tres_professores, aluno, area):
    quarto_professor = _cria_professor(4, "Professor 4")
    opcoes = [(professor, None) for professor in [*tres_professores, quarto_professor]]

    with pytest.raises(ValidationError):
        services.registrar_candidatura(aluno, opcoes)


# --------------------------------------------------------------------------
# avancar_cascata
# --------------------------------------------------------------------------


@pytest.mark.django_db
def test_avancar_cascata_marca_a_atual_como_expirada_e_envia_a_proxima(
    registra, avanca, tres_professores, aluno
):
    candidatura = registra(aluno, [(professor, None) for professor in tres_professores])
    mail.outbox.clear()
    opcao1 = candidatura.opcoes.get(ordem=1)

    avanca(candidatura)

    opcao1.refresh_from_db()
    candidatura.refresh_from_db()
    assert opcao1.situacao == OpcaoCandidatura.EXPIRADA
    assert opcao1.respondida_em is not None
    assert candidatura.status == Candidatura.EM_CURSO
    assert candidatura.opcao_atual == 2

    opcao2 = candidatura.opcoes.get(ordem=2)
    assert opcao2.situacao == OpcaoCandidatura.ENVIADA
    assert opcao2.prazo is not None

    assert len(mail.outbox) == 1
    assert mail.outbox[0].to == [tres_professores[1].usuario.email]


@pytest.mark.django_db
def test_avancar_cascata_nao_reescreve_situacao_ja_definida_pelo_chamador(
    registra, avanca, tres_professores, aluno
):
    """Quando quem chama `avancar_cascata` já marcou a opção corrente como
    RECUSADA (o caso de `recusar_opcao`, T9) antes de chamar esta função,
    `avancar_cascata` só avança — não sobrescreve a situação que o chamador
    já gravou. Só toca a situação da opção corrente quando ela ainda está
    ENVIADA (o caso do prazo estourado, T10)."""
    candidatura = registra(aluno, [(professor, None) for professor in tres_professores])
    mail.outbox.clear()
    opcao1 = candidatura.opcoes.get(ordem=1)
    opcao1.situacao = OpcaoCandidatura.RECUSADA
    opcao1.justificativa = "Sem vaga na área no momento."
    opcao1.save(update_fields=["situacao", "justificativa"])

    avanca(candidatura)

    opcao1.refresh_from_db()
    assert opcao1.situacao == OpcaoCandidatura.RECUSADA
    assert opcao1.justificativa == "Sem vaga na área no momento."


@pytest.mark.django_db
def test_esgotar_as_tres_opcoes_marca_candidatura_esgotada_e_notifica_coordenacao(
    registra, avanca, tres_professores, aluno
):
    coordenador = Usuario.objects.create_user(
        email="coordenador.cand@ufsm.br",
        password="x",
        nome_completo="Coordenadora Candidatura",
        cpf=_gera_cpf(30),
        is_coordenador=True,
        is_staff=True,
    )
    candidatura = registra(aluno, [(professor, None) for professor in tres_professores])
    mail.outbox.clear()

    avanca(candidatura)  # opção 1 expira, opção 2 é enviada
    mail.outbox.clear()
    avanca(candidatura)  # opção 2 expira, opção 3 é enviada
    mail.outbox.clear()
    avanca(candidatura)  # opção 3 expira, não há próxima -> ESGOTADA

    candidatura.refresh_from_db()
    assert candidatura.status == Candidatura.ESGOTADA
    ultima_opcao = candidatura.opcoes.get(ordem=3)
    assert ultima_opcao.situacao == OpcaoCandidatura.EXPIRADA

    destinatarios = {endereco for mensagem in mail.outbox for endereco in mensagem.to}
    assert aluno.usuario.email in destinatarios
    assert coordenador.email in destinatarios


# --------------------------------------------------------------------------
# cancelar_candidatura
# --------------------------------------------------------------------------


@pytest.mark.django_db
def test_cancelar_candidatura_marca_opcoes_restantes_como_cancelada(
    registra, tres_professores, aluno
):
    candidatura = registra(aluno, [(professor, None) for professor in tres_professores])

    services.cancelar_candidatura(candidatura, por=aluno.usuario)

    candidatura.refresh_from_db()
    assert candidatura.status == Candidatura.CANCELADA
    situacoes = list(candidatura.opcoes.order_by("ordem").values_list("situacao", flat=True))
    assert situacoes == [OpcaoCandidatura.CANCELADA] * 3


@pytest.mark.django_db
def test_cancelar_candidatura_preserva_opcoes_ja_respondidas(
    registra, avanca, tres_professores, aluno
):
    candidatura = registra(aluno, [(professor, None) for professor in tres_professores])
    avanca(candidatura)  # opção 1 vira EXPIRADA, opção 2 vira ENVIADA

    services.cancelar_candidatura(candidatura, por=aluno.usuario)

    opcao1, opcao2, opcao3 = candidatura.opcoes.order_by("ordem")
    assert opcao1.situacao == OpcaoCandidatura.EXPIRADA  # não reescrito
    assert opcao2.situacao == OpcaoCandidatura.CANCELADA  # estava ENVIADA
    assert opcao3.situacao == OpcaoCandidatura.CANCELADA  # estava AGUARDANDO


@pytest.mark.django_db
def test_somente_o_proprio_aluno_pode_cancelar(registra, tres_professores, aluno):
    outro_usuario = _cria_aluno(70).usuario
    candidatura = registra(aluno, [(tres_professores[0], None)])

    with pytest.raises(PermissionDenied):
        services.cancelar_candidatura(candidatura, por=outro_usuario)


@pytest.mark.django_db
def test_cancelar_candidatura_ja_encerrada_e_recusado(registra, tres_professores, aluno):
    candidatura = registra(aluno, [(tres_professores[0], None)])
    services.cancelar_candidatura(candidatura, por=aluno.usuario)

    with pytest.raises(ValidationError):
        services.cancelar_candidatura(candidatura, por=aluno.usuario)


# --------------------------------------------------------------------------
# As três tarefas Celery (chamadas diretamente aqui; T9 é quem vai acioná-las
# via `recusar_opcao`, mas a tarefa e o template já precisam existir e
# funcionar nesta tarefa).
# --------------------------------------------------------------------------


@pytest.mark.django_db
def test_tarefa_enviar_recusa_inclui_a_justificativa(settings, tres_professores, aluno):
    settings.CELERY_TASK_ALWAYS_EAGER = True
    candidatura = Candidatura.objects.create(aluno=aluno, ano=ANO_VIGENTE, periodo=PERIODO_VIGENTE)
    opcao = OpcaoCandidatura.objects.create(
        candidatura=candidatura,
        ordem=1,
        professor=tres_professores[0],
        situacao=OpcaoCandidatura.RECUSADA,
        justificativa="Já tenho orientandos suficientes na área.",
    )

    tasks.enviar_recusa(opcao.id)

    assert len(mail.outbox) == 1
    assert mail.outbox[0].to == [aluno.usuario.email]
    assert "Já tenho orientandos suficientes na área." in mail.outbox[0].body
