from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.db.models import Prefetch
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from apps.projetos import permissions, services
from apps.projetos.forms import (
    FormularioCandidatura,
    FormularioConcederLimite,
    FormularioCriarTccII,
    FormularioFiltroMural,
    FormularioRecusaOpcao,
    FormularioSubmissao,
    FormularioTema,
    FormularioTrocarOrientador,
)
from apps.projetos.models import Candidatura, LimiteOrientacao, OpcaoCandidatura, Projeto, Tema


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
    mesmo motivo citado em `tarefa-9-fix-1-brief.md:62-63` para a edição de
    tema na T6: é a mesma tela, os mesmos arquivos, e reabri-la depois custa
    resubmetê-la às cinco suítes de acessibilidade de novo. Sem ela,
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
    from apps.bancas.services import anexar_banca_ativa

    orientandos = list(services.orientandos_atuais(professor))
    anexar_banca_ativa(orientandos)
    for projeto in orientandos:
        projeto.ata_ativa = projeto.atas.select_related("revisao").order_by("-gerada_em").first()
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


@login_required
def candidatura(request):
    """Tela do aluno para montar, acompanhar e cancelar sua candidatura de
    orientação (T11, spec §6: "/candidatura/ | aluno | montar, acompanhar e
    cancelar").

    Portão de PAPEL antes de tocar `perfil_aluno` — mesma cautela de
    `meus_temas`/`orientacoes`, acima, para não repetir o 500 de usuário com
    papel mas sem perfil correspondente (Fase 1, `apps/contas/views.py::perfil`).

    TRÊS TELAS NA MESMA ROTA (a terceira acrescentada na rodada de correção 1
    da T11 — achado real da revisão, não hipotético: ver a docstring de
    `services.criar_projeto_sob_limite`, `apps/projetos/services.py`, para o
    caminho completo do defeito que ela fecha). Nesta ordem de prioridade:

    1. Aluno já tem `Projeto` ATIVO (`EM_ANDAMENTO`, ou qualquer status que
       não seja `CONCLUIDO`/`REPROVADO`) em TCC_I: mostra a ORIENTAÇÃO
       VIGENTE (orientador, tema se houver) — nunca o formulário de montar.
       Checado ANTES da `Candidatura` `EM_CURSO` (item 2), de propósito: as
       duas checagens não são mutuamente exclusivas por construção — o
       defeito que esta rodada fecha é justamente um aluno que tinha as duas
       ao mesmo tempo (uma candidatura antiga, aceita, que virou este
       `Projeto`, e uma segunda candidatura, separada, ainda `EM_CURSO` sem
       que nada a tivesse impedido de existir). `registrar_candidatura`
       (T8) ganhou uma checagem amigável que fecha esse caminho para
       candidaturas NOVAS, mas não apaga uma `Candidatura` `EM_CURSO` que já
       existisse de antes da correção — priorizar o `Projeto` aqui garante
       que a tela nunca minta sobre o fato mais importante (o aluno já tem
       orientador), mesmo com dado desse jeito.
    2. Sem `Projeto` ativo, mas com `Candidatura` `EM_CURSO` (nunca mais de
       uma ao mesmo tempo — `Candidatura.Meta.constraints`,
       `apps/projetos/models.py`): mostra o ACOMPANHAMENTO (as até três
       opções, qual delas a cascata está processando agora — `opcao_atual`
       — e a justificativa de qualquer recusa já recebida) e o formulário de
       CANCELAR.
    3. Nem um nem outro (aluno nunca se candidatou, ou a candidatura anterior
       já terminou sem virar `Projeto` — `ESGOTADA`/`CANCELADA`): mostra o
       formulário de MONTAR uma candidatura nova.

    Os três verbos do spec ("montar, acompanhar e cancelar") descrevem os
    itens 3 e 2 — o item 1 não é lacuna do spec, é o mesmo `Importante` que
    esta rodada de correção fecha: mostrar "Escolha até três temas..." a
    quem já tem orientador seria a própria tela reabrindo o caminho que a
    revisão reproduziu.

    ESCOPO da escolha (ver a docstring de `FormularioCandidatura`,
    `apps/projetos/forms.py`): só `Tema`, nunca "professor sem tema
    específico" — decisão do controlador desta tarefa. `professor` é
    derivado de `tema.professor` ao montar `opcoes` para
    `services.registrar_candidatura` (T8); o caminho `tema=None` do serviço
    continua existindo, só não é alcançável por este formulário.
    """
    permissions.garante(
        permissions.pode_montar_candidatura(request.user),
        "Somente alunos montam candidatura de orientação.",
    )
    aluno = request.user.perfil_aluno

    projeto_atual = services.projeto_ativo_do_aluno(request.user, Projeto.TCC_I)
    if projeto_atual is not None:
        return render(request, "projetos/candidatura.html", {"projeto_atual": projeto_atual})

    candidatura_atual = (
        aluno.candidaturas.filter(status=Candidatura.EM_CURSO)
        .prefetch_related(
            Prefetch(
                "opcoes",
                queryset=OpcaoCandidatura.objects.select_related("professor__usuario", "tema"),
            )
        )
        .first()
    )

    if candidatura_atual is not None:
        return render(
            request, "projetos/candidatura.html", {"candidatura_atual": candidatura_atual}
        )

    if request.method == "POST":
        formulario = FormularioCandidatura(request.POST)
        if formulario.is_valid():
            opcoes = [
                (tema.professor, tema)
                for tema in (
                    formulario.cleaned_data["opcao_1"],
                    formulario.cleaned_data.get("opcao_2"),
                    formulario.cleaned_data.get("opcao_3"),
                )
                if tema is not None
            ]
            try:
                services.registrar_candidatura(aluno, opcoes)
            except ValidationError as erro:
                formulario.add_error(None, erro.messages[0])
            else:
                messages.success(request, "Candidatura registrada.")
                return redirect("projetos:candidatura")
    else:
        formulario = FormularioCandidatura()

    return render(
        request,
        "projetos/candidatura.html",
        {"formulario": formulario, "candidatura_atual": None},
    )


