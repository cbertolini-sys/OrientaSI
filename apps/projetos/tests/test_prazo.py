"""Testes de `apps/projetos/tasks.py::avancar_candidaturas_vencidas` (T10,
spec §3.2, §5.2 e §3.8 — esta última é quem decide a existência da tarefa
periódica em si, "M4" da rodada de correção 1): a tarefa periódica que liga
o Celery Beat a `avancar_cascata` (T8) pela primeira vez neste bloco.

`avancar_cascata` já é, sozinha, a única autoridade sobre QUANDO avançar —
ela tem seu próprio guarda de prazo e sua própria trava (ver a docstring
dela em `apps/projetos/services.py`). O que esta suíte prova é mais estreito
e não se sobrepõe ao que `test_candidatura.py` já prova sobre
`avancar_cascata` em si:

1. A consulta desta tarefa (`situacao=ENVIADA` e `prazo__lt=agora`) escolhe
   exatamente as candidatas certas — nem menos (opção vencida fica presa
   para sempre), nem mais (opção ainda no prazo, ou já resolvida, é
   oferecida a `avancar_cascata` à toa).
2. A tarefa periódica, chamada duas vezes de forma sobreposta (dois ticks do
   Beat concorrentes, com threads e conexões reais — o cenário real sob
   carga), não contorna o guarda de `avancar_cascata` por fora (por
   exemplo, decidindo com base num estado que ela mesma leu e cacheou antes
   de chamar a função).

Cada teste de filtro (`test_opcao_vencida_avanca`,
`test_opcao_no_prazo_nao_avanca`,
`test_opcao_ja_resolvida_com_prazo_no_passado_nao_e_reprocessada`) foi
confirmado por mutação explícita. Convenção deste arquivo (M5 da rodada de
correção 1, para não haver duas regras diferentes competindo): a
transcrição completa de cada rodada de mutação mora no relatório da T10,
fora do código — comentário e docstring aqui descrevem o que o código FAZ.
A única exceção deliberada é quando o RESULTADO da medição muda o que a
garantia cobre, não só confirma o esperado (o caso do filtro de `prazo`,
abaixo): aí o resumo do experimento é narrado ao lado da própria garantia,
na docstring de `avancar_candidaturas_vencidas`
(`apps/projetos/tasks.py`) — porque o limite de uma garantia se escreve ao
lado dela, convenção deste bloco (não do `CLAUDE.md`, que não trata disso),
não só no relatório que ninguém mais vai reabrir.
"""

import logging
import threading
import time
from datetime import timedelta
from unittest import mock

import pytest
from django.core import mail
from django.db import connection
from django.utils import timezone

from apps.contas.models import Area, PerfilAluno, PerfilProfessor, Usuario
from apps.contas.validators import _digito
from apps.projetos import services, tasks
from apps.projetos.models import Candidatura, OpcaoCandidatura


# Faixa própria de CPF sintético (800000000+), livre das faixas já usadas por
# test_vagas.py (500...), test_coordenacao_concorrencia.py (400...),
# test_concorrencia.py (600...), test_fila_professor.py (700...) e
# test_candidatura.py (900...) — não colidiria de qualquer forma (cada teste
# roda numa transação revertida ao final, ou tem seu próprio banco sob
# `transaction=True`), mas a convenção do app é uma faixa por arquivo.
def _gera_cpf(indice):
    base = f"{800000000 + indice:09d}"
    d1 = _digito(base, 10)
    d2 = _digito(base + str(d1), 11)
    return base + str(d1) + str(d2)


def _cria_professor(indice):
    usuario = Usuario.objects.create_user(
        email=f"professor.prazo{indice}@ufsm.br",
        password="x",
        nome_completo=f"Professor Prazo {indice}",
        cpf=_gera_cpf(indice),
    )
    return PerfilProfessor.objects.create(usuario=usuario, siape=f"PRZ{indice}")


def _cria_aluno(indice):
    usuario = Usuario.objects.create_user(
        email=f"aluno.prazo{indice}@ufsm.br",
        password="x",
        nome_completo=f"Aluno Prazo {indice}",
        papel=Usuario.ALUNO,
        cpf=_gera_cpf(50 + indice),
    )
    return PerfilAluno.objects.create(usuario=usuario, matricula=f"2026PRZ{indice:03d}")


@pytest.fixture
def area(db):
    return Area.objects.create(nome="Engenharia de Software")


@pytest.fixture
def dois_professores(area):
    return [_cria_professor(indice) for indice in range(1, 3)]


