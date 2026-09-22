import pytest
from django.urls import reverse

from apps.contas.admin import FormularioCriacaoUsuario
from apps.contas.models import Usuario


@pytest.mark.django_db
def test_admin_nao_permite_promover_coordenador_direto_na_edicao(client):
    """ACHADO H3 da auditoria (2026-09-22): sem `is_coordenador` em
    `readonly_fields`, um staff com acesso a este modelo podia marcar
    `is_coordenador` direto no formulário, furando `LIMITE_COORDENADORES` e
    a trava do último coordenador — as duas vivem só em
    `services.promover_a_coordenador`/`revogar_coordenacao`. Prova por
    mutação: remover `is_coordenador` de `UsuarioAdmin.readonly_fields`
    faz este teste reprovar (o POST promoveria de verdade)."""
    superusuario = Usuario.objects.create_superuser(
        email="admin.h3@ufsm.br", password="x", nome_completo="Admin H3", cpf="12345678909"
    )
    alvo = Usuario.objects.create_user(
        email="alvo.h3@ufsm.br", password="x", nome_completo="Alvo H3", cpf="52998224725"
    )
    client.force_login(superusuario)

    url = reverse("admin:contas_usuario_change", args=[alvo.pk])
    resposta = client.post(
        url,
        {
            "email": alvo.email,
            "nome_completo": alvo.nome_completo,
            "cpf": alvo.cpf,
            "papel": Usuario.PROFESSOR,
            "is_coordenador": "on",
            "is_active": "on",
        },
        follow=True,
    )

    assert resposta.status_code == 200
    # A submissão precisa ter sido de fato aceita (sem erro de formulário
    # genérico barrando tudo) — senão o teste "passaria" mesmo sem a
    # proteção de `readonly_fields`, por um motivo totalmente alheio a
    # `is_coordenador`.
    assert "errornote" not in resposta.content.decode()
    alvo.refresh_from_db()
    assert alvo.is_coordenador is False


@pytest.mark.django_db
def test_admin_recusa_mudar_papel_de_coordenador_com_erro_de_formulario(client):
    """ACHADO F2 da re-auditoria (2026-09-22): H3 (achado acima) pôs
    `is_coordenador` em `readonly_fields`, mas o Django EXCLUI todo campo
    somente-leitura da validação de `Model.full_clean()` — a checagem do
    `CheckConstraint coordenador_e_professor` (que barrava, com erro de
    formulário legível, mudar o papel de um coordenador para ALUNO/SUGRAD)
    passou a ser pulada em silêncio, e a mesma ação virava um
    `IntegrityError` cru na gravação (500). Prova por mutação: remover o
    `clean()` de `FormularioEdicaoUsuario` faz este teste reprovar (o POST
    devolveria 500 em vez de reexibir o formulário com erro)."""
    superusuario = Usuario.objects.create_superuser(
        email="admin.f2@ufsm.br", password="x", nome_completo="Admin F2", cpf="12345678909"
    )
    coordenador = Usuario.objects.create_user(
        email="coord.f2@ufsm.br",
        password="x",
        nome_completo="Coordenador F2",
        cpf="52998224725",
        papel=Usuario.PROFESSOR,
        is_coordenador=True,
        is_staff=True,
    )
    client.force_login(superusuario)

    url = reverse("admin:contas_usuario_change", args=[coordenador.pk])
    resposta = client.post(
        url,
        {
            "email": coordenador.email,
            "nome_completo": coordenador.nome_completo,
            "cpf": coordenador.cpf,
            "papel": Usuario.ALUNO,
            "is_active": "on",
        },
        follow=True,
    )

    assert resposta.status_code == 200
    assert "errornote" in resposta.content.decode()
    coordenador.refresh_from_db()
    assert coordenador.papel == Usuario.PROFESSOR


