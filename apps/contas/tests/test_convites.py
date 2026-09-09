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
    # O token em claro só existe no corpo do e-mail.
    assert convite.token_hash not in mail.outbox[0].body


@pytest.mark.django_db
def test_convidar_envia_email_com_o_link(coordenadora, envia_convite):
    envia_convite("novo@ufsm.br", Usuario.ALUNO, por=coordenadora)

    assert len(mail.outbox) == 1
    assert "novo@ufsm.br" in mail.outbox[0].to
    assert "/convite/" in mail.outbox[0].body


@pytest.mark.django_db
def test_so_coordenador_convida(professor):
    with pytest.raises(PermissionDenied):
        services.convidar("novo@ufsm.br", Usuario.ALUNO, por=professor)


@pytest.mark.django_db
def test_recusa_convite_para_email_ja_cadastrado(coordenadora, professor):
    with pytest.raises(ValidationError):
        services.convidar(professor.email, Usuario.PROFESSOR, por=coordenadora)


@pytest.mark.django_db
def test_recusa_segundo_convite_ativo_para_o_mesmo_email(coordenadora, envia_convite):
    envia_convite("novo@ufsm.br", Usuario.ALUNO, por=coordenadora)
    with pytest.raises(ValidationError):
        services.convidar("novo@ufsm.br", Usuario.ALUNO, por=coordenadora)


@pytest.mark.django_db
def test_reenviar_invalida_o_convite_anterior(
    coordenadora, envia_convite, django_capture_on_commit_callbacks
):
    primeiro = envia_convite("novo@ufsm.br", Usuario.ALUNO, por=coordenadora)
    hash_antigo = primeiro.token_hash

    with django_capture_on_commit_callbacks(execute=True):
        segundo = services.reenviar_convite(primeiro, por=coordenadora)

    assert segundo.token_hash != hash_antigo
    assert not Convite.objects.filter(token_hash=hash_antigo, usado_em__isnull=True).exists()
    assert len(mail.outbox) == 2


@pytest.mark.django_db
def test_convite_expirado_nao_e_valido(coordenadora, envia_convite):
    convite = envia_convite("novo@ufsm.br", Usuario.ALUNO, por=coordenadora)
    convite.expira_em = timezone.now() - timezone.timedelta(seconds=1)
    convite.save(update_fields=["expira_em"])

    assert not convite.esta_valido()
