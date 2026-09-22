from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError, transaction

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


def _substituir_membros(banca, membros):
    """Apaga os `MembroBanca` atuais de `banca` (se houver) e cria os de
    `membros` — compartilhada por `agendar_banca` (não apaga nada, a banca é
    nova) e `editar_banca` (apaga os antigos primeiro). Extraída na correção
    da auditoria (achado L1): as duas funções tinham este bloco duplicado
    verbatim, incluindo o disparo de notificação."""
    banca.membros.all().delete()
    for membro in membros:
        MembroBanca.objects.create(banca=banca, **membro)

    transaction.on_commit(lambda: enviar_agendamento_banca.delay(banca.id))


@transaction.atomic
def agendar_banca(projeto, data_hora, local, membros, por):
    """Agenda a `Banca` de `projeto` — fecha `EM_ANDAMENTO` →
    `AGUARDANDO_DEFESA` (Bloco D, spec §5.1). `por` é o `Usuario`
    autenticado; a permissão (só o orientador do projeto) é checada aqui
    dentro, mesmo padrão de posse de
    `apps.projetos.services.enviar_submissao`.

    `@transaction.atomic` (correção da auditoria, achado H8/M3): a criação
    da `Banca` + dos dois `MembroBanca` + a transição de `Projeto.status`
    eram três/quatro `save()` independentes em autocommit — uma falha no
    meio deixava uma `Banca` órfã com menos de dois membros e o projeto
    ainda `EM_ANDAMENTO`, e o retry criava uma SEGUNDA `Banca` (só
    descoberta ao gerar a ata, que pega a mais recente). Agora tudo commita
    junto ou nada commita."""
    if not permissions.pode_agendar_banca(por, projeto):
        raise PermissionDenied("Somente o orientador do projeto agenda a banca.")
    if projeto.status != Projeto.EM_ANDAMENTO:
        raise ValidationError("Só é possível agendar banca com o projeto em andamento.")
    if not hasattr(projeto, "submissao"):
        raise ValidationError("O aluno ainda não enviou o trabalho — não há o que avaliar.")

    _valida_membros(membros, projeto.orientador)

    try:
        banca = Banca.objects.create(projeto=projeto, data_hora=data_hora, local=local)
    except IntegrityError as erro:
        # Defesa em profundidade (achado C1): a checagem de `projeto.status`
        # acima já deveria impedir duas bancas AGENDADA para o mesmo
        # projeto, mas sob concorrência real (duplo clique, duas abas) as
        # duas requisições podem empatar na leitura do status e colidir só
        # no banco, na `UniqueConstraint banca_ativa_unica_por_projeto` —
        # mesmo padrão de `apps.projetos.services.criar_projeto_sob_limite`.
        # Inspeciona QUAL constraint disparou (achado da revisão de código
        # desta mesma correção, 2026-09-22 — consistência com o padrão de
        # L5/H5 no resto deste PR): sem isto, uma constraint FUTURA em
        # `Banca` teria seu `IntegrityError` mal atribuído a "já existe uma
        # banca agendada", a mesma classe de bug que L5 fechou em
        # `criar_projeto_sob_limite`.
        nome_da_constraint = getattr(getattr(erro, "__cause__", None), "diag", None)
        nome_da_constraint = getattr(nome_da_constraint, "constraint_name", None)
        if nome_da_constraint != "banca_ativa_unica_por_projeto":
            raise
        raise ValidationError("Já existe uma banca agendada para este projeto.") from None

    # `_substituir_membros` (achado da revisão de código, consistência com
    # L1): antes, este trecho duplicava o mesmo laço de criação +
    # `transaction.on_commit` que `_substituir_membros` já existe para
    # compartilhar com `editar_banca` — a docstring do helper já afirmava
    # isso, mas o código não fazia. `banca.membros.all().delete()`, dentro
    # do helper, é um no-op aqui (a banca acabou de nascer, sem membros).
    _substituir_membros(banca, membros)

    projeto.status = Projeto.AGUARDANDO_DEFESA
    projeto.save(update_fields=["status"])

    return banca


