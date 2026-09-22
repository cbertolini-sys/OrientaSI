"""Regressão do achado residual da revisão de código da correção C3/H5
(2026-09-22): `aprovar_ata` ganhou `@transaction.atomic` para fechar o C3
original (estado parcial — ata aprovada, TCC I concluído, sem TCC II), mas
sem trava nenhuma na leitura de `revisao.status`, duas aprovações quase
simultâneas da MESMA ata liam as duas `PENDENTE` antes de qualquer uma
commitar. A segunda só era barrada depois, dentro de
`criar_tcc_ii_automatico`, com um `IntegrityError` cru que `aprovar_ata_view`
não captura — 500 na tela da SUGRAD, em vez da `ValidationError` amigável que
`aprovar_ata` já sabe produzir para "esta ata já foi revisada".

A correção acrescentou `RevisaoSUGRAD.objects.select_for_update()` no início
de `aprovar_ata`/`devolver_ata` — mesmo padrão de
`apps.contas.tests.test_coordenacao_concorrencia` (trava real, threads reais,
sobreposição forçada por atraso deliberado num `save()`, não por timing do
SO). `@pytest.mark.django_db(transaction=True)`: threads com conexões
próprias precisam ver os commits umas das outras de verdade.
"""

import threading
import time
from unittest import mock

import pytest
from django.core.exceptions import ValidationError
from django.db import connection
from django.utils import timezone

from apps.bancas.models import Banca
from apps.contas.models import PerfilAluno, PerfilProfessor, Usuario
from apps.contas.validators import _digito
from apps.documentos import services
from apps.documentos.models import RevisaoSUGRAD
from apps.projetos.models import Projeto


def _cpf(indice):
    base = f"{740000000 + indice:09d}"
    d1 = _digito(base, 10)
    d2 = _digito(base + str(d1), 11)
    return base + str(d1) + str(d2)


def _monta_ata_pendente():
    aluno = Usuario.objects.create_user(
        email="aluno.concorrencia.ata@ufsm.br",
        password="x",
        nome_completo="Aluno Concorrência Ata",
        papel=Usuario.ALUNO,
        cpf=_cpf(1),
    )
    PerfilAluno.objects.create(usuario=aluno, matricula="2026CONCATA1")
    professor = Usuario.objects.create_user(
        email="professor.concorrencia.ata@ufsm.br",
        password="x",
        nome_completo="Professor Concorrência Ata",
        cpf=_cpf(2),
    )
    PerfilProfessor.objects.create(usuario=professor, siape="CONCATA01")
    projeto = Projeto.objects.create(
        aluno=aluno,
        orientador=professor,
        etapa=Projeto.TCC_I,
        status=Projeto.APROVADO,
        ano=2026,
        periodo=1,
    )
    Banca.objects.create(
        projeto=projeto,
        data_hora=timezone.now(),
        local="Sala 1",
        status=Banca.REALIZADA,
        nota=8.0,
        resultado=Projeto.APROVADO_COM_RESSALVAS,
    )
    return services.gerar_ata(projeto)


def _aprova_em_thread(ata_id, sugrad_id, resultados, chave):
    """Roda `aprovar_ata` numa conexão própria (thread nova => conexão nova
    do Django), guardando o resultado (aprovado, recusado, ou uma exceção
    crua que NÃO deveria escapar) num dicionário compartilhado."""
    from apps.documentos.models import Ata

    connection.close()
    try:
        ata = Ata.objects.get(pk=ata_id)
        sugrad = Usuario.objects.get(pk=sugrad_id)
        services.aprovar_ata(ata, por=sugrad)
        resultados[chave] = "aprovada"
    except ValidationError as erro:
        resultados[chave] = f"recusada: {erro.messages[0]}"
    except Exception as erro:  # noqa: BLE001 — queremos capturar QUALQUER vazamento cru
        resultados[chave] = f"EXCECAO CRUA ({type(erro).__name__}): {erro}"
    finally:
        connection.close()