@pytest.fixture
def aluno(db):
    return _cria_aluno(1)


@pytest.fixture
def registra(settings, django_capture_on_commit_callbacks):
    """Mesmo padrão de `test_candidatura.py::registra`: captura os callbacks
    de `transaction.on_commit` para os testes que precisam medir e-mail."""
    settings.CELERY_TASK_ALWAYS_EAGER = True

    def _registra(*args, **kwargs):
        with django_capture_on_commit_callbacks(execute=True):
            return services.registrar_candidatura(*args, **kwargs)

    return _registra


@pytest.fixture
def roda_tarefa(django_capture_on_commit_callbacks):
    """Chama `tasks.avancar_candidaturas_vencidas` capturando os callbacks de
    `transaction.on_commit` — necessário porque `avancar_cascata`, dentro
    dela, agenda o e-mail da próxima opção via `on_commit`."""

    def _roda():
        with django_capture_on_commit_callbacks(execute=True):
            tasks.avancar_candidaturas_vencidas()

    return _roda


def _expira_prazo(opcao):
    """Empurra `opcao.prazo` para o passado e grava — mesmo helper de
    `test_candidatura.py`, duplicado aqui porque simula o prazo real
    estourado sem depender do relógio (proibido pelo brief: 'sem sleep e sem
    depender do relógio')."""
    opcao.prazo = timezone.now() - timedelta(seconds=1)
    opcao.save(update_fields=["prazo"])


# --------------------------------------------------------------------------
# Os dois testes do Passo 1 do brief.
# --------------------------------------------------------------------------


@pytest.mark.django_db
def test_opcao_vencida_avanca(registra, roda_tarefa, dois_professores, aluno):
    """Manipula `prazo` diretamente, sem sleep e sem depender do relógio: a
    opção 1 vence, a tarefa periódica avança a cascata para a opção 2 e
    notifica o professor 2 — exatamente o que `avancar_cascata` faria se
    fosse chamada diretamente (T8), só que agora é a tarefa periódica quem
    decide chamá-la.

    Importante 1 da rodada de correção 1: este é o único dos quatro testes
    do arquivo que também precisa do espião, com asserção POSITIVA
    (`assert_called_once`, não `assert_not_called`). Os outros três provam
    a consulta pela ausência de chamada — uma asserção negativa que passa
    tanto quando o filtro está certo quanto quando o `mock.patch` do alvo
    simplesmente não pega em nada (por exemplo, se alguém hastear o import
    de `avancar_cascata` para o topo do módulo — o `ruff` até sugere isso).
    Sem este teste, nada na suíte prova que o espião tem mira: os quatro
    poderiam estar cegos ao mesmo tempo, e passariam do mesmo jeito. `wraps=`
    garante que a função real roda de ponta a ponta — a asserção de estado
    abaixo continua sendo o teste de verdade; o espião só ancora que ela
    passou PORQUE o código certo rodou, não porque o patch furou."""
    candidatura = registra(aluno, [(professor, None) for professor in dois_professores])
    opcao1 = candidatura.opcoes.get(ordem=1)
    _expira_prazo(opcao1)
    mail.outbox.clear()

    with mock.patch(
        "apps.projetos.services.avancar_cascata", wraps=services.avancar_cascata
    ) as espiao:
        roda_tarefa()

    espiao.assert_called_once()
    opcao1.refresh_from_db()
    candidatura.refresh_from_db()
    assert opcao1.situacao == OpcaoCandidatura.EXPIRADA
    assert candidatura.opcao_atual == 2
    opcao2 = candidatura.opcoes.get(ordem=2)
    assert opcao2.situacao == OpcaoCandidatura.ENVIADA
    assert len(mail.outbox) == 1
    assert mail.outbox[0].to == [dois_professores[1].usuario.email]


