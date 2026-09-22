from django.db import models

from apps.contas.models import PerfilProfessor
from apps.projetos.models import Projeto


class Banca(models.Model):
    """Agendamento e resultado da apresentação de um `Projeto` (Bloco D,
    spec §4.2). `projeto` é `ForeignKey`, não `OneToOneField` — cancelar ou
    realizar a banca não apaga o registro (fica `CANCELADA`/`REALIZADA`,
    histórico), e nem uma banca cancelada nem uma já realizada impedem uma
    banca NOVA para o mesmo projeto depois — é exatamente o que acontece no
    ciclo `Reprovado → reabrir_projeto → Em Andamento → nova banca`
    (CLAUDE.md, "Ciclo de Vida", item 6). A restrição abaixo garante no
    máximo UMA banca `AGENDADA` por projeto ao mesmo tempo — a trava real é
    contra o DUPLO AGENDAMENTO, não contra o histórico.

    ACHADO DA AUDITORIA (2026-09-22, C1): até esta correção a condição era
    `~Q(status="CANCELADA")`, que também contava uma banca `REALIZADA` como
    ocupando a vaga — ou seja, uma banca `REALIZADA` (com resultado
    `Reprovado`) bloqueava PARA SEMPRE o reagendamento depois de
    `reabrir_projeto`, contradizendo tanto este docstring quanto o ciclo de
    vida documentado. `test_modelos.py` tem um teste dedicado que prova essa
    correção por mutação (reverter para `~Q(status="CANCELADA")` reprova o
    teste).
    """

    AGENDADA = "AGENDADA"
    REALIZADA = "REALIZADA"
    CANCELADA = "CANCELADA"
    STATUS = [
        (AGENDADA, "Agendada"),
        (REALIZADA, "Realizada"),
        (CANCELADA, "Cancelada"),
    ]

    projeto = models.ForeignKey(
        Projeto,
        on_delete=models.PROTECT,
        related_name="bancas",
        verbose_name="projeto",
    )
    data_hora = models.DateTimeField("data e hora")
    local = models.CharField("local", max_length=200)
    status = models.CharField("status", max_length=9, choices=STATUS, default=AGENDADA)
    # Uma nota e um resultado só, não um por membro (spec §3.2): decidido
    # coletivamente na apresentação, digitado pelo orientador. `resultado`
    # usa as MESMAS strings de `Projeto.APROVADO_COM_RESSALVAS`/
    # `Projeto.REPROVADO` — `registrar_resultado` grava
    # `projeto.status = banca.resultado` sem nenhuma tradução no meio.
    # `max_length=32` (achado L2 da auditoria, 2026-09-22): antes era 22, um
    # ajuste exato a `len("APROVADO_COM_RESSALVAS")` sem folga nenhuma — um
    # nome de status futuro mais comprido truncaria/erraria silenciosamente.
    # Continua acoplado ao `max_length` de `Projeto.status`, de propósito:
    # os dois precisam caber qualquer valor que passe por essa atribuição
    # direta.
    nota = models.DecimalField("nota", max_digits=3, decimal_places=1, null=True, blank=True)
    resultado = models.CharField(
        "resultado",
        max_length=32,
        choices=[
            (Projeto.APROVADO_COM_RESSALVAS, "Aprovado com ressalvas"),
            (Projeto.REPROVADO, "Reprovado"),
        ],
        blank=True,
        default="",
    )
    comentario = models.TextField("comentário", blank=True, default="")
    criada_em = models.DateTimeField("criada em", auto_now_add=True)

    class Meta:
        verbose_name = "banca"
        verbose_name_plural = "bancas"
        ordering = ["-criada_em"]
        constraints = [
            models.UniqueConstraint(
                fields=["projeto"],
                condition=models.Q(status="AGENDADA"),
                name="banca_ativa_unica_por_projeto",
            ),
        ]

    def __str__(self):
        return f"Banca de {self.projeto} — {self.get_status_display()}"


class MembroBanca(models.Model):
    """Um dos DOIS avaliadores adicionais de uma `Banca` — o orientador
    participa implicitamente, sem uma linha aqui (spec §3.1). Interno
    (`professor`, com conta no sistema) OU externo (`nome_externo`, só o
    nome — regra 3 do CLAUDE.md: sem FK, sem CPF, sem e-mail), nunca os
    dois, nunca nenhum — `CheckConstraint` abaixo.
    """

    banca = models.ForeignKey(
        Banca,
        # CASCADE, ao contrário de Banca.projeto (PROTECT): um MembroBanca
        # só existe em função da Banca que o contém — apagar a banca não
        # deixa membros órfãos para trás.
        on_delete=models.CASCADE,
        related_name="membros",
        verbose_name="banca",
    )
    professor = models.ForeignKey(
        PerfilProfessor,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="participacoes_em_banca",
        verbose_name="professor",
    )
    # `blank=True, default=""`, sem `null=True` (DJ001 — string vazia, não
    # NULL, é o sentinela idiomático de Django para "sem valor" num
    # CharField). A constraint abaixo usa `nome_externo=""`/`~Q(nome_externo="")`
    # em vez de `__isnull`, exatamente por isso.
    nome_externo = models.CharField("nome (externo)", max_length=200, blank=True, default="")

    class Meta:
        verbose_name = "membro da banca"
        verbose_name_plural = "membros da banca"
        constraints = [
            models.CheckConstraint(
                condition=(
                    models.Q(professor__isnull=False, nome_externo="")
                    | (models.Q(professor__isnull=True) & ~models.Q(nome_externo=""))
                ),
                name="membro_banca_interno_xor_externo",
            ),
        ]

    def __str__(self):
        if self.professor:
            return self.professor.usuario.nome_completo
        return f"{self.nome_externo} (externo)"


class ItemCorrecao(models.Model):
    """Um item do checklist de correções pós-banca do TCC II (Bloco F,
    spec §4.2) — digitado pelo orientador com base no que a banca pediu
    (`Banca.comentario`, Bloco D), não estruturado a partir da banca em si
    (decisão do brainstorming: a banca só tem nota+comentário geral, sem
    itens individuais).
    """

    projeto = models.ForeignKey(
        Projeto,
        on_delete=models.PROTECT,
        related_name="itens_correcao",
        verbose_name="projeto",
    )
    descricao = models.TextField("descrição")
    concluido = models.BooleanField("concluído", default=False)
    criado_em = models.DateTimeField("criado em", auto_now_add=True)

    class Meta:
        verbose_name = "item de correção"
        verbose_name_plural = "itens de correção"
        ordering = ["criado_em"]

    def __str__(self):
        return f"{self.projeto} — {self.descricao[:50]}"
