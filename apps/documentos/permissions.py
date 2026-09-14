from apps.contas.models import Usuario


def pode_revisar_ata(usuario):
    """`usuario` tem `papel == Usuario.SUGRAD` — permissão por PAPEL, não
    posse (Bloco E, spec §3.5): a SUGRAD é um setor único (regra
    inegociável nº 2 do CLAUDE.md), não dono de nenhum projeto específico —
    ela revisa a ata de QUALQUER projeto. Mesmo formato de
    `apps.projetos.permissions.pode_ajustar_orientacao`, que já checa
    `is_coordenador` em vez de posse."""
    return bool(usuario and usuario.is_authenticated and usuario.papel == Usuario.SUGRAD)


def pode_reenviar_ata(usuario, ata):
    """`usuario` é exatamente o orientador do projeto da `ata` — posse,
    não papel (Bloco E, spec §5.2)."""
    return bool(usuario and usuario.is_authenticated and usuario == ata.projeto.orientador)
