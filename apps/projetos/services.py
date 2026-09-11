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
    return autorizado or LIMITE_PADRAO_VAGAS


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

    1. Não depende de o conjunto de `Projeto` no limiar ser não-vazio. Neste
       sistema, hoje, o limiar (`ocupadas == limite - 1`) sempre tem pelo
       menos dois projetos já existentes, porque `LimiteOrientacao` só
       autoriza `limite > 3` — então travar esse conjunto não-vazio
       acidentalmente serializa também (ver o achado registrado em
       test_concorrencia.py). Se um dia o limite mínimo caísse para 1, ou o
       predicado de contagem mudasse, essa trava passaria a falhar em
       silêncio. Travar o professor não depende de nada disso: a linha do
       professor sempre existe, com ou sem nenhum `Projeto`.
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
        raise ValidationError(
            f"{professor.usuario.nome_completo} já tem {ocupadas} de {limite} vagas "
            f"ocupadas em {etapa} neste semestre. Peça à coordenação para elevar o "
            "limite, ou escolha outro orientador."
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
