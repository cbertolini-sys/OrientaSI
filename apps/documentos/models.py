from django.db import models

from apps.bancas.models import Banca
from apps.projetos.models import Projeto


class Ata(models.Model):
    """Documento formal da defesa do TCC I, gerado automaticamente ao
    aprovar o projeto (Bloco E, spec §4.1/§5.1) — nunca por upload do
    usuário, por isso `pdf` não tem `validators` de extensão/tamanho como
    `Submissao` (Bloco C): o conteúdo é sempre produzido por
    `apps.documentos.services.gerar_ata`, nunca por um formulário externo.
    """

    projeto = models.ForeignKey(
        Projeto,
        on_delete=models.PROTECT,
        related_name="atas",
        verbose_name="projeto",
    )
    banca = models.ForeignKey(
        Banca,
        on_delete=models.PROTECT,
        related_name="atas",
        verbose_name="banca",
    )
    # `unique=True` (achado M1 da auditoria, 2026-09-22): antes não havia
    # NENHUMA trava contra dois documentos oficiais com o mesmo número —
    # `services.gerar_ata` calcula `numero` com `count() + 1`, uma condição
    # de corrida deliberadamente aceita (custo documentado ali: aprovar um
    # TCC I é uma ação humana de baixa frequência) só sob concorrência REAL.
    # Sem esta trava, porém, a colisão era gravada em SILÊNCIO — nenhum
    # `IntegrityError`, nenhum log — e `count()` também não é monotônico:
    # apagar qualquer `Ata` pelo admin faz a próxima gerada reusar o número
    # da apagada, sem concorrência nenhuma envolvida. Agora qualquer colisão
    # vira um erro alto, não um documento legal duplicado silencioso.
    numero = models.CharField("número", max_length=20, unique=True)
    pdf = models.FileField("PDF", upload_to="atas/")
    gerada_em = models.DateTimeField("gerada em", auto_now_add=True)

    class Meta:
        verbose_name = "ata"
        verbose_name_plural = "atas"
        ordering = ["-gerada_em"]

    def __str__(self):
        return f"Ata {self.numero} — {self.projeto}"


class RevisaoSUGRAD(models.Model):
    """Decisão (atual) da SUGRAD sobre uma `Ata` — uma linha só por `Ata`,
    sobrescrita a cada decisão (Bloco E, spec §3.3): mesmo padrão de "sem
    histórico" de `Submissao` (Bloco C) e `Banca.resultado` (Bloco D)."""

    PENDENTE = "PENDENTE"
    APROVADA = "APROVADA"
    DEVOLVIDA = "DEVOLVIDA"
    STATUS = [
        (PENDENTE, "Pendente"),
        (APROVADA, "Aprovada"),
        (DEVOLVIDA, "Devolvida"),
    ]

    ata = models.OneToOneField(
        Ata,
        on_delete=models.CASCADE,
        related_name="revisao",
        verbose_name="ata",
    )
    status = models.CharField("status", max_length=9, choices=STATUS, default=PENDENTE)
    comentario = models.TextField("comentário", blank=True, default="")
    decidida_em = models.DateTimeField("decidida em", null=True, blank=True)

    class Meta:
        verbose_name = "revisão da SUGRAD"
        verbose_name_plural = "revisões da SUGRAD"

    def __str__(self):
        return f"Revisão de {self.ata} — {self.get_status_display()}"