@login_required
@require_POST
def cancelar_candidatura_view(request, candidatura_id):
    """Cancela a candidatura em curso do aluno autenticado (T11).

    Portão de papel primeiro, depois lookup JÁ ESCOPADO ao aluno autenticado
    (`get_object_or_404(Candidatura, pk=..., aluno=...)`) — mesmo padrão de
    `desativar_tema`/`aceitar_opcao_view`, acima: candidatura alheia e
    candidatura inexistente respondem os DOIS com 404, sem abrir um oráculo
    de existência sobre candidaturas de outros alunos.
    `services.cancelar_candidatura` mantém sua própria checagem de posse
    (`por == candidatura.aluno.usuario`) — redundante aqui, mas protege
    qualquer outro chamador que não escope o lookup do mesmo jeito.
    """
    permissions.garante(
        permissions.pode_montar_candidatura(request.user),
        "Somente alunos montam candidatura de orientação.",
    )
    candidatura_obj = get_object_or_404(
        Candidatura, pk=candidatura_id, aluno=request.user.perfil_aluno
    )
    try:
        services.cancelar_candidatura(candidatura_obj, por=request.user)
    except ValidationError as erro:
        messages.error(request, erro.messages[0])
    else:
        messages.success(request, "Candidatura cancelada.")
    return redirect("projetos:candidatura")


@login_required
def meu_tcc(request):
    """Tela do aluno para enviar/reenviar a submissão do TCC I (Bloco C,
    spec §6).

    Portão de PAPEL antes de tocar `perfil_aluno` — reaproveita
    `pode_montar_candidatura` (T11, Bloco B): apesar do nome, ela responde
    exatamente "`usuario` é um aluno com perfil?", a mesma pergunta que esta
    tela precisa fazer antes de qualquer coisa (mesma cautela de
    `candidatura`/`orientacoes`, acima, contra o 500 de usuário com papel
    mas sem perfil — Fase 1, `apps/contas/views.py::perfil`).

    Sem `Projeto` ativo: estado vazio, sem formulário — não há para onde
    enviar. Com `Projeto` ativo: formulário de envio/reenvio
    (`FormularioSubmissao`), pré-carregando a `Submissao` atual se houver
    (`hasattr(projeto, "submissao")` — acesso reverso de `OneToOneField` que
    levanta `RelatedObjectDoesNotExist`, subclasse de `ObjectDoesNotExist`,
    para quem ainda não enviou nada; usar `hasattr` aqui, do lado do Python,
    em vez de depender do `silent_variable_failure` do template, porque o
    valor é usado em lógica de view, não só de exibição).
    """
    permissions.garante(
        permissions.pode_montar_candidatura(request.user),
        "Somente alunos acessam esta tela.",
    )
    projeto = services.projeto_ativo_do_aluno(
        request.user, Projeto.TCC_II
    ) or services.projeto_ativo_do_aluno(request.user, Projeto.TCC_I)
    if projeto is None:
        return render(request, "projetos/meu_tcc.html", {"projeto": None})

    submissao_atual = projeto.submissao if hasattr(projeto, "submissao") else None

    itens_correcao_pendentes = []
    pode_assinar = False
    ja_assinou = False
    if projeto.etapa == Projeto.TCC_II:
        itens_correcao_pendentes = projeto.itens_correcao.filter(concluido=False)
        ja_assinou = hasattr(projeto, "termo_publicacao")
        pode_assinar = projeto.status == Projeto.APROVADO_COM_RESSALVAS and not ja_assinou

    if request.method == "POST" and request.POST.get("acao") == "assinar_termo":
        services.assinar_termo_publicacao(projeto, por=request.user)
        messages.success(request, "Termo de publicação assinado.")
        return redirect("projetos:meu_tcc")

    if request.method == "POST":
        formulario = FormularioSubmissao(request.POST, request.FILES)
        if formulario.is_valid():
            services.enviar_submissao(
                projeto,
                por=request.user,
                pdf=formulario.cleaned_data["pdf"],
                editavel=formulario.cleaned_data["editavel"],
            )
            messages.success(request, "Submissão enviada com sucesso.")
            return redirect("projetos:meu_tcc")
    else:
        formulario = FormularioSubmissao()

    return render(
        request,
        "projetos/meu_tcc.html",
        {
            "projeto": projeto,
            "formulario": formulario,
            "submissao_atual": submissao_atual,
            "itens_correcao_pendentes": itens_correcao_pendentes,
            "pode_assinar": pode_assinar,
            "ja_assinou": ja_assinou,
        },
    )


