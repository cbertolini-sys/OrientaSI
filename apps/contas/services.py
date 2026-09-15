import hashlib
import secrets

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.db.models import Prefetch
from django.utils import timezone

from apps.contas import permissions
from apps.contas.models import Area, Convite, Usuario

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


def coordenadores():
    """Origem ÚNICA de quem conta como coordenador(a) do sistema.

    **Decisão (revisão final): um coordenador desativado OCUPA vaga.** O teto
    de 4 (CLAUDE.md, regra inegociável nº 2) existe para limitar quem detém o
    poder de coordenação, e uma conta desativada pode ser reativada no admin a
    qualquer momento — se ela não ocupasse vaga, reativar a quinta pessoa
    furaria o teto sem passar por `promover_a_coordenador`.

    Esta função existe porque a tela e a regra discordavam (achado da revisão
    final): a view filtrava `is_active=True` para montar a lista, enquanto
    `promover_a_coordenador`/`revogar_coordenacao` contavam TODO
    `is_coordenador=True`. Com quatro coordenadores e um desativado, o painel
    anunciava "Coordenadores (3 de 4)", oferecia promoções, e o serviço as
    recusava com "O sistema admite no máximo 4 coordenadores".

    Consequência de projeto que vem junto: o painel PRECISA listar o
    coordenador inativo (marcado como tal, ver
    templates/contas/painel_coordenacao.html). Sem isso, a vaga que ele ocupa
    ficaria invisível e não haveria como liberá-la pela tela — o sistema
    travaria no teto sem saída, e a única saída seria o admin.
    """
    return Usuario.objects.filter(is_coordenador=True)


def professores_para_painel():
    """Todos os professores com `PerfilProfessor`, para a coluna
    "Professores" do painel da coordenação (pedido explícito do usuário,
    refatoração do painel em duas colunas) — dobra as antigas seções
    "Coordenadores"/"Promover a coordenador(a)" numa lista só: cada linha
    carrega `is_coordenador` (campo do próprio `Usuario`), e o template
    decide ali mesmo se mostra "Promover" ou "Revogar" — as duas ações
    continuam batendo nos mesmos `promover`/`revogar` (`views.py`) e na
    mesma trava de `LIMITE_COORDENADORES` (`promover_a_coordenador`,
    abaixo), só a apresentação mudou.

    `papel=PROFESSOR` sozinho, mesmo filtro de `candidatos_a_coordenacao()`
    logo abaixo — não exige `PerfilProfessor` existir: nem toda conta
    `papel=PROFESSOR` tem um (um superusuário criado por `createsuperuser`,
    por exemplo, ou a semeadura inicial do sistema), e a linha da tela usa
    só nome/e-mail/`is_coordenador`/`is_active`, nada que dependa do
    perfil. Não filtra por `is_active`, mesmo motivo de `coordenadores()`
    acima: uma conta desativada continua aparecendo, porque senão a
    coordenação não teria como vê-la ou agir sobre ela pela tela."""
    return Usuario.objects.filter(papel=Usuario.PROFESSOR)


def alunos_sem_tcc_ii_concluido():
    """Alunos que ainda não concluíram o TCC II, para a coluna "Alunos" do
    painel da coordenação (pedido explícito do usuário: "uma vez o aluno
    concluído o TCC II ele sai dessa lista"). "Concluído" é o status EXATO
    `Projeto.CONCLUIDO` do TCC_II — um TCC_II `Em Andamento`, `Reprovado` ou
    `Cancelado` mantém o aluno na lista, porque ele continua sem ter
    terminado o curso; um aluno sem nenhum TCC_II ainda (nem começou o TCC
    I) também continua na lista, pelo mesmo motivo.

    Import de `Projeto` LOCAL, não no topo do arquivo: `contas` é a app
    fundação do projeto (CLAUDE.md — "todo projeto já dependerá de
    contas"), então um import de módulo em `apps.projetos` no topo deste
    arquivo inverteria essa direção de dependência. Mesmo raciocínio do
    import local de `apps.contas.tasks` em `convidar`, acima — só que ali
    era pra adiar um import pesado (Celery), aqui é pra não apontar essa
    app fundação para uma app que depende dela."""
    from apps.projetos.models import Projeto

    concluiram_tcc_ii = Projeto.objects.filter(
        etapa=Projeto.TCC_II, status=Projeto.CONCLUIDO
    ).values("aluno_id")
    return (
        Usuario.objects.filter(papel=Usuario.ALUNO)
        .exclude(pk__in=concluiram_tcc_ii)
        .select_related("perfil_aluno")
    )


