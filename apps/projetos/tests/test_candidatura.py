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

import logging
import threading
import time
from datetime import timedelta
from unittest import mock

import pytest
from django.core import mail
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import connection
from django.utils import timezone

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


def _expira_prazo(opcao):
    """Empurra `opcao.prazo` para o passado e grava — simula o prazo real
    estourado. Necessário desde o guarda do Importante 1 (rodada de correção
    2): `avancar_cascata` não faz mais nada quando a opção corrente ainda
    está `ENVIADA` mas o `prazo` dela ainda não passou, então os testes que
    querem exercitar "o prazo estourou" precisam empurrar o prazo para trás
    antes de chamar — chamar logo após o registro (prazo 7 dias no futuro)
    virou, de propósito, um no-op."""
    opcao.prazo = timezone.now() - timedelta(seconds=1)
    opcao.save(update_fields=["prazo"])


def _avanca_por_prazo(avanca, candidatura):
    """`avanca(candidatura)` depois de expirar de verdade a opção que
    `opcao_atual` aponta — o padrão usado por todo teste que simula "o prazo
    estourou" (T10), em vez de "algo mudou na opção" (T9, que grava
    RECUSADA antes de chamar, sem precisar deste helper)."""
    candidatura.refresh_from_db()
    atual = candidatura.opcoes.get(ordem=candidatura.opcao_atual)
    _expira_prazo(atual)
    return avanca(candidatura)


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
    """M5 da rodada de correção 1: a versão original deste teste só provava o
    RESULTADO (`ValidationError`) — apagar `_possui_candidatura_em_curso`
    inteira deixava a suíte passando igual, porque a rede do
    `UniqueConstraint` produz o mesmo tipo de exceção com a mesma mensagem.
    O `mock.patch.object(..., wraps=...)` abaixo prova o MECANISMO: a
    checagem amigável é de fato chamada (não só "algo levanta
    ValidationError, não importa o quê")."""
    registra(aluno, [(tres_professores[0], None)])

    with mock.patch.object(
        services, "_possui_candidatura_em_curso", wraps=services._possui_candidatura_em_curso
    ) as checagem_amigavel:
        with pytest.raises(ValidationError):
            services.registrar_candidatura(aluno, [(tres_professores[1], None)])

    assert checagem_amigavel.called

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


@pytest.mark.django_db
def test_registrar_com_o_mesmo_professor_em_duas_opcoes_e_recusado(tres_professores, aluno):
    """M11 da rodada de correção 1: o mural (T7) não oferece repetir o mesmo
    professor em duas opções, mas o serviço é a camada de guarda (CLAUDE.md
    §4), e já confere posse de tema linhas abaixo — a mesma candidatura."""
    professor = tres_professores[0]

    with pytest.raises(ValidationError) as excinfo:
        services.registrar_candidatura(aluno, [(professor, None), (professor, None)])

    assert professor.usuario.nome_completo in excinfo.value.messages[0]
    assert not Candidatura.objects.filter(aluno=aluno).exists()


