import hashlib
import secrets

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.contas import permissions
from apps.contas.models import Convite, Usuario

MSG_SOMENTE_COORDENACAO = "Somente a coordenação envia convites."
MENSAGEM_CONVITE_INVALIDO = "Convite inválido, expirado ou já utilizado."

# Teto de coordenadores do sistema (CLAUDE.md, "Regras de Negócio
# Inegociáveis" item 2). Vive aqui, não em `Usuario`, porque é regra de
# negócio, não invariante de dado — a constraint do model
# (`coordenador_e_professor`, em `models.py`) cobre "todo coordenador é
# professor"; a contagem máxima é comportamento de serviço.
LIMITE_COORDENADORES = 4


def _hash(token):
    return hashlib.sha256(token.encode()).hexdigest()


@transaction.atomic
def convidar(email, papel, por):
    """Cria o convite e enfileira o e-mail. O token em claro só existe no e-mail."""
    permissions.garante(permissions.pode_convidar(por), MSG_SOMENTE_COORDENACAO)

    if papel not in dict(Convite.PAPEIS_CONVIDAVEIS):
        # SUGRAD fica de fora de propósito: a conta do setor é semeada pelo
        # comando `semear_sistema`, nunca convidada (spec §5.5/§5.1).
        raise ValidationError(f"Não é possível convidar alguém como {papel}.")

    email = email.strip().lower()
    if Usuario.objects.filter(email__iexact=email).exists():
        raise ValidationError(f"Já existe uma conta para {email}.")
    convite_ativo = Convite.objects.filter(
        email__iexact=email, usado_em__isnull=True, expira_em__gt=timezone.now()
    ).exists()
    if convite_ativo:
        raise ValidationError(f"Já existe um convite ativo para {email}. Reenvie-o, se preciso.")

    token = secrets.token_urlsafe(32)
    convite = Convite.objects.create(
        email=email,
        papel=papel,
        token_hash=_hash(token),
        criado_por=por,
        expira_em=timezone.now() + timezone.timedelta(days=settings.CONVITE_VALIDADE_DIAS),
    )

    from apps.contas.tasks import enviar_convite

    transaction.on_commit(lambda: enviar_convite.delay(convite.id, token))
    return convite


@transaction.atomic
def reenviar_convite(convite, por):
    """Invalida o convite anterior e emite outro: um link por vez, sempre."""
    permissions.garante(permissions.pode_convidar(por), MSG_SOMENTE_COORDENACAO)
    if convite.usado_em is not None:
        raise ValidationError("Este convite já foi utilizado.")

    # Expira o convite anterior em vez de marcá-lo como usado: usado_em
    # significa "alguém aceitou" (a Tarefa 8 o grava junto com
    # usuario_criado), e este convite não foi aceito, foi substituído.
    # esta_valido() já devolve False para um convite expirado, então isto
    # basta para aposentá-lo sem sujar um campo que outras telas vão ler.
    convite.expira_em = timezone.now()
    convite.save(update_fields=["expira_em"])
    return convidar(convite.email, convite.papel, por=por)


def busca_convite_valido(token, para_atualizacao=False):
    """Devolve o convite válido ou levanta a mensagem genérica.

    Token inexistente, expirado e já usado produzem a MESMA mensagem: distingui-los
    entregaria ao solicitante informação que ele não precisa ter (spec §6.2).

    `para_atualizacao=True` bloqueia a linha com `SELECT ... FOR UPDATE`, para que
    dois aceites simultâneos do mesmo token não passem ambos pela validação antes
    que o primeiro grave `usado_em` — só faz sentido dentro de uma transação
    (`aceitar_convite` é quem passa True; a view, ao só exibir o formulário,
    chama sem argumento extra e fora de qualquer transação).
    """
    consulta = Convite.objects.filter(token_hash=_hash(token))
    if para_atualizacao:
        consulta = consulta.select_for_update()
    convite = consulta.first()
    if convite is None or not convite.esta_valido():
        raise ValidationError(MENSAGEM_CONVITE_INVALIDO)
    return convite


@transaction.atomic
def _aceitar_convite_atomico(token, dados):
    from apps.contas.models import PerfilAluno, PerfilProfessor

    convite = busca_convite_valido(token, para_atualizacao=True)

    usuario = Usuario.objects.create_user(
        email=convite.email,
        password=dados["senha"],
        nome_completo=dados["nome_completo"],
        cpf=dados["cpf"],
        telefone=dados.get("telefone", ""),
        papel=convite.papel,
    )
    if dados.get("foto"):
        usuario.foto = dados["foto"]
        usuario.save(update_fields=["foto"])

    if convite.papel == Usuario.ALUNO:
        PerfilAluno.objects.create(usuario=usuario, matricula=dados["matricula"])
    else:
        PerfilProfessor.objects.create(usuario=usuario, siape=dados["siape"])

    convite.usado_em = timezone.now()
    convite.usuario_criado = usuario
    convite.save(update_fields=["usado_em", "usuario_criado"])
    return usuario


