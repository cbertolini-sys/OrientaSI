from datetime import timedelta

from django.conf import settings
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError, transaction
from django.db.models import BooleanField, Count, ExpressionWrapper, F, OuterRef, Q, Subquery, Value
from django.db.models.functions import Coalesce
from django.utils import timezone

from apps.comum.semestre import semestre_vigente
from apps.contas.models import PerfilProfessor
from apps.projetos import permissions
from apps.projetos.models import (
    Candidatura,
    LimiteOrientacao,
    OpcaoCandidatura,
    Projeto,
    Submissao,
    Tema,
)

# Teto padrão de vagas por professor, por etapa, no semestre vigente
# (CLAUDE.md, "Regras de Negócio Inegociáveis" item 1). A coordenação pode
# elevar este teto para um professor, etapa e semestre específicos —
# ver `LimiteOrientacao` e `limite_do_professor` — mas nunca reduzi-lo: é
# só uma exceção para cima (spec §3.6).
LIMITE_PADRAO_VAGAS = 3


def vagas_ocupadas(professor, etapa, ano, periodo):
    """Conta só os `Projeto` cujo carimbo de semestre é exatamente (ano,
    periodo) — spec §3.5. Um projeto de semestre anterior, mesmo em
    andamento, não pesa: essa é a decisão registrada no spec, com o custo
    aceito de um professor atrasado poder acumular mais orientandos ativos do
    que o teto permitiria contar de uma vez.

    Conta por SEMESTRE, não por `status`: um `Projeto` `REPROVADO` ou
    `CONCLUIDO` do semestre vigente ainda entra nesta contagem, porque o
    filtro abaixo não olha `status`. Inalcançável no Bloco B (só
    `EM_ANDAMENTO` existe até aqui), mas é uma decisão pendente do spec —
    registrada em §3.5 — para quando o Bloco C trouxer as demais transições.
    """
    return Projeto.objects.filter(
        orientador=professor.usuario, etapa=etapa, ano=ano, periodo=periodo
    ).count()


def limite_do_professor(professor, etapa, ano, periodo):
    """3, salvo autorização expressa da coordenação para este professor,
    nesta etapa, neste semestre (spec §3.6). A autorização vale só para a
    chave exata (professor, etapa, ano, periodo): não se propaga para outra
    etapa nem sobrevive à virada do semestre.
    """
    autorizado = (
        LimiteOrientacao.objects.filter(professor=professor, etapa=etapa, ano=ano, periodo=periodo)
        .values_list("limite", flat=True)
        .first()
    )
    # `is not None`, não `or`: `or` trataria um `limite` de 0 como "sem
    # autorização" e cairia no padrão. Hoje o `CheckConstraint(limite__gt=3)`
    # de `LimiteOrientacao` impede que 0 seja gravado, então esse caminho é
    # inalcançável — mas a função não deveria depender dessa constraint para
    # dizer o que "ausência de autorização" significa.
    return autorizado if autorizado is not None else LIMITE_PADRAO_VAGAS


@transaction.atomic
def criar_projeto_sob_limite(aluno, professor, tema, etapa):
    """Cria o `Projeto` sob a trava da linha do professor, e só se houver vaga.

    O travamento aqui é DIFERENTE do usado no teto de coordenadores
    (apps/contas/services.py::promover_a_coordenador), e a diferença é o
    ponto central desta função — não uma escolha de estilo.

    Lá, promover é um UPDATE de uma linha (`Usuario`) que já pertence ao
    conjunto travado (`papel=PROFESSOR`) desde o início da transação: travar
    esse conjunto serializa as duas promoções concorrentes porque a linha do
    alvo já estava lá para ser travada.

    Aqui, aceitar é um INSERT de `Projeto` novo. Travar os `Projeto` já
    existentes NÃO impede, em geral, uma segunda transação de inserir mais
    um — a linha do próximo projeto não existe ainda, então não há o que
    travar nela; é leitura fantasma. Por isso a trava é sobre a linha do
    `PerfilProfessor`, o recurso realmente disputado, e não sobre os
    `Projeto`, por três motivos que sobrevivem além do estado atual dos
    dados:

    1. Não depende de COMO a contagem é escrita. Travar os `Projeto`
       existentes (em vez da linha do professor) e ler a contagem num
       `SELECT` à parte (`vagas_ocupadas` faz isso: `.count()` roda como
       *statement* novo) FUNCIONA hoje, neste sistema — medido na revisão
       desta tarefa: a segunda transação bloqueia nas mesmas linhas
       pré-existentes que a primeira travou (o limiar sempre tem pelo menos
       dois projetos já existentes, porque `LimiteOrientacao` só autoriza
       `limite > 3`), e quando é liberada, sua *própria* chamada a
       `vagas_ocupadas` já enxerga o commit alheio. Mas basta tirar a
       contagem do PRÓPRIO queryset travado (`ocupadas = len(travados)`, em
       vez de um `.count()` novo) para a mesma trava sobre `Projeto`
       REPROVAR — medido na revisão desta tarefa, 4 projetos onde deveria
       haver 3 (ver test_concorrencia.py). Ou seja: travar `Projeto` não
       "funciona por sorte" de um jeito vago — funciona ou não conforme um
       detalhe de escrita da contagem, a poucos caracteres de distância, sem
       nada no código que sinalize a diferença para quem lê depois. Travar
       o professor não tem essa dependência: funciona com a contagem escrita
       de qualquer uma das duas formas, porque a segunda transação nem
       consegue começar a ler antes de a primeira liberar a linha.
    2. Trava uma única linha, com contenção previsível, em vez de um
       conjunto que cresce a cada semestre e que outra transação também
       precisaria enumerar por inteiro para colidir.
    3. Trava o recurso disputado. A capacidade do professor — quantos
       orientandos ele pode aceitar agora — é o que as duas transações
       disputam; travar a linha que representa essa capacidade deixa a
       intenção legível para quem ler este código depois.

    GARANTIA que esta trava entrega, e só esta: duas (ou mais) chamadas
    concorrentes para o MESMO professor são serializadas — a segunda espera a
    primeira liberar a linha do professor (commit ou rollback) antes de poder
    ler a contagem, então a contagem final não ultrapassa o limite lido
    dentro da transação vencedora. Para professores DIFERENTES não há
    contenção nenhuma — cada linha é independente, e não precisa haver. Esta
    trava também NÃO garante nada sobre uma leitura de
    `vagas_ocupadas`/`limite_do_professor` feita FORA desta função, sem o
    `select_for_update` — quem contornar esta função para ler ou decidir por
    conta própria não tem a garantia.

    Esta garantia DEPENDE do nível de isolamento ser READ COMMITTED — o
    padrão do PostgreSQL, e o que este projeto usa; a condição não é
    hipotética, é a premissa em vigor. T1 trava a linha do professor mas não
    a MODIFICA (só lê `vagas_ocupadas`/`limite_do_professor` e insere um
    `Projeto`, que é outra tabela). Sob REPEATABLE READ, quando T2 é
    liberada do bloqueio, o PostgreSQL não dispara erro de serialização —
    porque não houve UPDATE na linha travada — e T2 segue contando com o
    snapshot que tirou no início da própria transação, anterior ao projeto
    de T1: o teto é furado. Medido na revisão desta tarefa, rodando o serviço
    real, sem mutação nenhuma, só trocando o nível de isolamento da transação
    para REPEATABLE READ: mesma falha do contraexemplo abaixo, 4 projetos onde
    deveria haver 3. Não há teste no repositório que exercite REPEATABLE READ —
    esta medição foi feita fora da árvore, e é por isso que ela está descrita
    aqui em vez de provada ao lado.

    As duas leituras (`vagas_ocupadas` e `limite_do_professor`) acontecem
    DEPOIS do `select_for_update`, de propósito: se o limite fosse lido antes
    de travar a linha, duas transações concorrentes poderiam ler valores
    diferentes (um `LimiteOrientacao` sendo concedido ou revogado no meio do
    caminho) e o teto deixaria de ser garantia, só coincidência.

    Provado com threads e conexões reais em test_concorrencia.py, inclusive
    o contraexemplo: remover este `select_for_update` (sem substituí-lo por
    nenhum outro) faz o mesmo teste reprovar de forma determinística — as
    duas threads criam projeto (nenhuma é recusada) e o professor termina
    com 4 projetos sob um teto de 3 — ver a saída literal das duas execuções
    em tarefa-5-report.md.

    TRADUÇÃO DO `IntegrityError` de `Projeto` (rodada de correção 1 da T11).
    A trava acima protege a VAGA DO PROFESSOR — o recurso que esta função
    existe para disputar —, mas não protege o aluno de acabar com DOIS
    `Projeto` ativos na mesma etapa: isso é outro invariante, do
    `UniqueConstraint` "projeto_ativo_unico_por_aluno_e_etapa"
    (`aluno`+`etapa`, excluindo `CONCLUIDO`/`REPROVADO` —
    `apps/projetos/models.py::Projeto.Meta`), e nada nesta função lê esse
    estado antes de inserir. Achado real da revisão da T11: um aluno já
    `EM_ANDAMENTO` com um professor consegue registrar uma SEGUNDA
    candidatura (`registrar_candidatura`, abaixo, ganhou uma checagem
    amigável para o caso comum — ver `_possui_projeto_ativo` — mas não é
    exclusão mútua, pela mesma razão de que a checagem de vaga logo acima não
    é: lida fora de qualquer trava, pode ficar desatualizada); quando um
    segundo professor aceita essa segunda candidatura, o `INSERT` daqui bate
    no `UniqueConstraint` e o `IntegrityError` batia cru em
    `aceitar_opcao_view` (`apps/projetos/views.py`), que só captura
    `ValidationError` — 500 para um professor que não fez nada de errado.
    O `with transaction.atomic()` aninhado (mesmo SAVEPOINT que
    `registrar_candidatura`, linha 586, usa para o `UniqueConstraint` de
    `Candidatura`) isola esse `INSERT`, e o `except IntegrityError` abaixo
    traduz para uma `ValidationError` amigável, no mesmo PADRÃO daquela — a
    mensagem aqui é outra de propósito (nomeia a etapa e fala com o
    professor, não com o aluno), porque quem lê esta é quem tentou aceitar,
    não quem tentou se candidatar.
    """
    professor = PerfilProfessor.objects.select_for_update().get(pk=professor.pk)
    ano, periodo = semestre_vigente()
    ocupadas = vagas_ocupadas(professor, etapa, ano, periodo)
    limite = limite_do_professor(professor, etapa, ano, periodo)
    if ocupadas >= limite:
        # Rótulo de exibição do choice ("TCC I"), não o valor bruto gravado
        # no banco ("TCC_I") — a mensagem é para a pessoa ler, não para logar.
        etapa_legivel = dict(Projeto.ETAPAS).get(etapa, etapa)
        raise ValidationError(
            f"{professor.usuario.nome_completo} já tem {ocupadas} de {limite} vagas "
            f"ocupadas em {etapa_legivel} neste semestre. Peça à coordenação para elevar "
            "o limite, ou escolha outro orientador."
        )
    try:
        # SAVEPOINT (esta função já está dentro do `@transaction.atomic`
        # da própria `criar_projeto_sob_limite`) — mesmo raciocínio de
        # `registrar_candidatura`, linha 586: sem ele, o `IntegrityError` "envenena"
        # a transação externa inteira, e qualquer escrita futura na mesma
        # transação (não há nenhuma aqui hoje, mas `aceitar_opcao` continua
        # rodando depois deste retorno) encontraria "current transaction is
        # aborted" em vez do erro original.
        with transaction.atomic():
            return Projeto.objects.create(
                aluno=aluno.usuario,
                orientador=professor.usuario,
                tema=tema,
                etapa=etapa,
                status=Projeto.EM_ANDAMENTO,
                ano=ano,
                periodo=periodo,
            )
    except IntegrityError:
        etapa_legivel = dict(Projeto.ETAPAS).get(etapa, etapa)
        raise ValidationError(
            f"{aluno.usuario.nome_completo} já tem uma orientação em andamento em "
            f"{etapa_legivel} — não é possível abrir uma segunda."
        ) from None