@pytest.mark.django_db
def test_registrar_com_tema_desativado_e_recusado(tres_professores, aluno, area):
    """M11 da rodada de correção 1: um tema `ativo=False` já saiu do mural
    (T7), mas nada no serviço impedia uma opção apontando para ele —
    `criar_tema`/`desativar_tema` vivem no mesmo módulo e já sabem o que
    `ativo` significa."""
    tema_desativado = Tema.objects.create(
        professor=tres_professores[0],
        area=area,
        titulo="Tema desativado",
        descricao="Descrição.",
        ativo=False,
    )

    with pytest.raises(ValidationError) as excinfo:
        services.registrar_candidatura(aluno, [(tres_professores[0], tema_desativado)])

    assert "Tema desativado" in excinfo.value.messages[0]
    assert not Candidatura.objects.filter(aluno=aluno).exists()


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

    _avanca_por_prazo(avanca, candidatura)

    opcao1.refresh_from_db()
    candidatura.refresh_from_db()
    assert opcao1.situacao == OpcaoCandidatura.EXPIRADA
    # M10 da rodada de correção 1: `respondida_em` fica NULO na expiração —
    # spec §4.3 lista o campo como nulo "até acontecer", e expirar por prazo
    # não é uma resposta de ninguém.
    assert opcao1.respondida_em is None
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
def test_avancar_cascata_chamada_duas_vezes_antes_do_prazo_nao_consome_opcao(
    registra, avanca, tres_professores, aluno
):
    """Importante 1 da rodada de correção 2, reprodução SONDA G do brief: a
    trava sozinha (rodada de correção 1) fechou o dano ANTIGO (e-mail
    duplicado, prazo reescrito), mas abriu um NOVO, pior — uma segunda
    chamada de `avancar_cascata` sobre a MESMA candidatura, sem que o prazo
    real tenha passado, consumia uma opção do aluno: o professor da opção 2
    chegava a ser notificado e a opção já nascia EXPIRADA no mesmo instante,
    sem os 7 dias terem passado. É perda de estado, não barulho — pior que o
    defeito antigo. O guarda de prazo fecha isso: `avancar_cascata` só
    expira a opção corrente quando o `prazo` dela já passou de verdade."""
    candidatura = _avanca_por_prazo(
        avanca, registra(aluno, [(professor, None) for professor in tres_professores])
    )  # 1a chamada: opcao1 expira DE VERDADE, opcao2 é enviada
    opcao2 = candidatura.opcoes.get(ordem=2)
    prazo_gravado_por_esta_chamada = opcao2.prazo
    mail.outbox.clear()

    avanca(candidatura)  # 2a chamada, SEM o prazo de opcao2 ter passado

    opcao2.refresh_from_db()
    candidatura.refresh_from_db()
    assert opcao2.situacao == OpcaoCandidatura.ENVIADA  # não consumida
    assert opcao2.prazo == prazo_gravado_por_esta_chamada  # não reiniciado
    assert candidatura.opcao_atual == 2  # não avançou
    assert mail.outbox == []  # nenhum professor notificado à toa


@pytest.mark.django_db
def test_avancar_cascata_retorna_a_candidatura_recarregada(registra, tres_professores, aluno):
    """Importante 2 da rodada de correção 2: `avancar_cascata` recarrega a
    candidatura sob `select_for_update` e rebinda o NOME LOCAL — o objeto
    que o chamador passou fica parado no estado de antes da chamada. Quem
    chama deve usar o RETORNO, não o argumento (a T9 vai fazer "marca
    RECUSADA → `avancar_cascata(candidatura)` → renderiza a candidatura")."""
    candidatura = registra(aluno, [(professor, None) for professor in tres_professores])
    _expira_prazo(candidatura.opcoes.get(ordem=1))

    candidatura_retornada = services.avancar_cascata(candidatura)

    assert candidatura.opcao_atual == 1  # objeto do chamador: obsoleto, de propósito
    assert candidatura_retornada.pk == candidatura.pk
    assert candidatura_retornada.opcao_atual == 2  # retorno: atualizado


@pytest.mark.django_db
def test_avancar_cascata_nao_ressuscita_opcao_cancelada_de_candidatura_aceita(
    registra, avanca, tres_professores, aluno
):
    """Crítico da rodada de correção 1, reprodução SONDA B do brief: depois
    de um aceite (simulado aqui como `aceitar_opcao`/T9 faria — candidatura
    ACEITA, opção 1 ACEITA, opções 2 e 3 CANCELADA), uma chamada futura de
    `avancar_cascata` sobre a MESMA candidatura (ex.: a T10 processando um
    prazo que já não importa mais) não pode trazer a opção 2 de volta a
    ENVIADA. Antes da correção, ela trazia — e mandava e-mail a um professor
    convidando-o a orientar um aluno que já tem orientador."""
    candidatura = registra(aluno, [(professor, None) for professor in tres_professores])
    opcao1, opcao2, opcao3 = candidatura.opcoes.order_by("ordem")
    opcao1.situacao = OpcaoCandidatura.ACEITA
    opcao1.save(update_fields=["situacao"])
    OpcaoCandidatura.objects.filter(pk__in=[opcao2.pk, opcao3.pk]).update(
        situacao=OpcaoCandidatura.CANCELADA
    )
    candidatura.status = Candidatura.ACEITA
    candidatura.save(update_fields=["status"])
    mail.outbox.clear()

    avanca(candidatura)

    opcao2.refresh_from_db()
    candidatura.refresh_from_db()
    assert opcao2.situacao == OpcaoCandidatura.CANCELADA  # não ressuscitada
    assert candidatura.status == Candidatura.ACEITA  # não reescrito
    assert candidatura.opcao_atual == 1  # não avançado
    assert mail.outbox == []  # nenhum professor foi incomodado de novo