@transaction.atomic
def atualiza_perfil(usuario, telefone, areas=None, foto=None):
    """Atualiza os dados que a própria pessoa mantém sobre si.

    `areas` só é aplicado a quem **tem** `PerfilProfessor` — a checagem é
    `hasattr(usuario, "perfil_professor")`, não `usuario.papel ==
    Usuario.PROFESSOR`: o papel `PROFESSOR` é o padrão de
    `Usuario.objects.create_user`/`create_superuser`
    (`GerenciadorUsuario`), mas nada cria `PerfilProfessor` automaticamente,
    e `usuario.perfil_professor` levanta `RelatedObjectDoesNotExist` para
    quem tem o papel mas não o perfil (o superusuário criado por
    `createsuperuser`, por exemplo). Passar `areas` para quem não tem
    `PerfilProfessor` é silenciosamente ignorado, não é um erro: a view só
    envia `areas` a quem `FormularioPerfilProfessor` atende, e essa escolha
    de formulário já usa a mesma condição de `hasattr`.
    """
    usuario.telefone = telefone
    campos = ["telefone"]
    if foto:
        usuario.foto = foto
        campos.append("foto")
    usuario.save(update_fields=campos)

    if areas is not None and hasattr(usuario, "perfil_professor"):
        usuario.perfil_professor.areas.set(areas)
    return usuario


def aceitar_convite(token, dados):
    """Cria o Usuario e o perfil correspondente a partir de um convite válido.

    A criação de fato roda em `_aceitar_convite_atomico`, atômica de propósito:
    se a criação do perfil falhar (matrícula ou SIAPE duplicados, por exemplo), a
    transação desfaz também o Usuario recém-criado — nunca pode sobrar uma conta
    sem perfil.

    Esta função por fora não é atômica: ela só existe para converter o
    `IntegrityError` que escapar dali (rede de segurança contra corrida — o
    formulário já valida unicidade de CPF/matrícula/SIAPE antes de chegar aqui,
    mas duas requisições simultâneas podem empatar na checagem e colidir só no
    banco) numa `ValidationError`, a mesma exceção que a view já sabe exibir como
    erro de formulário em vez de deixar um IntegrityError não tratado virar 500.
    """
    try:
        return _aceitar_convite_atomico(token, dados)
    except IntegrityError as erro:
        raise ValidationError(
            "Não foi possível concluir o cadastro: um dos dados informados "
            "(CPF, matrícula ou SIAPE) já está em uso."
        ) from erro


@transaction.atomic
def promover_a_coordenador(usuario, por):
    """Promove `usuario` a coordenador(a), sob o teto de `LIMITE_COORDENADORES`.

    O `select_for_update` não é decoração: promover é um UPDATE de uma linha que
    passa a integrar o próprio conjunto travado (`is_coordenador=True`), então duas
    promoções simultâneas se serializam — a segunda só prossegue depois que a
    primeira grava, e relê a contagem já atualizada. Sem o bloqueio, duas
    requisições concorrentes poderiam ler "3 coordenadores" ao mesmo tempo e as
    duas promoverem, ultrapassando o teto.
    """
    permissions.garante(permissions.pode_promover(por), "Somente a coordenação promove.")

    if usuario.papel != Usuario.PROFESSOR:
        raise ValidationError("Somente professores podem ser coordenadores.")
    if usuario.is_coordenador:
        raise ValidationError(f"{usuario.nome_completo} já é coordenador(a).")

    atuais = list(Usuario.objects.select_for_update().filter(is_coordenador=True))
    if len(atuais) >= LIMITE_COORDENADORES:
        raise ValidationError(
            f"O sistema admite no máximo {LIMITE_COORDENADORES} coordenadores. "
            "Revogue a coordenação de alguém antes de nomear outra pessoa."
        )

    usuario.is_coordenador = True
    usuario.is_staff = True
    usuario.save(update_fields=["is_coordenador", "is_staff"])
    return usuario


@transaction.atomic
def revogar_coordenacao(usuario, por):
    """Revoga a coordenação de `usuario`, recusando deixar o sistema sem
    nenhum coordenador.

    Mesmo raciocínio de `select_for_update` que `promover_a_coordenador`: a
    contagem de coordenadores travada evita que duas revogações simultâneas
    (por exemplo, duas pessoas revogando coordenadores diferentes ao mesmo
    tempo, quando restam só dois) derrubem o sistema a zero coordenadores.
    """
    permissions.garante(permissions.pode_promover(por), "Somente a coordenação revoga.")

    if not usuario.is_coordenador:
        raise ValidationError(f"{usuario.nome_completo} não é coordenador(a).")

    atuais = list(Usuario.objects.select_for_update().filter(is_coordenador=True))
    if len(atuais) <= 1:
        raise ValidationError(
            "Este é o último coordenador do sistema. Nomeie outro antes de revogar "
            "esta coordenação."
        )

    usuario.is_coordenador = False
    usuario.is_staff = False
    usuario.save(update_fields=["is_coordenador", "is_staff"])
    return usuario
