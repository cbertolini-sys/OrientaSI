from django.contrib.auth.models import AbstractBaseUser, BaseUserManager, PermissionsMixin
from django.db import models
from django.db.models import Q
from django.utils import timezone

from apps.comum.validators import valida_extensao_imagem, valida_tamanho_arquivo
from apps.contas.validators import valida_cpf


class GerenciadorUsuario(BaseUserManager):
    use_in_migrations = True

    def _criar(self, email, password, **extra):
        if not email:
            raise ValueError("O e-mail é obrigatório.")
        # E-mail é o identificador de login (USERNAME_FIELD): minusculizamos o
        # endereço inteiro, não só o domínio como normalize_email faz sozinho,
        # porque nenhum provedor real trata "Prof@" e "prof@" como contas
        # diferentes — sem isto, duas grafias da mesma pessoa passariam pelo
        # unique=True e criariam contas duplicadas.
        usuario = self.model(email=self.normalize_email(email).lower(), **extra)
        usuario.set_password(password)
        usuario.save(using=self._db)
        return usuario

    def get_by_natural_key(self, email):
        # O Django chama este método em todo backend de autenticação (login,
        # recuperação de senha etc.) para localizar o usuário pelo
        # USERNAME_FIELD. A implementação padrão (BaseUserManager) faz busca
        # exata, mas `_criar` grava o e-mail inteiro em minúsculas — então
        # quem se cadastrou como "Ana@ufsm.br" está gravado como
        # "ana@ufsm.br", e digitar o e-mail com maiúsculas no login não
        # encontraria a conta sem esta sobrescrita.
        try:
            return self.get(**{f"{self.model.USERNAME_FIELD}__iexact": email})
        except self.model.MultipleObjectsReturned:
            # Defesa em profundidade: o sinal `normaliza_email_do_usuario`
            # (apps/contas/signals.py) impede gravações novas com grafias
            # duplicadas, mas não apaga duplicatas que já existissem no
            # banco antes dele existir. Cair para a busca exata evita um 500
            # imprevisível (achado na revisão 1 da T9) e autentica quem
            # digitou a grafia exatamente como está gravada; quem digitar
            # outra grafia recebe a mensagem normal de credenciais
            # inválidas, não um erro de servidor.
            return self.get(**{self.model.USERNAME_FIELD: email})

    def create_user(self, email, password=None, **extra):
        extra.setdefault("papel", Usuario.PROFESSOR)
        extra.setdefault("is_staff", False)
        extra.setdefault("is_superuser", False)
        return self._criar(email, password, **extra)

    def create_superuser(self, email, password, **extra):
        extra.setdefault("papel", Usuario.PROFESSOR)
        extra["is_staff"] = True
        extra["is_superuser"] = True
        return self._criar(email, password, **extra)


class Usuario(AbstractBaseUser, PermissionsMixin):
    ALUNO = "ALUNO"
    PROFESSOR = "PROFESSOR"
    SUGRAD = "SUGRAD"
    PAPEIS = [(ALUNO, "Aluno"), (PROFESSOR, "Professor"), (SUGRAD, "SUGRAD")]

    email = models.EmailField("e-mail", unique=True)
    nome_completo = models.CharField("nome completo", max_length=200)
    cpf = models.CharField(
        "CPF", max_length=11, unique=True, null=True, blank=True, validators=[valida_cpf]
    )
    telefone = models.CharField("telefone", max_length=20, blank=True)
    foto = models.ImageField(
        "foto",
        upload_to="fotos/",
        blank=True,
        validators=[valida_extensao_imagem, valida_tamanho_arquivo],
    )
    papel = models.CharField("papel", max_length=10, choices=PAPEIS, default=PROFESSOR)
    is_coordenador = models.BooleanField("é coordenador", default=False)
    is_active = models.BooleanField("ativo", default=True)
    is_staff = models.BooleanField("acessa o admin", default=False)
    criado_em = models.DateTimeField("criado em", auto_now_add=True)

    objects = GerenciadorUsuario()

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = ["nome_completo", "cpf"]

    class Meta:
        verbose_name = "usuário"
        verbose_name_plural = "usuários"
        ordering = ["nome_completo"]
        constraints = [
            # A conta da SUGRAD é um setor, não uma pessoa, e não tem CPF.
            # O reforço "& ~Q(cpf='')" existe porque blank=True permite que o
            # admin grave "" em vez de None, e "" satisfaz cpf__isnull=False.
            models.CheckConstraint(
                condition=Q(papel="SUGRAD") | (Q(cpf__isnull=False) & ~Q(cpf="")),
                name="cpf_obrigatorio_para_pessoas",
            ),
            # Índice parcial: o banco recusa a segunda conta SUGRAD (spec §5.1).
            models.UniqueConstraint(
                fields=["papel"], condition=Q(papel="SUGRAD"), name="conta_sugrad_unica"
            ),
            models.CheckConstraint(
                condition=Q(is_coordenador=False) | Q(papel="PROFESSOR"),
                name="coordenador_e_professor",
            ),
        ]

    def __str__(self):
        return f"{self.nome_completo} <{self.email}>"