@pytest.mark.django_db
def test_avancar_cascata_nao_reenvia_apos_aluno_cancelar(registra, avanca, tres_professores, aluno):
    """Crítico da rodada de correção 1, reprodução SONDA B2 do brief: o aluno
    cancela a candidatura enquanto a opção 1 ainda está ENVIADA; uma chamada
    de `avancar_cascata` que chegue depois (o prazo daquela opção estourando
    já sem efeito nenhum) não pode reenviar nada."""
    candidatura = registra(aluno, [(professor, None) for professor in tres_professores])
    services.cancelar_candidatura(candidatura, por=aluno.usuario)
    mail.outbox.clear()

    avanca(candidatura)

    situacoes = list(candidatura.opcoes.order_by("ordem").values_list("situacao", flat=True))
    assert situacoes == [OpcaoCandidatura.CANCELADA] * 3
    candidatura.refresh_from_db()
    assert candidatura.status == Candidatura.CANCELADA
    assert mail.outbox == []


def _avanca_em_thread(candidatura_id, resultados, chave):
    """Roda `avancar_cascata` numa conexão de banco própria (nova thread do
    Python => nova conexão do Django) — mesmo padrão de
    `test_concorrencia.py::_aceita_em_thread`."""
    connection.close()
    try:
        candidatura = Candidatura.objects.get(pk=candidatura_id)
        services.avancar_cascata(candidatura)
        resultados[chave] = "concluiu"
    except Exception as erro:  # noqa: BLE001 — qualquer exceção é resultado a inspecionar
        resultados[chave] = f"erro: {erro}"
    finally:
        connection.close()


