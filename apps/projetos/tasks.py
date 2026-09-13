import logging

from celery import shared_task
from django.conf import settings
from django.core.mail import send_mail
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils import timezone

logger = logging.getLogger(__name__)

# As três notificações do Bloco B (spec §7), seguindo o padrão de
# `apps/contas/tasks.py::enviar_convite`: `render_to_string` de um template
# em templates/email/, `send_mail`, e retentativa com recuo exponencial
# explícito no `countdown` — `retry_backoff` do decorator só vale para
# `autoretry_for`, e aqui o retry é manual (`self.retry(...)` no `except`).
#
# Nenhuma das três aponta para as telas de `/orientacoes/` ou `/candidatura/`
# (T9 e T11) nem para o painel da coordenação (T12): essas rotas não existem
# nesta tarefa. O link é sempre a tela de login (CLAUDE.md, regra 5: "e-mails
# contêm links direcionando para a tela de login/painel"), de onde quem
# recebe o e-mail é redirecionado para o que precisa fazer, uma vez logado.


def _link_login():
    return f"{settings.URL_BASE}{reverse('login')}"


@shared_task(bind=True, max_retries=3)
def enviar_manifestacao(self, opcao_id):
    """Avisa o professor da `OpcaoCandidatura` de que recebeu uma nova
    manifestação de interesse — a opção da vez na cascata (spec §7.1)."""
    from apps.projetos.models import OpcaoCandidatura

    opcao = OpcaoCandidatura.objects.select_related(
        "professor__usuario", "candidatura__aluno__usuario", "tema"
    ).get(pk=opcao_id)
    corpo = render_to_string(
        "email/manifestacao_interesse.txt",
        {
            "opcao": opcao,
            "aluno": opcao.candidatura.aluno.usuario,
            "link": _link_login(),
            "prazo_dias": settings.PRAZO_RESPOSTA_DIAS,
        },
    )
    try:
        send_mail(
            subject="OrientaSI — nova manifestação de interesse em orientação",
            message=corpo,
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[opcao.professor.usuario.email],
        )
    except Exception as erro:  # noqa: BLE001 — repetimos qualquer falha de entrega
        # Mesmo recuo exponencial de `enviar_convite` (apps/contas/tasks.py).
        raise self.retry(exc=erro, countdown=60 * 2**self.request.retries) from erro


@shared_task(bind=True, max_retries=3)
def enviar_recusa(self, opcao_id):
    """Avisa o aluno de que uma opção foi recusada, com a justificativa —
    obrigatória por spec §6 ("sem ela, a recusa é silêncio com outro nome").
    Chamada por `recusar_opcao` (T9); esta tarefa só entrega o e-mail."""
    from apps.projetos.models import OpcaoCandidatura

    opcao = OpcaoCandidatura.objects.select_related(
        "professor__usuario", "candidatura__aluno__usuario"
    ).get(pk=opcao_id)
    corpo = render_to_string(
        "email/candidatura_recusada.txt",
        {"opcao": opcao, "link": _link_login()},
    )
    try:
        send_mail(
            subject="OrientaSI — sua manifestação de interesse foi recusada",
            message=corpo,
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[opcao.candidatura.aluno.usuario.email],
        )
    except Exception as erro:  # noqa: BLE001 — repetimos qualquer falha de entrega
        raise self.retry(exc=erro, countdown=60 * 2**self.request.retries) from erro


