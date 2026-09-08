import pytest

from apps.contas.admin import FormularioCriacaoUsuario


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
