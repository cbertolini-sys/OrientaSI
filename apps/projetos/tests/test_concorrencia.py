"""Prova de concorrência de `criar_projeto_sob_limite` (spec §5.3 e §9).

Aceitar uma opção é um `INSERT` de `Projeto` novo, não um `UPDATE` de linha
existente — a diferença que importa em relação ao teto de coordenadores do
Bloco A (`apps/contas/services.py::promover_a_coordenador`). Lá, travar o
conjunto de professores funciona porque a linha promovida já pertence a esse
conjunto (é um `UPDATE`). Aqui, a implementação trava a linha do
`PerfilProfessor` — o recurso disputado —, não os `Projeto` existentes.

**Por que não travar os `Projeto` existentes (achado da autorrevisão desta
tarefa, e por que a mutação do Passo 6 do brief foi trocada):** a primeira
tentativa deste teste trocava o `select_for_update` da linha do professor por
um `select_for_update` sobre os `Projeto` já existentes, como o brief original
pedia. Rodado de verdade, ESSE TESTE NÃO REPROVAVA — porque `LimiteOrientacao`
só aceita `limite > 3` (`CheckConstraint` em `apps/projetos/models.py`), o
limite efetivo de qualquer professor é sempre 3 ou mais, e por isso o
limiar (`ocupadas == limite - 1`) sempre tem PELO MENOS DOIS projetos já
existentes. Travar esse conjunto não-vazio faz as duas transações
concorrentes disputarem AS MESMAS linhas (os projetos que já existem) e
serializarem por acidente: a segunda fica bloqueada até a primeira comitar, e
quando é liberada, sua chamada a `vagas_ocupadas` roda como um SELECT novo,
com snapshot próprio de READ COMMITTED, e enxerga o projeto recém-criado —
então recusa corretamente, mas não porque a trava sobre `Projeto` proteja a
inserção fantasma: só porque, neste sistema, o conjunto travado nunca está
vazio no limiar. Um travamento assim funcionaria "por sorte" enquanto o
limite mínimo for 3, e pararia de funcionar se um dia caísse para 1. A
mutação que de fato reprova, verificada abaixo, é remover o travamento por
completo — ela prova o que interessa (que a proteção existe), sem depender de
qual das duas linhas foi escolhida para travar.

**Como a sobreposição é forçada, sem depender do escalonador:** ao contrário
de um monkeypatch que atrasasse a LEITURA da contagem (tentado e descartado:
atrasar a leitura em si faz a leitura, quando finalmente acontece, enxergar
o que já foi commitado nesse meio-tempo — inclusive sob a mutação errada, o
que mascara o defeito), este teste atrasa a ESCRITA, no mesmo padrão de
`apps/contas/tests/test_coordenacao_concorrencia.py`: um monkeypatch de
`Projeto.save` atrasa em 1s exclusivamente a gravação do projeto de T1 — no
ponto em que `criar_projeto_sob_limite` já leu a contagem e decidiu criar,
mas ainda não gravou. Como as DUAS leituras (T1 e T2) acontecem rápido, perto
do início, e só a ESCRITA de T1 é atrasada, T2 tem a janela real de 1s para
ler a MESMA contagem desatualizada que T1 leu — se nada as serializar, as
duas decidem "cabe" e as duas gravam, estourando o teto. Com o travamento
certo (linha do professor), T2 não consegue nem começar sua leitura: fica
bloqueada tentando travar a mesma linha do professor que T1 já travou, e só
lê a contagem depois que T1 comita.

Usa `@pytest.mark.django_db(transaction=True)` pelo mesmo motivo do teste
homólogo em `apps/contas/tests/test_coordenacao_concorrencia.py`: threads
reais, cada uma com sua própria conexão, precisam enxergar o commit uma da
outra de verdade. O wrapper padrão de transação por teste do pytest-django
manteria as duas "transações" na mesma conexão/transação Python, e não
haveria concorrência nenhuma para provar.
"""

import threading
import time
from unittest import mock

import pytest
from django.core.exceptions import ValidationError
from django.db import connection

from apps.comum.semestre import semestre_vigente
from apps.contas.models import Area, PerfilAluno, PerfilProfessor, Usuario
from apps.contas.validators import _digito
from apps.projetos import services
from apps.projetos.models import Projeto, Tema

ANO_VIGENTE, PERIODO_VIGENTE = semestre_vigente()


def _gera_cpf(indice):
    base = f"{600000000 + indice:09d}"
    d1 = _digito(base, 10)
    d2 = _digito(base + str(d1), 11)
    return base + str(d1) + str(d2)


def _cria_professor(indice):
    usuario = Usuario.objects.create_user(
        email=f"orientador.concorrencia{indice}@ufsm.br",
        password="x",
        nome_completo=f"Orientador Concorrência {indice}",
        cpf=_gera_cpf(indice),
    )
    return PerfilProfessor.objects.create(usuario=usuario, siape=f"800{indice:04d}")