@pytest.mark.django_db
def test_opcao_no_prazo_nao_avanca(registra, roda_tarefa, dois_professores, aluno):
    """Opção recém-enviada, prazo real 7 dias no futuro (`PRAZO_RESPOSTA_DIAS`,
    `config/settings.py`) — a tarefa não deve tocar nela, nem sequer
    OFERECÊ-LA a `avancar_cascata`.

    MEDIDO (não só suposto) para escolher a asserção certa: a primeira
    versão deste teste só checava o estado final (`opcao_atual == 1`,
    `situacao == ENVIADA`) e NÃO discriminava — removido o filtro
    `prazo__lt=agora` da consulta (trocado por `pk__gt=0`, sempre
    verdadeiro), rodei a suíte e ela continuou passando, porque
    `avancar_cascata` (`apps/projetos/services.py`) tem seu PRÓPRIO guarda
    de prazo, que olha a opção CORRENTE de novo, direto do banco, no
    momento em que roda — e nesta candidatura a opção corrente É a mesma
    opção que a consulta mutada teria devolvido. O guarda dela absorve a
    consulta frouxa e o estado final fica correto de qualquer jeito; ver o
    relatório da T10 para a transcrição literal dessa rodada.

    A asserção que de fato discrimina é sobre a CHAMADA, não sobre o
    estado: com o filtro de prazo no lugar, `avancar_cascata` nunca deveria
    sequer ser chamada aqui, porque a consulta não deveria devolver nada.
    Removido o filtro, ela É chamada (a asserção abaixo falha) — mesmo que
    o resultado dela, sozinho, seja inofensivo graças ao guarda interno.
    Isto prova que o filtro de prazo faz o trabalho que se espera dele (não
    oferecer a opção), não que a ausência dele corromperia o estado — essa
    segunda garantia é só de `avancar_cascata`, já provada em
    `test_candidatura.py`."""
    candidatura = registra(aluno, [(professor, None) for professor in dois_professores])
    opcao1 = candidatura.opcoes.get(ordem=1)
    assert opcao1.prazo > timezone.now()  # pré-condição: prazo real no futuro
    mail.outbox.clear()

    with mock.patch(
        "apps.projetos.services.avancar_cascata", wraps=services.avancar_cascata
    ) as espiao:
        roda_tarefa()

    espiao.assert_not_called()
    opcao1.refresh_from_db()
    candidatura.refresh_from_db()
    assert opcao1.situacao == OpcaoCandidatura.ENVIADA
    assert candidatura.opcao_atual == 1
    assert mail.outbox == []


# --------------------------------------------------------------------------
# Prova por mutação do filtro de `situacao=ENVIADA` (acréscimo do brief).
# --------------------------------------------------------------------------


@pytest.mark.django_db
def test_opcao_ja_resolvida_com_prazo_no_passado_nao_e_reprocessada(
    registra, roda_tarefa, dois_professores, aluno
):
    """Uma opção JÁ RESOLVIDA (aqui, `RECUSADA`) cujo `prazo` também está no
    passado — o caso real é a opção 1 recusada por `recusar_opcao` (T9)
    muito antes dos 7 dias do prazo original vencerem: `prazo` não é
    apagado nem atualizado quando alguém responde antes da hora, então ele
    continua ali, cada vez mais no passado, para sempre.

    Sem o filtro `situacao=ENVIADA`, a consulta desta tarefa devolveria essa
    opção como candidata EM TODO TICK futuro do Beat (o `prazo` dela nunca
    deixa de estar no passado), e a tarefa chamaria `avancar_cascata` para a
    mesma candidatura de novo, sem que nada de novo tenha acontecido —
    exatamente o "sendo processada de novo" do acréscimo do brief.
    `avancar_cascata` tem seu próprio guarda (olha a opção CORRENTE, não a
    que casou com a consulta) e não corrompe nada nesse caso — mas a
    consulta correta nem deveria oferecer essa opção a ela. Provado aqui com
    um espião: `avancar_cascata` não é chamada NENHUMA vez neste tick,
    porque a única opção com prazo vencido (opção 1) não está mais
    `ENVIADA`, e a opção corrente (opção 2) segue dentro do prazo.

    Prova por mutação: removido o filtro `situacao=ENVIADA` da consulta,
    este teste reprova — o espião registra uma chamada a `avancar_cascata`
    que não deveria acontecer.
    """
    candidatura = registra(aluno, [(professor, None) for professor in dois_professores])
    opcao1 = candidatura.opcoes.get(ordem=1)
    # Simula "recusada há muito tempo, bem antes do prazo original vencer":
    # situação resolvida, mas o carimbo de prazo continua no passado.
    opcao1.situacao = OpcaoCandidatura.RECUSADA
    opcao1.justificativa = "Sem vaga na área no momento."
    opcao1.save(update_fields=["situacao", "justificativa"])
    _expira_prazo(opcao1)
    # `recusar_opcao` (T9) já teria avançado a cascata de verdade quando a
    # recusa aconteceu; aqui fazemos isso manualmente para não depender da
    # T9 nesta suíte — a opção 2 fica ENVIADA, dentro do prazo real.
    candidatura.opcao_atual = 2
    candidatura.save(update_fields=["opcao_atual"])
    services._enviar_opcao(candidatura.opcoes.get(ordem=2))
    mail.outbox.clear()

    with mock.patch(
        "apps.projetos.services.avancar_cascata", wraps=services.avancar_cascata
    ) as espiao:
        roda_tarefa()

    espiao.assert_not_called()
    opcao1.refresh_from_db()
    candidatura.refresh_from_db()
    assert opcao1.situacao == OpcaoCandidatura.RECUSADA  # não tocada
    assert candidatura.opcao_atual == 2  # não avançou de novo
    assert mail.outbox == []


