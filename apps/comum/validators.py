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
