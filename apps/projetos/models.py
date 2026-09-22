from django.db import models
from django.db.models import Q

from apps.comum.validators import (
    valida_extensao_editavel,
    valida_extensao_pdf,
    valida_tamanho_arquivo,
)
from apps.contas.models import Area, PerfilAluno, PerfilProfessor, Usuario

# Compartilhado por Projeto e LimiteOrientacao: o semestre gravado é sempre o
# par (ano, período), e período só assume 1 ou 2 (spec §3.4).
PERIODOS = [(1, "1º"), (2, "2º")]

# Única lista de status TERMINAIS de `Projeto` (achado C4 da auditoria,
# 2026-09-22). Módulo, não atributo de classe: `Projeto.Meta.constraints`
# roda dentro de um `class Meta:` ANINHADO, que não enxerga o corpo da
# classe externa por nome (só o escopo do módulo) — por isso o
# `UniqueConstraint` original já usava literais soltos, não
# `Projeto.CONCLUIDO` etc. Um valor de módulo é a única forma de a
# constraint E as funções de `services.py` (`_possui_projeto_ativo`,
# `projeto_ativo_do_aluno`) compartilharem a MESMA lista sem duplicar —
# antes, `services.py` excluía só `CONCLUIDO`/`REPROVADO` (esquecido quando
# `CANCELADO` foi acrescentado na migração 0004), e um aluno com projeto
# `CANCELADO` ficava lido como se ainda tivesse uma orientação ativa,
# travado para sempre — mesmo o banco já permitindo uma nova candidatura.
STATUS_TERMINAIS_PROJETO = ["CONCLUIDO", "REPROVADO", "CANCELADO"]