@shared_task
def avancar_candidaturas_vencidas():
    """Tarefa periódica (Celery Beat, `CELERY_BEAT_SCHEDULE` em
    `config/settings.py`, de hora em hora) que avança a cascata de toda
    candidatura cuja opção corrente venceu o prazo de resposta (spec §3.2 e
    §5.2), sem esperar o professor responder.

    `@shared_task` simples, sem `bind`/`max_retries`, ao contrário das três
    tarefas acima: esta tarefa não envia e-mail diretamente — quem envia é
    `avancar_cascata`, através de `_enviar_opcao` → `enviar_manifestacao`,
    já com seu próprio retry. Se uma chamada de `avancar_cascata` aqui
    dentro falhar (exceção não tratada), a exceção sobe e o Celery marca
    esta execução como falha, mas a PRÓXIMA execução horária do Beat
    encontra a mesma opção ainda `ENVIADA` e vencida (nada aqui muda seu
    estado antes de `avancar_cascata` rodar) e tenta de novo — não há
    e-mail desta tarefa para duplicar sob retry, então retry automático não
    compraria nada que o próprio agendamento horário não já dê de graça.

    A CONSULTA — o que decide QUAIS candidatas oferecer a `avancar_cascata`,
    nunca SE ela deve avançar (isso é só dela, ver a docstring de
    `avancar_cascata` em `apps/projetos/services.py`):

    - `situacao=ENVIADA`: só uma opção pendurada esperando resposta pode ter
      vencido sem resposta. Uma opção já `RECUSADA`/`ACEITA`/`EXPIRADA`/
      `CANCELADA` não é tocada aqui de novo, mesmo que o `prazo` dela
      continue no passado para sempre (ele não é limpo nem atualizado
      quando alguém responde antes da hora) — sem este filtro, toda opção
      já resolvida entraria na lista de candidatas em TODO tick futuro do
      Beat, e `avancar_cascata` seria chamada de novo para a mesma
      candidatura sem que nada de novo tivesse acontecido. Provado por
      mutação em `apps/projetos/tests/test_prazo.py::
      test_opcao_ja_resolvida_com_prazo_no_passado_nao_e_reprocessada`.
    - `prazo__lt=agora`: só uma opção cujo prazo JÁ passou de verdade — não
      basta estar `ENVIADA`. MEDIDO: removida esta condição, o estado final
      de `test_opcao_no_prazo_nao_avanca` continua correto mesmo assim —
      `avancar_cascata` tem seu PRÓPRIO guarda de prazo, que revalida a
      opção corrente direto do banco e absorve a consulta frouxa. A prova
      por mutação que discrimina é sobre a CHAMADA, não o estado final:
      com o filtro, `avancar_cascata` não deveria ser chamada NENHUMA vez
      quando nada venceu; removido, ela É chamada (inofensivamente, graças
      ao guarda dela) — ver o espião em
      `apps/projetos/tests/test_prazo.py::test_opcao_no_prazo_nao_avanca`
      e a transcrição no relatório da T10.

    NÃO filtra por `candidatura__status=EM_CURSO`: isso duplicaria, em SQL,
    a checagem que `avancar_cascata` já faz em Python como a primeira coisa
    que faz, sob a trava dela — repetir a regra aqui criaria duas fontes da
    mesma verdade (mesma lição de `temas_do_mural`, T7, que reimplementava
    em SQL uma regra que já existia em Python). `avancar_cascata` é a única
    autoridade sobre quando avançar; esta consulta só decide quais
    candidatas oferecer a ela.

    NÃO pré-carrega nem cacheia o estado de cada opção antes de chamar
    `avancar_cascata`: o laço abaixo só passa `opcao.candidatura` adiante —
    nunca decide, a partir do que esta consulta leu, se algo deve mudar.
    Isso é o que torna esta tarefa idempotente mesmo sob dois ticks do Beat
    sobrepostos (a execução anterior ainda rodando quando a próxima
    dispara): a segunda execução pode incluir a MESMA opção na sua própria
    lista, lida antes da primeira ter comitado — mas `avancar_cascata`,
    chamada por ambas, revalida tudo sob `select_for_update` no momento em
    que roda, não a partir de nenhum estado que esta tarefa tenha lido
    antes. Provado com threads e conexões reais em
    `apps/projetos/tests/test_prazo.py::
    test_dois_ticks_do_beat_sobrepostos_nao_duplicam_avanco`.
    """
    from apps.projetos.models import OpcaoCandidatura
    from apps.projetos.services import avancar_cascata

    opcoes_vencidas = OpcaoCandidatura.objects.filter(
        situacao=OpcaoCandidatura.ENVIADA,
        prazo__lt=timezone.now(),
    ).select_related("candidatura")

    for opcao in opcoes_vencidas:
        avancar_cascata(opcao.candidatura)


