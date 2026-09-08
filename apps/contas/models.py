from django.contrib.auth.models import AbstractBaseUser, BaseUserManager, PermissionsMixin
from django.db import models
from django.db.models import Q

from apps.comum.validators import valida_extensao_imagem, valida_tamanho_arquivo
from apps.contas.validators import valida_cpf


class GerenciadorUsuario(BaseUserManager):
    use_in_migrations = True

    def _criar(self, email, password, **extra):
        if not email:
            raise ValueError("O e-mail é obrigatório.")
        usuario = self.model(email=self.normalize_email(email), **extra)
        usuario.set_password(password)
        usuario.save(using=self._db)
        return usuario

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
