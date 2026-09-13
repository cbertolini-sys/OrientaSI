from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from apps.projetos import permissions, services
from apps.projetos.forms import FormularioFiltroMural, FormularioRecusaOpcao, FormularioTema
from apps.projetos.models import OpcaoCandidatura, Tema


@login_required
def mural(request):
    """Mural de temas (T7): o aluno navega os temas `ativo` de todos os
    professores antes de se candidatar (candidatura em si é a T8).

    Autenticada mas SEM portão de papel — ao contrário de `meus_temas`
    (exclusiva de quem tem `PerfilProfessor`), qualquer usuário logado pode
    abrir esta tela: um professor navegando o mural para ver a oferta dos
    colegas não é um cenário que o spec proíba, e não há nenhuma ação nesta
    tela (só listagem) que dependa do papel de quem olha.

    O filtro de área é lido do próprio `request.GET` — `request.GET or None`
    devolve `None` para um `QueryDict` vazio (usuário ainda não filtrou
    nada), o que deixa o formulário DESLIGADO (sem erros, sem
    `aria-invalid`) na primeira visita, em vez de "vinculado e válido com
    tudo em branco".
    """
    formulario = FormularioFiltroMural(request.GET or None)
    area = formulario.cleaned_data["area"] if formulario.is_valid() else None
    temas = services.temas_do_mural(area=area)
    return render(request, "projetos/mural.html", {"formulario": formulario, "temas": temas})


@login_required
def meus_temas(request):
    """Painel do professor para cadastrar os temas que oferece (T6). O mural
    público que os alunos veem (Tarefa 7) só lista os temas `ativo` deste
    professor.

    A permissão é conferida ANTES de acessar `request.user.perfil_professor`
    (achado herdado de `apps/contas/views.py::perfil`, Fase 1): o papel
    PROFESSOR é o padrão de `create_user`/`create_superuser`, mas nada cria
    `PerfilProfessor` automaticamente, e acessar o perfil sem essa checagem
    levantaria `RelatedObjectDoesNotExist` (500) para quem tem o papel mas
    não o perfil.
    """
    permissions.garante(
        permissions.pode_criar_tema(request.user), "Somente professores cadastram temas."
    )
    professor = request.user.perfil_professor

    if request.method == "POST":
        formulario = FormularioTema(request.POST, professor=professor)
        if formulario.is_valid():
            try:
                services.criar_tema(
                    professor=professor,
                    area=formulario.cleaned_data["area"],
                    titulo=formulario.cleaned_data["titulo"],
                    descricao=formulario.cleaned_data["descricao"],
                    por=request.user,
                )
            except ValidationError as erro:
                # Não alcançável por ESTA tela hoje: `FormularioTema.area` já
                # restringe o `<select>` às áreas do professor
                # (`professor.areas.all()`), então uma área fora dessa lista
                # é recusada antes, em `ModelChoiceField.to_python`, com a
                # mensagem genérica do Django — nunca chega aqui (verificado
                # rodando o teste, não só lendo o código; ver preocupação nº3
                # do relatório da T6). Este `except` continua sendo a única
                # reação correta se o queryset do widget for afrouxado depois
                # (ex.: um bug que volte a `Area.objects.all()`), então fica.
                formulario.add_error("area", erro.messages[0])
            else:
                messages.success(request, "Tema cadastrado.")
                return redirect("projetos:meus_temas")
    else:
        formulario = FormularioTema(professor=professor)

    return render(
        request,
        "projetos/meus_temas.html",
        {"formulario": formulario, "temas": professor.temas.all()},
    )


