from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from apps.contas import permissions, services
from apps.contas.forms import (
    FormularioAlunoConvidado,
    FormularioConvite,
    FormularioPerfil,
    FormularioPerfilAluno,
    FormularioPerfilProfessor,
    FormularioProfessorConvidado,
)
from apps.contas.models import Convite, Usuario


def aceitar_convite(request, token):
    """Tela em que a pessoa convidada preenche seus dados e cria a conta."""
    try:
        convite = services.busca_convite_valido(token)
    except ValidationError as erro:
        return render(
            request,
            "contas/convite_invalido.html",
            {"mensagem": erro.messages[0]},
            status=404,
        )

    Formulario = (
        FormularioAlunoConvidado if convite.papel == Usuario.ALUNO else FormularioProfessorConvidado
    )
    # `email=convite.email` alimenta a validação de similaridade de senha do
    # formulário (`FormularioConvidado.clean`), que compara a senha escolhida
    # com os dados da pessoa.
    formulario = Formulario(request.POST or None, request.FILES or None, email=convite.email)

    if request.method == "POST" and formulario.is_valid():
        try:
            usuario = services.aceitar_convite(token, formulario.cleaned_data)
        except ValidationError as erro:
            formulario.add_error(None, erro.messages[0])
        else:
            login(request, usuario)
            messages.success(request, "Cadastro concluído. Bem-vindo(a) ao OrientaSI.")
            return redirect("inicio")

    return render(
        request,
        "contas/aceitar_convite.html",
        {"formulario": formulario, "convite": convite},
    )


@login_required
def perfil(request):
    """Tela em que a pessoa autenticada mantém os próprios dados — nome,
    e-mail, CPF, telefone e foto pra qualquer papel, mais o campo exclusivo
    de quem tem `PerfilProfessor` (SIAPE + áreas de atuação) ou
    `PerfilAluno` (matrícula). Pedido explícito do usuário: "editar todos os
    campos quando entro como professor ou coordenador ou aluno" —
    coordenador não tem perfil próprio, é um `PerfilProfessor` com
    `is_coordenador=True`, então cai no mesmo ramo de professor.

    A condição é a **existência do perfil** (`hasattr`), não o `papel`: o
    papel padrão de `Usuario.objects.create_user`/`create_superuser` é
    `PROFESSOR` (`apps/contas/models.py::GerenciadorUsuario`), mas nada cria
    `PerfilProfessor` automaticamente — nem o `createsuperuser` que o
    `CLAUDE.md` manda rodar, nem a conta da coordenação (que a Tarefa 11 vai
    autenticar). Usar `request.user.papel == Usuario.PROFESSOR` como
    condição, como o brief sugeria, levava a `RelatedObjectDoesNotExist` (500)
    ao tentar ler `request.user.perfil_professor.areas` de quem tem o papel
    mas não o perfil. Quem não tem nenhum dos dois perfis (a conta da
    SUGRAD, ou um professor sem `PerfilProfessor`) cai no formulário base,
    `FormularioPerfil` — sem matrícula nem SIAPE, mas com nome/e-mail/CPF
    (CPF opcional pra SUGRAD, ver `FormularioPerfil.clean_cpf`).
    """
    tem_perfil_professor = hasattr(request.user, "perfil_professor")
    tem_perfil_aluno = hasattr(request.user, "perfil_aluno")
    if tem_perfil_professor:
        Formulario = FormularioPerfilProfessor
    elif tem_perfil_aluno:
        Formulario = FormularioPerfilAluno
    else:
        Formulario = FormularioPerfil

    if request.method == "POST":
        formulario = Formulario(request.POST, request.FILES, usuario=request.user)
        if formulario.is_valid():
            # `try/except` (achado M6 da auditoria, 2026-09-22): duas
            # gravações concorrentes do mesmo CPF/e-mail/matrícula/SIAPE
            # passam as duas pelo `clean_*` do formulário e só colidem no
            # `UniqueConstraint` do banco — sem isto, a segunda estourava
            # um `IntegrityError` cru (500) em vez de um erro de formulário.
            try:
                services.atualiza_perfil(
                    request.user,
                    nome_completo=formulario.cleaned_data["nome_completo"],
                    email=formulario.cleaned_data["email"],
                    cpf=formulario.cleaned_data["cpf"],
                    telefone=formulario.cleaned_data["telefone"],
                    areas=formulario.cleaned_data.get("areas"),
                    foto=formulario.cleaned_data.get("foto"),
                    matricula=formulario.cleaned_data.get("matricula"),
                    siape=formulario.cleaned_data.get("siape"),
                )
            except ValidationError as erro:
                formulario.add_error(None, erro.messages[0])
            else:
                messages.success(request, "Perfil atualizado.")
                return redirect("contas:perfil")
    else:
        inicial = {
            "nome_completo": request.user.nome_completo,
            "email": request.user.email,
            "cpf": request.user.cpf,
            "telefone": request.user.telefone,
        }
        if tem_perfil_professor:
            inicial["areas"] = request.user.perfil_professor.areas.all()
            inicial["siape"] = request.user.perfil_professor.siape
        elif tem_perfil_aluno:
            inicial["matricula"] = request.user.perfil_aluno.matricula
        formulario = Formulario(initial=inicial, usuario=request.user)

    contexto = {"formulario": formulario}
    if tem_perfil_professor:
        # O `<select multiple>`/`CheckboxSelectMultiple` genérico de
        # `formulario.areas` some do template (templates/contas/perfil.html
        # renderiza a árvore área/subárea "na mão", agrupada por
        # `services.areas_agrupadas_por_area` — pedido explícito do usuário
        # de manter a ordem da lista do CNPq/CAPES e deixar só as 16
        # subáreas marcáveis, com as 4 áreas como cabeçalho de agrupamento).
        # `campo.value()` devolve pks como `int` (a partir de `initial`, uma
        # queryset de `Area`) OU como `str` (a partir de `request.POST`, um
        # formulário inválido que volta pra tela) — normalizar os dois pra
        # `int` aqui é o que permite ao template comparar com `subarea.pk`
        # direto, sem depender de tipo.
        valor_areas = formulario["areas"].value() or []
        contexto["areas_selecionadas"] = {
            int(v.pk if hasattr(v, "pk") else v) for v in valor_areas
        }
        contexto["areas_agrupadas"] = services.areas_agrupadas_por_area()

    return render(request, "contas/perfil.html", contexto)