# --------------------------------------------------------------------------
# Idempotência da TAREFA PERIÓDICA sob dois ticks do Beat sobrepostos —
# threads e conexões reais, padrão de test_concorrencia.py. O guarda de
# `avancar_cascata` já deveria proteger isso; este teste confirma que a
# tarefa periódica não o contorna por fora (por exemplo, decidindo com base
# num estado que ela mesma leu e cacheou antes de chamar a função).
# --------------------------------------------------------------------------


def _roda_tarefa_em_thread(resultados, chave):
    """Roda `avancar_candidaturas_vencidas` numa conexão de banco própria
    (nova thread do Python => nova conexão do Django) — mesmo padrão de
    `_avanca_cascata_em_thread` em `test_concorrencia.py`."""
    connection.close()
    try:
        tasks.avancar_candidaturas_vencidas()
        resultados[chave] = "concluido"
    finally:
        connection.close()


@pytest.mark.django_db(transaction=True)
def test_dois_ticks_do_beat_sobrepostos_nao_duplicam_avanco(settings):
    """Dois ticks do Beat disparando `avancar_candidaturas_vencidas` ao
    mesmo tempo sobre a MESMA candidatura vencida — cenário real sob carga
    (a execução anterior ainda rodando quando a próxima dispara).

    Mesmo mecanismo de atraso forçado de
    `test_concorrencia.py::test_aceitar_opcao_e_avancar_cascata_concorrentes_nao_duplicam_desfecho`:
    a gravação que marca a opção 1 `EXPIRADA` (dentro da `avancar_cascata`
    chamada pela primeira thread) é atrasada em 1s — tempo real para a
    segunda thread rodar sua PRÓPRIA consulta de candidatas (um SELECT
    simples, sem trava, que ainda enxerga a opção 1 como `ENVIADA`, porque a
    primeira thread não comitou) e tentar (e bloquear tentando) travar a
    MESMA linha de `Candidatura` que a primeira já travou dentro de
    `avancar_cascata`. Com a trava e o guarda certos, a segunda thread só
    lê o estado depois que a primeira comita, encontra a opção corrente
    (agora a opção 2) `ENVIADA` com prazo no FUTURO, e o guarda de prazo de
    `avancar_cascata` a faz não fazer nada.
    """
    settings.CELERY_TASK_ALWAYS_EAGER = True
    Area.objects.create(nome="Engenharia de Software")
    professor1 = _cria_professor(10)
    professor2 = _cria_professor(11)
    aluno = _cria_aluno(10)

    candidatura = services.registrar_candidatura(aluno, [(professor1, None), (professor2, None)])
    opcao1 = candidatura.opcoes.get(ordem=1)
    opcao1.prazo = timezone.now() - timedelta(seconds=1)
    opcao1.save(update_fields=["prazo"])
    mail.outbox.clear()

    save_original = OpcaoCandidatura.save

    def save_com_atraso(self, *args, **kwargs):
        # Só atrasa a gravação que marca a opção 1 EXPIRADA — a chamada de
        # `avancar_cascata` que a encontra de fato vencida. A segunda thread,
        # bloqueada tentando travar a Candidatura, nunca chega a chamar isto.
        if self.pk == opcao1.pk:
            time.sleep(1.0)
        return save_original(self, *args, **kwargs)

    resultados = {}
    t1 = threading.Thread(target=_roda_tarefa_em_thread, args=(resultados, "t1"))
    t2 = threading.Thread(target=_roda_tarefa_em_thread, args=(resultados, "t2"))

    with mock.patch.object(OpcaoCandidatura, "save", save_com_atraso):
        t1.start()
        time.sleep(0.2)  # garante que t1 já leu a candidata antes de t2 consultar
        t2.start()
        t1.join()
        t2.join()

    candidatura.refresh_from_db()
    opcao1.refresh_from_db()
    opcao2 = candidatura.opcoes.get(ordem=2)

    assert resultados == {"t1": "concluido", "t2": "concluido"}
    assert opcao1.situacao == OpcaoCandidatura.EXPIRADA
    assert candidatura.status == Candidatura.EM_CURSO
    assert candidatura.opcao_atual == 2
    assert opcao2.situacao == OpcaoCandidatura.ENVIADA
    # Um só e-mail para o professor 2 — se a segunda thread tivesse
    # contornado o guarda, o professor 2 seria notificado duas vezes, ou a
    # opção 2 teria o prazo reescrito por uma segunda passagem.
    assert len(mail.outbox) == 1
    assert mail.outbox[0].to == [professor2.usuario.email]