@pytest.mark.django_db(transaction=True)
def test_avancar_cascata_concorrente_nao_duplica_email_nem_reescreve_prazo():
    """Prova por THREADS reais (não sequencial — a reprodução sequencial do
    Importante 1 é `test_avancar_cascata_chamada_duas_vezes_antes_do_prazo_nao_consome_opcao`,
    acima) de que a trava (`select_for_update`, Crítico da rodada de
    correção 1) e o guarda de prazo (Importante 1 da rodada de correção 2)
    seguram juntos sob concorrência real: uma das duas chamadas é atrasada
    de propósito para garantir sobreposição verdadeira (mesma técnica de
    `test_concorrencia.py`: atrasar a ESCRITA de T1, não a leitura, para T2
    ter uma janela real em que o estado ainda não mudou).

    Com a trava: T2, ao ser liberada, lê o estado JÁ avançado por T1 (opção
    2 `ENVIADA`, prazo recém-gravado no futuro) — não o estado desatualizado
    que tinha em memória. Com o guarda de prazo: T2, vendo essa opção 2
    ainda `ENVIADA` mas com prazo no futuro, não faz mais NADA — nem
    duplica o e-mail de T1, nem avança para a opção 3 à toa (o "passo a
    mais" que a rodada de correção 1 ainda deixava passar). T1 é quem
    processa o único evento real (o prazo da opção 1, empurrado para o
    passado antes de começar); T2 conclui sem erro e sem efeito.

    `@pytest.mark.django_db(transaction=True)`, não o `db` padrão: threads
    reais com conexões próprias precisam enxergar o commit uma da outra de
    verdade (mesmo motivo de `test_concorrencia.py`).

    `tasks.enviar_manifestacao.delay` é substituído por um gravador simples
    em vez de rodar sob `CELERY_TASK_ALWAYS_EAGER`: achado da rodada de
    correção 1 — o modo eager do Celery marca "dentro de uma tarefa" com uma
    flag GLOBAL, não por thread (`celery._state._task_join_will_block`,
    salva/restaurada por `denied_join_result()` em `celery/result.py`).
    Duas THREADS reais executando tarefas eager ao mesmo tempo disputam essa
    mesma variável sem nenhuma trava: uma pode restaurar o valor errado por
    cima da outra ao terminar, deixando a flag travada em `True` para o
    resto do processo — reproduzido medindo `tests/test_celery.py` reprovar
    logo em seguida, sem relação de código nenhuma com aquele teste. Não é
    um defeito desta função nem deste projeto — é uma limitação conhecida de
    rodar tarefas Celery de verdade dentro de `threading.Thread`s
    concorrentes; a saída é não fazer isso: o que este teste mede é o
    COMPORTAMENTO DE BANCO de `avancar_cascata` sob concorrência (quantas
    vezes cada opção é enfileirada para e-mail), não a entrega em si — que
    já tem cobertura própria, sequencial, nos testes acima.
    """
    professores = [
        _cria_professor(indice, f"Professor Concorrência {indice}") for indice in (1, 2, 3)
    ]
    aluno_local = _cria_aluno(50)
    envios = []

    with mock.patch.object(tasks.enviar_manifestacao, "delay", envios.append):
        candidatura = services.registrar_candidatura(
            aluno_local, [(professor, None) for professor in professores]
        )
    envios.clear()  # o envio da opção 1 (registro) não é o que este teste mede
    opcao1 = candidatura.opcoes.get(ordem=1)
    _expira_prazo(opcao1)  # T1 precisa de um evento real para processar
    opcao2_pk = candidatura.opcoes.get(ordem=2).pk
    resultados = {}

    save_original = OpcaoCandidatura.save

    prazos_gravados_na_opcao2 = []

    def save_com_atraso(self, *args, **kwargs):
        # Atrasa só a gravação da opção 2 virando ENVIADA — o ponto em que
        # T1 já decidiu avançar mas ainda não commitou. T2 fica bloqueada no
        # `select_for_update` da CANDIDATURA (não desta linha) até T1 soltar
        # a trava; o atraso aqui só garante que a janela de bloqueio seja
        # longa o bastante para T2 realmente chegar a tentar entrar antes de
        # T1 terminar.
        if self.pk == opcao2_pk and self.situacao == OpcaoCandidatura.ENVIADA:
            # Mn4 da rodada de correção 2: o nome do teste promete "nem
            # reescreve prazo" — registra aqui TODA gravação de opcao2 como
            # ENVIADA, para depois afirmar que só aconteceu uma vez.
            prazos_gravados_na_opcao2.append(self.prazo)
            time.sleep(1.0)
        return save_original(self, *args, **kwargs)

    t1 = threading.Thread(target=_avanca_em_thread, args=(candidatura.pk, resultados, "t1"))
    t2 = threading.Thread(target=_avanca_em_thread, args=(candidatura.pk, resultados, "t2"))

    with (
        mock.patch.object(OpcaoCandidatura, "save", save_com_atraso),
        mock.patch.object(tasks.enviar_manifestacao, "delay", envios.append),
    ):
        t1.start()
        time.sleep(0.2)  # garante que T1 já pegou a trava antes de T2 tentar
        t2.start()
        t1.join()
        t2.join()

    assert resultados == {"t1": "concluiu", "t2": "concluiu"}, resultados

    candidatura.refresh_from_db()
    opcao1.refresh_from_db()
    opcao2, opcao3 = candidatura.opcoes.filter(ordem__in=[2, 3]).order_by("ordem")
    assert opcao1.situacao == OpcaoCandidatura.EXPIRADA  # T1: único evento real
    assert opcao2.situacao == OpcaoCandidatura.ENVIADA  # T2 não tocou (guarda de prazo)
    assert opcao3.situacao == OpcaoCandidatura.AGUARDANDO  # T2 não chegou aqui
    assert candidatura.opcao_atual == 2  # T2 não avançou nada

    # A opção 2 foi enfileirada para e-mail EXATAMENTE UMA VEZ, por T1. T2
    # não enfileirou nada — nem duplicata da opção 2, nem avanço à toa para
    # a opção 3.
    assert envios == [opcao2_pk], f"esperava só [{opcao2_pk}], veio {envios}"
    # Mn4: o nome do teste promete "nem reescreve prazo" — afirma isso de
    # verdade, não só por inferência da situação não ter mudado.
    assert len(prazos_gravados_na_opcao2) == 1, prazos_gravados_na_opcao2
    assert opcao2.prazo == prazos_gravados_na_opcao2[0]


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

    _avanca_por_prazo(avanca, candidatura)  # opção 1 expira, opção 2 é enviada
    mail.outbox.clear()
    _avanca_por_prazo(avanca, candidatura)  # opção 2 expira, opção 3 é enviada
    mail.outbox.clear()
    _avanca_por_prazo(avanca, candidatura)  # opção 3 expira, não há próxima -> ESGOTADA

    candidatura.refresh_from_db()
    assert candidatura.status == Candidatura.ESGOTADA
    ultima_opcao = candidatura.opcoes.get(ordem=3)
    assert ultima_opcao.situacao == OpcaoCandidatura.EXPIRADA

    destinatarios = {endereco for mensagem in mail.outbox for endereco in mensagem.to}
    assert aluno.usuario.email in destinatarios
    assert coordenador.email in destinatarios

    # Importante 3 da rodada de correção 1: os dois grupos recebem TEXTOS
    # diferentes — o do aluno não é o mesmo corpo com o destinatário trocado.
    mensagem_do_aluno = next(m for m in mail.outbox if aluno.usuario.email in m.to)
    mensagem_da_coordenacao = next(m for m in mail.outbox if coordenador.email in m.to)
    assert mensagem_do_aluno.body != mensagem_da_coordenacao.body
    # O texto da coordenação chama para uma AÇÃO dela ("para agir"); o do
    # aluno é informativo — ele não é quem vai alocar ninguém.
    assert "para agir" in mensagem_da_coordenacao.body
    assert "para agir" not in mensagem_do_aluno.body
    # As três opções desta candidatura, refletidas como número real, não
    # como "três" cravado no texto (o caso de 1 ou 2 opções é coberto em
    # test_esgotar_com_menos_de_tres_opcoes_relata_o_numero_real_delas).
    assert "3" in mensagem_do_aluno.body
    assert "3" in mensagem_da_coordenacao.body
    # Mn5 da rodada de correção 2: com coordenador ATIVO no sistema (este
    # teste tem um), a frase "a coordenação já foi avisada" é verdadeira.
    assert "já foi avisada" in mensagem_do_aluno.body


