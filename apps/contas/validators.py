from django.core.exceptions import ValidationError

SEQUENCIAS_INVALIDAS = {str(d) * 11 for d in range(10)}


def _digito(base, peso_inicial):
    soma = sum(int(d) * p for d, p in zip(base, range(peso_inicial, 1, -1), strict=True))
    resto = (soma * 10) % 11
    return 0 if resto == 10 else resto


def valida_cpf(valor):
    """Aceita apenas os 11 dígitos, já sem pontuação, com dígitos verificadores válidos."""
    if not valor.isdigit() or len(valor) != 11:
        raise ValidationError("O CPF deve conter exatamente 11 dígitos, sem pontos ou traços.")
    if valor in SEQUENCIAS_INVALIDAS:
        raise ValidationError("CPF inválido.")
    if _digito(valor[:9], 10) != int(valor[9]) or _digito(valor[:10], 11) != int(valor[10]):
        raise ValidationError("CPF inválido.")
