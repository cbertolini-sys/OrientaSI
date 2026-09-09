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
    formulario = Formulario(request.POST or None, request.FILES or None)

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
    """Tela em que a pessoa autenticada mantém os próprios dados. Quem tem
    `PerfilProfessor` recebe também o campo de áreas de atuação; quem não
    tem, não.

    A condição é a **existência do perfil** (`hasattr`), não o `papel`: o
    papel padrão de `Usuario.objects.create_user`/`create_superuser` é
    `PROFESSOR` (`apps/contas/models.py::GerenciadorUsuario`), mas nada cria
    `PerfilProfessor` automaticamente — nem o `createsuperuser` que o
    `CLAUDE.md` manda rodar, nem a conta da coordenação (que a Tarefa 11 vai
    autenticar). Usar `request.user.papel == Usuario.PROFESSOR` como
    condição, como o brief sugeria, levava a `RelatedObjectDoesNotExist` (500)
    ao tentar ler `request.user.perfil_professor.areas` de quem tem o papel
    mas não o perfil.
    """
    tem_perfil_professor = hasattr(request.user, "perfil_professor")
    Formulario = FormularioPerfilProfessor if tem_perfil_professor else FormularioPerfil

    if request.method == "POST":
        formulario = Formulario(request.POST, request.FILES)
        if formulario.is_valid():
            services.atualiza_perfil(
                request.user,
                telefone=formulario.cleaned_data["telefone"],
                areas=formulario.cleaned_data.get("areas"),
                foto=formulario.cleaned_data.get("foto"),
            )
            messages.success(request, "Perfil atualizado.")
            return redirect("contas:perfil")
    else:
        inicial = {"telefone": request.user.telefone}
        if tem_perfil_professor:
            inicial["areas"] = request.user.perfil_professor.areas.all()
        formulario = Formulario(initial=inicial)

    return render(request, "contas/perfil.html", {"formulario": formulario})


@login_required
def painel(request):
    """Painel da coordenação: envio de convites e a interface das duas regras
    inegociáveis do projeto (CLAUDE.md), promover e revogar — ver `promover`
    e `revogar` abaixo. Toda regra de negócio (teto de coordenadores, trava
    do último coordenador, validação de convite) vive em `services`; esta
    view só orquestra formulário, chamada ao serviço e mensagem de
    resultado.
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

    return render(
        request,
        "contas/painel_coordenacao.html",
        {
            "formulario": formulario,
            "convites": Convite.objects.select_related("criado_por")[:50],
            "coordenadores": Usuario.objects.filter(is_coordenador=True, is_active=True),
            # `Usuario.Meta.ordering = ["nome_completo"]` já ordena; sem
            # order_by explícito aqui de propósito, para não duplicar o que
            # o model já garante. `is_active=True` (achado da revisão 1):
            # sem ele, um professor desativado apareceria como promovível
            # (ou, na lista de cima, como coordenador ainda ativo).
            "candidatos_promocao": Usuario.objects.filter(
                papel=Usuario.PROFESSOR, is_coordenador=False, is_active=True
            )[:50],
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
