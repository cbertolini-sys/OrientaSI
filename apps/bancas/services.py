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
