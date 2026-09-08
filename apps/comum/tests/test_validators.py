import pytest
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile

from apps.comum.validators import (
    valida_extensao_documento,
    valida_extensao_imagem,
    valida_tamanho_arquivo,
)


def test_valida_extensao_documento_aceita_pdf():
    valida_extensao_documento(SimpleUploadedFile("tcc.pdf", b"conteudo"))


def test_valida_extensao_documento_aceita_docx():
    valida_extensao_documento(SimpleUploadedFile("tcc.docx", b"conteudo"))


def test_valida_extensao_documento_recusa_extensao_invalida():
    with pytest.raises(ValidationError):
        valida_extensao_documento(SimpleUploadedFile("tcc.exe", b"conteudo"))


def test_valida_extensao_imagem_aceita_png():
    valida_extensao_imagem(SimpleUploadedFile("foto.png", b"conteudo"))


def test_valida_extensao_imagem_recusa_extensao_invalida():
    with pytest.raises(ValidationError):
        valida_extensao_imagem(SimpleUploadedFile("foto.pdf", b"conteudo"))


def test_valida_tamanho_arquivo_aceita_dentro_do_limite(settings):
    settings.TAMANHO_MAXIMO_UPLOAD_MB = 1
    arquivo = SimpleUploadedFile("tcc.pdf", b"x" * (1024 * 1024 - 1))
    valida_tamanho_arquivo(arquivo)


def test_valida_tamanho_arquivo_recusa_acima_do_limite(settings):
    settings.TAMANHO_MAXIMO_UPLOAD_MB = 1
    arquivo = SimpleUploadedFile("tcc.pdf", b"x" * (1024 * 1024 + 1))
    with pytest.raises(ValidationError):
        valida_tamanho_arquivo(arquivo)