@transaction.atomic
def criar_tema(professor, area, titulo, descricao, por):
    """Cadastra um `Tema` oferecido por `professor` (T6, mural do Bloco B).

    `por` é quem está EXECUTANDO a ação, e precisa ser EXATAMENTE o
    `professor` alvo (`permissions.pode_criar_tema_para`) — ao contrário de
    `convidar`/`promover_a_coordenador` em `apps/contas/services.py`, onde o
    alvo é legitimamente um terceiro (quem convida não é quem se cadastra),
    aqui o dono do tema é o próprio autor: não existe cenário em que o
    professor A deva poder publicar um tema em nome do professor B. Uma
    versão anterior desta função checava só `pode_criar_tema(por)` ("por é
    UM professor?"), sem ligar `por` a `professor` — o que deixava passar
    exatamente esse caso (achado da rodada de correção 1 da T6, reproduzido
    e fechado por `test_professor_nao_cria_tema_em_nome_de_outro`).

    A área precisa estar entre as que `professor` declarou em
    `PerfilProfessor.areas` — sem essa trava, o mural (Tarefa 7) anunciaria
    um tema numa área em que o professor não afirma atuar. A mensagem nomeia
    a área recusada, para a pessoa entender o que fazer (declarar a área no
    perfil antes, ou escolher outra já declarada).
    """
    permissions.garante(
        permissions.pode_criar_tema_para(por, professor),
        "Você só pode cadastrar temas em seu próprio nome.",
    )
    if not professor.areas.filter(pk=area.pk).exists():
        raise ValidationError(
            f'Você ainda não declarou atuar em "{area.nome}". Adicione essa área ao seu '
            "perfil antes de publicar um tema nela."
        )
    return Tema.objects.create(professor=professor, area=area, titulo=titulo, descricao=descricao)


@transaction.atomic
def desativar_tema(tema, por):
    """Desativa `tema` (`ativo = False`) sem apagá-lo: candidaturas antigas
    que o referenciam (`OpcaoCandidatura.tema`) continuam legíveis, e o
    `PROTECT` desse campo (apps/projetos/models.py) depende de o registro do
    tema nunca ser removido.

    Só o professor que cadastrou o tema pode desativá-lo — nem outro
    professor, nem um aluno. A checagem vive em
    `permissions.pode_desativar_tema` (rodada de correção 1 da T6: antes era
    um `hasattr(...) and ...` embutido aqui, duplicando o que
    `pode_criar_tema` já sabia fazer).
    """
    permissions.garante(
        permissions.pode_desativar_tema(por, tema),
        "Você só pode desativar temas que você mesmo cadastrou.",
    )
    tema.ativo = False
    tema.save(update_fields=["ativo"])


@transaction.atomic
def editar_tema(tema, area, titulo, descricao, por):
    """Edita título, descrição e área de um `tema` já cadastrado (spec §2 e
    §6: o professor "publica, edita e desativa os próprios temas" —
    acréscimo de escopo da rodada de correção 1 da T6; o plano original do
    Bloco B não tinha nenhuma tarefa que implementasse edição, e o spec é
    quem manda).

    Mesma checagem de posse de `desativar_tema`
    (`permissions.pode_editar_tema`) e mesma validação de área de
    `criar_tema` (`tema.professor.areas`), com a mesma mensagem.

    DELIBERADAMENTE sem trava para tema com candidaturas: o spec concede a
    edição sem condicioná-la (§2, §6), e o tema é a oferta do próprio
    professor — inventar uma restrição que o spec não pede seria regra de
    negócio que ninguém especificou.

    LACUNA REGISTRADA, não decidida aqui (spec §4.1): editar um tema que já
    recebeu candidatura muda a oferta debaixo de quem se candidatou a ele —
    `OpcaoCandidatura.tema` aponta para o MESMO registro, então o título, a
    descrição ou a área que o aluno viu ao se candidatar deixam de bater com
    o que está gravado, retroativamente, sem aviso a ninguém. O que o Bloco B
    NÃO tem é registro do que o aluno viu: `OpcaoCandidatura` guarda só a FK
    `tema`, sem cópia de título ou descrição — então não há divergência
    detectável, só um texto que mudou. O Bloco C, com prazo e cascata
    sobre essas opções, encosta diretamente nisso e precisa decidir o que
    fazer (bloquear, avisar o aluno, ou versionar o tema) antes de chegar lá.
    """
    permissions.garante(
        permissions.pode_editar_tema(por, tema),
        "Você só pode editar temas que você mesmo cadastrou.",
    )
    if not tema.professor.areas.filter(pk=area.pk).exists():
        raise ValidationError(
            f'Você ainda não declarou atuar em "{area.nome}". Adicione essa área ao seu '
            "perfil antes de publicar um tema nela."
        )
    tema.area = area
    tema.titulo = titulo
    tema.descricao = descricao
    tema.save(update_fields=["area", "titulo", "descricao"])
    return tema


def temas_do_mural(area=None):
    """Temas `ativo=True` para o mural que o aluno usa antes de se candidatar
    (T7; a candidatura em si é a T8), com a vaga do professor já anotada por
    linha — `professor_tem_vaga`, usado pelo template para marcar cada tema.

    A vaga é contada em `Projeto.TCC_I`, sempre — não é um parâmetro, e não
    existe uma opção "TCC_II" aqui. Isto não é uma escolha de UI: é a única
    etapa em que este bloco cria `Projeto`. `criar_projeto_sob_limite`,
    acima, sempre grava `etapa=Projeto.TCC_I` quando o professor aceita uma
    candidatura (spec §3.7, linha 147: "quando o professor aceita, nasce um
    `Projeto` com `etapa=TCC_I`"; critério 8 do §10 repete a mesma frase), e
    `Candidatura` não tem campo `etapa` — não há como o mural saber de outra
    etapa além desta.

    N+1 evitado por construção, não por sorte: uma chamada a
    `vagas_ocupadas`/`limite_do_professor` POR TEMA faria uma consulta por
    linha do mural. Em vez disso, as duas contagens são resolvidas dentro do
    MESMO SELECT que busca os temas — `vagas_ocupadas_do_professor` é um
    `Count` com `filter` sobre os `Projeto` do professor daquela linha (uma
    junção, não uma subconsulta por linha), e `limite_de_vagas_do_professor`
    é uma subconsulta CORRELACIONADA (`Subquery`/`OuterRef`) ao professor da
    mesma linha — o Postgres resolve as duas junto com a busca dos temas,
    então o número de consultas não cresce com o número de temas nem de
    professores. Provado com `django_assert_num_queries` comparando um mural
    de 3 temas/3 professores com um de 6/6 em
    `apps/projetos/tests/test_mural.py::test_temas_do_mural_sem_n_mais_um`.

    `limite_de_vagas_do_professor` reflete uma eventual autorização da
    coordenação (`LimiteOrientacao`, mesma regra de `limite_do_professor`
    acima) para a etapa/semestre em questão; na ausência de uma,
    `Coalesce` cai para `LIMITE_PADRAO_VAGAS` — mesmo comportamento de
    `limite_do_professor`, sem chamá-la (chamá-la exigiria uma consulta por
    professor, o N+1 que este serviço existe para evitar).
    """
    ano, periodo = semestre_vigente()
    limite_concedido = LimiteOrientacao.objects.filter(
        professor=OuterRef("professor"),
        etapa=Projeto.TCC_I,
        ano=ano,
        periodo=periodo,
    ).values("limite")[:1]

    qs = (
        Tema.objects.filter(ativo=True)
        .select_related("professor__usuario", "area")
        .annotate(
            vagas_ocupadas_do_professor=Count(
                "professor__usuario__projetos_orientados",
                filter=Q(
                    professor__usuario__projetos_orientados__etapa=Projeto.TCC_I,
                    professor__usuario__projetos_orientados__ano=ano,
                    professor__usuario__projetos_orientados__periodo=periodo,
                ),
                distinct=True,
            ),
            limite_de_vagas_do_professor=Coalesce(
                Subquery(limite_concedido), Value(LIMITE_PADRAO_VAGAS)
            ),
        )
        .annotate(
            professor_tem_vaga=ExpressionWrapper(
                Q(vagas_ocupadas_do_professor__lt=F("limite_de_vagas_do_professor")),
                output_field=BooleanField(),
            )
        )
    )
    if area is not None:
        qs = qs.filter(area=area)
    return qs


