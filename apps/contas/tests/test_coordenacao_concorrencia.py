"""Regressão do achado da revisão 1 da Tarefa 11: `promover_a_coordenador`
travava sobre `is_coordenador=True`, um predicado que MUDA com a própria
promoção — em READ COMMITTED, o PostgreSQL decide quais linhas um
`SELECT ... FOR UPDATE` vai travar pelo snapshot do início do comando, e a
linha do alvo ainda tinha `is_coordenador=False` nesse instante, então nunca
entrava no conjunto travado. Duas promoções de alvos diferentes, sobrepostas
de propósito, liam "3 coordenadores" cada uma e as duas promoviam,
terminando em 5 (teto = 4). A correção trava sobre `papel=PROFESSOR` — um
predicado que a promoção não muda — para que a linha do alvo já esteja no
conjunto travado desde o início, nas duas transações concorrentes.

Este teste reproduz a MESMA sobreposição real (não simulada) usada para
diagnosticar o defeito e confirmar a correção (ver
`.superpowers/sdd/2026-09-08-fundacao-e-contas/tarefa-11-report.md`, seção
da revisão 1, para a saída das duas execuções manuais contra o Postgres do
projeto). Usa `@pytest.mark.django_db(transaction=True)` porque threads
reais, cada uma com sua própria conexão, precisam ver commits umas das
outras de verdade — o wrapper padrão de transação por teste do
pytest-django manteria as duas "transações" na mesma conexão/transação
Python, o que não reproduz corrida nenhuma.

**Como a sobreposição é forçada, sem depender de timing do SO:** um
monkeypatch de `Usuario.save` atrasa em 1s exclusivamente o `save()` do alvo
da primeira thread (`T1`), no exato ponto em que `promover_a_coordenador` já
executou seu `SELECT ... FOR UPDATE` e decidiu promover — ou seja, depois de
travar as linhas, mas antes de gravar e comitar. Isso mantém a transação de
T1 aberta tempo de sobra para a segunda thread (`T2`, iniciada 0,2s depois)
com certeza tentar sua própria trava e ser forçada a esperar. Sem esse
atraso deliberado, o teste dependeria de o SO agendar as duas threads com
sobreposição real — nem sempre verdade, e um teste que só falha às vezes é
pior que não ter teste."""

import threading
import time
from unittest import mock

import pytest
from django.core.exceptions import ValidationError
from django.db import connection

from apps.contas import services
from apps.contas.models import Usuario
from apps.contas.validators import _digito


def _gera_cpf(indice):
    base = f"{400000000 + indice:09d}"
    d1 = _digito(base, 10)
    d2 = _digito(base + str(d1), 11)
    return base + str(d1) + str(d2)


def _cria_professor(indice, coordenador=False):
    return Usuario.objects.create_user(
        email=f"concorrencia{indice}@ufsm.br",
        password="x",
        nome_completo=f"Concorrência {indice}",
        cpf=_gera_cpf(indice),
        is_coordenador=coordenador,
        is_staff=coordenador,
    )


def _promove_em_thread(usuario, coordenador, resultados, chave):
    """Roda `promover_a_coordenador` numa conexão de banco própria (nova
    thread do Python => nova conexão do Django), guardando o resultado
    (sucesso ou a mensagem de erro) num dicionário compartilhado."""
    connection.close()
    try:
        services.promover_a_coordenador(usuario, por=coordenador)
        resultados[chave] = "promovido"
    except ValidationError as erro:
        resultados[chave] = f"recusado: {erro.messages[0]}"
    finally:
        connection.close()


@pytest.mark.django_db(transaction=True)
def test_promover_sob_sobreposicao_real_nao_ultrapassa_o_teto():
    coordenadora = _cria_professor(0, coordenador=True)
    _cria_professor(1, coordenador=True)
    _cria_professor(2, coordenador=True)
    alvo_t1 = _cria_professor(10)
    alvo_t2 = _cria_professor(11)
    resultados = {}

    save_original = Usuario.save

    def save_com_atraso(self, *args, **kwargs):
        # Só atrasa a gravação do alvo de T1, e só a gravação que
        # `promover_a_coordenador` faz (update_fields específico) — não
        # qualquer outro save() que aconteça no processo.
        if self.pk == alvo_t1.pk and kwargs.get("update_fields") == [
            "is_coordenador",
            "is_staff",
        ]:
            time.sleep(1.0)
        return save_original(self, *args, **kwargs)

    t1 = threading.Thread(target=_promove_em_thread, args=(alvo_t1, coordenadora, resultados, "t1"))
    t2 = threading.Thread(target=_promove_em_thread, args=(alvo_t2, coordenadora, resultados, "t2"))

    with mock.patch.object(Usuario, "save", save_com_atraso):
        t1.start()
        time.sleep(0.2)  # garante que T1 já executou seu SELECT ... FOR UPDATE
        t2.start()
        t1.join()
        t2.join()

    total_coordenadores = Usuario.objects.filter(is_coordenador=True).count()

    assert total_coordenadores <= services.LIMITE_COORDENADORES, (
        f"o teto de {services.LIMITE_COORDENADORES} coordenadores foi ultrapassado sob "
        f"concorrência real: {total_coordenadores} coordenadores no final. "
        f"Resultados de cada thread: {resultados}"
    )
    # Uma das duas teve que ser recusada (não as duas: a promoção de T1
    # sozinha é legítima, o sistema tinha só 3 coordenadores antes dela).
    assert "recusado" in resultados["t1"] or "recusado" in resultados["t2"], (
        f"esperava que uma das duas promoções concorrentes fosse recusada pelo teto, "
        f"e nenhuma foi: {resultados}"
    )
