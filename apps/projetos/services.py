from datetime import timedelta

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.db.models import BooleanField, Count, ExpressionWrapper, F, OuterRef, Q, Subquery, Value
from django.db.models.functions import Coalesce
from django.utils import timezone

from apps.comum.semestre import semestre_vigente
from apps.contas.models import PerfilProfessor
from apps.projetos import permissions
from apps.projetos.models import Candidatura, LimiteOrientacao, OpcaoCandidatura, Projeto, Tema

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
    return Projeto.objects.create(
        aluno=aluno.usuario,
        orientador=professor.usuario,
        tema=tema,
        etapa=etapa,
        status=Projeto.EM_ANDAMENTO,
        ano=ano,
        periodo=periodo,
    )


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


def _possui_candidatura_em_curso(aluno):
    """A checagem AMIGÁVEL de "este aluno já tem um pedido em andamento" —
    extraída como função à parte só para que o teste de corrida
    (test_candidatura.py::test_registrar_converte_erro_de_integridade_do_banco_em_validationerror)
    consiga substituí-la por `monkeypatch` e simular a janela entre esta
    leitura e o INSERT abaixo. Fora do teste, ela sempre reflete o banco no
    momento em que é chamada.
    """
    return Candidatura.objects.filter(aluno=aluno, status=Candidatura.EM_CURSO).exists()


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
    """
    if not opcoes:
        raise ValidationError("Escolha ao menos um professor para se candidatar.")
    if len(opcoes) > 3:
        raise ValidationError("A candidatura admite no máximo três opções.")

    if _possui_candidatura_em_curso(aluno):
        raise ValidationError(
            "Você já tem uma candidatura em curso. Cancele-a antes de registrar outra."
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
    """
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