def manifestacoes_pendentes(professor):
    """Manifestações de interesse aguardando resposta de `professor` — a
    fila que `projetos:orientacoes` lista (T9, spec §6).

    Extraída para cá na rodada de correção 1 da T9 (Menor 8): a consulta
    morava direto na view, assimétrica com `temas_do_mural`, acima, que já
    tem a sua no serviço — a leitura sem regra de negócio não é proibida em
    `views.py` (CLAUDE.md §4 proíbe REGRA DE NEGÓCIO lá, não leitura), mas
    manter as duas juntas aqui evita que consumidores futuros decidam entre
    copiar a consulta ou importar a view.
    """
    return (
        OpcaoCandidatura.objects.filter(professor=professor, situacao=OpcaoCandidatura.ENVIADA)
        .select_related("candidatura__aluno__usuario", "tema")
        .order_by("prazo")
    )


def orientandos_atuais(professor):
    """Projetos de orientação em andamento de `professor` no semestre
    vigente — a segunda metade de `/orientacoes/` que o spec §6 pede ("fila
    de manifestações **e orientandos atuais**") e que nenhuma das treze
    tarefas do plano original implementava (`grep -n "orientandos"` vazio no
    plano inteiro — defeito do plano, fechado nesta rodada de correção da T9,
    ver `tarefa-9-fix-1-brief.md`).

    Filtra por `status__in=[EM_ANDAMENTO, AGUARDANDO_DEFESA, REPROVADO]`
    (Bloco D, spec §3.7 — ampliado do filtro original só `EM_ANDAMENTO` do
    Bloco B): o orientador precisa continuar vendo o projeto em
    `/orientacoes/` para agendar/editar/cancelar a banca, registrar o
    resultado, ou reabrir/cancelar um projeto reprovado — todas ações deste
    bloco. `CONCLUIDO` e `CANCELADO` ficam de fora — são estados terminais,
    e um projeto encerrado não precisa ocupar "orientandos atuais" para
    sempre. O spec não decide se um orientando recém-concluído deveria
    continuar aparecendo aqui por algum tempo (ex.: até o professor
    "arquivar"), e esta função também não decide por ele — LACUNA
    REGISTRADA, não uma escolha silenciosa, no mesmo formato das demais
    lacunas deste bloco (ver, por exemplo, a de `editar_tema`, acima, sobre
    tema editado depois de já ter candidatura).

    Sem `ano`/`periodo` como parâmetro, ao contrário de `vagas_ocupadas`:
    esta função sempre olha o semestre VIGENTE (`semestre_vigente()`) — a
    tela não tem motivo para mostrar orientandos de semestres passados, e
    não expõe esse filtro ao professor.
    """
    ano, periodo = semestre_vigente()
    return (
        Projeto.objects.filter(
            orientador=professor.usuario,
            ano=ano,
            periodo=periodo,
            status__in=[
                Projeto.EM_ANDAMENTO,
                Projeto.AGUARDANDO_DEFESA,
                Projeto.REPROVADO,
                Projeto.APROVADO_COM_RESSALVAS,
                Projeto.APROVADO,
            ],
        )
        .select_related("aluno", "tema", "submissao")
        .order_by("aluno__nome_completo")
    )


def projeto_ativo_do_aluno(usuario, etapa):
    """`Projeto` de `usuario` em `etapa` que ainda não terminou —
    `CONCLUIDO`/`REPROVADO` são estados terminais e ficam de fora, mesma
    condição do `UniqueConstraint` de `Projeto.Meta`
    (`projeto_ativo_unico_por_aluno_e_etapa`). `None` se não houver.

    Extraída de `views.py::candidatura` (T11, Bloco B) para esta tarefa
    (Bloco C) não duplicar a mesma consulta uma segunda vez em
    `views.py::meu_tcc`.
    """
    return (
        Projeto.objects.filter(aluno=usuario, etapa=etapa)
        .exclude(status__in=[Projeto.CONCLUIDO, Projeto.REPROVADO])
        .select_related("orientador", "tema")
        .first()
    )


@transaction.atomic
def enviar_submissao(projeto, por, pdf, editavel):
    """Registra o envio (ou reenvio) do trabalho escrito de `projeto` (Bloco
    C, spec §5). Cria a `Submissao` na primeira chamada; nas seguintes,
    ATUALIZA a mesma linha (substitui `pdf`/`editavel`, incrementa `versao`)
    — não existe histórico de versões anteriores (spec §3.2, decisão do
    usuário, custo aceito).

    GARANTIA que esta função entrega, e só esta: `por` é exatamente o aluno
    de `projeto` (`permissions.pode_enviar_submissao`), e `projeto.status`
    é `EM_ANDAMENTO` no momento da chamada. Ela NÃO garante nada sobre uma
    corrida entre dois reenvios simultâneos do mesmo aluno — não há
    `select_for_update` aqui, porque o recurso (a `Submissao` de UM projeto)
    não é disputado por partes concorrentes do sistema do jeito que vagas de
    professor são: só o próprio aluno escreve nesta linha, e duas abas do
    mesmo aluno reenviando ao mesmo tempo é uma corrida de baixíssimo risco
    (o pior caso é a versão que perder a corrida ficar como se nunca tivesse
    sido enviada — sem corrupção de dado, só uma versão a menos do que o
    aluno esperava).
    """
    permissions.garante(
        permissions.pode_enviar_submissao(por, projeto),
        "Você só pode enviar a submissão do seu próprio projeto.",
    )
    if projeto.status != Projeto.EM_ANDAMENTO:
        raise ValidationError(
            "Este projeto não está mais em andamento — não é possível enviar ou "
            "reenviar a submissão."
        )

    submissao, criada = Submissao.objects.get_or_create(
        projeto=projeto, defaults={"pdf": pdf, "editavel": editavel}
    )
    if not criada:
        submissao.pdf = pdf
        submissao.editavel = editavel
        submissao.versao += 1
        submissao.save(update_fields=["pdf", "editavel", "versao", "atualizada_em"])
    return submissao


def _possui_candidatura_em_curso(aluno):
    """A checagem AMIGÁVEL de "este aluno já tem um pedido em andamento" —
    extraída como função à parte só para que o teste de corrida
    (test_candidatura.py::test_registrar_converte_erro_de_integridade_do_banco_em_validationerror)
    consiga substituí-la por `monkeypatch` e simular a janela entre esta
    leitura e o INSERT abaixo. Fora do teste, ela sempre reflete o banco no
    momento em que é chamada.
    """
    return Candidatura.objects.filter(aluno=aluno, status=Candidatura.EM_CURSO).exists()


def _possui_projeto_ativo(aluno):
    """A checagem AMIGÁVEL de "este aluno já tem uma orientação em
    andamento" (rodada de correção 1 da T11) — mesmo formato de
    `_possui_candidatura_em_curso`, acima, e mesma limitação: só reflete o
    banco no instante em que é chamada, sem trava nenhuma.

    A condição espelha o `UniqueConstraint` "projeto_ativo_unico_por_aluno_e_etapa"
    (`apps/projetos/models.py::Projeto.Meta`) — `aluno`+`etapa`, excluindo
    `CONCLUIDO`/`REPROVADO`. `etapa=Projeto.TCC_I` é fixo, não um parâmetro:
    mesma citação já usada alhures neste arquivo (`temas_do_mural`,
    `registrar_candidatura` logo abaixo) — `Candidatura` não tem campo
    `etapa`, e TCC_I é a única que este bloco cria.
    """
    return (
        Projeto.objects.filter(aluno=aluno.usuario, etapa=Projeto.TCC_I)
        .exclude(status__in=[Projeto.CONCLUIDO, Projeto.REPROVADO])
        .exists()
    )