# --------------------------------------------------------------------------
# Importante 2 da rodada de correção 1: uma candidatura com erro não pode
# travar as demais do mesmo tick — o `for` original propagava a primeira
# exceção e abortava antes de alcançar as candidaturas seguintes, mesmo que
# elas não tivessem nada de errado.
# --------------------------------------------------------------------------


@pytest.mark.django_db
def test_candidatura_com_erro_nao_trava_as_demais_do_mesmo_tick(registra, roda_tarefa):
    """Três candidaturas vencidas no mesmo tick; a do MEIO (`candidatura2`,
    identificada por `pk`, não por posição — a ordem de iteração da consulta
    não é garantida) levanta uma exceção dentro de `avancar_cascata`.

    Prova por mutação (transcrição no relatório da rodada de correção 1):
    revertido o `try/except` por iteração em `avancar_candidaturas_vencidas`
    (voltando ao `for` que só chama `avancar_cascata` direto), este teste
    reprova — a exceção da candidatura 2 propaga e interrompe o `for` antes
    de alcançar a candidatura processada depois dela na ordem de iteração
    real, e a asserção de que AS DUAS outras avançaram falha para uma delas.
    """
    professores = [_cria_professor(indice) for indice in range(20, 26)]
    aluno1, aluno2, aluno3 = (_cria_aluno(indice) for indice in range(30, 33))

    candidatura1 = registra(aluno1, [(professores[0], None), (professores[1], None)])
    candidatura2 = registra(aluno2, [(professores[2], None), (professores[3], None)])
    candidatura3 = registra(aluno3, [(professores[4], None), (professores[5], None)])

    for candidatura in (candidatura1, candidatura2, candidatura3):
        _expira_prazo(candidatura.opcoes.get(ordem=1))
    mail.outbox.clear()

    avancar_de_verdade = services.avancar_cascata

    def avancar_com_erro_na_candidatura_2(candidatura):
        if candidatura.pk == candidatura2.pk:
            raise RuntimeError("falha proposital de teste — dado sujo simulado")
        return avancar_de_verdade(candidatura)

    logger_da_tarefa = logging.getLogger("apps.projetos.tasks")
    with mock.patch(
        "apps.projetos.services.avancar_cascata",
        side_effect=avancar_com_erro_na_candidatura_2,
    ):
        with mock.patch.object(logger_da_tarefa, "exception") as espiao_log:
            roda_tarefa()

    candidatura1.refresh_from_db()
    candidatura2.refresh_from_db()
    candidatura3.refresh_from_db()

    # As duas candidaturas SEM erro avançaram normalmente — não ficaram
    # presas esperando a vez de uma candidatura que nunca chegaria a rodar.
    assert candidatura1.opcao_atual == 2
    assert candidatura3.opcao_atual == 2
    # A candidatura COM erro não avançou — nem deveria: `avancar_cascata`
    # levantou antes de gravar qualquer coisa. Ela continua na opção 1,
    # ainda `ENVIADA` e vencida, pronta para ser tentada de novo no próximo
    # tick (mesma lógica de retry que já valia sem o isolamento).
    candidatura2.refresh_from_db()
    assert candidatura2.opcao_atual == 1
    opcao1_da_2 = candidatura2.opcoes.get(ordem=1)
    assert opcao1_da_2.situacao == OpcaoCandidatura.ENVIADA
    # A falha foi logada com stack trace (`logger.exception`), não
    # engolida em silêncio — é o único sinal que sobra no log do worker.
    espiao_log.assert_called_once()
    argumentos_do_log = espiao_log.call_args
    assert candidatura2.pk in argumentos_do_log.args
    assert len(mail.outbox) == 2  # um e-mail por candidatura que avançou de verdade