def areas_agrupadas_por_area():
    """As 4 ÁREAS do CNPq/CAPES, cada uma com suas SUBÁREAS já pré-carregadas,
    na ordem de exibição (`Area.ordem`) — usado pelo formulário de perfil do
    professor (`templates/contas/perfil.html`) pra mostrar a Tabela de Áreas
    do Conhecimento com a hierarquia visível e na ordem exata da lista
    original (área, depois suas subáreas, depois a próxima área), não a
    ordem alfabética que `ModelMultipleChoiceField.queryset` sozinho
    produziria.

    Devolve as áreas de topo (`area=None`) com as subáreas de cada uma já
    pré-carregadas (`related_name="subareas"`, ver `Area.area` em
    `models.py`). Uma área futura criada pela coordenação via `/admin/` sem
    área-pai vira seu próprio grupo, sem subárea abaixo — ainda aparece,
    mesmo sem ser marcável (só as subáreas são, ver `FormularioPerfilProfessor.areas`).
    """
    subareas = Area.objects.order_by("ordem", "nome")
    return (
        Area.objects.filter(area__isnull=True)
        .order_by("ordem", "nome")
        .prefetch_related(Prefetch("subareas", queryset=subareas))
    )


def candidatos_a_coordenacao():
    """Professores que podem ser promovidos hoje — o complemento exato do que
    `promover_a_coordenador` aceita como alvo.

    A filtragem por `is_active` é regra de negócio (quem pode receber o poder
    de coordenação) e por isso mora aqui, não em `views.py` (CLAUDE.md, regra
    4). Antes desta extração, a view filtrava por conta própria e o serviço
    não recusava alvo inativo: bastava postar o `usuario_id` de um professor
    desativado para promovê-lo.
    """
    return Usuario.objects.filter(papel=Usuario.PROFESSOR, is_coordenador=False, is_active=True)