@login_required
def painel_orientacoes(request):
    """Painel da coordenação para trocar orientador e ajustar limites de
    vaga (T12, spec §6: "/painel/orientacoes/ | coordenação | visão geral,
    troca de orientador, limites").

    Portão de PAPEL via `pode_ajustar_orientacao` — checagem direta de
    `is_coordenador`, um campo booleano de `Usuario`, não um perfil
    separado: ao contrário de `meus_temas`/`orientacoes`/`candidatura`
    (acima), não há `RelatedObjectDoesNotExist` a evitar aqui.

    A tela combina DUAS ações independentes (spec §6): trocar orientador
    (um `FormularioTrocarOrientador` POR projeto listado, cada POST
    endereçado à sua própria rota — `trocar_orientador_view`, abaixo) e
    conceder limite (um único `FormularioConcederLimite`, tratado aqui
    mesmo, no mesmo padrão de `apps/contas/views.py::painel`, que trata o
    formulário de convite na própria rota do painel e delega
    promover/revogar a rotas à parte).
    """
    permissions.garante(
        permissions.pode_ajustar_orientacao(request.user),
        "Esta área é exclusiva da coordenação.",
    )

    if request.method == "POST":
        formulario_limite = FormularioConcederLimite(request.POST)
        if formulario_limite.is_valid():
            try:
                services.conceder_limite(
                    professor=formulario_limite.cleaned_data["professor"],
                    etapa=formulario_limite.cleaned_data["etapa"],
                    limite=formulario_limite.cleaned_data["limite"],
                    justificativa=formulario_limite.cleaned_data["justificativa"],
                    por=request.user,
                )
            except ValidationError as erro:
                formulario_limite.add_error(None, erro.messages[0])
            else:
                messages.success(request, "Limite concedido.")
                return redirect("projetos:painel_orientacoes")
    else:
        formulario_limite = FormularioConcederLimite()

    projetos = Projeto.objects.select_related("aluno", "orientador", "tema").order_by(
        "orientador__nome_completo", "aluno__nome_completo"
    )
    itens_projeto = [
        {
            "projeto": projeto,
            "formulario_troca": FormularioTrocarOrientador(
                projeto=projeto, auto_id=f"id_troca_{projeto.pk}_%s"
            ),
        }
        for projeto in projetos
    ]
    limites = LimiteOrientacao.objects.select_related(
        "professor__usuario", "autorizado_por"
    ).order_by("-criado_em")

    return render(
        request,
        "projetos/painel_orientacoes.html",
        {
            "itens_projeto": itens_projeto,
            "limites": limites,
            "formulario_limite": formulario_limite,
            "limite_padrao": services.LIMITE_PADRAO_VAGAS,
        },
    )


@login_required
@require_POST
def trocar_orientador_view(request, projeto_id):
    """Troca o orientador do projeto indicado pelo formulário do painel da
    coordenação (T12).

    Portão de papel ANTES do lookup do projeto — mesmo motivo de
    `apps/contas/views.py::promover`/`revogar`: checar quem pede antes de
    buscar o alvo evita que a ordem das respostas (403 vs. 404) revele a
    existência de um projeto a quem não tem acesso a esta tela. Sem escopo
    no lookup (ao contrário de `desativar_tema`/`aceitar_opcao_view`,
    acima): a coordenação tem "visão geral" (spec §6) sobre TODO projeto,
    não só os de um professor ou aluno específico.
    """
    permissions.garante(
        permissions.pode_ajustar_orientacao(request.user),
        "Esta área é exclusiva da coordenação.",
    )
    projeto = get_object_or_404(Projeto, pk=projeto_id)
    formulario = FormularioTrocarOrientador(request.POST, projeto=projeto)
    if not formulario.is_valid():
        messages.error(request, "Selecione um novo orientador válido.")
        return redirect("projetos:painel_orientacoes")

    try:
        services.trocar_orientador(
            projeto, formulario.cleaned_data["novo_orientador"], por=request.user
        )
    except ValidationError as erro:
        messages.error(request, erro.messages[0])
    else:
        messages.success(request, "Orientador do projeto atualizado.")
    return redirect("projetos:painel_orientacoes")