@transaction.atomic
def registrar_candidatura(aluno, opcoes):
    """Registra o pedido de orientação de `aluno`, com até três opções
    ordenadas (spec §5.2), e dispara a cascata na primeira delas — só ela
    recebe e-mail agora; a segunda e a terceira só são acionadas se a
    anterior for recusada ou expirar (`avancar_cascata`).

    `opcoes` é uma lista ordenada de `(professor, tema_ou_None)` — a ordem
    da lista É a ordem da cascata (posição 0 vira `ordem=1`).

    GARANTIA que a checagem de vaga aqui entrega, e só esta (ambiguidade 2 do
    controlador da Tarefa 8): é uma ECONOMIA DE TEMPO das duas pessoas, não
    exclusão mútua. Ela lê `vagas_ocupadas`/`limite_do_professor` FORA de
    qualquer `select_for_update` — de propósito, porque travar a linha do
    professor aqui exigiria manter o lock até a candidatura inteira ser
    gravada, por um pedido que pode nem ser aceito nunca. Entre o instante em
    que esta função lê a contagem e o instante em que um professor
    eventualmente ACEITA esta opção (T9), outras candidaturas podem ocupar as
    vagas que pareciam livres agora. A garantia real — o teto de vagas nunca
    é ultrapassado — é só de `criar_projeto_sob_limite` (T5), que revalida
    tudo sob `select_for_update` dentro da própria transação do aceite.
    Remover esta checagem NÃO abre brecha para o limite ser furado (T5 ainda
    trava); ela só deixa de economizar o tempo do professor e do aluno num
    alvo que já era impossível — ver Passo 6 do brief (prova por mutação).

    GARANTIA de "um aluno, uma candidatura em curso" (ambiguidade 3 do
    controlador): a checagem amigável (`_possui_candidatura_em_curso`) é só
    isso — amigável. Duas submissões simultâneas do mesmo aluno podem passar
    as duas por ela antes de qualquer uma commitar. Quem garante de fato é o
    `UniqueConstraint` parcial de `Candidatura.Meta` (só uma linha EM_CURSO
    por aluno) — o `try/except IntegrityError` abaixo existe para essa
    garantia de banco não vazar como um 500 cru: ela vira a MESMA
    `ValidationError` amigável que a checagem em Python levantaria se
    tivesse enxergado a outra candidatura a tempo.

    GARANTIA de "aluno já alocado não abre nova candidatura" (Importante da
    rodada de correção 1 da T11 — achado real da revisão, não hipotético: um
    aluno com `Projeto` `EM_ANDAMENTO` conseguia montar uma segunda
    candidatura pela tela `/candidatura/`, e o segundo aceite virava um
    `IntegrityError` cru — 500 — em `aceitar_opcao_view`). A checagem
    amigável (`_possui_projeto_ativo`) tem a MESMA limitação estrutural da
    checagem de vaga logo acima: lida fora de qualquer `select_for_update`,
    pode ficar desatualizada entre esta leitura e um aceite concorrente em
    outra candidatura do mesmo aluno. Quem garante de fato — o aluno nunca
    termina com dois `Projeto` ativos na mesma etapa — é o `UniqueConstraint`
    "projeto_ativo_unico_por_aluno_e_etapa" (`Projeto.Meta`), via a tradução
    do `IntegrityError` em `criar_projeto_sob_limite` (T5, acima): o mesmo
    padrão que este parágrafo já descreve para `Candidatura`, agora repetido
    para `Projeto`.
    """
    if not opcoes:
        raise ValidationError("Escolha ao menos um professor para se candidatar.")
    if len(opcoes) > 3:
        raise ValidationError("A candidatura admite no máximo três opções.")

    if _possui_candidatura_em_curso(aluno):
        raise ValidationError(
            "Você já tem uma candidatura em curso. Cancele-a antes de registrar outra."
        )

    if _possui_projeto_ativo(aluno):
        raise ValidationError(
            f"{aluno.usuario.nome_completo} já tem uma orientação em andamento e não pode "
            "abrir uma nova candidatura."
        )

    ano, periodo = semestre_vigente()
    professores_ja_escolhidos = set()
    for professor, tema in opcoes:
        # M11 da rodada de correção 1: o mural (T7) não oferece nenhum dos
        # dois casos abaixo, mas o serviço é a camada de guarda (CLAUDE.md
        # §4) — ele já confere posse do tema duas linhas abaixo, então
        # deixar de conferir "ativo" e "repetido" seria uma assimetria dele
        # consigo mesmo, não uma omissão inofensiva.
        if professor.pk in professores_ja_escolhidos:
            raise ValidationError(
                f"{professor.usuario.nome_completo} aparece mais de uma vez na candidatura."
            )
        professores_ja_escolhidos.add(professor.pk)

        if tema is not None and tema.professor_id != professor.pk:
            # A trigger `valida_tema_do_professor_da_opcao` (migração 0002)
            # recusaria este INSERT de qualquer forma — esta checagem NÃO a
            # duplica como regra independente, é a mesma condição, escrita
            # aqui só para dar uma mensagem legível em vez do IntegrityError
            # cru que a trigger levantaria.
            raise ValidationError(
                f'O tema "{tema.titulo}" não pertence a {professor.usuario.nome_completo}.'
            )
        if tema is not None and not tema.ativo:
            raise ValidationError(
                f'O tema "{tema.titulo}" não está mais ativo. Escolha outro tema ou '
                "candidate-se ao professor sem um tema específico."
            )
        # Ambiguidade 2 (ver docstring acima): aviso, não garantia. `Projeto.TCC_I`
        # é fixo, não um parâmetro: aceitar sempre cria o Projeto com
        # etapa=TCC_I (spec §3.7, linha 147; critério 8 do §10, linha 508), e
        # `Candidatura` não tem campo `etapa` — não há outra etapa para esta
        # checagem considerar (Importante 4 da rodada de correção 1; mesma
        # citação já usada por `temas_do_mural`, acima).
        ocupadas = vagas_ocupadas(professor, Projeto.TCC_I, ano, periodo)
        limite = limite_do_professor(professor, Projeto.TCC_I, ano, periodo)
        if ocupadas >= limite:
            raise ValidationError(
                f"{professor.usuario.nome_completo} já está com {ocupadas} de {limite} vagas "
                "ocupadas em TCC I neste semestre. Escolha outro orientador."
            )

    try:
        # O `with transaction.atomic()` aninhado abre um SAVEPOINT (esta
        # função já está dentro do `@transaction.atomic` da própria
        # `registrar_candidatura`). CORREÇÃO ao relatório original da T8
        # (M6 da rodada de correção 1): a afirmação de que um teste provava
        # este savepoint necessário estava errada — removendo-o (mantendo o
        # `try/except`), a suíte inteira continua passando, porque hoje o
        # `except` relança IMEDIATAMENTE e a transação externa é desfeita por
        # inteiro na saída da função; a transação "envenenada" pelo
        # `IntegrityError` nunca chega a ser consultada de novo. O savepoint
        # fica mesmo assim, como defesa para quem adicionar código DEPOIS
        # deste bloco `try` no futuro (uma escrita adicional na mesma
        # transação encontraria "current transaction is aborted" sem ele) —
        # é custo baixo (um SAVEPOINT a mais) contra uma classe de erro que
        # já mordeu este projeto antes (ver o resto desta docstring).
        with transaction.atomic():
            candidatura = Candidatura.objects.create(aluno=aluno, ano=ano, periodo=periodo)
    except IntegrityError:
        # A corrida da ambiguidade 3: a checagem amigável acima não viu a
        # outra candidatura em curso a tempo, e o UniqueConstraint do banco
        # recusou o INSERT. Mesma mensagem que a checagem amigável daria.
        raise ValidationError(
            "Você já tem uma candidatura em curso. Cancele-a antes de registrar outra."
        ) from None

    for ordem, (professor, tema) in enumerate(opcoes, start=1):
        OpcaoCandidatura.objects.create(
            candidatura=candidatura, ordem=ordem, professor=professor, tema=tema
        )

    _enviar_opcao(candidatura.opcoes.get(ordem=1))
    return candidatura


def _enviar_opcao(opcao):
    """Marca `opcao` como ENVIADA, com prazo de `PRAZO_RESPOSTA_DIAS` a
    partir de agora, e agenda o e-mail ao professor — o passo comum a
    `registrar_candidatura` (primeira opção) e `avancar_cascata` (as
    seguintes).
    """
    agora = timezone.now()
    opcao.situacao = OpcaoCandidatura.ENVIADA
    opcao.enviada_em = agora
    opcao.prazo = agora + timedelta(days=settings.PRAZO_RESPOSTA_DIAS)
    opcao.save(update_fields=["situacao", "enviada_em", "prazo"])

    from apps.projetos.tasks import enviar_manifestacao

    transaction.on_commit(lambda: enviar_manifestacao.delay(opcao.id))