class Tema(models.Model):
    professor = models.ForeignKey(
        PerfilProfessor,
        # PROTECT, não CASCADE: apagar o perfil de um professor não pode apagar,
        # em cascata, o histórico de temas que candidaturas antigas referenciam.
        on_delete=models.PROTECT,
        related_name="temas",
        verbose_name="professor",
    )
    # M2M, não FK (acréscimo posterior, pedido explícito do usuário: "área"
    # deveria deixar selecionar uma ou várias subáreas). Sem `on_delete`
    # (não existe pra M2M) — apagar uma `Area` só remove a linha de junção,
    # nunca o `Tema`; `PROTECT` na FK antiga não tinha equivalente aqui
    # porque nada mais depende de uma área específica do tema continuar
    # existindo (ao contrário de `professor`, que `OpcaoCandidatura`/
    # `Projeto` referenciam via o próprio `Tema`, não via a área dele).
    areas = models.ManyToManyField(
        Area,
        related_name="temas",
        verbose_name="áreas",
    )
    titulo = models.CharField("título", max_length=200)
    descricao = models.TextField("descrição")
    # SEM teto de vagas POR TEMA (decisão explícita do usuário, revertendo
    # uma tentativa anterior de `Tema.vagas`): o mesmo tema pode ser
    # associado a mais de um aluno livremente — quem limita é só o teto do
    # PROFESSOR (`LIMITE_PADRAO_VAGAS`/`LimiteOrientacao`, `services.py`).
    # Um segundo teto, por tema, confundia mais do que ajudava.
    # Desativar tira o tema do mural sem apagar histórico: candidaturas que já
    # apontam para ele continuam legíveis (spec §4.1) — e continua permitido
    # mesmo depois de algum aluno já ter escolhido o tema.
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
    CANCELADO = "CANCELADO"
    STATUS = [
        (EM_ANDAMENTO, "Em andamento"),
        (AGUARDANDO_DEFESA, "Aguardando defesa"),
        (APROVADO_COM_RESSALVAS, "Aprovado com ressalvas"),
        (APROVADO, "Aprovado"),
        (CONCLUIDO, "Concluído"),
        (REPROVADO, "Reprovado"),
        (CANCELADO, "Cancelado"),
    ]
    # Exposto como atributo de classe (`Projeto.STATUS_TERMINAIS`) para quem
    # ler de fora — a fonte real é o valor de módulo `STATUS_TERMINAIS_PROJETO`
    # acima, ver o comentário lá para o porquê.
    STATUS_TERMINAIS = STATUS_TERMINAIS_PROJETO

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
    # `max_length=32` (achado L2 da auditoria, 2026-09-22): era 22, ajuste
    # exato ao maior valor de `STATUS` sem folga — `apps.bancas.services
    # .registrar_resultado` grava `Banca.resultado` aqui sem tradução, e os
    # dois campos precisam ficar com o mesmo tamanho (ver o comentário em
    # `apps.bancas.models.Banca.resultado`).
    status = models.CharField("status", max_length=32, choices=STATUS, default=EM_ANDAMENTO)
    # Carimbo do semestre em que o projeto NASCEU (spec §3.4): dois inteiros,
    # congelados na criação. O semestre vigente muda a cada consulta a
    # apps.comum.semestre.semestre_vigente(); este par não muda nunca — se o
    # mês de corte for ajustado depois, as contagens de vaga já feitas não
    # mudam retroativamente.
    ano = models.PositiveIntegerField("ano")
    periodo = models.PositiveSmallIntegerField("período", choices=PERIODOS)
    anterior = models.ForeignKey(
        "self",
        # SET_NULL: apagar o TCC I não pode impedir a consulta ao TCC II
        # que restou — o vínculo é só um ponteiro histórico, não uma
        # dependência de integridade acadêmica.
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="proximos",
        verbose_name="projeto anterior",
    )
    coorientador = models.ForeignKey(
        PerfilProfessor,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="projetos_como_coorientador",
        verbose_name="coorientador",
    )
    coorientador_externo = models.CharField(
        "coorientador (externo)", max_length=200, blank=True, default=""
    )
    criado_em = models.DateTimeField("criado em", auto_now_add=True)

    class Meta:
        verbose_name = "projeto"
        verbose_name_plural = "projetos"
        ordering = ["-criado_em"]
        constraints = [
            # Um aluno só pode ter um projeto ATIVO por etapa — CONCLUIDO,
            # REPROVADO e CANCELADO (Bloco D) são estados terminais e ficam de
            # fora da condição, para que um TCC já encerrado não impeça o
            # aluno de iniciar outro na mesma etapa (ex.: reprovado e
            # reiniciando, ou cancelado e recomeçando).
            models.UniqueConstraint(
                fields=["aluno", "etapa"],
                condition=~Q(status__in=STATUS_TERMINAIS_PROJETO),
                name="projeto_ativo_unico_por_aluno_e_etapa",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(coorientador__isnull=True, coorientador_externo="")
                    | (models.Q(coorientador__isnull=False) & models.Q(coorientador_externo=""))
                    | (models.Q(coorientador__isnull=True) & ~models.Q(coorientador_externo=""))
                ),
                name="projeto_coorientador_nao_duplo",
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


class Candidatura(models.Model):
    """O pedido de um aluno por orientação: uma linha por tentativa, com até
    três alvos ordenados em `OpcaoCandidatura` (spec §4.2).

    É separada de `OpcaoCandidatura` porque o pedido tem um único status (isto
    é o que a trava abaixo protege), enquanto cada alvo tem seu próprio
    desfecho — juntá-los na mesma tabela obrigaria toda consulta por "pedido
    em curso" a agregar três linhas em vez de ler uma.
    """

    EM_CURSO = "EM_CURSO"
    ACEITA = "ACEITA"
    ESGOTADA = "ESGOTADA"
    CANCELADA = "CANCELADA"
    STATUS = [
        (EM_CURSO, "Em curso"),
        (ACEITA, "Aceita"),
        (ESGOTADA, "Esgotada"),
        (CANCELADA, "Cancelada"),
    ]

    aluno = models.ForeignKey(
        PerfilAluno,
        # PROTECT: o histórico de candidaturas de um aluno não pode ser
        # apagado em cascata só porque o perfil foi removido.
        on_delete=models.PROTECT,
        related_name="candidaturas",
        verbose_name="aluno",
    )
    # `choices` restringe o que formulário e admin aceitam, mas NÃO é trava de
    # banco: um INSERT feito fora do Django aceita qualquer string de até 9
    # caracteres. A trava real (uma única candidatura EM_CURSO por aluno) está
    # em Meta.constraints, abaixo.
    status = models.CharField("status", max_length=9, choices=STATUS, default=EM_CURSO)
    opcao_atual = models.PositiveSmallIntegerField(
        "opção atual", default=1, help_text="Ordem (1 a 3) em que a cascata de opções está."
    )
    # Carimbo do semestre em que o pedido nasceu — mesmo raciocínio de
    # congelamento do campo homônimo em Projeto.
    ano = models.PositiveIntegerField("ano")
    periodo = models.PositiveSmallIntegerField("período", choices=PERIODOS)
    criado_em = models.DateTimeField("criado em", auto_now_add=True)

    class Meta:
        verbose_name = "candidatura"
        verbose_name_plural = "candidaturas"
        ordering = ["-criado_em"]
        constraints = [
            # Impede dois pedidos simultâneos do mesmo aluno: índice único
            # parcial, só sobre as linhas EM_CURSO — candidaturas já
            # encerradas (aceita, esgotada, cancelada) ficam de fora da
            # condição, para não impedir um novo pedido depois que o anterior
            # terminou.
            models.UniqueConstraint(
                fields=["aluno"],
                condition=Q(status="EM_CURSO"),
                name="candidatura_em_curso_unica_por_aluno",
            ),
        ]

    def __str__(self):
        return f"{self.aluno} — {self.get_status_display()} ({self.ano}/{self.periodo})"


class OpcaoCandidatura(models.Model):
    """Um alvo ordenado dentro de uma `Candidatura`: até três por pedido, cada
    um com seu próprio professor, tema (opcional) e desfecho (spec §4.3).
    """

    AGUARDANDO = "AGUARDANDO"
    ENVIADA = "ENVIADA"
    ACEITA = "ACEITA"
    RECUSADA = "RECUSADA"
    EXPIRADA = "EXPIRADA"
    CANCELADA = "CANCELADA"
    SITUACOES = [
        (AGUARDANDO, "Aguardando"),
        (ENVIADA, "Enviada"),
        (ACEITA, "Aceita"),
        (RECUSADA, "Recusada"),
        (EXPIRADA, "Expirada"),
        (CANCELADA, "Cancelada"),
    ]

    candidatura = models.ForeignKey(
        Candidatura,
        # CASCADE: uma opção só existe enquanto pertencer a um pedido; apagar
        # a candidatura apaga seus até três alvos junto.
        on_delete=models.CASCADE,
        related_name="opcoes",
        verbose_name="candidatura",
    )
    ordem = models.PositiveSmallIntegerField("ordem")
    professor = models.ForeignKey(
        PerfilProfessor,
        on_delete=models.PROTECT,
        related_name="opcoes_recebidas",
        verbose_name="professor",
    )
    # Nulo = "aberto a temas": o aluno pede este professor sem escolher um
    # tema publicado por ele. PROTECT: um tema referenciado por uma opção não
    # pode ser apagado por baixo do histórico do pedido.
    tema = models.ForeignKey(
        Tema,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="opcoes",
        verbose_name="tema",
    )
    # Mesma ressalva do `status` de Candidatura: `choices` não é trava de banco.
    situacao = models.CharField("situação", max_length=10, choices=SITUACOES, default=AGUARDANDO)
    enviada_em = models.DateTimeField("enviada em", null=True, blank=True)
    prazo = models.DateTimeField("prazo", null=True, blank=True)
    respondida_em = models.DateTimeField("respondida em", null=True, blank=True)
    justificativa = models.TextField("justificativa", blank=True)

    class Meta:
        verbose_name = "opção de candidatura"
        verbose_name_plural = "opções de candidatura"
        ordering = ["candidatura", "ordem"]
        constraints = [
            # Impede duas "primeiras opções" (ou segundas, ou terceiras) na
            # mesma candidatura.
            models.UniqueConstraint(
                fields=["candidatura", "ordem"], name="opcao_ordem_unica_por_candidatura"
            ),
            # Impede uma quarta opção entrando por qualquer caminho —
            # inclusive um INSERT que não passe pela camada de serviço.
            models.CheckConstraint(
                condition=Q(ordem__gte=1) & Q(ordem__lte=3),
                name="opcao_ordem_entre_um_e_tres",
            ),
            # A trava "tema pertence ao professor da opção" NÃO está aqui: um
            # CheckConstraint do Postgres não pode consultar outra tabela —
            # uma condição como Q(tema__professor=F("professor")) levanta
            # django.core.exceptions.FieldError ("Joined field references are
            # not permitted in this query") ao tentar aplicar a migração,
            # verificado manualmente antes de escrever este modelo. Por isso
            # essa trava é uma TRIGGER de banco, criada na migração 0002 via
            # RunSQL (ver migrations/0002_candidatura_opcaocandidatura.py) e
            # sem depender de clean()/formulário, que só roda quando alguém
            # chama full_clean() explicitamente.
            #
            # LIMITE da trigger: ela observa INSERT/UPDATE em
            # OpcaoCandidatura, não em Tema. Um UPDATE que troque
            # Tema.professor não é visto por ela e quebra o invariante
            # retroativamente em toda opção já gravada apontando para aquele
            # tema — TemaAdmin.get_readonly_fields (apps/projetos/admin.py)
            # fecha esse caminho pelo admin, mas um UPDATE direto por SQL ou
            # shell continua passando. Fechar de vez exigiria uma trigger
            # espelhada em projetos_tema (revalidando as opções dependentes)
            # ou a FK composta (tema_id, professor_id) contra um
            # UniqueConstraint(id, professor) em Tema — nenhuma das duas
            # implementada aqui.
        ]

    def __str__(self):
        return f"{self.candidatura} — opção {self.ordem} ({self.get_situacao_display()})"


class Submissao(models.Model):
    """O trabalho escrito que o aluno entrega para a banca (Bloco C, spec
    §4.1) — uma linha por `Projeto`, não uma tabela de histórico: reenviar
    ATUALIZA esta mesma linha, substituindo os arquivos e incrementando
    `versao`. A versão anterior não fica acessível pelo sistema depois de
    substituída — decisão do usuário, ciente do custo (sem histórico para
    auditar depois de uma correção). Ver `services.enviar_submissao`.
    """

    projeto = models.OneToOneField(
        Projeto,
        # PROTECT: apagar o Projeto não pode arrastar a submissão em
        # cascata, mesmo raciocínio de Candidatura.aluno/OpcaoCandidatura.tema
        # no Bloco B.
        on_delete=models.PROTECT,
        related_name="submissao",
        verbose_name="projeto",
    )
    pdf = models.FileField(
        "PDF",
        upload_to="submissoes/",
        validators=[valida_extensao_pdf, valida_tamanho_arquivo],
    )
    editavel = models.FileField(
        "editável",
        upload_to="submissoes/",
        validators=[valida_extensao_editavel, valida_tamanho_arquivo],
    )
    versao = models.PositiveSmallIntegerField("versão", default=1)
    enviada_em = models.DateTimeField("enviada em", auto_now_add=True)
    atualizada_em = models.DateTimeField("atualizada em", auto_now=True)

    class Meta:
        verbose_name = "submissão"
        verbose_name_plural = "submissões"

    def __str__(self):
        return f"{self.projeto} — versão {self.versao}"


class TermoPublicacao(models.Model):
    """Aceite de publicação do TCC II no catálogo público — a EXISTÊNCIA da
    linha já significa "assinado" (Bloco F, spec §3.4): sem campo booleano
    redundante, sem estado intermediário. Ao contrário de `RevisaoSUGRAD`
    (Bloco E), que pode ser revisitada, assinar o termo é uma ação única,
    sem volta.
    """

    projeto = models.OneToOneField(
        Projeto,
        on_delete=models.PROTECT,
        related_name="termo_publicacao",
        verbose_name="projeto",
    )
    assinado_em = models.DateTimeField("assinado em", auto_now_add=True)

    class Meta:
        verbose_name = "termo de publicação"
        verbose_name_plural = "termos de publicação"

    def __str__(self):
        return f"Termo de {self.projeto} — assinado em {self.assinado_em:%d/%m/%Y}"