class Area(models.Model):
    """Vocabulário controlado de áreas de atuação, mantido pela coordenação.

    Vive em contas e não em projetos porque é a única direção acíclica: projetos
    já dependerá de contas (todo projeto aponta para um Usuario). Spec §5.4.
    """

    nome = models.CharField("nome", max_length=120, unique=True)
    descricao = models.TextField("descrição", blank=True)
    # Terminologia CNPq/CAPES real (corrigida a pedido do usuário — a
    # primeira versão desta hierarquia invertia os nomes): a tabela tem 4
    # ÁREAS (Teoria da Computação, Matemática da Computação, Metodologia e
    # Técnicas da Computação, Sistemas de Computação), cada uma com uma ou
    # mais SUBÁREAS (16 ao todo — ver a migração de dados). Uma linha de
    # `Area` que É uma subárea aponta pra sua área via este campo; uma linha
    # que É uma área (de topo) deixa `area=None`. `related_name="subareas"`
    # é o que permite `area.subareas.all()` a partir de uma área de topo.
    area = models.ForeignKey(
        "self",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="subareas",
        verbose_name="área",
        help_text="Área à qual esta subárea pertence (vazio para uma área em si).",
    )
    # `default=1000`: mantém as 20 áreas do CNPq/CAPES (ordem 1-20, ver a
    # migração de dados) sempre à frente de qualquer área futura criada pela
    # coordenação via /admin/ sem `ordem` explícita — estas caem no fim da
    # lista, ordenadas por nome entre si (empate no `Meta.ordering` abaixo).
    ordem = models.PositiveSmallIntegerField("ordem de exibição", default=1000)

    class Meta:
        verbose_name = "área"
        verbose_name_plural = "áreas"
        ordering = ["ordem", "nome"]

    def __str__(self):
        return self.nome


class PerfilAluno(models.Model):
    usuario = models.OneToOneField(
        Usuario,
        on_delete=models.CASCADE,
        related_name="perfil_aluno",
        verbose_name="usuário",
    )
    matricula = models.CharField("matrícula", max_length=20, unique=True)

    class Meta:
        verbose_name = "perfil de aluno"
        verbose_name_plural = "perfis de alunos"

    def __str__(self):
        return f"{self.usuario.nome_completo} ({self.matricula})"


class PerfilProfessor(models.Model):
    usuario = models.OneToOneField(
        Usuario,
        on_delete=models.CASCADE,
        related_name="perfil_professor",
        verbose_name="usuário",
    )
    siape = models.CharField("SIAPE", max_length=20, unique=True)
    areas = models.ManyToManyField(
        Area,
        blank=True,
        related_name="professores",
        verbose_name="áreas de atuação",
    )

    class Meta:
        verbose_name = "perfil de professor"
        verbose_name_plural = "perfis de professores"

    def __str__(self):
        return f"{self.usuario.nome_completo} (SIAPE {self.siape})"


class Convite(models.Model):
    PAPEIS_CONVIDAVEIS = [(Usuario.ALUNO, "Aluno"), (Usuario.PROFESSOR, "Professor")]

    # Índice porque o serviço filtra por e-mail a cada convite novo (checagem
    # de convite ativo) — sem índice, essa consulta varre a tabela inteira a
    # cada convidar().
    #
    # O comentário original desta linha estava factualmente errado, e o erro
    # custou uma migração (0005): ele afirmava que o índice servia a uma
    # consulta que na época era `email__iexact`, e um índice B-tree simples
    # NÃO é usado por `email__iexact` — o Postgres traduz isso para
    # `UPPER("email") = UPPER(%s)`, que só um índice funcional sobre
    # `UPPER(email)` atenderia. A correção (revisão final) foi na consulta,
    # não no índice: `services.convidar` já normaliza o e-mail para
    # minúsculas antes de gravar, e o sinal `normaliza_email_do_usuario`
    # (signals.py) garante o mesmo para `Usuario.email`, então a busca pode
    # ser por igualdade exata — que é exatamente o que este índice serve.
    email = models.EmailField("e-mail", db_index=True)
    papel = models.CharField("papel", max_length=10, choices=PAPEIS_CONVIDAVEIS)
    # Guardamos o hash, nunca o token em claro: se o banco vazar, os convites
    # pendentes não são utilizáveis (spec §5.5).
    token_hash = models.CharField("hash do token", max_length=64, unique=True)
    criado_por = models.ForeignKey(
        Usuario,
        on_delete=models.PROTECT,
        related_name="convites_enviados",
        verbose_name="criado por",
    )
    criado_em = models.DateTimeField("criado em", auto_now_add=True)
    expira_em = models.DateTimeField("expira em")
    usado_em = models.DateTimeField("usado em", null=True, blank=True)
    usuario_criado = models.OneToOneField(
        Usuario,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="convite_de_origem",
        verbose_name="usuário criado",
    )

    class Meta:
        verbose_name = "convite"
        verbose_name_plural = "convites"
        ordering = ["-criado_em"]

    def __str__(self):
        return f"Convite para {self.email} ({self.get_papel_display()})"

    def esta_valido(self):
        return self.usado_em is None and self.expira_em > timezone.now()
