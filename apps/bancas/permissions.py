def pode_agendar_banca(usuario, projeto):
    """`usuario` é exatamente o orientador de `projeto` — posse, não papel
    (Bloco D, spec §6). A view escopa o lookup do `Projeto` ao orientador
    autenticado; esta função é defesa em profundidade para quem chamar o
    serviço sem passar por lá."""
    return bool(usuario and usuario.is_authenticated and usuario == projeto.orientador)


def pode_editar_banca(usuario, banca):
    """Mesma regra de posse de `pode_agendar_banca`, sobre o projeto DONO
    da banca."""
    return bool(usuario and usuario.is_authenticated and usuario == banca.projeto.orientador)


def pode_cancelar_banca(usuario, banca):
    """Mesma regra de posse de `pode_editar_banca`."""
    return bool(usuario and usuario.is_authenticated and usuario == banca.projeto.orientador)


def pode_registrar_resultado_banca(usuario, banca):
    """Mesma regra de posse de `pode_editar_banca`."""
    return bool(usuario and usuario.is_authenticated and usuario == banca.projeto.orientador)
