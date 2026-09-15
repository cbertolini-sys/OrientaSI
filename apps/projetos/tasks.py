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
    candidatura cuja opção corrente venceu o prazo de resposta (spec §3.2,
    §5.2 e, principalmente, §3.8 linha 158 — "O prazo avança por tarefa
    periódica, com agendamento estático": é essa linha, não §3.2 nem §5.2,
    que decide a EXISTÊNCIA desta tarefa e a recusa de `django-celery-beat`
    que o comentário de `CELERY_BEAT_SCHEDULE`, em `config/settings.py`,
    reproduz), sem esperar o professor responder.

    `@shared_task` simples, sem `bind`/`max_retries`, ao contrário das três
    tarefas acima: esta tarefa não envia e-mail diretamente — quem envia é
    `avancar_cascata`, através de `_enviar_opcao` → `enviar_manifestacao`,
    já com seu próprio retry. Não há e-mail desta tarefa para duplicar sob
    retry automático do Celery, então isso não compraria nada que o próprio
    agendamento horário não já dê de graça — mas isso NÃO significa "deixar
    a exceção subir e derrubar a execução inteira": ver o `try/except` por
    ITERAÇÃO logo abaixo (Importante 2 da rodada de correção 1), que isola
    a falha de uma candidatura sem interromper as demais do mesmo tick. Uma
    falha (tratada ou não) na candidatura X não muda o estado dela antes de
    `avancar_cascata` rodar, então a PRÓXIMA execução horária do Beat
    encontra a mesma opção ainda `ENVIADA` e vencida e tenta de novo —
    isso continua valendo por candidatura, com o isolamento.

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
        try:
            avancar_cascata(opcao.candidatura)
        except Exception:  # noqa: BLE001 — uma candidatura ruim não pode travar as outras
            # Importante 2 da rodada de correção 1: sem este isolamento por
            # iteração, uma exceção na candidatura N interrompe o `for` antes
            # de alcançar N+1, N+2... — e não é transitório: um dado sujo ou
            # um `IntegrityError` recorrente aborta no MESMO ponto a cada
            # tick horário, para sempre, deixando as candidaturas seguintes
            # (cujas opções não têm nada de errado) presas indefinidamente
            # numa opção vencida, sem sinal além deste traceback no log do
            # worker. A falha em SI não é escondida (é logada com stack
            # trace) nem silenciosamente "resolvida": a candidatura que
            # falhou continua com a opção vencida no próximo tick, porque
            # nada mudou de estado — mesmo raciocínio de retry que já valia
            # sem este `try` (ver acima), só que agora sem starvation das
            # candidaturas saudáveis do mesmo tick.
            logger.exception(
                "Falha ao avançar a cascata da candidatura %s (opção %s) — "
                "as demais do mesmo tick seguem.",
                opcao.candidatura_id,
                opcao.pk,
            )
    # Provado por mutação (removido este `try/except`) em
    # `apps/projetos/tests/test_prazo.py::
    # test_candidatura_com_erro_nao_trava_as_demais_do_mesmo_tick` — ver a
    # transcrição no relatório da rodada de correção 1.


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


@shared_task(bind=True, max_retries=3)
def enviar_tcc_ii_criado(self, projeto_id):
    """Avisa o aluno de que o TCC II foi criado — automático ou manual
    (Bloco F, spec §8)."""
    from apps.projetos.models import Projeto

    projeto = Projeto.objects.select_related("aluno", "orientador").get(pk=projeto_id)
    corpo = render_to_string(
        "email/tcc_ii_criado.txt",
        {"aluno": projeto.aluno, "orientador": projeto.orientador, "link": _link_login()},
    )
    try:
        send_mail(
            subject="OrientaSI — seu TCC II foi criado",
            message=corpo,
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[projeto.aluno.email],
        )
    except Exception as erro:  # noqa: BLE001 — repetimos qualquer falha de entrega
        raise self.retry(exc=erro, countdown=60 * 2**self.request.retries) from erro


@shared_task(bind=True, max_retries=3)
def enviar_tcc_i_criado(self, projeto_id):
    """Avisa o aluno de que o TCC I foi criado manualmente pelo professor —
    espelha `enviar_tcc_ii_criado` acima, para o caminho novo de
    `services.criar_tcc_i_manual` (exceção à regra inegociável nº 8,
    CLAUDE.md). O caminho normal de TCC I (`aceitar_opcao`, cascata de
    candidatura) não envia este e-mail — o aluno já sabe que se candidatou e
    foi aceito; este aqui existe pro caminho manual, onde a criação é
    iniciativa do professor e o aluno precisa ser avisado."""
    from apps.projetos.models import Projeto

    projeto = Projeto.objects.select_related("aluno", "orientador").get(pk=projeto_id)
    corpo = render_to_string(
        "email/tcc_i_criado.txt",
        {"aluno": projeto.aluno, "orientador": projeto.orientador, "link": _link_login()},
    )
    try:
        send_mail(
            subject="OrientaSI — seu TCC I foi criado",
            message=corpo,
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[projeto.aluno.email],
        )
    except Exception as erro:  # noqa: BLE001 — repetimos qualquer falha de entrega
        raise self.retry(exc=erro, countdown=60 * 2**self.request.retries) from erro