@pytest.mark.django_db
def test_admin_recusa_desativar_ultimo_coordenador_ativo(client):
    """ACHADO F1 da re-auditoria (2026-09-22): `services.revogar_coordenacao`
    (achado H2) trava o piso de coordenadores só contra a REVOGAÇÃO —
    `is_active` continua um campo comum do formulário, e nada impedia um
    superusuário de desativar o último coordenador ativo pelo admin
    diretamente, sem passar pela revogação nenhuma. Prova por mutação:
    remover a checagem de `is_active` do `clean()` de
    `FormularioEdicaoUsuario` faz este teste reprovar (a desativação
    vingaria)."""
    superusuario = Usuario.objects.create_superuser(
        email="admin.f1@ufsm.br", password="x", nome_completo="Admin F1", cpf="12345678909"
    )
    unico_coordenador = Usuario.objects.create_user(
        email="unico.f1@ufsm.br",
        password="x",
        nome_completo="Único Coordenador F1",
        cpf="52998224725",
        papel=Usuario.PROFESSOR,
        is_coordenador=True,
        is_staff=True,
    )
    client.force_login(superusuario)

    url = reverse("admin:contas_usuario_change", args=[unico_coordenador.pk])
    resposta = client.post(
        url,
        {
            "email": unico_coordenador.email,
            "nome_completo": unico_coordenador.nome_completo,
            "cpf": unico_coordenador.cpf,
            "papel": Usuario.PROFESSOR,
            # "is_active" OMITIDO de propósito: um checkbox desmarcado não
            # é enviado no POST — é assim que se desativa pelo admin.
        },
        follow=True,
    )

    assert resposta.status_code == 200
    assert "errornote" in resposta.content.decode()
    unico_coordenador.refresh_from_db()
    assert unico_coordenador.is_active is True


@pytest.mark.django_db
def test_admin_permite_desativar_coordenador_quando_ha_outro_ativo(client):
    """Contraprova de `test_admin_recusa_desativar_ultimo_coordenador_ativo`:
    desativar um coordenador enquanto sobra outro ativo continua permitido."""
    superusuario = Usuario.objects.create_superuser(
        email="admin.f1b@ufsm.br", password="x", nome_completo="Admin F1b", cpf="12345678909"
    )
    coordenador_a = Usuario.objects.create_user(
        email="coord.a.f1b@ufsm.br",
        password="x",
        nome_completo="Coordenador A F1b",
        cpf="52998224725",
        papel=Usuario.PROFESSOR,
        is_coordenador=True,
        is_staff=True,
    )
    Usuario.objects.create_user(
        email="coord.b.f1b@ufsm.br",
        password="x",
        nome_completo="Coordenador B F1b",
        cpf="16899535009",
        papel=Usuario.PROFESSOR,
        is_coordenador=True,
        is_staff=True,
    )
    client.force_login(superusuario)

    url = reverse("admin:contas_usuario_change", args=[coordenador_a.pk])
    resposta = client.post(
        url,
        {
            "email": coordenador_a.email,
            "nome_completo": coordenador_a.nome_completo,
            "cpf": coordenador_a.cpf,
            "papel": Usuario.PROFESSOR,
        },
        follow=True,
    )

    assert resposta.status_code == 200
    assert "errornote" not in resposta.content.decode()
    coordenador_a.refresh_from_db()
    assert coordenador_a.is_active is False


@pytest.mark.django_db
def test_formulario_de_criacao_do_admin_grava_senha_com_hash():
    """Regressão: sem UserCreationForm, o admin gravaria a senha em texto puro."""
    formulario = FormularioCriacaoUsuario(
        data={
            "email": "ana@ufsm.br",
            "nome_completo": "Ana",
            "cpf": "52998224725",
            "password1": "senha-forte-123",
            "password2": "senha-forte-123",
        }
    )
    assert formulario.is_valid(), formulario.errors

    usuario = formulario.save()
    usuario.refresh_from_db()

    assert usuario.password != "senha-forte-123"
    assert usuario.check_password("senha-forte-123")
