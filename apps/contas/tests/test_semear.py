import re
from pathlib import Path

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from apps.contas.models import Usuario
from apps.contas.validators import valida_cpf

RAIZ = Path(__file__).resolve().parents[3]

ARGUMENTOS = [
    "--email-coordenador",
    "coord@ufsm.br",
    "--nome-coordenador",
    "Coordenação do Curso",
    "--cpf-coordenador",
    "52998224725",
    "--email-sugrad",
    "sugrad@ufsm.br",
]


@pytest.mark.django_db
def test_semear_cria_sugrad_e_coordenador():
    call_command("semear_sistema", *ARGUMENTOS)

    coordenadora = Usuario.objects.get(email="coord@ufsm.br")
    assert coordenadora.is_coordenador is True
    assert coordenadora.is_staff is True
    assert coordenadora.papel == Usuario.PROFESSOR

    sugrad = Usuario.objects.get(email="sugrad@ufsm.br")
    assert sugrad.papel == Usuario.SUGRAD
    assert sugrad.cpf is None


@pytest.mark.django_db
def test_semear_e_idempotente():
    call_command("semear_sistema", *ARGUMENTOS)
    call_command("semear_sistema", *ARGUMENTOS)

    assert Usuario.objects.filter(email="coord@ufsm.br").count() == 1
    assert Usuario.objects.filter(papel=Usuario.SUGRAD).count() == 1


@pytest.mark.django_db
def test_semear_nao_rebaixa_quem_ja_e_coordenador():
    call_command("semear_sistema", *ARGUMENTOS)
    outra = Usuario.objects.create_user(
        email="outra@ufsm.br",
        password="x",
        nome_completo="Outra",
        cpf="16899535009",
        is_coordenador=True,
        is_staff=True,
    )

    call_command("semear_sistema", *ARGUMENTOS)

    outra.refresh_from_db()
    assert outra.is_coordenador is True


@pytest.mark.django_db
def test_semear_recusa_novo_coordenador_quando_ja_existe_um():
    # Regra de negócio inegociável nº 2 (CLAUDE.md): quem nomeia coordenadores
    # depois do primeiro é o painel da coordenação, não semear_sistema. Sem
    # esta recusa, rodar o comando de novo num sistema já em uso, com um
    # --email-coordenador diferente, promoveria mais uma pessoa sem passar
    # pelo teto de 4 — o comando nunca o consulta.
    call_command("semear_sistema", *ARGUMENTOS)

    outros_argumentos = [
        "--email-coordenador",
        "novo@ufsm.br",
        "--nome-coordenador",
        "Outra Pessoa",
        "--cpf-coordenador",
        "16899535009",
        "--email-sugrad",
        "sugrad@ufsm.br",
    ]
    with pytest.raises(CommandError):
        call_command("semear_sistema", *outros_argumentos)

    # Nem a conta chegou a ser criada: a recusa acontece antes da criação,
    # então não sobra um professor comum "esquecido" pela metade.
    assert not Usuario.objects.filter(email="novo@ufsm.br").exists()
    assert Usuario.objects.filter(papel=Usuario.PROFESSOR, is_coordenador=True).count() == 1


@pytest.mark.django_db
def test_semear_encontra_coordenador_por_email_mesmo_com_grafia_diferente():
    # A busca do coordenador é __iexact (services.convidar e
    # GerenciadorUsuario.get_by_natural_key seguem o mesmo padrão): sem isto,
    # rodar o comando de novo com outra grafia do mesmo e-mail colidiria no
    # unique=True do banco com um IntegrityError que o comando relataria,
    # errado, como CPF duplicado.
    call_command("semear_sistema", *ARGUMENTOS)

    outra_grafia = [
        "--email-coordenador",
        "COORD@UFSM.BR",
        "--nome-coordenador",
        "Coordenação do Curso",
        "--cpf-coordenador",
        "52998224725",
        "--email-sugrad",
        "sugrad@ufsm.br",
    ]
    call_command("semear_sistema", *outra_grafia)

    assert Usuario.objects.filter(email__iexact="coord@ufsm.br").count() == 1
    coordenadora = Usuario.objects.get(email__iexact="coord@ufsm.br")
    assert coordenadora.is_coordenador is True


@pytest.mark.django_db
def test_semear_recusa_papel_incompativel_com_coordenacao():
    # O e-mail do coordenador já pertence a uma conta ALUNO: promovê-la
    # esbarraria na constraint `coordenador_e_professor` (models.py) com um
    # IntegrityError opaco. O comando precisa falhar antes, com uma
    # mensagem que diga o que está errado.
    Usuario.objects.create_user(
        email="coord@ufsm.br",
        password="x",
        nome_completo="Já é aluno",
        cpf="16899535009",
        papel=Usuario.ALUNO,
    )

    with pytest.raises(CommandError):
        call_command("semear_sistema", *ARGUMENTOS)


@pytest.mark.django_db
def test_semear_converte_integrity_error_em_command_error():
    # CPF do coordenador já usado por outra conta (e-mail diferente, então a
    # busca __iexact não a encontra e o comando tenta criar uma conta nova,
    # que esbarra no unique=True de cpf). Isto precisa terminar em
    # CommandError, não num IntegrityError cru sem contexto para quem
    # instala o sistema.
    Usuario.objects.create_user(
        email="alguem@ufsm.br",
        password="x",
        nome_completo="Já usa este CPF",
        cpf="52998224725",
        papel=Usuario.PROFESSOR,
    )

    with pytest.raises(CommandError):
        call_command("semear_sistema", *ARGUMENTOS)

    # Atômico: nem a SUGRAD deveria ter sobrado, já que o comando falhou.
    assert not Usuario.objects.filter(papel=Usuario.SUGRAD).exists()


@pytest.mark.django_db
def test_semear_recusa_cpf_invalido():
    """`valida_cpf` está declarado em `Usuario.cpf.validators`, mas validator
    de model só roda em `full_clean()` — que nem `Usuario.objects.create()`
    nem `GerenciadorUsuario._criar` chamam. O comando não conferia nada, e o
    README mandava semear com `00000000000`, uma das `SEQUENCIAS_INVALIDAS`
    do próprio validator: o primeiro coordenador do sistema nascia com CPF
    inválido, seguindo a documentação (achado da revisão final)."""
    argumentos = [
        "--email-coordenador",
        "coord@ufsm.br",
        "--nome-coordenador",
        "Coordenação do Curso",
        "--cpf-coordenador",
        "00000000000",
        "--email-sugrad",
        "sugrad@ufsm.br",
    ]

    with pytest.raises(CommandError) as erro:
        call_command("semear_sistema", *argumentos)

    assert "CPF" in str(erro.value)
    # Atômico e cedo: nem a conta da SUGRAD chega a ser criada.
    assert not Usuario.objects.exists()


def test_readme_documenta_um_cpf_valido():
    """O exemplo do README é copiado e colado por quem instala o sistema — se
    ele traz um CPF que o validator recusa, a primeira instalação falha."""
    readme = (RAIZ / "README.md").read_text(encoding="utf-8")
    cpf = re.search(r"--cpf-coordenador (\d+)", readme).group(1)
    valida_cpf(cpf)