@login_required
@require_POST
def desativar_tema(request, tema_id):
    """Desativa um tema do professor autenticado.

    Portão de PAPEL primeiro (`pode_criar_tema`, sem tocar
    `perfil_professor` antes dele — mesma cautela de `meus_temas` para não
    repetir o 500 de professor sem perfil), depois um lookup JÁ ESCOPADO ao
    professor autenticado (`professor=request.user.perfil_professor`): tema
    alheio e tema inexistente respondem os DOIS com 404, uniformemente
    (rodada de correção 2 da T6).

    A versão anterior buscava o tema por pk primeiro (sem escopo) e só então
    checava posse via `services.desativar_tema` — que levanta
    `PermissionDenied`/403 para tema alheio e 404 para pk inexistente. Essa
    diferença é um ORÁCULO: com pk sequencial, dá para descobrir que uma
    linha existe (403) sem descobrir de quem é ou qual o título, tentando
    ids em sequência (medido pelo revisor: tema ativo alheio → 403, tema
    inativo alheio → 403, id inexistente → 404). Como o mural da Tarefa 7
    só lista temas ATIVOS, o que esse oráculo entregava a mais era
    exatamente a contagem dos temas DESATIVADOS de outros professores —
    pouco, sem PII, mas mensurável, o que basta para não ser "nada".

    `services.desativar_tema` continua com sua própria checagem de posse
    (`permissions.pode_desativar_tema`) — redundante quando chamada por
    AQUI, porque o `get_object_or_404` já garante posse antes de chegar lá,
    mas é o que protege qualquer outro chamador do serviço que não escope o
    lookup do mesmo jeito."""
    permissions.garante(
        permissions.pode_criar_tema(request.user), "Somente professores cadastram temas."
    )
    tema = get_object_or_404(Tema, pk=tema_id, professor=request.user.perfil_professor)
    services.desativar_tema(tema, por=request.user)
    messages.success(request, "Tema desativado.")
    return redirect("projetos:meus_temas")


@login_required
def editar_tema(request, tema_id):
    """Edita um tema do professor autenticado (acréscimo de escopo da
    rodada de correção 1 da T6: o spec exige edição em §2 e §6, e nenhuma
    tarefa do plano original a implementava).

    Mesma ordem de `desativar_tema` (rodada de correção 2 da T6): portão de
    papel (`pode_criar_tema`) antes de tocar `perfil_professor`, depois um
    lookup já escopado ao professor autenticado — tema alheio e tema
    inexistente respondem os DOIS com 404, sem o oráculo que a versão
    anterior (buscar por pk cru, checar posse com `permissions.pode_editar_tema`
    depois) deixava passar: 403 para tema alheio existente, 404 para pk
    inexistente, distinguíveis por tentativa.

    Reaproveita o mesmo formulário (`FormularioTema`) do cadastro, com
    `initial=` para pré-preencher os valores atuais — não duplica o
    formulário.
    """
    permissions.garante(
        permissions.pode_criar_tema(request.user), "Somente professores cadastram temas."
    )
    tema = get_object_or_404(Tema, pk=tema_id, professor=request.user.perfil_professor)
    professor = tema.professor

    if request.method == "POST":
        formulario = FormularioTema(request.POST, professor=professor)
        if formulario.is_valid():
            try:
                services.editar_tema(
                    tema,
                    area=formulario.cleaned_data["area"],
                    titulo=formulario.cleaned_data["titulo"],
                    descricao=formulario.cleaned_data["descricao"],
                    por=request.user,
                )
            except ValidationError as erro:
                # Mesma ressalva de `meus_temas`: não alcançável por esta
                # tela hoje, porque `FormularioTema.area` já restringe o
                # `<select>` às áreas do professor — fica como a reação
                # correta se essa restrição for afrouxada depois.
                formulario.add_error("area", erro.messages[0])
            else:
                messages.success(request, "Tema atualizado.")
                return redirect("projetos:meus_temas")
    else:
        formulario = FormularioTema(
            initial={"titulo": tema.titulo, "descricao": tema.descricao, "area": tema.area},
            professor=professor,
        )

    return render(request, "projetos/editar_tema.html", {"formulario": formulario, "tema": tema})


