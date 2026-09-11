from django.core.exceptions import ValidationError
from django.db import transaction

from apps.comum.semestre import semestre_vigente
from apps.contas.models import PerfilProfessor
from apps.projetos.models import LimiteOrientacao, Projeto

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
    de T1: o teto é furado. Medido rodando o serviço real, sem mutação
    nenhuma, só trocando o nível de isolamento da transação para REPEATABLE
    READ: mesma falha do contraexemplo abaixo, 4 projetos onde deveria haver
    3.

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
