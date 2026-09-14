"""Teste de `FormularioDevolverAta` (Bloco E, spec §7)."""

from apps.documentos.forms import FormularioDevolverAta


def test_formulario_devolver_ata_exige_comentario():
    formulario = FormularioDevolverAta(data={"comentario": ""})
    assert not formulario.is_valid()


def test_formulario_devolver_ata_aceita_comentario():
    formulario = FormularioDevolverAta(data={"comentario": "Falta a assinatura do orientador."})
    assert formulario.is_valid(), formulario.errors
