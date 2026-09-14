from django.core.exceptions import PermissionDenied


def garante(condicao, mensagem):
    if not condicao:
        raise PermissionDenied(mensagem)


def pode_criar_tema(usuario):
    """Só quem tem `PerfilProfessor` cadastra temas.

    A checagem é a EXISTÊNCIA do perfil (`hasattr`), não `usuario.papel ==
    Usuario.PROFESSOR`: o papel padrão de
    `Usuario.objects.create_user`/`create_superuser` é PROFESSOR
    (`apps.contas.models.GerenciadorUsuario`), mas nada cria
    `PerfilProfessor` automaticamente — nem o `createsuperuser` que o
    CLAUDE.md manda rodar. Usar `papel` aqui reproduziria, para
    `/temas/meus/`, o mesmo `RelatedObjectDoesNotExist` (500) que
    `apps/contas/views.py::perfil` já teve na Fase 1.
    """
    return bool(usuario and usuario.is_authenticated and hasattr(usuario, "perfil_professor"))


def _e_o_dono(usuario, professor):
    """`usuario` tem `PerfilProfessor` E é exatamente o `professor` dado —
    a checagem de posse compartilhada por criar/editar/desativar tema
    (rodada de correção 1 da T6). `pode_criar_tema` sozinho só responde "é
    professor?"; esta função responde "é ESTE professor?", o que faltava
    para `criar_tema` recusar um professor A publicando em nome de um
    professor B."""
    return pode_criar_tema(usuario) and usuario.perfil_professor == professor


def pode_criar_tema_para(usuario, professor):
    """`usuario` pode cadastrar um tema em nome de `professor` — hoje,
    somente o próprio `professor` (`usuario.perfil_professor == professor`).

    Distinta de `pode_criar_tema(usuario)`, que só pergunta se `usuario` é
    UM professor, sem ligá-lo ao alvo: sem esta função, `criar_tema`
    aceitava `por` professor e `professor` alvo desencontrados — um
    professor A criando um `Tema` cujo dono gravado é o professor B."""
    return _e_o_dono(usuario, professor)


def pode_desativar_tema(usuario, tema):
    """Só o professor que cadastrou `tema` pode desativá-lo — nem outro
    professor, nem um aluno."""
    return _e_o_dono(usuario, tema.professor)


def pode_editar_tema(usuario, tema):
    """Mesma regra de posse de `pode_desativar_tema`: só o professor que
    cadastrou `tema` pode editá-lo."""
    return _e_o_dono(usuario, tema.professor)


def pode_montar_candidatura(usuario):
    """Só quem tem `PerfilAluno` monta, acompanha ou cancela uma candidatura
    de orientação (T11, spec §6 — "/candidatura/ | aluno | montar, acompanhar
    e cancelar").

    Mesmo formato de `pode_criar_tema`, acima: a checagem é a EXISTÊNCIA do
    perfil (`hasattr(usuario, "perfil_aluno")`), não `usuario.papel ==
    Usuario.ALUNO` — nada cria `PerfilAluno` automaticamente quando um
    `Usuario` é criado com `papel=ALUNO` (mesma lacuna que `create_user`/
    `create_superuser` deixam para `PerfilProfessor`), e usar `papel` aqui
    reproduziria, para `/candidatura/`, o mesmo `RelatedObjectDoesNotExist`
    (500) que `apps/contas/views.py::perfil` já teve na Fase 1.
    """
    return bool(usuario and usuario.is_authenticated and hasattr(usuario, "perfil_aluno"))


def pode_ajustar_orientacao(usuario):
    """Só a coordenação troca o orientador de um projeto (T12, spec §6:
    "/painel/orientacoes/ | coordenação | visão geral, troca de orientador,
    limites").

    Checa `usuario.is_coordenador` diretamente — um campo booleano de
    `Usuario` (`apps/contas/models.py`), não um perfil separado como
    `perfil_professor`/`perfil_aluno`: coordenador é um professor promovido
    (`apps/contas/services.py::promover_a_coordenador`), sem modelo de
    perfil próprio. Por isso, ao contrário de `pode_criar_tema`/
    `pode_montar_candidatura` (acima), não há `RelatedObjectDoesNotExist` a
    evitar aqui — `is_coordenador` sempre existe, com `default=False`.
    """
    return bool(usuario and usuario.is_authenticated and usuario.is_coordenador)


def pode_conceder_limite(usuario):
    """Mesma regra de `pode_ajustar_orientacao`, acima: só a coordenação
    concede ou revoga limites elevados de vaga (T12, spec §3.6)."""
    return bool(usuario and usuario.is_authenticated and usuario.is_coordenador)


def pode_enviar_submissao(usuario, projeto):
    """`usuario` é exatamente o aluno de `projeto` — checagem de POSSE, não
    de papel (Bloco C, spec §5). `Projeto.aluno` é `Usuario` diretamente
    (ao contrário de `Candidatura.aluno`, que é `PerfilAluno`) — comparação
    direta, sem passar por nenhum perfil."""
    return bool(usuario and usuario.is_authenticated and usuario == projeto.aluno)


def pode_responder_opcao(usuario, opcao):
    """`usuario` pode aceitar/recusar `opcao` — só o professor DONO dela
    (T9), mesma checagem de POSSE de `_e_o_dono`: pergunta "é ESTE
    professor?", não "é um professor?" (isso é `pode_criar_tema`, reusada
    como portão de papel pela view `projetos:orientacoes`).

    Conflito de ESTADO (a opção já foi respondida, expirou, ou a candidatura
    já não está mais `EM_CURSO`) NÃO é checado aqui — é erro de NEGÓCIO,
    tratado por `services.aceitar_opcao`/`recusar_opcao` com
    `ValidationError`, nunca com `PermissionDenied`. Esta função só responde
    "esta opção é endereçada a este professor?".
    """
    return bool(
        usuario
        and usuario.is_authenticated
        and hasattr(usuario, "perfil_professor")
        and usuario.perfil_professor == opcao.professor
    )


def pode_reabrir_projeto(usuario, projeto):
    """`usuario` é exatamente o orientador de `projeto` (Bloco D, spec §3.6)
    — posse, não papel."""
    return bool(usuario and usuario.is_authenticated and usuario == projeto.orientador)


def pode_cancelar_projeto(usuario, projeto):
    """Mesma regra de posse de `pode_reabrir_projeto`."""
    return bool(usuario and usuario.is_authenticated and usuario == projeto.orientador)


def pode_aprovar_projeto(usuario, projeto):
    """`usuario` é exatamente o orientador de `projeto` (Bloco E, spec §3.1)
    — posse, não papel."""
    return bool(usuario and usuario.is_authenticated and usuario == projeto.orientador)
