from django.db import models
from django.db.models import Q

from apps.contas.models import Area, PerfilProfessor, Usuario

# Compartilhado por Projeto e LimiteOrientacao: o semestre gravado é sempre o
# par (ano, período), e período só assume 1 ou 2 (spec §3.4).
PERIODOS = [(1, "1º"), (2, "2º")]


class Tema(models.Model):
    professor = models.ForeignKey(
        PerfilProfessor,
        # PROTECT, não CASCADE: apagar o perfil de um professor não pode apagar,
        # em cascata, o histórico de temas que candidaturas antigas referenciam.
        on_delete=models.PROTECT,
        related_name="temas",
        verbose_name="professor",
    )
    area = models.ForeignKey(
        Area,
        on_delete=models.PROTECT,
        related_name="temas",
        verbose_name="área",
    )
    titulo = models.CharField("título", max_length=200)
    descricao = models.TextField("descrição")
    # Desativar tira o tema do mural sem apagar histórico: candidaturas que já
    # apontam para ele continuam legíveis (spec §4.1).
    ativo = models.BooleanField("ativo", default=True)
    criado_em = models.DateTimeField("criado em", auto_now_add=True)

    class Meta:
        verbose_name = "tema"
        verbose_name_plural = "temas"
        ordering = ["-criado_em"]

    def __str__(self):
        return self.titulo


class Projeto(models.Model):
    TCC_I = "TCC_I"
    TCC_II = "TCC_II"
    ETAPAS = [(TCC_I, "TCC I"), (TCC_II, "TCC II")]

    # Ciclo completo do CLAUDE.md. Só EM_ANDAMENTO é alcançável neste bloco —
    # o aceite de uma opção cria o Projeto e para por aqui —, mas o campo já
    # nasce com o vocabulário inteiro: o Bloco C conduz as transições
    # seguintes sobre o mesmo modelo, não sobre um campo remodelado depois.
    EM_ANDAMENTO = "EM_ANDAMENTO"
    AGUARDANDO_DEFESA = "AGUARDANDO_DEFESA"
    APROVADO_COM_RESSALVAS = "APROVADO_COM_RESSALVAS"
    APROVADO = "APROVADO"
    CONCLUIDO = "CONCLUIDO"
    REPROVADO = "REPROVADO"
    STATUS = [
        (EM_ANDAMENTO, "Em andamento"),
        (AGUARDANDO_DEFESA, "Aguardando defesa"),
        (APROVADO_COM_RESSALVAS, "Aprovado com ressalvas"),
        (APROVADO, "Aprovado"),
        (CONCLUIDO, "Concluído"),
        (REPROVADO, "Reprovado"),
    ]

    aluno = models.ForeignKey(
        Usuario,
        on_delete=models.PROTECT,
        related_name="projetos_como_aluno",
        verbose_name="aluno",
    )
    orientador = models.ForeignKey(
        Usuario,
        on_delete=models.PROTECT,
        related_name="projetos_orientados",
        verbose_name="orientador",
    )
    tema = models.ForeignKey(
        Tema,
        # SET_NULL: um projeto "aberto a temas" (candidatura sem tema publicado
        # escolhido) não referencia nenhum, e apagar o Tema não pode arrastar o
        # Projeto junto.
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="projetos",
        verbose_name="tema",
    )
    etapa = models.CharField("etapa", max_length=6, choices=ETAPAS)
    status = models.CharField("status", max_length=22, choices=STATUS, default=EM_ANDAMENTO)
    # Carimbo do semestre em que o projeto NASCEU (spec §3.4): dois inteiros,
    # congelados na criação. O semestre vigente muda a cada consulta a
    # apps.comum.semestre.semestre_vigente(); este par não muda nunca — se o
    # mês de corte for ajustado depois, as contagens de vaga já feitas não
    # mudam retroativamente.
    ano = models.PositiveIntegerField("ano")
    periodo = models.PositiveSmallIntegerField("período", choices=PERIODOS)
    criado_em = models.DateTimeField("criado em", auto_now_add=True)

    class Meta:
        verbose_name = "projeto"
        verbose_name_plural = "projetos"
        ordering = ["-criado_em"]
        constraints = [
            # Um aluno só pode ter um projeto ATIVO por etapa — CONCLUIDO e
            # REPROVADO são estados terminais e ficam de fora da condição, para
            # que um TCC já encerrado não impeça o aluno de iniciar outro na
            # mesma etapa (ex.: reprovado e reiniciando).
            models.UniqueConstraint(
                fields=["aluno", "etapa"],
                condition=~Q(status__in=["CONCLUIDO", "REPROVADO"]),
                name="projeto_ativo_unico_por_aluno_e_etapa",
            ),
        ]

    def __str__(self):
        return (
            f"{self.aluno.nome_completo} — {self.get_etapa_display()} "
            f"({self.ano}/{self.periodo})"
        )


class LimiteOrientacao(models.Model):
    """Autoriza uma EXCEÇÃO PARA CIMA ao teto padrão de vagas por professor,
    etapa e semestre (spec §3.6) — nunca redução. A autorização vale só para o
    semestre e a etapa gravados: uma exceção pontual não vira permanente por
    esquecimento, e revogá-la (fora deste modelo, na camada de serviço) não
    desfaz projetos já criados, só trava o próximo aceite.
    """

    professor = models.ForeignKey(
        PerfilProfessor,
        on_delete=models.PROTECT,
        related_name="limites_de_orientacao",
        verbose_name="professor",
    )
    etapa = models.CharField("etapa", max_length=6, choices=Projeto.ETAPAS)
    ano = models.PositiveIntegerField("ano")
    periodo = models.PositiveSmallIntegerField("período", choices=PERIODOS)
    limite = models.PositiveSmallIntegerField("limite")
    justificativa = models.TextField("justificativa")
    autorizado_por = models.ForeignKey(
        Usuario,
        on_delete=models.PROTECT,
        related_name="limites_concedidos",
        verbose_name="autorizado por",
    )
    criado_em = models.DateTimeField("criado em", auto_now_add=True)

    class Meta:
        verbose_name = "limite de orientação"
        verbose_name_plural = "limites de orientação"
        ordering = ["-criado_em"]
        constraints = [
            models.UniqueConstraint(
                fields=["professor", "etapa", "ano", "periodo"],
                name="limite_unico_por_professor_etapa_e_semestre",
            ),
            # ">" e não ">=": este modelo só existe para autorizar exceção PARA
            # CIMA ao teto padrão de 3 vagas. Restringir o teto para baixo seria
            # outra funcionalidade, com outras perguntas (quem pode reduzir? o
            # que acontece com quem já está acima do novo teto?) — e um
            # "limite" de 2 ou 3 gravado por engano travaria aceites que
            # deveriam ser permitidos, em silêncio. O "3" é literal, não
            # importado de LIMITE_PADRAO_VAGAS (apps/projetos/services.py):
            # models.py não pode depender de services.py (tests/test_arquitetura.py).
            models.CheckConstraint(condition=Q(limite__gt=3), name="limite_maior_que_padrao"),
        ]

    def __str__(self):
        return (
            f"{self.professor} — {self.get_etapa_display()} ({self.ano}/{self.periodo}): "
            f"{self.limite}"
        )