@transaction.atomic
def avancar_cascata(candidatura):
    """Avança a cascata de `candidatura` para a próxima opção, ou esgota a
    candidatura se não houver mais nenhuma (spec §5.2).

    Chamada em dois contextos, e só um deles precisa que esta função MUDE a
    situação da opção corrente:

    - Pelo prazo estourado (tarefa periódica, T10): a opção corrente ainda
      está `ENVIADA` quando esta função é chamada, e é esta função quem a
      marca `EXPIRADA` — mas só se o prazo dela JÁ passou de verdade (ver
      Importante 1 da rodada de correção 2, abaixo).
    - Por `recusar_opcao` (T9): quem chama já marcou a opção corrente como
      `RECUSADA`, com a justificativa, ANTES de chamar `avancar_cascata` —
      esta função não sobrescreve isso. Ela só toca a situação da opção
      corrente quando a encontra ainda `ENVIADA`.

    RETORNO — leia antes de usar o argumento depois de chamar (Importante 2
    da rodada de correção 2). Esta função recarrega a candidatura sob
    `select_for_update` e trabalha sobre essa cópia, não sobre o objeto que
    o chamador passou: todo `save()` acontece na cópia recarregada, e o
    objeto original, em memória, FICA PARADO no estado de antes da chamada
    — `status` e `opcao_atual` desatualizados. Esta função DEVOLVE a cópia
    recarregada (já com todas as mudanças aplicadas); quem chama e precisa
    do estado pós-avanço (T9: "marca RECUSADA → `avancar_cascata` → renderiza
    a candidatura") deve usar o RETORNO, nunca o argumento. Medido: o objeto
    do chamador continua reportando `EM_CURSO` depois de a candidatura virar
    `ESGOTADA` no banco, se ninguém usar o retorno nem `refresh_from_db()`.

    TRAVAMENTO (Crítico da rodada de correção 1). Antes desta correção, a
    função só olhava `ordem`, nunca `candidatura.status` — chamada sobre uma
    candidatura já `ACEITA` ou `CANCELADA`, ela ressuscitava a próxima opção
    de `CANCELADA` para `ENVIADA` e mandava e-mail a um professor convidando-o
    a orientar um aluno que já tem orientador (ou que desistiu). Reproduzido
    sem trava nenhuma: aceitar a opção 1 e chamar `avancar_cascata` de novo
    trazia a opção 2 de volta à vida; cancelar a candidatura e chamar de novo
    fazia o mesmo.

    A causa era uma só: esta função é `@transaction.atomic`, mas
    atomicidade sozinha não serializa nada — só embrulha várias escritas
    numa transação. O recurso disputado é a PRÓPRIA linha de `candidatura`,
    e ninguém a travava. Ao contrário do `INSERT` de `Projeto` novo que
    `criar_projeto_sob_limite` (T5) protege — onde travar um conjunto vazio
    não adianta nada, porque a linha nova ainda não existe para ser travada
    —, aqui a disputa é sobre uma linha que JÁ EXISTE e sofre `UPDATE`.

    A receita que funciona aqui NÃO é "a linha já existe, então travá-la
    basta" — dito assim, soaria como precedente de
    `apps/contas/services.py::promover_a_coordenador`, e seria o OPOSTO do
    que aquela função ensina: ela documenta, longamente, que travar só o
    SUBCONJUNTO que a própria escrita altera NÃO previne a corrida — por
    isso trava `papel=PROFESSOR` inteiro, não só a linha promovida. O que
    faz `select_for_update` na própria linha bastar AQUI é outra condição,
    específica deste caso: TODOS os concorrentes disputam a MESMA linha (o
    `pk` da candidatura, fixo, conhecido antes de qualquer leitura), e o
    predicado do lock não muda entre eles. Não há "subconjunto que pode
    crescer" para escapar por fora, como havia no teto de coordenadores.

    GARANTIA que esta trava entrega, e só esta: recarregada sob
    `select_for_update`, a candidatura só é lida DEPOIS de qualquer chamada
    concorrente anterior sobre a MESMA linha ter comitado (ou revertido) —
    esta chamada nunca parte de um valor em memória desatualizado, sempre do
    último estado commitado. Combinada com a checagem de `status` logo a
    seguir, uma candidatura que já saiu de `EM_CURSO` nunca tem opção
    nenhuma tocada por esta função, não importa o que o objeto `candidatura`
    passado pelo chamador dizia antes da trava.

    NÃO GARANTE, sozinha: que duas chamadas para o MESMO evento lógico (dois
    workers do Beat processando o mesmo prazo estourado, por exemplo)
    resultem num único avanço — a segunda, liberada, enxergaria o estado JÁ
    avançado pela primeira. É por isso que existe o guarda de prazo logo
    abaixo (Importante 1): a trava sozinha impede a CORRIDA (duas escritas
    disputando a mesma linha ao mesmo tempo), mas não distingue "prazo
    realmente estourado" de "cascata que acabou de avançar por outro
    motivo" — quem distingue isso é o guarda.

    Isolamento: a garantia da trava depende de READ COMMITTED (o padrão do
    PostgreSQL e o que este projeto usa) — mesma premissa de
    `criar_projeto_sob_limite`, mas a garantia AQUI é mais forte que a de
    lá, não a mesma: em `criar_projeto_sob_limite`, sob REPEATABLE READ, o
    teto FURA em silêncio, porque T1 trava a linha do professor sem
    MODIFICÁ-LA (só lê e insere `Projeto`, outra tabela) — medido na T5.
    Aqui, medido nesta rodada: sob REPEATABLE READ, a segunda transação que
    tenta `save()` na MESMA linha de `candidatura` já modificada pela
    primeira recebe `could not serialize access due to concurrent update`
    do próprio PostgreSQL, e o invariante se mantém — porque aqui, ao
    contrário de lá, a transação que trava TAMBÉM escreve na linha travada.
    A garantia sob RC continua sendo a documentada acima; a observação sob
    RR é só isso — uma observação, não uma segunda garantia testada e
    mantida por este projeto.

    Provado em `apps/projetos/tests/test_candidatura.py` (não em
    `test_concorrencia.py`, que não menciona esta função): uma chamada
    sequencial sobre candidatura `ACEITA` ou `CANCELADA` nunca reenvia
    e-mail nem ressuscita opção `CANCELADA`
    (`test_avancar_cascata_nao_ressuscita_opcao_cancelada_de_candidatura_aceita`,
    `test_avancar_cascata_nao_reenvia_apos_aluno_cancelar` — sequenciais,
    sem threads); duas chamadas CONCORRENTES, com threads e conexões reais,
    na mesma candidatura `EM_CURSO`, nunca mandam dois e-mails para o mesmo
    professor nem reescrevem o prazo da mesma opção
    (`test_avancar_cascata_concorrente_nao_duplica_email_nem_reescreve_prazo`).
    As três mutações medidas nesta rodada reprovam subconjuntos DIFERENTES,
    não os mesmos três testes: sem a checagem de `status` (mantendo a
    trava), os dois primeiros reprovam; sem `select_for_update` (mantendo a
    checagem de status), só o terceiro reprova; sem as duas, os três
    reprovam.

    IMPORTANTE 1 (rodada de correção 2) — o guarda de prazo, e por que ele
    existe. A trava, sozinha, fechou o dano ANTIGO (e-mail duplicado, prazo
    reescrito) mas abriu um dano NOVO, pior: medido, uma segunda chamada
    logo em seguida da primeira (mesmo eixo do defeito antigo, sem que
    nenhum evento real tenha acontecido) fazia a opção 2 nascer `ENVIADA` E
    já virar `EXPIRADA` no MESMO avanço — o professor da opção 2 chega a ser
    notificado ("você tem 7 dias") e a opção morre no mesmo instante, sem os
    7 dias terem passado. Isso CONSOME uma das três chances do aluno sem
    nenhum motivo real — pior que duplicar e-mail, que era só barulho; isto
    é perda de estado. O guarda fecha exatamente o caminho que importa: só a
    tarefa periódica (T10) pode chamar esta função sem que algo tenha
    acontecido de fato com a opção corrente (ela dispara pelo relógio, não
    por uma resposta) — então, se a opção que `opcao_atual` aponta ainda
    está `ENVIADA` mas o `prazo` dela ainda não passou, não há evento
    nenhum que justifique avançar, e a função não faz nada.
    """
    candidatura = Candidatura.objects.select_for_update().get(pk=candidatura.pk)
    if candidatura.status != Candidatura.EM_CURSO:
        # A candidatura já terminou (ACEITA, ESGOTADA ou CANCELADA) — nada
        # aqui é "a próxima opção" de mais nada. Retorno silencioso, não
        # erro: para quem chama (T9 depois de aceitar/recusar, T10 depois do
        # aluno ter cancelado enquanto o prazo corria), "não há mais cascata
        # para avançar" não é uma falha, é o estado esperado.
        return candidatura

    atual = candidatura.opcoes.filter(ordem=candidatura.opcao_atual).first()
    if atual is not None and atual.situacao == OpcaoCandidatura.ENVIADA:
        if atual.prazo is not None and atual.prazo > timezone.now():
            # Guarda do Importante 1 (rodada de correção 2): a opção ainda
            # está ENVIADA, mas o prazo real dela não passou — não houve
            # recusa (isso teria trocado a situação para RECUSADA antes de
            # chamar) nem expiração de verdade. Nada aconteceu, então nada
            # muda. Fecha o Beat chamando duas vezes (ou cedo demais por
            # qualquer bug de agendamento) sem custar nada à T9.
            return candidatura
        # `respondida_em` NÃO é preenchido aqui (M10 da rodada de correção
        # 1): o campo, por spec §4.3, é nulo "até acontecer" — e expirar por
        # prazo não é uma resposta de ninguém. Só `situacao` muda.
        atual.situacao = OpcaoCandidatura.EXPIRADA
        atual.save(update_fields=["situacao"])

    proxima = candidatura.opcoes.filter(ordem=candidatura.opcao_atual + 1).first()
    if proxima is None:
        candidatura.status = Candidatura.ESGOTADA
        candidatura.save(update_fields=["status"])

        from apps.projetos.tasks import enviar_esgotamento

        transaction.on_commit(lambda: enviar_esgotamento.delay(candidatura.id))
        return candidatura

    candidatura.opcao_atual = proxima.ordem
    candidatura.save(update_fields=["opcao_atual"])
    _enviar_opcao(proxima)
    return candidatura