@shared_task(bind=True, max_retries=3)
def enviar_esgotamento(self, candidatura_id):
    """Avisa a coordenação E o aluno de que as opções se esgotaram sem
    aceite (spec §5.2 e §7.3): quem esgotou é precisamente quem precisa de
    alocação manual, e a coordenação é quem tem esse poder — se o estado só
    existisse na tela do aluno, ninguém agiria.

    Dois `send_mail` distintos, não um só com os dois grupos no mesmo `to`:
    o aluno não precisa ver os e-mails de toda a coordenação (nem
    vice-versa) para saber que a candidatura esgotou. E dois TEXTOS
    distintos (rodada de correção 1, Importante 3) — antes desta correção os
    dois grupos recebiam o MESMO corpo, escrito na terceira pessoa para a
    coordenação ("este(a) aluno(a) precisa de alocação manual"), e o aluno
    lia um chamado a uma ação que não era dele. Também usa
    `candidatura.opcoes.count()` em vez do "três" cravado no texto original
    — `registrar_candidatura` aceita 1 a 3 opções, e uma candidatura de 1 ou
    2 opções chegava a dizer "as três opções ... se esgotaram", falso em
    dois dos três casos.

    RESÍDUO CONHECIDO (M9 da rodada de correção 1, comentário corrigido na
    rodada de correção 2 — Mn6): os dois `send_mail` abaixo têm cada um seu
    próprio `try/except`, para que uma falha no segundo não seja atribuída
    ao primeiro. Isso NÃO elimina toda duplicata possível: se o envio ao
    aluno tiver sucesso e o envio à coordenação falhar, `self.retry`
    reexecuta a tarefa INTEIRA do zero (é assim que o Celery reprocessa uma
    tarefa) — e o aluno recebe o e-mail de novo, apesar de o primeiro envio
    já ter chegado. A saída barata de verdade — não implementada aqui, fora
    de escopo desta rodada — é separar os dois envios em DUAS TAREFAS
    CELERY INDEPENDENTES (`enviar_esgotamento_aluno`/
    `enviar_esgotamento_coordenacao`), cada uma com seu próprio retry: uma
    falhar não reexecuta a outra. Um campo de controle em `Candidatura`
    resolveria o mesmo problema, mas é mais caro e mais estado para manter
    do que só separar a tarefa em duas.
    """
    from apps.contas.services import coordenadores
    from apps.projetos.models import Candidatura

    candidatura = Candidatura.objects.select_related("aluno__usuario").get(pk=candidatura_id)

    # M7 da rodada de correção 1: `coordenadores()` (apps/contas/services.py)
    # conta TAMBÉM coordenadores desativados de propósito — é a origem única
    # do teto de 4 do CLAUDE.md, e alterá-la aqui vazaria essa decisão para
    # fora do lugar que a define. Um coordenador inativo não pode agir sobre
    # o e-mail, então o filtro por `is_active` é feito AQUI, no ponto de
    # envio, não na função compartilhada.
    #
    # Calculado ANTES do e-mail do aluno, de propósito (Mn5 da rodada de
    # correção 2): o texto do aluno afirma "a coordenação já foi avisada"
    # só quando isso for verdade — sem isto, um sistema sem nenhum
    # coordenador ativo mandava essa frase ao aluno de qualquer jeito,
    # prometendo uma ação que não ia acontecer.
    destinatarios_coordenacao = list(
        coordenadores().filter(is_active=True).values_list("email", flat=True)
    )
    contexto = {
        "aluno": candidatura.aluno.usuario,
        "link": _link_login(),
        "total_opcoes": candidatura.opcoes.count(),
        "coordenacao_notificada": bool(destinatarios_coordenacao),
    }

    try:
        corpo_aluno = render_to_string("email/candidatura_esgotada_aluno.txt", contexto)
        send_mail(
            subject="OrientaSI — sua candidatura de orientação esgotou as opções",
            message=corpo_aluno,
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[candidatura.aluno.usuario.email],
        )
    except Exception as erro:  # noqa: BLE001 — repetimos qualquer falha de entrega
        raise self.retry(exc=erro, countdown=60 * 2**self.request.retries) from erro

    if not destinatarios_coordenacao:
        # M8: sem isso, um sistema sem nenhum coordenador ativo falha em
        # silêncio — a candidatura fica ESGOTADA, o aluno é avisado, e
        # ninguém com poder de agir sequer sabe que precisa agir.
        logger.warning(
            "enviar_esgotamento: candidatura %s esgotou, mas não há coordenador ativo "
            "para notificar.",
            candidatura_id,
        )
        return

    try:
        corpo_coordenacao = render_to_string("email/candidatura_esgotada_coordenacao.txt", contexto)
        send_mail(
            subject="OrientaSI — candidatura sem orientador precisa de alocação manual",
            message=corpo_coordenacao,
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=destinatarios_coordenacao,
        )
    except Exception as erro:  # noqa: BLE001 — repetimos qualquer falha de entrega
        raise self.retry(exc=erro, countdown=60 * 2**self.request.retries) from erro