@transaction.atomic
def editar_banca(banca, data_hora, local, membros, por):
    """Reagenda `banca` — só permitida enquanto `AGENDADA` (Bloco D, spec
    §5.1). Substitui os `MembroBanca` (apaga os antigos, cria os novos) em
    vez de tentar casar a lista antiga com a nova membro a membro — mais
    simples, e o histórico de "quem era o membro antes" não é um requisito
    deste bloco.

    `@transaction.atomic` (achado H8/M3): sem isto, uma falha na recriação
    dos membros (depois do `.delete()` dos antigos) deixava a banca com ZERO
    membros — e é essa banca que `gerar_ata` renderiza no PDF oficial."""
    if not permissions.pode_editar_banca(por, banca):
        raise PermissionDenied("Somente o orientador do projeto edita a banca.")
    if banca.status != Banca.AGENDADA:
        raise ValidationError("Só é possível editar uma banca ainda agendada.")

    _valida_membros(membros, banca.projeto.orientador)

    banca.data_hora = data_hora
    banca.local = local
    banca.save(update_fields=["data_hora", "local"])

    _substituir_membros(banca, membros)

    return banca


@transaction.atomic
def cancelar_banca(banca, por):
    """Cancela `banca` e devolve o projeto a `EM_ANDAMENTO` — o orientador
    pode agendar uma banca nova depois (Bloco D, spec §3.4/§5.1). Sem
    notificação por e-mail (spec §8).

    `@transaction.atomic` (achado H8): as duas gravações (`Banca.status` e
    `Projeto.status`) agora commitam juntas. Também passa a EXIGIR
    (achado M4) que o projeto esteja mesmo `AGUARDANDO_DEFESA` antes de
    reverter — antes a reversão era incondicional, inferindo o estado do
    projeto a partir do estado da banca em vez de checá-lo."""
    if not permissions.pode_cancelar_banca(por, banca):
        raise PermissionDenied("Somente o orientador do projeto cancela a banca.")
    if banca.status != Banca.AGENDADA:
        raise ValidationError("Só é possível cancelar uma banca ainda agendada.")
    if banca.projeto.status != Projeto.AGUARDANDO_DEFESA:
        raise ValidationError(
            "O projeto desta banca não está aguardando defesa — não há o que reverter."
        )

    banca.status = Banca.CANCELADA
    banca.save(update_fields=["status"])

    banca.projeto.status = Projeto.EM_ANDAMENTO
    banca.projeto.save(update_fields=["status"])


