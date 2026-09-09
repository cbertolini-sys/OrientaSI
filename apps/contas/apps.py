from django.apps import AppConfig


class ContasConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.contas"
    verbose_name = "Contas"

    def ready(self):
        # Conecta o sinal que normaliza o e-mail em qualquer caminho de
        # escrita (T9, revisão 1) — precisa ser importado aqui para o
        # @receiver registrar o handler; sem isto, o módulo nunca é
        # carregado e o sinal nunca dispara.
        from apps.contas import signals  # noqa: F401
