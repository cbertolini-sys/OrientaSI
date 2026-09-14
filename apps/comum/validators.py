from pathlib import Path

from django.conf import settings
from django.core.exceptions import ValidationError

EXTENSOES_DOCUMENTO = {".pdf", ".docx"}
EXTENSOES_IMAGEM = {".jpg", ".jpeg", ".png", ".webp"}


def _valida_extensao(arquivo, permitidas):
    extensao = Path(arquivo.name).suffix.lower()
    if extensao not in permitidas:
        aceitas = ", ".join(sorted(permitidas))
        raise ValidationError(f"Extensão {extensao or 'ausente'} não aceita. Envie: {aceitas}.")


def valida_extensao_documento(arquivo):
    _valida_extensao(arquivo, EXTENSOES_DOCUMENTO)


def valida_extensao_imagem(arquivo):
    _valida_extensao(arquivo, EXTENSOES_IMAGEM)


def valida_tamanho_arquivo(arquivo):
    limite = settings.TAMANHO_MAXIMO_UPLOAD_MB * 1024 * 1024
    if arquivo.size > limite:
        raise ValidationError(
            f"Arquivo de {arquivo.size / 1024 / 1024:.1f}MB excede o limite de "
            f"{settings.TAMANHO_MAXIMO_UPLOAD_MB}MB."
        )


EXTENSAO_PDF = {".pdf"}
EXTENSAO_EDITAVEL = {".docx"}


def valida_extensao_pdf(arquivo):
    """Só `.pdf` — usado no campo `pdf` de `Submissao`
    (`apps/projetos/models.py`). Distinto de `valida_extensao_documento`,
    que aceita `.pdf` OU `.docx` em qualquer campo: `Submissao` tem dois
    campos com formatos diferentes e nomes que prometem qual é qual, e o
    validator genérico deixaria um `.docx` passar despercebido no campo
    `pdf` (spec do Bloco C, §4.1)."""
    _valida_extensao(arquivo, EXTENSAO_PDF)


def valida_extensao_editavel(arquivo):
    """Só `.docx` — usado no campo `editavel` de `Submissao`. Ver
    `valida_extensao_pdf`, acima, para o motivo de não reaproveitar
    `valida_extensao_documento`."""
    _valida_extensao(arquivo, EXTENSAO_EDITAVEL)