@login_required
@require_POST
def revogar_limite_view(request, limite_id):
    """Revoga um limite elevado de vagas (T12). Mesmo padrão de portão de
    papel antes do lookup, sem escopo (visão geral da coordenação), de
    `trocar_orientador_view`, acima."""
    permissions.garante(
        permissions.pode_conceder_limite(request.user),
        "Esta área é exclusiva da coordenação.",
    )
    limite = get_object_or_404(LimiteOrientacao, pk=limite_id)
    services.revogar_limite(limite, por=request.user)
    messages.success(request, "Limite revogado.")
    return redirect("projetos:painel_orientacoes")


@login_required
@require_POST
def reabrir_projeto_view(request, projeto_id):
    """Reabre um `Projeto` `REPROVADO` — volta a `EM_ANDAMENTO` (Bloco D,
    spec §7). Lookup escopado ao orientador autenticado, mesmo padrão de
    `desativar_tema`: projeto alheio e inexistente respondem os dois com
    404."""
    projeto = get_object_or_404(Projeto, pk=projeto_id, orientador=request.user)
    services.reabrir_projeto(projeto, por=request.user)
    messages.success(request, "Projeto reaberto.")
    return redirect("projetos:orientacoes")


@login_required
@require_POST
def cancelar_projeto_view(request, projeto_id):
    """Cancela definitivamente um `Projeto` `REPROVADO` (Bloco D, spec §7).
    Mesmo padrão de lookup escopado de `reabrir_projeto_view`."""
    projeto = get_object_or_404(Projeto, pk=projeto_id, orientador=request.user)
    services.cancelar_projeto(projeto, por=request.user)
    messages.success(request, "Projeto cancelado.")
    return redirect("projetos:orientacoes")


@login_required
@require_POST
def aprovar_projeto_view(request, projeto_id):
    """Aprova um `Projeto` `Aprovado com Ressalvas` — gera a ata e notifica
    a SUGRAD (Bloco E, spec §7). Lookup escopado ao orientador autenticado,
    mesmo padrão de `desativar_tema`."""
    projeto = get_object_or_404(Projeto, pk=projeto_id, orientador=request.user)
    services.aprovar_projeto(projeto, por=request.user)
    messages.success(request, "Projeto aprovado. A ata foi gerada e enviada à SUGRAD.")
    return redirect("projetos:orientacoes")


@login_required
@require_POST
def reenviar_ata_view(request, ata_id):
    """Reenvia à SUGRAD uma ata devolvida (Bloco E, spec §7). Lookup
    escopado via `projeto__orientador`, mesmo raciocínio de
    `aprovar_projeto_view`."""
    from apps.documentos.models import Ata
    from apps.documentos.services import reenviar_a_sugrad

    ata = get_object_or_404(Ata, pk=ata_id, projeto__orientador=request.user)
    reenviar_a_sugrad(ata, por=request.user)
    messages.success(request, "Ata reenviada à SUGRAD.")
    return redirect("projetos:orientacoes")


@login_required
def criar_tcc_ii_manual_view(request):
    """Professor cria um TCC II manualmente (Bloco F, spec §7). Portão de
    PAPEL primeiro (`pode_criar_tema`, mesmo reaproveitamento de
    `orientacoes`/`meus_temas` — ela só pergunta "é professor?"), antes de
    tocar `perfil_professor`."""
    permissions.garante(
        permissions.pode_criar_tema(request.user), "Somente professores criam TCC II."
    )
    professor = request.user.perfil_professor

    if request.method == "POST":
        formulario = FormularioCriarTccII(request.POST)
        if formulario.is_valid():
            try:
                services.criar_tcc_ii_manual(
                    formulario.cleaned_data["aluno"], professor, por=request.user
                )
            except ValidationError as erro:
                formulario.add_error(None, erro.messages[0])
            else:
                messages.success(request, "TCC II criado.")
                return redirect("projetos:orientacoes")
    else:
        formulario = FormularioCriarTccII()

    return render(request, "projetos/criar_tcc_ii.html", {"formulario": formulario})
