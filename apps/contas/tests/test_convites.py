import hashlib
import re

import pytest
from django.core import mail
from django.core.exceptions import PermissionDenied, ValidationError
from django.utils import timezone

from apps.contas import services
from apps.contas.models import Convite, Usuario


@pytest.fixture
def coordenadora(db):
    return Usuario.objects.create_user(
        email="coord@ufsm.br",
        password="x",
        nome_completo="Coordenadora",
        cpf="52998224725",
        is_coordenador=True,
        is_staff=True,
    )


@pytest.fixture
def professor(db):
    return Usuario.objects.create_user(
        email="prof@ufsm.br", password="x", nome_completo="Professor", cpf="16899535009"
    )


# services.convidar enfileira o e-mail em transaction.on_commit, e o pytest-django
# reverte a transacao de cada teste: sem capturar os callbacks, o on_commit nunca
# dispara e mail.outbox fica vazio. A fixture abaixo executa os callbacks pendentes.
@pytest.fixture
def envia_convite(settings, django_capture_on_commit_callbacks):
    settings.CELERY_TASK_ALWAYS_EAGER = True

    def _envia(*args, **kwargs):
        with django_capture_on_commit_callbacks(execute=True):
            return services.convidar(*args, **kwargs)

    return _envia


@pytest.mark.django_db
def test_convidar_grava_o_hash_e_nunca_o_token_em_claro(coordenadora, envia_convite):
    convite = envia_convite("novo@ufsm.br", Usuario.ALUNO, por=coordenadora)

    assert convite.email == "novo@ufsm.br"
    assert convite.usado_em is None
    assert convite.esta_valido()
    assert len(convite.token_hash) == 64

    corpo = mail.outbox[0].body
    token = re.search(r"/convite/([\w-]+)/", corpo).group(1)
    # O hash gravado corresponde ao token realmente enviado...
    assert hashlib.sha256(token.encode()).hexdigest() == convite.token_hash
    # ...e o token em claro não aparece persistido em nenhum campo da linha.
    valores_gravados = Convite.objects.filter(pk=convite.pk).values()[0]
    assert token not in valores_gravados.values()


@pytest.mark.django_db
def test_convidar_envia_email_com_o_link(coordenadora, envia_convite, settings):
    envia_convite("novo@ufsm.br", Usuario.ALUNO, por=coordenadora)

    assert len(mail.outbox) == 1
    assert "novo@ufsm.br" in mail.outbox[0].to
    # O link é absoluto: usa URL_BASE, não só o caminho relativo.
    assert f"{settings.URL_BASE}/convite/" in mail.outbox[0].body


@pytest.mark.django_db
def test_so_coordenador_convida(professor):
    with pytest.raises(PermissionDenied):
        services.convidar("novo@ufsm.br", Usuario.ALUNO, por=professor)


@pytest.mark.django_db
def test_recusa_papel_invalido_para_convite(coordenadora):
    # SUGRAD não é convidável: a conta do setor é semeada, nunca convidada.
    with pytest.raises(ValidationError):
        services.convidar("novo@ufsm.br", Usuario.SUGRAD, por=coordenadora)


@pytest.mark.django_db
def test_recusa_convite_para_email_ja_cadastrado(coordenadora, professor):
    with pytest.raises(ValidationError):
        services.convidar(professor.email, Usuario.PROFESSOR, por=coordenadora)


@pytest.mark.django_db
def test_recusa_convite_para_email_ja_cadastrado_com_caixa_diferente(coordenadora):
    Usuario.objects.create_user(
        email="fulano@ufsm.br", password="x", nome_completo="Fulano", cpf="11144477735"
    )

    with pytest.raises(ValidationError):
        services.convidar("FULANO@UFSM.BR", Usuario.PROFESSOR, por=coordenadora)


@pytest.mark.django_db
def test_usuario_e_gravado_com_email_em_minusculas():
    usuario = Usuario.objects.create_user(
        email="Fulano.DeTal@UFSM.br",
        password="x",
        nome_completo="Fulano de Tal",
        cpf="12345678909",
    )

    assert usuario.email == "fulano.detal@ufsm.br"


@pytest.mark.django_db
def test_recusa_segundo_convite_ativo_para_o_mesmo_email(coordenadora, envia_convite):
    envia_convite("novo@ufsm.br", Usuario.ALUNO, por=coordenadora)
    with pytest.raises(ValidationError):
        services.convidar("novo@ufsm.br", Usuario.ALUNO, por=coordenadora)


@pytest.mark.django_db
def test_permite_novo_convite_apos_expiracao(coordenadora, envia_convite):
    primeiro = envia_convite("novo@ufsm.br", Usuario.ALUNO, por=coordenadora)
    primeiro.expira_em = timezone.now() - timezone.timedelta(seconds=1)
    primeiro.save(update_fields=["expira_em"])

    segundo = envia_convite("novo@ufsm.br", Usuario.ALUNO, por=coordenadora)

    assert segundo.pk != primeiro.pk
    assert len(mail.outbox) == 2


@pytest.mark.django_db
def test_reenviar_invalida_o_convite_anterior(
    coordenadora, envia_convite, django_capture_on_commit_callbacks
):
    primeiro = envia_convite("novo@ufsm.br", Usuario.ALUNO, por=coordenadora)

    with django_capture_on_commit_callbacks(execute=True):
        segundo = services.reenviar_convite(primeiro, por=coordenadora)

    primeiro.refresh_from_db()
    assert segundo.token_hash != primeiro.token_hash
    assert not primeiro.esta_valido()
    assert len(mail.outbox) == 2


@pytest.mark.django_db
def test_so_coordenador_reenvia(coordenadora, professor, envia_convite):
    convite = envia_convite("novo@ufsm.br", Usuario.ALUNO, por=coordenadora)

    with pytest.raises(PermissionDenied):
        services.reenviar_convite(convite, por=professor)


@pytest.mark.django_db
def test_recusa_reenviar_convite_ja_usado(coordenadora, envia_convite):
    convite = envia_convite("novo@ufsm.br", Usuario.ALUNO, por=coordenadora)
    convite.usado_em = timezone.now()
    convite.save(update_fields=["usado_em"])

    with pytest.raises(ValidationError):
        services.reenviar_convite(convite, por=coordenadora)


@pytest.mark.django_db
def test_convite_expirado_nao_e_valido(coordenadora, envia_convite):
    convite = envia_convite("novo@ufsm.br", Usuario.ALUNO, por=coordenadora)
    convite.expira_em = timezone.now() - timezone.timedelta(seconds=1)
    convite.save(update_fields=["expira_em"])

    assert not convite.esta_valido()