@login_required
def painel(request):
    """Painel da coordenação: envio de convites e a interface das duas regras
    inegociáveis do projeto (CLAUDE.md), promover e revogar — ver `promover`
    e `revogar` abaixo. Toda regra de negócio (teto de coordenadores, trava
    do último coordenador, validação de convite) vive em `services`; esta
    view só orquestra formulário, chamada ao serviço e mensagem de
    resultado.

    Layout em duas colunas (pedido explícito do usuário, refatoração
    posterior): à esquerda, "Professores" (dobra as antigas seções
    "Coordenadores"/"Promover a coordenador(a)" numa lista só — cada linha
    decide sozinha, por `is_coordenador`, se oferece "Revogar" ou
    "Promover"), "Alunos" (quem ainda não concluiu o TCC II) e "Convites
    enviados"; à direita, "Convidar". `candidatos_promocao_ids` continua
    vindo de `services.candidatos_a_coordenacao()` — só ele decide se o
    botão "Promover" aparece numa linha de não-coordenador, pra não oferecer
    uma ação fadada à recusa do serviço (professor inativo, por exemplo) —
    mesmo raciocínio de `services.reenviar_convite`/"Reenviar convite" não
    aparecer pra um convite já usado.
    """
    permissions.garante(
        permissions.pode_convidar(request.user), "Esta área é exclusiva da coordenação."
    )

    formulario = FormularioConvite(request.POST or None)
    if request.method == "POST" and formulario.is_valid():
        try:
            services.convidar(
                formulario.cleaned_data["email"],
                formulario.cleaned_data["papel"],
                por=request.user,
            )
        except ValidationError as erro:
            formulario.add_error("email", erro.messages[0])
        else:
            messages.success(request, "Convite enviado.")
            return redirect("contas:painel")

    coordenadores = services.coordenadores()
    return render(
        request,
        "contas/painel_coordenacao.html",
        {
            "formulario": formulario,
            "convites": services.convites_recentes(),
            # As listas vêm do SERVIÇO, não de um filtro escrito aqui
            # (achado da revisão final): quem conta como coordenador e quem
            # pode ser promovido é regra de negócio (CLAUDE.md, regra 4), e
            # enquanto a view tinha a sua própria versão do filtro, a tela
            # anunciava "Coordenadores (3 de 4)" e o serviço recusava a
            # promoção pelo teto de 4. Mesma origem, mesma contagem.
            # `Usuario.Meta.ordering = ["nome_completo"]` já ordena; sem
            # order_by explícito aqui de propósito, para não duplicar o que
            # o model já garante.
            "professores": services.professores_para_painel(),
            "candidatos_promocao_ids": set(
                services.candidatos_a_coordenacao().values_list("pk", flat=True)
            ),
            "total_coordenadores": coordenadores.count(),
            "alunos": services.alunos_sem_tcc_ii_concluido(),
            "limite": services.LIMITE_COORDENADORES,
        },
    )