def _cria_perfil_aluno(indice):
    usuario = Usuario.objects.create_user(
        email=f"aluno.concorrencia{indice}@ufsm.br",
        password="x",
        nome_completo=f"Aluno Concorrência {indice}",
        papel=Usuario.ALUNO,
        cpf=_gera_cpf(100 + indice),
    )
    return PerfilAluno.objects.create(usuario=usuario, matricula=f"20261{indice:04d}")


def _aceita_em_thread(perfil_aluno, professor, tema, etapa, resultados, chave):
    """Roda `criar_projeto_sob_limite` numa conexão de banco própria (nova
    thread do Python => nova conexão do Django), guardando o resultado
    (sucesso ou a mensagem de erro) num dicionário compartilhado."""
    connection.close()
    try:
        services.criar_projeto_sob_limite(perfil_aluno, professor, tema, etapa)
        resultados[chave] = "criado"
    except ValidationError as erro:
        resultados[chave] = f"recusado: {erro.messages[0]}"
    finally:
        connection.close()


@pytest.mark.django_db(transaction=True)
def test_duas_aceitacoes_simultaneas_no_ultimo_lugar_resultam_em_uma_recusa():
    """Aceitar é um INSERT, não um UPDATE — travar os Projeto existentes não impede
    outra transação de inserir mais um (leitura fantasma). O travamento é na linha do
    professor, que é o recurso disputado. Este teste prova isso com threads e conexões
    reais; sem ele, a garantia seria só uma frase no comentário — que foi exatamente
    como a Fase 1 descobriu que o raciocínio do spec estava errado.
    """
    area = Area.objects.create(nome="Engenharia de Software")
    professor = _cria_professor(0)
    tema = Tema.objects.create(
        professor=professor, area=area, titulo="Tema", descricao="Descrição do tema."
    )
    # Duas vagas já ocupadas de três (LIMITE_PADRAO_VAGAS): resta exatamente
    # UMA vaga, e é essa vaga que as duas threads vão disputar. Precisam cair
    # no semestre VIGENTE (não num fixo) porque `criar_projeto_sob_limite`
    # conta só o semestre vigente (spec §3.5) — e é ele quem decide, dentro da
    # trava, qual semestre isso é.
    for indice in range(2):
        Projeto.objects.create(
            aluno=_cria_perfil_aluno(indice).usuario,
            orientador=professor.usuario,
            tema=tema,
            etapa=Projeto.TCC_I,
            status=Projeto.EM_ANDAMENTO,
            ano=ANO_VIGENTE,
            periodo=PERIODO_VIGENTE,
        )
    aluno_t1 = _cria_perfil_aluno(10)
    aluno_t2 = _cria_perfil_aluno(11)
    resultados = {}

    save_original = Projeto.save

    def save_com_atraso(self, *args, **kwargs):
        # Só atrasa a GRAVAÇÃO (não a leitura) do projeto de T1, e só quando
        # ainda não tem pk — ou seja, é a inserção nova de `.create()`, não
        # algum outro save() incidental. `criar_projeto_sob_limite` já
        # travou (ou não, sob a mutação do Passo 6), já leu a contagem e o
        # limite, e já decidiu criar quando chega aqui: o atraso acontece
        # DEPOIS da decisão, antes de ela virar linha no banco.
        if self.pk is None and self.aluno_id == aluno_t1.usuario_id:
            time.sleep(1.0)
        return save_original(self, *args, **kwargs)

    t1 = threading.Thread(
        target=_aceita_em_thread,
        args=(aluno_t1, professor, tema, Projeto.TCC_I, resultados, "t1"),
    )
    t2 = threading.Thread(
        target=_aceita_em_thread,
        args=(aluno_t2, professor, tema, Projeto.TCC_I, resultados, "t2"),
    )

    with mock.patch.object(Projeto, "save", save_com_atraso):
        t1.start()
        time.sleep(0.2)  # garante que T1 já leu a contagem antes de T2 começar
        t2.start()
        t1.join()
        t2.join()

    total_projetos = Projeto.objects.filter(
        orientador=professor.usuario, etapa=Projeto.TCC_I
    ).count()

    assert total_projetos == services.LIMITE_PADRAO_VAGAS, (
        f"o teto de {services.LIMITE_PADRAO_VAGAS} vagas foi ultrapassado sob concorrência "
        f"real: {total_projetos} projetos no final para o mesmo professor. "
        f"Resultados de cada thread: {resultados}"
    )
    assert "recusado" in resultados["t1"] or "recusado" in resultados["t2"], (
        f"esperava que uma das duas aceitações concorrentes fosse recusada pelo teto de "
        f"vagas, e nenhuma foi: {resultados}"
    )
    assert "criado" in resultados["t1"] or "criado" in resultados["t2"], (
        f"esperava que uma das duas aceitações concorrentes fosse aceita (a vaga existia "
        f"antes das duas tentativas): {resultados}"
    )
