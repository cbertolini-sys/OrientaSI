from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction

from apps.bancas import permissions
from apps.bancas.models import Banca, ItemCorrecao, MembroBanca
from apps.bancas.tasks import enviar_agendamento_banca, enviar_item_correcao_criado
from apps.projetos.models import Projeto


def _valida_membros(membros, orientador):
    """Compartilhada por `agendar_banca`/`editar_banca`: exatamente 2
    `membros`, nenhum sendo o próprio `orientador` (um `Usuario`), nenhum
    `professor` repetido entre os dois. Levanta `ValidationError` com
    mensagem específica para cada caso — não um `assert` genérico."""
    if len(membros) != 2:
        raise ValidationError("A banca precisa de exatamente dois membros, além do orientador.")

    professores = [m["professor"] for m in membros if "professor" in m]
    for professor in professores:
        if professor.usuario_id == orientador.id:
            raise ValidationError("O orientador já participa da banca — não é um dos dois membros.")
    if len(professores) != len({p.pk for p in professores}):
        raise ValidationError("Os dois membros professores precisam ser diferentes.")


def agendar_banca(projeto, data_hora, local, membros, por):
    """Agenda a `Banca` de `projeto` — fecha `EM_ANDAMENTO` →
    `AGUARDANDO_DEFESA` (Bloco D, spec §5.1). `por` é o `Usuario`
    autenticado; a permissão (só o orientador do projeto) é checada aqui
    dentro, mesmo padrão de posse de
    `apps.projetos.services.enviar_submissao`."""
    if not permissions.pode_agendar_banca(por, projeto):
        raise PermissionDenied("Somente o orientador do projeto agenda a banca.")
    if projeto.status != Projeto.EM_ANDAMENTO:
        raise ValidationError("Só é possível agendar banca com o projeto em andamento.")
    if not hasattr(projeto, "submissao"):
        raise ValidationError("O aluno ainda não enviou o trabalho — não há o que avaliar.")

    _valida_membros(membros, projeto.orientador)

    banca = Banca.objects.create(projeto=projeto, data_hora=data_hora, local=local)
    for membro in membros:
        MembroBanca.objects.create(banca=banca, **membro)

    projeto.status = Projeto.AGUARDANDO_DEFESA
    projeto.save(update_fields=["status"])

    transaction.on_commit(lambda: enviar_agendamento_banca.delay(banca.id))

    return banca


def editar_banca(banca, data_hora, local, membros, por):
    """Reagenda `banca` — só permitida enquanto `AGENDADA` (Bloco D, spec
    §5.1). Substitui os `MembroBanca` (apaga os antigos, cria os novos) em
    vez de tentar casar a lista antiga com a nova membro a membro — mais
    simples, e o histórico de "quem era o membro antes" não é um requisito
    deste bloco."""
    if not permissions.pode_editar_banca(por, banca):
        raise PermissionDenied("Somente o orientador do projeto edita a banca.")
    if banca.status != Banca.AGENDADA:
        raise ValidationError("Só é possível editar uma banca ainda agendada.")

    _valida_membros(membros, banca.projeto.orientador)

    banca.data_hora = data_hora
    banca.local = local
    banca.save(update_fields=["data_hora", "local"])

    banca.membros.all().delete()
    for membro in membros:
        MembroBanca.objects.create(banca=banca, **membro)

    transaction.on_commit(lambda: enviar_agendamento_banca.delay(banca.id))

    return banca


def cancelar_banca(banca, por):
    """Cancela `banca` e devolve o projeto a `EM_ANDAMENTO` — o orientador
    pode agendar uma banca nova depois (Bloco D, spec §3.4/§5.1). Sem
    notificação por e-mail (spec §8)."""
    if not permissions.pode_cancelar_banca(por, banca):
        raise PermissionDenied("Somente o orientador do projeto cancela a banca.")
    if banca.status != Banca.AGENDADA:
        raise ValidationError("Só é possível cancelar uma banca ainda agendada.")

    banca.status = Banca.CANCELADA
    banca.save(update_fields=["status"])

    banca.projeto.status = Projeto.EM_ANDAMENTO
    banca.projeto.save(update_fields=["status"])


def registrar_resultado(banca, nota, resultado, comentario, por):
    """Registra o resultado da apresentação — fecha `AGUARDANDO_DEFESA` →
    `resultado` (Bloco D, spec §3.2/§5.1). Sem trava de data (§3.5): confia
    no orientador para só chamar depois que a apresentação aconteceu."""
    if not permissions.pode_registrar_resultado_banca(por, banca):
        raise PermissionDenied("Somente o orientador do projeto registra o resultado.")
    if banca.status != Banca.AGENDADA:
        raise ValidationError("Esta banca já teve o resultado registrado, ou foi cancelada.")

    banca.nota = nota
    banca.resultado = resultado
    banca.comentario = comentario
    banca.status = Banca.REALIZADA
    banca.save(update_fields=["nota", "resultado", "comentario", "status"])

    banca.projeto.status = resultado
    banca.projeto.save(update_fields=["status"])

    return banca


def anexar_banca_ativa(projetos):
    """Decora cada `Projeto` de `projetos` (lista já materializada, não
    queryset) com `.banca_ativa` — a `Banca` não cancelada desse projeto, ou
    `None` (Bloco D, spec §3.7/§7). UMA query para todos os projetos, não
    uma por projeto: mesma disciplina de N+1 de
    `apps.projetos.services.orientandos_atuais` (`select_related`) — aqui
    não dá pra usar `select_related`/`prefetch_related` na queryset de
    `Projeto` porque `Banca.projeto` é o lado FK inverso vindo de OUTRO
    app; a alternativa é este mapa construído com uma query só."""
    ids = [p.id for p in projetos]
    bancas_por_projeto = {
        banca.projeto_id: banca
        for banca in Banca.objects.filter(projeto_id__in=ids)
        .exclude(status=Banca.CANCELADA)
        .prefetch_related("membros__professor__usuario")
    }
    for projeto in projetos:
        projeto.banca_ativa = bancas_por_projeto.get(projeto.id)
    return projetos


def criar_item_correcao(projeto, descricao, por):
    """Orientador digita um item do checklist de correções (Bloco F, spec
    §5.2) — baseado no que a banca pediu (`Banca.comentario`), não
    estruturado a partir da banca em si. Notifica o aluno por e-mail a cada
    item novo (decisão explícita do usuário, spec §8)."""
    if not permissions.pode_gerenciar_correcao(por, projeto):
        raise PermissionDenied("Somente o orientador do projeto gerencia as correções.")

    item = ItemCorrecao.objects.create(projeto=projeto, descricao=descricao)

    transaction.on_commit(lambda: enviar_item_correcao_criado.delay(item.id))

    return item


def concluir_item_correcao(item, por):
    """Orientador marca um item de correção como resolvido (Bloco F, spec
    §5.2). Sem notificação — o aluno já viu o item ao ser criado; concluir
    é informação de controle do orientador, não algo acionável pro aluno."""
    if not permissions.pode_gerenciar_correcao(por, item.projeto):
        raise PermissionDenied("Somente o orientador do projeto gerencia as correções.")

    item.concluido = True
    item.save(update_fields=["concluido"])