@pytest.mark.django_db(transaction=True)
def test_aprovar_ata_sob_sobreposicao_real_nao_vaza_integrityerror(settings):
    """`settings.CELERY_TASK_ALWAYS_EAGER = True` (achado da revisão de
    código desta mesma correção, 2026-09-22 — mesmo raciocínio já registrado
    em `apps.projetos.tests.test_concorrencia`, Tarefa 13): este teste usa
    `django_db(transaction=True)` — as transações de `gerar_ata`/`aprovar_ata`
    COMITAM de verdade, ao contrário dos testes com rollback padrão. Sem o
    modo eager, os `on_commit` de `gerar_ata` (`enviar_ata_para_sugrad`) e de
    `criar_tcc_ii_automatico` (`enviar_tcc_ii_criado`) despacham `.delay()`
    para o broker Redis REAL, e o `celery_worker` real do `docker-compose`
    processa a tarefa depois que o teardown deste teste já truncou a tabela —
    `Ata.DoesNotExist`/`Projeto.DoesNotExist` no log do worker (ou, num
    ambiente de CI sem Redis alcançável, um `OperationalError` cru vazando
    de dentro do `on_commit` e derrubando o teste por um motivo alheio à
    corrida que ele existe para provar). Nenhuma asserção deste teste
    depende do e-mail; o modo eager só evita a publicação no broker real."""
    settings.CELERY_TASK_ALWAYS_EAGER = True
    ata = _monta_ata_pendente()
    sugrad = Usuario.objects.create_user(
        email="sugrad.concorrencia.ata@ufsm.br",
        password="x",
        nome_completo="SUGRAD Concorrência",
        papel=Usuario.SUGRAD,
        cpf=None,
    )
    resultados = {}

    save_original = RevisaoSUGRAD.save

    def save_com_atraso(self, *args, **kwargs):
        # Só atrasa a gravação DESTA revisão, e só quando ela está virando
        # APROVADA — o exato ponto em que `aprovar_ata` já travou a linha
        # (SELECT ... FOR UPDATE) e decidiu aprovar, mas ainda não commitou.
        if self.ata_id == ata.pk and self.status == RevisaoSUGRAD.APROVADA:
            time.sleep(1.0)
        return save_original(self, *args, **kwargs)

    t1 = threading.Thread(
        target=_aprova_em_thread, args=(ata.pk, sugrad.pk, resultados, "t1")
    )
    t2 = threading.Thread(
        target=_aprova_em_thread, args=(ata.pk, sugrad.pk, resultados, "t2")
    )

    with mock.patch.object(RevisaoSUGRAD, "save", save_com_atraso):
        t1.start()
        time.sleep(0.2)  # garante que T1 já executou seu SELECT ... FOR UPDATE
        t2.start()
        t1.join()
        t2.join()

    # A prova central: NENHUMA das duas threads deixou uma exceção crua
    # escapar (IntegrityError não traduzido) — uma aprovou, a outra foi
    # educadamente recusada.
    for chave in ("t1", "t2"):
        assert "EXCECAO CRUA" not in resultados[chave], (
            f"{chave} vazou uma exceção crua em vez de ValidationError: {resultados}"
        )
    assert "aprovada" in resultados.values(), resultados

    # A recusa precisa ser ESPECIFICAMENTE "esta ata já foi revisada" —
    # não qualquer recusa (achado M-1 da re-auditoria, 2026-09-22: a
    # asserção genérica `any(v.startswith("recusada"))` não provava a
    # trava `select_for_update`, porque a SEGUNDA camada de defesa
    # (`criar_tcc_ii_automatico` traduzindo o `IntegrityError` de "já tem
    # um TCC II ativo") sozinha já produziria uma recusa igualmente válida
    # SEM a trava — mascarando a ausência dela. Só a trava faz a segunda
    # thread reler `revisao.status` já como `APROVADA` e recusar por ESTE
    # motivo específico, antes de chegar perto de `criar_tcc_ii_automatico`.
    # Prova por mutação: remover `select_for_update` de `aprovar_ata`
    # (mantendo a leitura solta `revisao = ata.revisao`) faz este teste
    # reprovar — a recusa passa a ser "já tem um TCC II ativo", não esta.
    assert any(
        v == "recusada: Esta ata já foi revisada." for v in resultados.values()
    ), resultados

    # E só um TCC II foi criado, não dois.
    ata.projeto.refresh_from_db()
    total_tcc_ii = Projeto.objects.filter(anterior=ata.projeto, etapa=Projeto.TCC_II).count()
    assert total_tcc_ii == 1, f"esperava exatamente 1 TCC II criado, achou {total_tcc_ii}"