@transaction.atomic
def convidar(email, papel, por):
    """Cria o convite e enfileira o e-mail. O token em claro só existe no e-mail."""
    permissions.garante(permissions.pode_convidar(por), MSG_SOMENTE_COORDENACAO)

    if papel not in dict(Convite.PAPEIS_CONVIDAVEIS):
        # SUGRAD fica de fora de propósito: a conta do setor é semeada pelo
        # comando `semear_sistema`, nunca convidada (spec §5.5/§5.1).
        raise ValidationError(f"Não é possível convidar alguém como {papel}.")

    # Igualdade exata, e não `__iexact` (revisão final): o e-mail já foi
    # normalizado para minúsculas na linha logo abaixo, `Convite.email` só é gravado
    # por esta função (sempre minúsculo) e `Usuario.email` é minusculizado
    # pelo sinal `normaliza_email_do_usuario` em QUALQUER caminho de escrita.
    # `__iexact` vira `UPPER("email") = UPPER(%s)` no Postgres, que não usa o
    # índice B-tree de `Convite.email` — com igualdade exata, o índice serve.
    email = email.strip().lower()
    if Usuario.objects.filter(email=email).exists():
        raise ValidationError(f"Já existe uma conta para {email}.")
    convite_ativo = Convite.objects.filter(
        email=email, usado_em__isnull=True, expira_em__gt=timezone.now()
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
def atualiza_perfil(
    usuario,
    *,
    nome_completo,
    email,
    cpf,
    telefone,
    areas=None,
    foto=None,
    matricula=None,
    siape=None,
):
    """Atualiza os dados que a própria pessoa mantém sobre si — identidade
    (nome/e-mail/CPF) e contato para qualquer papel, mais o campo exclusivo
    de quem tem `PerfilAluno` (matrícula) ou `PerfilProfessor` (SIAPE +
    áreas de atuação). Pedido explícito do usuário: "editar todos os campos
    quando entro como professor ou coordenador ou aluno" — coordenador não
    tem perfil próprio, é um `PerfilProfessor` com `is_coordenador=True`,
    então cai no mesmo ramo de professor.

    `matricula`/`areas`/`siape` só são aplicados a quem **tem** o perfil
    correspondente — a checagem é `hasattr(usuario, "perfil_aluno"/
    "perfil_professor")`, não `usuario.papel`: o papel padrão de
    `Usuario.objects.create_user`/`create_superuser` é `PROFESSOR`
    (`GerenciadorUsuario`), mas nada cria `PerfilProfessor` automaticamente,
    e `usuario.perfil_professor` levanta `RelatedObjectDoesNotExist` para
    quem tem o papel mas não o perfil (o superusuário criado por
    `createsuperuser`, por exemplo). Passar um desses pra quem não tem o
    perfil correspondente é silenciosamente ignorado, não é um erro: a view
    só envia cada um a quem o formulário certo (`FormularioPerfilAluno`/
    `FormularioPerfilProfessor`) atende, e essa escolha de formulário já usa
    a mesma condição de `hasattr`.
    """
    usuario.nome_completo = nome_completo
    usuario.email = email
    usuario.cpf = cpf or None
    usuario.telefone = telefone
    campos = ["nome_completo", "email", "cpf", "telefone"]
    if foto:
        usuario.foto = foto
        campos.append("foto")
    usuario.save(update_fields=campos)

    if areas is not None and hasattr(usuario, "perfil_professor"):
        usuario.perfil_professor.areas.set(areas)
    if siape is not None and hasattr(usuario, "perfil_professor"):
        usuario.perfil_professor.siape = siape
        usuario.perfil_professor.save(update_fields=["siape"])
    if matricula is not None and hasattr(usuario, "perfil_aluno"):
        usuario.perfil_aluno.matricula = matricula
        usuario.perfil_aluno.save(update_fields=["matricula"])
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

    O `select_for_update` trava TODOS os professores (`papel=PROFESSOR`), não só
    quem já é coordenador — e essa é a correção de um defeito real encontrado na
    revisão 1 desta tarefa. Uma primeira versão travava só `is_coordenador=True`,
    copiando um raciocínio do plano original que estava errado: "promover é um
    UPDATE de uma linha que passa a integrar o próprio conjunto travado, então
    duas promoções simultâneas se serializam". ISSO NÃO PREVINE A CORRIDA. Em READ
    COMMITTED, o PostgreSQL decide quais linhas um `SELECT ... FOR UPDATE` vai
    travar pelo snapshot do início do próprio comando — e a linha do alvo ainda
    tem `is_coordenador=False` nesse instante, então ela NUNCA entra no conjunto
    travado por essa condição. Duas promoções concorrentes de alvos diferentes
    liam "3 coordenadores" cada uma (nenhuma travava a linha da outra, porque a
    condição `is_coordenador=True` nunca incluía nenhum dos dois alvos) e as duas
    promoviam, terminando em 5 — reproduzido contra o PostgreSQL do projeto antes
    desta correção (saída registrada em tarefa-11-report.md, seção da revisão 1).

    Travar por `papel=PROFESSOR` funciona porque esse predicado NÃO muda com a
    promoção (só `is_coordenador` muda): a linha do alvo já pertence ao conjunto
    travado desde o início do comando, para as duas transações concorrentes,
    porque ambas travam TODOS os professores, não um subconjunto que a própria
    promoção altera. Quando a primeira transação comita, a segunda — que estava
    bloqueada tentando travar a MESMA linha do alvo da primeira, já que essa
    linha também é `papel=PROFESSOR` e portanto também fazia parte do conjunto
    que a segunda tentava travar — é liberada, e o PostgreSQL reavalia
    (EvalPlanQual) essa linha especificamente, porque ela estava no conjunto
    candidato da segunda transação E foi modificada nesse meio-tempo. A segunda
    transação enxerga a versão já promovida e conta corretamente 4, recusando a
    quinta promoção.
    """
    permissions.garante(permissions.pode_promover(por), "Somente a coordenação promove.")

    if usuario.papel != Usuario.PROFESSOR:
        raise ValidationError("Somente professores podem ser coordenadores.")
    if usuario.is_coordenador:
        raise ValidationError(f"{usuario.nome_completo} já é coordenador(a).")
    if not usuario.is_active:
        # A recusa mora aqui, e não só na filtragem da lista exibida pelo
        # painel (achado da revisão final): quem postasse o `usuario_id` de um
        # professor desativado direto na rota de promoção passava, porque o
        # serviço nunca olhava `is_active`. Dar coordenação a uma conta que
        # não consegue nem entrar no sistema também queimaria uma das 4 vagas,
        # já que coordenador inativo ocupa vaga (ver `coordenadores`).
        raise ValidationError(
            f"{usuario.nome_completo} está com a conta desativada e não pode "
            "ser promovido(a). Reative a conta antes."
        )

    # Mesmo predicado de `coordenadores()` (`is_coordenador=True`, ativos ou
    # não), só que contado sobre as linhas já travadas — o travamento por
    # `papel=PROFESSOR` é o que serializa promoções concorrentes, ver acima.
    professores = list(Usuario.objects.select_for_update().filter(papel=Usuario.PROFESSOR))
    atuais = sum(1 for professor in professores if professor.is_coordenador)
    if atuais >= LIMITE_COORDENADORES:
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

    Ao contrário de `promover_a_coordenador` (ver o porquê na docstring dela,
    corrigida na revisão 1 desta tarefa), travar só `is_coordenador=True` AQUI é
    suficiente e correto — as duas funções não seguem "o mesmo raciocínio", e
    dizer isso foi o erro original. A diferença: o predicado `is_coordenador=True`
    já inclui, desde o início do comando, TODO coordenador atual — inclusive o
    alvo desta revogação (que só chega até aqui por já ser coordenador) e
    qualquer coordenador que uma revogação concorrente esteja mirando. Quando a
    primeira revogação comita (mudando `is_coordenador` de True para False), a
    linha que ela modificou já estava no conjunto candidato da segunda
    transação — o PostgreSQL reavalia essa linha (EvalPlanQual) ao desbloquear e
    a REMOVE do resultado, porque ela deixou de satisfazer `is_coordenador=True`.
    A segunda transação enxerga a contagem já reduzida e decide corretamente.
    Reproduzido contra o PostgreSQL do projeto (revisão 1): sob a mesma
    sobreposição real que furou `promover_a_coordenador`, esta trava se manteve.
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