@login_required
def orientacoes(request):
    """Fila do professor: manifestações de interesse pendentes de resposta,
    e os orientandos que ele já tem no semestre vigente (T9, spec §6 —
    "/orientacoes/ | professor | fila de manifestações **e orientandos
    atuais**").

    A segunda metade (orientandos atuais) foi acrescentada na rodada de
    correção 1: nenhuma das treze tarefas do plano original a implementava
    — defeito do plano, fechado aqui em vez de numa tarefa futura, pelo
    mesmo motivo da edição de tema na T6 (é a mesma tela; reabri-la depois
    custa resubmetê-la às cinco suítes de acessibilidade de novo). Sem ela,
    a tela mentia por omissão logo depois de um aceite: a manifestação
    aceita some da fila, e "Nenhuma manifestação aguardando sua resposta no
    momento" ficava como se fosse a única informação da página — um
    professor com três orientandos e zero pendências via uma tela que,
    pelo título, parecia dizer que ele não tem nada.

    Portão de PAPEL antes de tocar `perfil_professor` — mesma cautela de
    `meus_temas`, acima, para não repetir o 500 de professor sem perfil
    (Fase 1, `apps/contas/views.py::perfil`). Reusa `pode_criar_tema` como
    portão de papel: apesar do nome, ela responde exatamente "`usuario` é um
    professor com perfil?" (ver a docstring dela em `permissions.py`), a
    mesma pergunta que esta tela precisa fazer antes de listar a fila —
    `pode_responder_opcao` é checagem de POSSE de uma opção específica, não
    serve como portão de entrada da tela.

    As duas consultas moram em `services.py`
    (`manifestacoes_pendentes`/`orientandos_atuais`, Menor 8 da rodada de
    correção 1) — simétrico com `mural` (T7), que já usa
    `services.temas_do_mural` em vez de montar o queryset aqui.

    Um `FormularioRecusaOpcao` por opção pendente, cada um com `auto_id`
    próprio (`FormularioRecusaOpcao`, em `forms.py`): sem isso, o `id` do
    campo "justificativa" se repetiria a cada `<li>` da lista, e o
    `<label for=...>` do parcial `contas/_campo.html` apontaria para mais de
    um controle.
    """
    permissions.garante(
        permissions.pode_criar_tema(request.user),
        "Somente professores acessam a fila de orientações.",
    )
    professor = request.user.perfil_professor
    itens = [
        {
            "opcao": opcao,
            "formulario_recusa": FormularioRecusaOpcao(auto_id=f"id_recusa_{opcao.pk}_%s"),
        }
        for opcao in services.manifestacoes_pendentes(professor)
    ]
    orientandos = services.orientandos_atuais(professor)
    return render(
        request, "projetos/orientacoes.html", {"itens": itens, "orientandos": orientandos}
    )


@login_required
@require_POST
def aceitar_opcao_view(request, opcao_id):
    """Aceita uma manifestação da fila do professor autenticado (T9).

    Portão de papel primeiro, depois lookup JÁ ESCOPADO ao professor
    autenticado (`get_object_or_404(OpcaoCandidatura, pk=..., professor=...)`)
    — mesmo padrão de `desativar_tema`/`editar_tema`, acima: manifestação
    alheia e manifestação inexistente respondem os DOIS com 404, sem abrir
    um oráculo de existência sobre a fila de outros professores.
    `services.aceitar_opcao` mantém sua própria checagem de posse
    (`permissions.pode_responder_opcao`) — redundante aqui, mas protege
    qualquer outro chamador que não escope o lookup do mesmo jeito.
    """
    permissions.garante(
        permissions.pode_criar_tema(request.user),
        "Somente professores acessam a fila de orientações.",
    )
    opcao = get_object_or_404(
        OpcaoCandidatura, pk=opcao_id, professor=request.user.perfil_professor
    )
    try:
        services.aceitar_opcao(opcao, por=request.user)
    except ValidationError as erro:
        messages.error(request, erro.messages[0])
    else:
        messages.success(request, "Manifestação aceita — o projeto de orientação foi criado.")
    return redirect("projetos:orientacoes")


@login_required
@require_POST
def recusar_opcao_view(request, opcao_id):
    """Recusa uma manifestação da fila do professor autenticado, com
    justificativa obrigatória (T9). Mesmo padrão de posse via lookup
    escopado de `aceitar_opcao_view`, acima.

    Um formulário inválido (justificativa em branco) não impede que a lista
    inteira seja perdida: a resposta é sempre um redirect para
    `projetos:orientacoes` (padrão redirect-after-POST já usado por
    `desativar_tema`), com o erro relatado via `messages` — não há estado de
    formulário parcial para preservar entre POST e a nova renderização,
    porque a página lista várias manifestações, não uma edição de registro
    único.
    """
    permissions.garante(
        permissions.pode_criar_tema(request.user),
        "Somente professores acessam a fila de orientações.",
    )
    opcao = get_object_or_404(
        OpcaoCandidatura, pk=opcao_id, professor=request.user.perfil_professor
    )
    formulario = FormularioRecusaOpcao(request.POST)
    if not formulario.is_valid():
        messages.error(request, "Informe uma justificativa para recusar.")
        return redirect("projetos:orientacoes")

    try:
        services.recusar_opcao(
            opcao, por=request.user, justificativa=formulario.cleaned_data["justificativa"]
        )
    except ValidationError as erro:
        messages.error(request, erro.messages[0])
    else:
        messages.success(request, "Manifestação recusada. O aluno foi avisado.")
    return redirect("projetos:orientacoes")