@transaction.atomic
def cancelar_candidatura(candidatura, por):
    """Cancela `candidatura` a pedido de `por` — hoje, só o próprio aluno
    (spec §6, tela `/candidatura/`: "montar, acompanhar e cancelar").

    Marca a candidatura e as opções que ainda não têm desfecho (`AGUARDANDO`
    ou `ENVIADA`) como `CANCELADA`; opções já respondidas (`ACEITA`,
    `RECUSADA`, `EXPIRADA`) mantêm seu desfecho — cancelar não reescreve
    histórico.

    TRAVA DA CANDIDATURA (acréscimo do controlador da T9): até a T9, esta
    função rodava sem `select_for_update` — não alcançável enquanto nada
    mais disputasse a linha da candidatura, mas passa a ser no instante em
    que `aceitar_opcao`/`recusar_opcao` (acima) e `avancar_cascata` existem
    e competem pela MESMA linha. Mesma trava, mesma ordem (Candidatura
    primeiro — não há segunda linha em disputa aqui) e mesma checagem de
    status logo a seguir, sobre o estado RECARREGADO, não sobre o objeto
    `candidatura` que o chamador passou — ver `avancar_cascata`, acima,
    para a mesma garantia (recarregada sob a trava, nunca lida a partir de
    um valor em memória desatualizado).
    """
    candidatura = Candidatura.objects.select_for_update().get(pk=candidatura.pk)
    permissions.garante(
        por == candidatura.aluno.usuario,
        "Você só pode cancelar sua própria candidatura.",
    )
    if candidatura.status != Candidatura.EM_CURSO:
        raise ValidationError("Esta candidatura já foi encerrada e não pode mais ser cancelada.")

    candidatura.status = Candidatura.CANCELADA
    candidatura.save(update_fields=["status"])
    candidatura.opcoes.filter(
        situacao__in=[OpcaoCandidatura.AGUARDANDO, OpcaoCandidatura.ENVIADA]
    ).update(situacao=OpcaoCandidatura.CANCELADA)


@transaction.atomic
def trocar_orientador(projeto, novo_professor, por):
    """Troca o orientador de `projeto` para `novo_professor` (T12, painel da
    coordenação — spec §6 e §10 critério 12: "a coordenação troca o
    orientador de um projeto; a vaga do professor novo é revalidada").

    MESMA disciplina de travamento de `criar_projeto_sob_limite` (T5,
    acima) — leia a docstring dela inteira antes de mexer aqui. A única
    diferença estrutural é que ali a escrita disputada é um INSERT de
    `Projeto` novo, e aqui é um UPDATE de um `Projeto` já existente; o
    recurso disputado continua sendo a MESMA linha, a do `PerfilProfessor`
    do professor NOVO — travar `Projeto` não ajudaria aqui pela mesma razão
    que não ajudaria lá (a segunda transação não precisa da linha do
    `Projeto` para decidir se cabe mais um, só da contagem e do limite do
    professor).

    GARANTIA, e limite dela: idêntica à de `criar_projeto_sob_limite` — duas
    (ou mais) chamadas concorrentes para o MESMO professor novo são
    serializadas pela trava da linha dele; para professores novos
    DIFERENTES não há contenção nenhuma. Também depende de READ COMMITTED
    (o padrão deste projeto), pelo mesmo motivo de lá: esta função trava a
    linha do professor mas não a MODIFICA (só lê `vagas_ocupadas`/
    `limite_do_professor` e grava no `Projeto`, outra linha) — sob REPEATABLE
    READ o mesmo furo documentado em `criar_projeto_sob_limite` se
    aplicaria aqui. Não medido de novo nesta tarefa: reaproveita a mesma
    análise, não uma segunda medição. Provado com threads e conexões reais
    em `test_concorrencia.py::
    test_duas_trocas_simultaneas_para_o_mesmo_professor_no_ultimo_lugar_resultam_em_uma_recusa`.

    SEMESTRE: revalida usando `projeto.ano`/`projeto.periodo` — o carimbo
    que o próprio `Projeto` já carrega desde que nasceu e que não muda
    depois (`apps/projetos/models.py::Projeto`) — e NUNCA
    `semestre_vigente()`. Um projeto pertence ao semestre em que nasceu;
    trocar de orientador não muda isso. Usar o semestre vigente contaria a
    vaga do professor novo no semestre ERRADO se a troca acontecer depois
    da virada — discriminado em
    `test_painel_orientacoes.py::test_trocar_orientador_usa_semestre_do_projeto_nao_o_vigente`
    (professor lotado no semestre do projeto, com vaga de sobra no vigente:
    só a implementação que olha o semestre do projeto recusa).

    LACUNA REGISTRADA, não decidida aqui (mesmo formato das demais lacunas
    deste arquivo — ver, por exemplo, a de `editar_tema`, acima, sobre tema
    editado depois de já ter candidatura): `novo_professor` sendo o MESMO
    professor que já orienta `projeto` conta a vaga já ocupada por este
    projeto contra o teto do próprio professor, e pode recusar uma "troca"
    que não muda nada. A tela (`FormularioTrocarOrientador`,
    `apps/projetos/forms.py`) evita o caso excluindo o orientador atual do
    `<select>`, mas este serviço, chamado direto, não tem essa proteção.

    SEGUNDA LACUNA REGISTRADA (rodada de correção 1 da T12, spec §5.3): a
    mensagem de recusa acima ("Conceda um limite maior a ele...") pressupõe
    que a coordenação CONSEGUE conceder esse limite — verdade só quando
    `projeto.ano`/`projeto.periodo` é o semestre VIGENTE. `conceder_limite`
    (abaixo) só concede para o semestre vigente, nunca para um semestre
    passado; para um `Projeto` de semestre passado, esta mensagem aconselha
    uma ação que a coordenação não tem como executar. Não decidida aqui —
    ver a nota completa no spec.
    """
    permissions.garante(
        permissions.pode_ajustar_orientacao(por),
        "Somente a coordenação troca o orientador de um projeto.",
    )
    professor = PerfilProfessor.objects.select_for_update().get(pk=novo_professor.pk)
    ocupadas = vagas_ocupadas(professor, projeto.etapa, projeto.ano, projeto.periodo)
    limite = limite_do_professor(professor, projeto.etapa, projeto.ano, projeto.periodo)
    if ocupadas >= limite:
        etapa_legivel = dict(Projeto.ETAPAS).get(projeto.etapa, projeto.etapa)
        raise ValidationError(
            f"{professor.usuario.nome_completo} já tem {ocupadas} de {limite} vagas "
            f"ocupadas em {etapa_legivel} no semestre {projeto.ano}/{projeto.periodo}. "
            "Conceda um limite maior a ele ou escolha outro orientador."
        )
    projeto.orientador = professor.usuario
    projeto.save(update_fields=["orientador"])
    return projeto


def _possui_limite_para_chave(professor, etapa, ano, periodo):
    """Checagem AMIGÁVEL de "já existe uma autorização para esta chave
    exata" — mesmo formato de `_possui_candidatura_em_curso`/
    `_possui_projeto_ativo`, acima, e mesma limitação: só reflete o banco no
    instante em que é chamada, sem trava nenhuma. Extraída à parte para que
    o teste de corrida
    (`test_painel_orientacoes.py::test_conceder_limite_converte_erro_de_integridade_em_validationerror`)
    consiga substituí-la por `monkeypatch`, simulando a janela entre esta
    leitura e o INSERT de `conceder_limite` abaixo — mesmo mecanismo dos
    dois exemplos citados.
    """
    return LimiteOrientacao.objects.filter(
        professor=professor, etapa=etapa, ano=ano, periodo=periodo
    ).exists()


