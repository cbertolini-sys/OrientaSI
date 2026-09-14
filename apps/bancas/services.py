from django.core.exceptions import PermissionDenied, ValidationError

from apps.bancas import permissions
from apps.bancas.models import Banca, MembroBanca
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