@transaction.atomic
def registrar_resultado(banca, nota, resultado, comentario, por):
    """Registra o resultado da apresentação — fecha `AGUARDANDO_DEFESA` →
    `resultado` (Bloco D, spec §3.2/§5.1). Sem trava de data (§3.5): confia
    no orientador para só chamar depois que a apresentação aconteceu.

    `@transaction.atomic` (achado H8) + duas checagens novas (achado M2):
    (1) `resultado` é validado contra a whitelist de `Banca.resultado.choices`
    ANTES de ser gravado em `Projeto.status` — antes, um chamador de serviço
    fora do formulário (só o formulário restringia os dois valores possíveis)
    conseguia jogar o projeto em qualquer string de até 22 caracteres; (2) o
    `Projeto` precisa estar mesmo em `AGUARDANDO_DEFESA` — antes a função só
    confiava em `banca.status == AGENDADA` como proxy do status do projeto."""
    if not permissions.pode_registrar_resultado_banca(por, banca):
        raise PermissionDenied("Somente o orientador do projeto registra o resultado.")
    if banca.status != Banca.AGENDADA:
        raise ValidationError("Esta banca já teve o resultado registrado, ou foi cancelada.")
    if banca.projeto.status != Projeto.AGUARDANDO_DEFESA:
        raise ValidationError("Este projeto não está aguardando defesa.")

    valores_permitidos = {valor for valor, _ in Banca._meta.get_field("resultado").choices}
    if resultado not in valores_permitidos:
        raise ValidationError("Resultado inválido.")

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
    queryset) com `.banca_ativa` — a `Banca` NÃO CANCELADA mais recente
    desse projeto, ou `None` (Bloco D, spec §3.7/§7). "Mais recente" importa
    desde a correção da auditoria (C1): depois que `reabrir_projeto` deixou
    de ser bloqueado por uma banca `REALIZADA` antiga, um projeto pode ter
    DUAS bancas não canceladas ao mesmo tempo — a `REALIZADA` do ciclo
    anterior (reprovado) e a `AGENDADA` do novo ciclo. É sempre a mais nova
    que a tela precisa: se há uma `AGENDADA`, ela é sempre a mais recente
    (só se cria uma banca nova com o projeto `EM_ANDAMENTO`, ou seja, depois
    de qualquer banca anterior já ter sido resolvida); senão, a `REALIZADA`
    mais recente é o que sustenta o ramo "Resultado da banca: Reprovado" do
    template para um projeto ainda não reaberto.

    UMA query para todos os projetos, não uma por projeto: mesma disciplina
    de N+1 de `apps.projetos.services.orientandos_atuais`
    (`select_related`) — aqui não dá pra usar
    `select_related`/`prefetch_related` na queryset de `Projeto` porque
    `Banca.projeto` é o lado FK inverso vindo de OUTRO app; a alternativa é
    este mapa construído com uma query só, em ordem ASCENDENTE de
    `criada_em` para que a última atribuição no laço abaixo fique com a mais
    recente (o `Meta.ordering` de `Banca` é descendente — por isso o
    `order_by` explícito aqui não é redundante)."""
    ids = [p.id for p in projetos]
    bancas = (
        Banca.objects.filter(projeto_id__in=ids)
        .exclude(status=Banca.CANCELADA)
        .order_by("criada_em")
        .prefetch_related("membros__professor__usuario")
    )
    bancas_por_projeto = {}
    for banca in bancas:
        bancas_por_projeto[banca.projeto_id] = banca
    for projeto in projetos:
        projeto.banca_ativa = bancas_por_projeto.get(projeto.id)
    return projetos


def _garante_checklist_aplicavel(projeto):
    """Compartilhada por `criar_item_correcao`/`concluir_item_correcao`
    (achado H4 da auditoria): o checklist de correções é exclusivo do TCC II
    e só faz sentido no intervalo pós-banca (`APROVADO_COM_RESSALVAS`), como
    o CLAUDE.md descreve — mas essa restrição vivia SÓ num `{% elif %}` de
    template (`orientacoes.html`), puramente de apresentação. Um orientador
    acessando `/bancas/<id>/correcoes/` direto para um TCC I, ou depois do
    projeto já ter saído de `APROVADO_COM_RESSALVAS`, passava sem checagem
    nenhuma — inclusive disparando o e-mail ao aluno. Movida para cá,
    achado, além disso, uma violação da regra 4 do CLAUDE.md (regra de
    negócio não pode morar só em template/views.py)."""
    if projeto.etapa != Projeto.TCC_II:
        raise ValidationError("O checklist de correções é exclusivo do TCC II.")
    if projeto.status != Projeto.APROVADO_COM_RESSALVAS:
        raise ValidationError(
            "O checklist de correções só pode ser alterado enquanto o projeto "
            "está aguardando as correções pós-banca."
        )


@transaction.atomic
def criar_item_correcao(projeto, descricao, por):
    """Orientador digita um item do checklist de correções (Bloco F, spec
    §5.2) — baseado no que a banca pediu (`Banca.comentario`), não
    estruturado a partir da banca em si. Notifica o aluno por e-mail a cada
    item novo (decisão explícita do usuário, spec §8).

    `@transaction.atomic` (achado H8) e checagem de etapa/status (achado H4,
    ver `_garante_checklist_aplicavel`)."""
    if not permissions.pode_gerenciar_correcao(por, projeto):
        raise PermissionDenied("Somente o orientador do projeto gerencia as correções.")
    _garante_checklist_aplicavel(projeto)

    item = ItemCorrecao.objects.create(projeto=projeto, descricao=descricao)

    transaction.on_commit(lambda: enviar_item_correcao_criado.delay(item.id))

    return item


def concluir_item_correcao(item, por):
    """Orientador marca um item de correção como resolvido (Bloco F, spec
    §5.2). Sem notificação — o aluno já viu o item ao ser criado; concluir
    é informação de controle do orientador, não algo acionável pro aluno.

    Checagem de etapa/status (achado H4, ver `_garante_checklist_aplicavel`):
    um item só pode ser concluído enquanto o projeto ainda está no intervalo
    em que o checklist é avaliado — depois de `Aprovado`/`Concluído`,
    concluir um item não tem mais efeito nenhum sobre `aprovar_projeto` e só
    confundiria o histórico."""
    if not permissions.pode_gerenciar_correcao(por, item.projeto):
        raise PermissionDenied("Somente o orientador do projeto gerencia as correções.")
    _garante_checklist_aplicavel(item.projeto)

    item.concluido = True
    item.save(update_fields=["concluido"])