@transaction.atomic
def conceder_limite(professor, etapa, limite, justificativa, por):
    """Concede um limite ELEVADO de vagas a `professor`, nesta `etapa`, no
    semestre VIGENTE (T12, painel da coordenação — spec §3.6 e §10 critério
    10: "a coordenação eleva o limite daquele professor com justificativa;
    o quarto aceite passa").

    SEMESTRE: sempre `semestre_vigente()`, nunca um parâmetro — ao contrário
    de `trocar_orientador`, acima, que revalida sobre o semestre CONGELADO
    do projeto que já existe, uma concessão NOVA só pode servir para
    decisões FUTURAS (o próximo aceite, a próxima troca); não há tela nem
    pedido do spec (§6) para a coordenação escolher um ano/período
    arbitrário na hora de conceder.

    LACUNA REGISTRADA (rodada de correção 1 da T12, spec §5.3): esta função
    só concede para o semestre VIGENTE, mas `trocar_orientador` revalida
    vaga no semestre do PROJETO — para um `Projeto` de um semestre PASSADO,
    a mensagem de recusa de `trocar_orientador` aconselha "conceda um
    limite maior a ele", e esta função não tem como conceder nada para
    aquele semestre. As duas decisões são corretas isoladamente; a nota
    completa, não decidida aqui, está no spec.

    RECUSAS, nesta ordem: permissão (só coordenação); limite que não eleva
    nada acima do teto padrão (ambiguidade 1 do controlador da T12 —
    `LimiteOrientacao.Meta.constraints` já impõe `limite > 3` no banco com
    `CheckConstraint`, esta checagem só dá uma mensagem legível ANTES do
    INSERT, no mesmo espírito de outras checagens deste arquivo que
    antecipam uma trigger/constraint com uma mensagem melhor); justificativa
    vazia (spec §3.6: "a justificativa é obrigatória... a decisão precisa
    sobreviver à memória de quem estava na coordenação"); e por fim a chave
    (professor, etapa, ano, periodo) já autorizada.

    CHAVE JÁ AUTORIZADA (ambiguidade 1 do controlador): recusada com
    `ValidationError`, nunca uma atualização in-place — sobrescrever
    apagaria a `justificativa` e o `autorizado_por` da concessão anterior
    sem deixar rastro. Mesmo raciocínio que `registrar_candidatura` (acima)
    usa para candidatura em curso ("cancele antes de registrar outra") e que
    a T11 usou para `Projeto` ativo. A checagem amigável
    (`_possui_limite_para_chave`) tem a MESMA limitação estrutural das
    outras deste arquivo — lida fora de qualquer trava, pode ficar
    desatualizada entre esta leitura e uma concessão concorrente para a
    MESMA chave. Quem garante de fato é o `UniqueConstraint`
    "limite_unico_por_professor_etapa_e_semestre"
    (`apps/projetos/models.py::LimiteOrientacao.Meta`), via o
    `try/except IntegrityError` abaixo — mesmo padrão de
    `registrar_candidatura` e `criar_projeto_sob_limite` (T5), acima: o
    SAVEPOINT aninhado (`with transaction.atomic()`) isola o INSERT para que
    o `IntegrityError`, se disparar, não "envenene" a transação inteira
    desta função.

    QUAL CONSTRAINT DISPAROU (Menor da rodada de correção 1): `LimiteOrientacao.Meta`
    tem DUAS constraints — a `UniqueConstraint` acima e
    `CheckConstraint(limite__gt=3, name="limite_maior_que_padrao")`. A checagem
    Python de `limite <= LIMITE_PADRAO_VAGAS`, logo no início desta função, já
    intercepta todo valor que violaria o `CheckConstraint` antes de chegar
    neste INSERT — então, hoje, todo `IntegrityError` que sai daqui só pode
    ser o `UniqueConstraint`. O `except` abaixo não presume isso: ele lê
    `erro.__cause__.diag.constraint_name` (o psycopg, driver deste projeto,
    expõe o nome da constraint que o Postgres reportou) e só traduz a
    mensagem amigável quando o nome bate com o `UniqueConstraint` esperado;
    qualquer outro nome (uma constraint nova adicionada ao modelo no futuro,
    por exemplo) é relançado como está, em vez de mentir sobre qual
    constraint disparou.
    """
    permissions.garante(
        permissions.pode_conceder_limite(por),
        "Somente a coordenação concede limites de orientação.",
    )
    if limite <= LIMITE_PADRAO_VAGAS:
        raise ValidationError(
            f"O limite precisa ser maior que {LIMITE_PADRAO_VAGAS} — esse já é o teto padrão "
            f"que vale para todo professor; conceder {limite} não muda nada."
        )
    if not justificativa or not justificativa.strip():
        raise ValidationError("Informe uma justificativa para conceder o limite.")

    ano, periodo = semestre_vigente()
    etapa_legivel = dict(Projeto.ETAPAS).get(etapa, etapa)
    mensagem_ja_autorizado = (
        f"{professor.usuario.nome_completo} já tem uma autorização de limite para "
        f"{etapa_legivel} neste semestre ({ano}/{periodo}). Revogue a existente antes de "
        "conceder outra."
    )
    if _possui_limite_para_chave(professor, etapa, ano, periodo):
        raise ValidationError(mensagem_ja_autorizado)
    try:
        with transaction.atomic():
            return LimiteOrientacao.objects.create(
                professor=professor,
                etapa=etapa,
                ano=ano,
                periodo=periodo,
                limite=limite,
                justificativa=justificativa.strip(),
                autorizado_por=por,
            )
    except IntegrityError as erro:
        nome_da_constraint = getattr(getattr(erro, "__cause__", None), "diag", None)
        nome_da_constraint = getattr(nome_da_constraint, "constraint_name", None)
        if nome_da_constraint != "limite_unico_por_professor_etapa_e_semestre":
            # Não é a corrida que esta função sabe traduzir — ver a nota
            # "QUAL CONSTRAINT DISPAROU" na docstring acima. Relança o
            # IntegrityError original em vez de afirmar uma causa que não
            # foi verificada.
            raise
        raise ValidationError(mensagem_ja_autorizado) from None


@transaction.atomic
def revogar_limite(limite, por):
    """Revoga `limite` (T12, spec §3.6 e §10 critério 11: "revogar o limite
    não desfaz os projetos já criados, e trava o próximo aceite").

    Revogar é DELETAR a linha — nada em `LimiteOrientacao` marca "revogado"
    (não há campo para isso, e nenhum `PROTECT` aponta para este modelo —
    `apps/projetos/models.py::LimiteOrientacao` só declara `PROTECT` NELE
    PRÓPRIO apontando para `PerfilProfessor`/`Usuario`, na direção
    contrária). Sem a linha, `limite_do_professor` (acima) simplesmente
    deixa de encontrar uma autorização para a chave (professor, etapa, ano,
    periodo) e volta a responder `LIMITE_PADRAO_VAGAS` — é essa queda, não
    uma escrita nova, quem "trava o próximo aceite": nenhum `Projeto` já
    criado sob a autorização é tocado, só a PRÓXIMA leitura de vaga
    (`criar_projeto_sob_limite`/`trocar_orientador`) volta a ver o teto
    padrão.
    """
    permissions.garante(
        permissions.pode_conceder_limite(por),
        "Somente a coordenação revoga limites de orientação.",
    )
    limite.delete()


def _erro_de_conflito_de_estado():
    return ValidationError(
        "Esta manifestação não está mais disponível para resposta — outra ação já a "
        "resolveu (aceite, recusa ou expiração), ou o aluno cancelou a candidatura."
    )


@transaction.atomic
def aceitar_opcao(opcao, por):
    """Aceita `opcao` em nome de `por` (professor dono dela — T9, spec
    §5.2 e §5.3): cria o `Projeto` e cancela as demais opções, ainda sem
    desfecho, da mesma `Candidatura`.

    ORDEM DE AQUISIÇÃO DE LOCKS — contrato entre esta função e T5
    (`criar_projeto_sob_limite`, acima, linha 172). Esta função trava a
    `Candidatura` PRIMEIRO — mesma trava e mesma checagem de status que
    `avancar_cascata` usa (acima, linha 745) — e só DEPOIS chama
    `criar_projeto_sob_limite`, que trava `PerfilProfessor`. A ordem
    Candidatura → PerfilProfessor precisa ser a MESMA em toda chamada que
    trave as duas linhas: um caminho que a inverta (professor primeiro,
    candidatura depois) cria risco de deadlock com qualquer código futuro
    que trave as duas na ordem contrária — duas transações esperando, cada
    uma, a linha que a outra já segura.

    GARANTIA de revalidação de vaga: esta função NÃO reimplementa a
    contagem de vagas — ela chama `criar_projeto_sob_limite` DENTRO da
    própria transação (o `@transaction.atomic` aninhado abre um SAVEPOINT,
    não uma transação nova), que revalida `vagas_ocupadas`/
    `limite_do_professor` sob `select_for_update` da linha do professor. O
    e-mail que o professor recebeu pode ter dias (spec §5.3): se a vaga
    sumiu nesse meio-tempo, a `ValidationError` dela propaga para fora
    desta função, e o `@transaction.atomic` desfaz por inteiro o que esta
    função já tiver preparado — nada é gravado (opção continua `ENVIADA`,
    candidatura continua `EM_CURSO`).

    A opção é RELIDA sob a trava da candidatura (`candidatura.opcoes.get`),
    não usada a partir do argumento `opcao` recebido: o argumento pode estar
    desatualizado se outra transação (outro `aceitar_opcao`/`recusar_opcao`/
    `avancar_cascata` sobre a MESMA candidatura) tiver comitado entre o
    instante em que o chamador buscou `opcao` e o instante em que esta
    função conseguiu a trava — mesmo raciocínio do RETORNO de
    `avancar_cascata` (acima, linha 639 e seguintes).

    Checagem de POSSE (`permissions.pode_responder_opcao`) é redundante
    quando esta função é chamada pela view `projetos:orientacoes`, que já
    escopa o lookup da opção ao professor autenticado (mesmo padrão de
    `views.py::editar_tema`) — mas protege qualquer outro chamador que não
    escope o lookup do mesmo jeito (mesmo raciocínio de
    `criar_tema`/`editar_tema`, acima).

    Conflito de ESTADO (a opção já não está `ENVIADA`, ou a candidatura já
    não está `EM_CURSO` — outra ação já resolveu, o prazo expirou, ou o
    aluno cancelou) é `ValidationError`, não `PermissionDenied`: quem chama
    TEM posse da opção, só chegou tarde. Não há caso especial para "aluno
    cancelou" — a checagem genérica de `candidatura.status` já cobre isso,
    porque cancelar marca a candidatura `CANCELADA` (`cancelar_candidatura`,
    acima).

    GARANTIA da trava de `Candidatura`, vista A PARTIR DAQUI (Menor 4 da
    rodada de correção 1 — o texto completo da garantia mora em
    `avancar_cascata`, acima, para não duplicar; esta função só acrescenta o
    que falta ver do lado de quem chama): esta função nunca decide sobre um
    estado de `Candidatura`/`OpcaoCandidatura` mais velho que o último commit
    concorrente sobre a MESMA linha. Ela NÃO garante nada sobre um chamador
    que leia `Candidatura`/`OpcaoCandidatura` por fora desta função (ou de
    `recusar_opcao`/`avancar_cascata`/`cancelar_candidatura`, que travam a
    mesma linha, na mesma ordem) sem usar `select_for_update` — um `admin.py`
    ou um comando de management que leia essas tabelas direto não tem
    nenhuma das garantias documentadas aqui.
    """
    candidatura = Candidatura.objects.select_for_update().get(pk=opcao.candidatura_id)
    opcao = candidatura.opcoes.select_related("professor", "tema").get(pk=opcao.pk)
    permissions.garante(
        permissions.pode_responder_opcao(por, opcao),
        "Você só pode responder manifestações endereçadas a você.",
    )
    if candidatura.status != Candidatura.EM_CURSO or opcao.situacao != OpcaoCandidatura.ENVIADA:
        raise _erro_de_conflito_de_estado()

    projeto = criar_projeto_sob_limite(
        candidatura.aluno, opcao.professor, opcao.tema, Projeto.TCC_I
    )

    opcao.situacao = OpcaoCandidatura.ACEITA
    opcao.respondida_em = timezone.now()
    opcao.save(update_fields=["situacao", "respondida_em"])

    candidatura.status = Candidatura.ACEITA
    candidatura.save(update_fields=["status"])
    # As demais opções (a que já foi respondida por esta chamada não entra
    # no filtro — situação ACEITA — e a `exclude` é redundante com isso, mas
    # deixa explícito que esta opção nunca deveria ser tocada aqui de
    # qualquer forma) — spec §5.2: "opções restantes → CANCELADA".
    candidatura.opcoes.filter(
        situacao__in=[OpcaoCandidatura.AGUARDANDO, OpcaoCandidatura.ENVIADA]
    ).exclude(pk=opcao.pk).update(situacao=OpcaoCandidatura.CANCELADA)

    return projeto


