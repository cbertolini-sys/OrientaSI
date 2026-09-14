from django import forms

from apps.contas.forms import MisturaAcessibilidadeFormulario


class FormularioDevolverAta(MisturaAcessibilidadeFormulario, forms.Form):
    """Devolução de uma ata pela SUGRAD (Bloco E, spec §7) — o comentário é
    obrigatório: sem ele, a devolução é silêncio com outro nome, e o
    orientador não sabe o que corrigir (mesmo raciocínio de
    `FormularioRecusaOpcao`, Bloco B)."""

    comentario = forms.CharField(
        label="Comentário",
        widget=forms.Textarea(attrs={"class": "textarea w-full"}),
    )