def _usuario_do_post(request):
    """Converte `usuario_id` do POST num `Usuario`, ou levanta 404.

    Guarda de tipo, não regra de negócio: `Usuario.pk` é inteiro, e um
    `usuario_id` não numérico (formulário adulterado) faria
    `get_object_or_404` propagar um `ValueError` cru (500) em vez de um 404
    — o `get_object_or_404` do Django só converte `DoesNotExist` em
    `Http404`, não `ValueError`.
    """
    usuario_id = request.POST.get("usuario_id", "")
    if not usuario_id.isdigit():
        raise Http404("Usuário inválido.")
    return get_object_or_404(Usuario, pk=usuario_id)


def _convite_do_post(request):
    """Converte `convite_id` do POST num `Convite`, ou levanta 404. Mesma
    guarda de tipo de `_usuario_do_post`, pelo mesmo motivo."""
    convite_id = request.POST.get("convite_id", "")
    if not convite_id.isdigit():
        raise Http404("Convite inválido.")
    return get_object_or_404(Convite, pk=convite_id)


@login_required
@require_POST
def reenviar(request):
    """Reenvia o convite indicado pela lista de convites do painel.

    A porta que faltava (achado da revisão final): `services.reenviar_convite`
    existia desde a T7, com quatro testes, e nenhuma URL, view ou botão o
    alcançava. O beco sem saída era real — `convidar` enfileira o e-mail em
    `transaction.on_commit`, então um broker fora do ar deixa o convite
    GRAVADO e o e-mail nunca enviado; tentar de novo esbarra em "Já existe um
    convite ativo para X. Reenvie-o, se preciso.", e o painel listava o
    convite como "Pendente" sem oferecer reenvio nenhum. Sem shell, a saída
    era esperar sete dias até a expiração.

    Mesma ordem de `promover`/`revogar`: permissão conferida ANTES do lookup
    do alvo, para que a resposta não distinga um `convite_id` existente de um
    inexistente para quem não tem permissão.
    """
    permissions.garante(permissions.pode_convidar(request.user), services.MSG_SOMENTE_COORDENACAO)
    convite = _convite_do_post(request)
    try:
        services.reenviar_convite(convite, por=request.user)
    except ValidationError as erro:
        messages.error(request, erro.messages[0])
    else:
        messages.success(request, f"Convite reenviado para {convite.email}.")
    return redirect("contas:painel")


@login_required
@require_POST
def promover(request):
    """Promove a coordenador(a) o usuário indicado pelo formulário de
    confirmação do painel. `services.promover_a_coordenador` aplica o teto
    de `LIMITE_COORDENADORES` coordenadores — aqui só convertemos o
    resultado em mensagem visível na tela, a "mensagem clara" que os
    critérios de aceitação exigem para a quinta promoção recusada.

    A permissão é conferida AQUI, antes de `_usuario_do_post` buscar o alvo
    — não só dentro do serviço (achado da revisão 1). Buscar o alvo antes
    de checar quem está pedindo deixaria um professor comum distinguir um
    `usuario_id` existente (403, depois da checagem do serviço) de um
    inexistente (404, do próprio lookup): a ordem das duas respostas
    permitiria enumerar contas por tentativa. Isto é portão de acesso, não
    regra de negócio vazando para a view — o mesmo papel que `painel` já
    cumpre para a página inteira; o teto e a trava continuam só no
    serviço.
    """
    permissions.garante(permissions.pode_promover(request.user), "Somente a coordenação promove.")
    alvo = _usuario_do_post(request)
    try:
        services.promover_a_coordenador(alvo, por=request.user)
    except ValidationError as erro:
        messages.error(request, erro.messages[0])
    else:
        messages.success(request, f"{alvo.nome_completo} agora é coordenador(a).")
    return redirect("contas:painel")


@login_required
@require_POST
def revogar(request):
    """Revoga a coordenação do usuário indicado pelo formulário de
    confirmação do painel. `services.revogar_coordenacao` recusa deixar o
    sistema sem nenhum coordenador — aqui só convertemos essa recusa em
    mensagem visível, a "mensagem clara" que os critérios de aceitação
    exigem para a revogação do último coordenador.

    Mesmo motivo de `promover` para checar a permissão antes do lookup do
    alvo: sem isso, a ordem 404/403 permitiria enumerar contas.
    """
    permissions.garante(permissions.pode_promover(request.user), "Somente a coordenação revoga.")
    alvo = _usuario_do_post(request)
    try:
        services.revogar_coordenacao(alvo, por=request.user)
    except ValidationError as erro:
        messages.error(request, erro.messages[0])
    else:
        messages.success(request, f"A coordenação de {alvo.nome_completo} foi revogada.")
    return redirect("contas:painel")
