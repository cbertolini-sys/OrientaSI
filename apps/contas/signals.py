from django.db.models.signals import pre_save
from django.dispatch import receiver

from apps.contas.models import Usuario


@receiver(pre_save, sender=Usuario)
def normaliza_email_do_usuario(sender, instance, **kwargs):
    """Garante e-mail em minúsculas em QUALQUER caminho de escrita, não só
    `GerenciadorUsuario._criar` (T7).

    `restricoes-globais.md` proíbe lógica em `models.py` além de campos,
    `Meta` e `__str__` — por isso a normalização mora aqui, num sinal
    conectado em `ContasConfig.ready()`, e não num `Usuario.save()`
    sobrescrito.

    Por que isto é necessário mesmo com `_criar` já normalizando: o admin
    (via `ModelForm.save()`) e o shell chamam `Usuario(...).save()`
    diretamente, sem passar pelo gerenciador. Sem esta rede de segurança,
    "Ana@ufsm.br" e "ana@ufsm.br" conviviam como duas contas — o Postgres
    trata `EmailField(unique=True)` como sensível a maiúsculas — e
    `GerenciadorUsuario.get_by_natural_key` (T9, busca `__iexact`) levantava
    `MultipleObjectsReturned` (500) ao autenticar qualquer uma delas.
    Normalizando aqui, a segunda gravação esbarra no `unique=True` de
    verdade (`IntegrityError`), em vez de criar a duplicata.
    """
    if instance.email:
        instance.email = instance.email.lower()
