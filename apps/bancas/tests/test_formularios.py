"""Testes de `FormularioBanca`/`FormularioResultadoBanca` (Bloco D, spec §7)."""

import pytest

from apps.bancas.forms import FormularioBanca, FormularioResultadoBanca
from apps.contas.models import PerfilProfessor, Usuario
from apps.contas.validators import _digito
from apps.projetos.models import Projeto


def _cpf(indice):
    base = f"{660000000 + indice:09d}"
    d1 = _digito(base, 10)
    d2 = _digito(base + str(d1), 11)
    return base + str(d1) + str(d2)


def _professor(indice, nome):
    usuario = Usuario.objects.create_user(
        email=f"professor.formulario.{indice}@ufsm.br",
        password="x",
        nome_completo=nome,
        cpf=_cpf(indice),
    )
    return PerfilProfessor.objects.create(usuario=usuario, siape=f"FORM{indice:03d}")


@pytest.mark.django_db
def test_formulario_banca_aceita_professor_e_externo():
    orientador = _professor(1, "Orientador Formulário")
    membro = _professor(2, "Membro Formulário")
    formulario = FormularioBanca(
        data={
            "data_hora": "2026-12-01T14:00",
            "local": "Sala 5",
            "membro_1_professor": membro.pk,
            "membro_1_externo": "",
            "membro_2_professor": "",
            "membro_2_externo": "Fulano Externo",
        },
        orientador=orientador.usuario,
    )
    assert formulario.is_valid(), formulario.errors
    membros = formulario.cleaned_data["membros"]
    assert membros[0] == {"professor": membro}
    assert membros[1] == {"nome_externo": "Fulano Externo"}


@pytest.mark.django_db
def test_formulario_banca_recusa_membro_com_os_dois_campos():
    orientador = _professor(3, "Orientador Formulário Dois")
    membro = _professor(4, "Membro Formulário Dois")
    formulario = FormularioBanca(
        data={
            "data_hora": "2026-12-01T14:00",
            "local": "Sala 5",
            "membro_1_professor": membro.pk,
            "membro_1_externo": "Fulano",
            "membro_2_professor": "",
            "membro_2_externo": "Beltrano",
        },
        orientador=orientador.usuario,
    )
    assert not formulario.is_valid()


@pytest.mark.django_db
def test_formulario_banca_recusa_membro_sem_nenhum_campo():
    orientador = _professor(5, "Orientador Formulário Três")
    formulario = FormularioBanca(
        data={
            "data_hora": "2026-12-01T14:00",
            "local": "Sala 5",
            "membro_1_professor": "",
            "membro_1_externo": "",
            "membro_2_professor": "",
            "membro_2_externo": "Beltrano",
        },
        orientador=orientador.usuario,
    )
    assert not formulario.is_valid()


@pytest.mark.django_db
def test_formulario_banca_exclui_o_orientador_do_queryset():
    orientador = _professor(6, "Orientador Formulário Quatro")
    formulario = FormularioBanca(orientador=orientador.usuario)
    assert orientador not in formulario.fields["membro_1_professor"].queryset
    assert orientador not in formulario.fields["membro_2_professor"].queryset


def test_formulario_resultado_banca_aceita_aprovado_com_ressalvas():
    formulario = FormularioResultadoBanca(
        data={"nota": "8.5", "resultado": Projeto.APROVADO_COM_RESSALVAS, "comentario": "Ok."}
    )
    assert formulario.is_valid(), formulario.errors


def test_formulario_resultado_banca_recusa_nota_fora_da_faixa():
    formulario = FormularioResultadoBanca(
        data={"nota": "11", "resultado": Projeto.APROVADO_COM_RESSALVAS, "comentario": ""}
    )
    assert not formulario.is_valid()