@pytest.mark.django_db
def test_esgotamento_nao_afirma_que_avisou_coordenacao_sem_coordenador_ativo(
    registra, avanca, tres_professores, aluno
):
    """Mn5 da rodada de correção 2: o e-mail do aluno afirmava "a
    coordenação já foi avisada" mesmo quando não havia nenhum coordenador
    ativo para receber o segundo e-mail — prometendo uma ação que não
    aconteceu, exatamente no caminho em que a mentira dói mais (o aluno
    acha que alguém vai agir, e ninguém foi avisado)."""
    candidatura = registra(aluno, [(professor, None) for professor in tres_professores])
    mail.outbox.clear()
    _avanca_por_prazo(avanca, candidatura)
    mail.outbox.clear()
    _avanca_por_prazo(avanca, candidatura)
    mail.outbox.clear()

    _avanca_por_prazo(avanca, candidatura)  # esgota, sem nenhum coordenador no sistema

    assert len(mail.outbox) == 1  # só o aluno — sem coordenador ativo para o segundo e-mail
    assert "já foi avisada" not in mail.outbox[0].body


@pytest.mark.django_db
def test_esgotar_com_menos_de_tres_opcoes_relata_o_numero_real_delas(registra, avanca, aluno):
    """Importante 3 da rodada de correção 1: `registrar_candidatura` aceita
    1 a 3 opções — uma candidatura de UMA opção só que se esgota não pode
    dizer "as três opções se esgotaram", que seria falso."""
    professor_unico = _cria_professor(90, "Professor Único")
    candidatura = registra(aluno, [(professor_unico, None)])
    mail.outbox.clear()

    _avanca_por_prazo(avanca, candidatura)  # única opção expira -> ESGOTADA

    candidatura.refresh_from_db()
    assert candidatura.status == Candidatura.ESGOTADA
    # Mn8 da rodada de correção 2: com uma opção só, o texto do aluno diz "a
    # única opção", não "a 1 opção" — daí checar "única", não o dígito.
    assert len(mail.outbox) == 1  # só o aluno: nenhum coordenador criado neste teste
    assert "três" not in mail.outbox[0].body.lower()
    assert "única" in mail.outbox[0].body.lower()