@transaction.atomic
def recusar_opcao(opcao, por, justificativa):
    """Recusa `opcao` em nome de `por` (professor dono dela — T9), com
    `justificativa` obrigatória (spec §6: "sem ela, a recusa é silêncio com
    outro nome"), e avança a cascata para a próxima opção do aluno
    (`avancar_cascata`, acima).

    `justificativa` é validada ANTES de travar qualquer coisa: é checagem de
    entrada, não de concorrência, e falhar rápido evita tomar a trava da
    candidatura por uma chamada que já se sabe inválida. Isso NÃO é um
    oráculo (Preocupação 3 do relatório original, aceita como está pela
    revisão da rodada de correção 1): a mensagem de erro só ecoa o próprio
    input do chamador ("informe uma justificativa"), sem revelar nada sobre
    o estado de `opcao`/`candidatura` que a checagem de posse ou de status —
    ambas feitas DEPOIS, sob a trava — protegeriam. Um professor sem posse
    da opção que envie justificativa vazia recebe o mesmo `ValidationError`
    de entrada que qualquer outro chamador receberia; ele só aprende que
    esqueceu a justificativa, não se a opção é dele.

    MESMA ORDEM DE TRAVAS que `aceitar_opcao`, acima: trava a `Candidatura`
    primeiro, com a mesma checagem de posse e status.

    Leia a docstring de `avancar_cascata` (acima) inteira antes de mexer
    aqui — ela documenta três pontos que este chamador precisa respeitar,
    e os três importam para esta função especificamente:

    1. Ela ESPERA que a opção corrente já esteja marcada `RECUSADA`, com a
       justificativa, ANTES de ser chamada — não sobrescreve isso, só avança
       a partir do que encontrar. Por isso `opcao.situacao`/`justificativa`/
       `respondida_em` são gravados ANTES da chamada a `avancar_cascata`
       abaixo, nunca depois.
    2. O guarda de prazo dela (linha ~623: "se a opção que `opcao_atual`
       aponta ainda está `ENVIADA` e o prazo real não passou, não faz
       nada") não afeta este caminho: quando `avancar_cascata` é chamada
       abaixo, a opção já foi gravada como `RECUSADA` pelo ponto 1 — o
       guarda só olha opção ainda `ENVIADA`.
    3. Ela RETORNA a candidatura recarregada, e o argumento que esta função
       tinha em mãos (a variável `candidatura`, travada acima) fica
       obsoleto depois da chamada. Por isso esta função devolve o RETORNO
       de `avancar_cascata`, não a `candidatura` local.

    `enviar_recusa` (T8, `apps/projetos/tasks.py`) é enfileirada por
    `transaction.on_commit`, no mesmo padrão de `_enviar_opcao` acima — o
    e-mail só sai se esta transação de fato comitar. A T8 criou a tarefa e o
    template (`templates/email/candidatura_recusada.txt`) com teste direto,
    mas nenhum serviço a chamava até esta função existir.
    """
    if not justificativa or not justificativa.strip():
        raise ValidationError("Informe uma justificativa para recusar.")

    candidatura = Candidatura.objects.select_for_update().get(pk=opcao.candidatura_id)
    opcao = candidatura.opcoes.get(pk=opcao.pk)
    permissions.garante(
        permissions.pode_responder_opcao(por, opcao),
        "Você só pode responder manifestações endereçadas a você.",
    )
    if candidatura.status != Candidatura.EM_CURSO or opcao.situacao != OpcaoCandidatura.ENVIADA:
        raise _erro_de_conflito_de_estado()

    opcao.situacao = OpcaoCandidatura.RECUSADA
    # `.strip()` (Menor 7 da rodada de correção 1): a validação acima já usa
    # `.strip()` para decidir se a justificativa é vazia, mas gravava o
    # texto ORIGINAL, com espaços nas pontas se houvesse algum. Não
    # alcançável pela tela hoje — `forms.CharField` já normaliza — mas a
    # gravação não deveria depender disso para estar correta.
    opcao.justificativa = justificativa.strip()
    opcao.respondida_em = timezone.now()
    opcao.save(update_fields=["situacao", "justificativa", "respondida_em"])

    from apps.projetos.tasks import enviar_recusa

    transaction.on_commit(lambda: enviar_recusa.delay(opcao.id))

    return avancar_cascata(candidatura)


def reabrir_projeto(projeto, por):
    """Reabre um `Projeto` `REPROVADO` — volta a `EM_ANDAMENTO`, o aluno
    tenta de novo (Bloco D, spec §3.6). Só o orientador, só a partir de
    `REPROVADO`."""
    if not permissions.pode_reabrir_projeto(por, projeto):
        raise PermissionDenied("Somente o orientador do projeto pode reabri-lo.")
    if projeto.status != Projeto.REPROVADO:
        raise ValidationError("Só é possível reabrir um projeto reprovado.")

    projeto.status = Projeto.EM_ANDAMENTO
    projeto.save(update_fields=["status"])


def cancelar_projeto(projeto, por):
    """Encerra definitivamente um `Projeto` `REPROVADO` (Bloco D, spec
    §3.6) — distinto de `REPROVADO`: registra que o projeto foi encerrado,
    não só que a banca não aprovou."""
    if not permissions.pode_cancelar_projeto(por, projeto):
        raise PermissionDenied("Somente o orientador do projeto pode cancelá-lo.")
    if projeto.status != Projeto.REPROVADO:
        raise ValidationError("Só é possível cancelar um projeto reprovado.")

    projeto.status = Projeto.CANCELADO
    projeto.save(update_fields=["status"])


def aprovar_projeto(projeto, por):
    """Confirma que o aluno corrigiu o que a banca pediu — fecha
    `Aprovado com Ressalvas` → `Aprovado` para o TCC I (Bloco E, spec §3.1).
    Sem checklist: o `inicio.pdf` só descreve checklist de correções para o
    TCC II (Bloco F, ainda não existe); esta transição é uma confirmação
    simples do orientador."""
    if not permissions.pode_aprovar_projeto(por, projeto):
        raise PermissionDenied("Somente o orientador do projeto pode aprová-lo.")
    if projeto.status != Projeto.APROVADO_COM_RESSALVAS:
        raise ValidationError("Só é possível aprovar um projeto aprovado com ressalvas.")

    projeto.status = Projeto.APROVADO
    projeto.save(update_fields=["status"])

    from apps.documentos.services import gerar_ata

    gerar_ata(projeto)


def criar_tcc_ii_automatico(projeto_tcc_i):
    """Cria o TCC II a partir de um TCC I `Concluído` (Bloco F, spec §3.1)
    — chamada por `apps.documentos.services.aprovar_ata` no momento em que
    o TCC I vira `CONCLUIDO`. Copia aluno, orientador e coorientador; NÃO
    checa limite de vagas (é continuação de um aluno que o professor já
    orienta, não um compromisso novo — ao contrário de
    `criar_tcc_ii_manual`, que reaproveita `criar_projeto_sob_limite`)."""
    ano, periodo = semestre_vigente()
    return Projeto.objects.create(
        aluno=projeto_tcc_i.aluno,
        orientador=projeto_tcc_i.orientador,
        coorientador=projeto_tcc_i.coorientador,
        coorientador_externo=projeto_tcc_i.coorientador_externo,
        etapa=Projeto.TCC_II,
        status=Projeto.EM_ANDAMENTO,
        anterior=projeto_tcc_i,
        ano=ano,
        periodo=periodo,
    )