@pytest.mark.django_db
def test_esgotamento_nao_notifica_coordenador_inativo(registra, avanca, tres_professores, aluno):
    """M7 da rodada de correção 1: `coordenadores()` (apps/contas/services.py)
    conta coordenadores desativados de propósito, para o teto de 4 do
    CLAUDE.md — mas um deles não pode agir sobre um e-mail de alocação
    manual. O filtro é no ponto de envio, não em `coordenadores()`."""
    coordenador_ativo = Usuario.objects.create_user(
        email="coordenador.ativo.cand@ufsm.br",
        password="x",
        nome_completo="Coordenadora Ativa",
        cpf=_gera_cpf(31),
        is_coordenador=True,
        is_staff=True,
        is_active=True,
    )
    coordenador_inativo = Usuario.objects.create_user(
        email="coordenador.inativo.cand@ufsm.br",
        password="x",
        nome_completo="Coordenador Inativo",
        cpf=_gera_cpf(32),
        is_coordenador=True,
        is_staff=True,
        is_active=False,
    )
    candidatura = registra(aluno, [(professor, None) for professor in tres_professores])
    mail.outbox.clear()
    _avanca_por_prazo(avanca, candidatura)
    mail.outbox.clear()
    _avanca_por_prazo(avanca, candidatura)
    mail.outbox.clear()

    _avanca_por_prazo(avanca, candidatura)  # esgota

    destinatarios = {endereco for mensagem in mail.outbox for endereco in mensagem.to}
    assert coordenador_ativo.email in destinatarios
    assert coordenador_inativo.email not in destinatarios


@pytest.mark.django_db
def test_esgotamento_sem_coordenador_ativo_registra_log(
    caplog, registra, avanca, tres_professores, aluno
):
    """M8 da rodada de correção 1: sem isso, um sistema sem nenhum
    coordenador ATIVO falha em silêncio — a candidatura fica ESGOTADA, o
    aluno é avisado, e ninguém com poder de agir sequer sabe que precisa."""
    candidatura = registra(aluno, [(professor, None) for professor in tres_professores])
    mail.outbox.clear()
    _avanca_por_prazo(avanca, candidatura)
    mail.outbox.clear()
    _avanca_por_prazo(avanca, candidatura)
    mail.outbox.clear()

    with caplog.at_level(logging.WARNING, logger="apps.projetos.tasks"):
        _avanca_por_prazo(avanca, candidatura)  # esgota, sem nenhum coordenador no sistema

    # Só o aluno recebeu e-mail — não há coordenador ativo para receber nada.
    assert {endereco for mensagem in mail.outbox for endereco in mensagem.to} == {
        aluno.usuario.email
    }
    assert any("não há coordenador ativo" in registro.message for registro in caplog.records)


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
    _avanca_por_prazo(avanca, candidatura)  # opção 1 vira EXPIRADA, opção 2 vira ENVIADA

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
