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
pedia, com a contagem feita por `vagas_ocupadas` (um `.count()`, que roda como
*statement* separado). Rodado de verdade, ESSA FORMA ESPECÍFICA NÃO REPROVAVA
— porque `LimiteOrientacao` só aceita `limite > 3` (`CheckConstraint` em
`apps/projetos/models.py`), o limite efetivo de qualquer professor é sempre 3
ou mais, e por isso o limiar (`ocupadas == limite - 1`) sempre tem PELO MENOS
DOIS projetos já existentes. Travar esse conjunto não-vazio faz as duas
transações concorrentes disputarem AS MESMAS linhas (os projetos que já
existem) e serializarem por acidente: a segunda fica bloqueada até a primeira
comitar, e quando é liberada, sua chamada a `vagas_ocupadas` roda como um
SELECT novo, com snapshot próprio de READ COMMITTED, e enxerga o projeto
recém-criado — então recusa corretamente, mas não porque a trava sobre
`Projeto` proteja a inserção fantasma: só porque, neste sistema, o conjunto
travado nunca está vazio no limiar.

**Isso não é o quadro completo — medido na revisão desta tarefa:** a mesma
trava sobre `Projeto`, com a contagem tirada do PRÓPRIO queryset travado
(`ocupadas = len(travados)`, em vez de um `.count()` à parte) **REPROVA**,
com 4 projetos onde deveria haver 3 — a leitura fantasma que o spec §5.3
descreve é literalmente demonstrável, e só desaparece quando a contagem vira
um *statement* à parte que enxerga o commit alheio. Isso não enfraquece a
escolha de travar o professor — fortalece: não é que travar `Projeto`
"funcione por sorte" de um jeito vago que pararia de funcionar só se o limite
mínimo caísse para 1; é que ela funciona ou não conforme um detalhe de
escrita da contagem, a poucos caracteres de distância, sem nada no código que
sinalize a diferença. A trava sobre o professor não tem essa fragilidade: as
duas formas de escrever a contagem dão o resultado certo, porque a segunda
transação nem consegue começar a ler antes de a primeira liberar a linha. A
mutação usada abaixo para provar a necessidade de ALGUMA trava — a que de
fato reprova de forma simples e determinística — é remover o travamento por
completo, sem substituí-lo por nenhum outro.

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
from datetime import timedelta
from unittest import mock

import pytest
from django.core import mail
from django.core.exceptions import ValidationError
from django.db import connection
from django.utils import timezone

from apps.comum.semestre import semestre_vigente
from apps.contas.models import Area, PerfilAluno, PerfilProfessor, Usuario
from apps.contas.validators import _digito
from apps.projetos import services
from apps.projetos.models import Candidatura, OpcaoCandidatura, Projeto, Tema

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


# --------------------------------------------------------------------------
# T12: trocar_orientador (painel da coordenação) — spec §5.3, explícita:
# "aplicada em aceitar_opcao e trocar_orientador, nunca só numa das duas".
# A disputa é a MESMA da prova acima (a linha do PerfilProfessor do
# professor NOVO), só que a escrita disputada é um UPDATE em `Projeto` já
# existente, não um INSERT — ver a docstring de
# `services.trocar_orientador` (apps/projetos/services.py) para a
# comparação completa com `criar_projeto_sob_limite`.
# --------------------------------------------------------------------------


def _troca_em_thread(projeto_id, professor_novo_pk, por_id, resultados, chave):
    """Roda `services.trocar_orientador` numa conexão de banco própria —
    mesmo padrão de `_aceita_em_thread`, acima."""
    connection.close()
    try:
        projeto = Projeto.objects.get(pk=projeto_id)
        professor_novo = PerfilProfessor.objects.get(pk=professor_novo_pk)
        por = Usuario.objects.get(pk=por_id)
        services.trocar_orientador(projeto, professor_novo, por=por)
        resultados[chave] = "trocado"
    except ValidationError as erro:
        resultados[chave] = f"recusado: {erro.messages[0]}"
    finally:
        connection.close()


@pytest.mark.django_db(transaction=True)
def test_duas_trocas_simultaneas_para_o_mesmo_professor_no_ultimo_lugar_resultam_em_uma_recusa():
    """Duas trocas de orientador, para dois PROJETOS de dois professores
    ANTIGOS diferentes, disputam a MESMA última vaga do MESMO professor
    NOVO. Sem a trava certa (a linha do `PerfilProfessor` do professor
    novo), as duas leriam "2 de 3 vagas ocupadas" e as duas trocariam,
    terminando com 4 projetos sob um teto de 3 — o mesmo furo que
    `test_duas_aceitacoes_simultaneas_no_ultimo_lugar_resultam_em_uma_recusa`,
    acima, prova para `criar_projeto_sob_limite`, só que aqui a escrita
    disputada é um UPDATE (`Projeto.orientador`), não um INSERT.

    Mesmo mecanismo de atraso forçado das provas acima: só a ESCRITA do
    projeto de T1 (`Projeto.save`, que `trocar_orientador` chama depois de
    já ter travado a linha do professor novo e decidido que cabe) é
    atrasada em 1s — tempo real para T2 tentar (e bloquear tentando) travar
    a MESMA linha do professor novo que T1 já travou.
    """
    professor_novo = _cria_professor(50)
    professor_antigo_1 = _cria_professor(51)
    professor_antigo_2 = _cria_professor(52)
    coordenador = Usuario.objects.create_user(
        email="coordenador.concorrencia.troca@ufsm.br",
        password="x",
        nome_completo="Coordenadora Concorrência Troca",
        cpf=_gera_cpf(53),
        is_coordenador=True,
        is_staff=True,
    )

    # 2 de 3 vagas do professor NOVO já ocupadas — resta exatamente UMA
    # vaga, e é essa vaga que as duas trocas disputam.
    for indice in range(2):
        Projeto.objects.create(
            aluno=_cria_perfil_aluno(indice + 300).usuario,
            orientador=professor_novo.usuario,
            etapa=Projeto.TCC_I,
            status=Projeto.EM_ANDAMENTO,
            ano=ANO_VIGENTE,
            periodo=PERIODO_VIGENTE,
        )

    projeto_1 = Projeto.objects.create(
        aluno=_cria_perfil_aluno(310).usuario,
        orientador=professor_antigo_1.usuario,
        etapa=Projeto.TCC_I,
        status=Projeto.EM_ANDAMENTO,
        ano=ANO_VIGENTE,
        periodo=PERIODO_VIGENTE,
    )
    projeto_2 = Projeto.objects.create(
        aluno=_cria_perfil_aluno(311).usuario,
        orientador=professor_antigo_2.usuario,
        etapa=Projeto.TCC_I,
        status=Projeto.EM_ANDAMENTO,
        ano=ANO_VIGENTE,
        periodo=PERIODO_VIGENTE,
    )

    resultados = {}
    save_original = Projeto.save

    def save_com_atraso(self, *args, **kwargs):
        # Diferente da mutação de INSERT acima (`self.pk is None`): aqui a
        # escrita disputada é um UPDATE de um Projeto que já existe, então o
        # que identifica "a gravação de T1" é o PK do projeto que T1 está
        # trocando, não a ausência de PK.
        if self.pk == projeto_1.pk:
            time.sleep(1.0)
        return save_original(self, *args, **kwargs)

    t1 = threading.Thread(
        target=_troca_em_thread,
        args=(projeto_1.pk, professor_novo.pk, coordenador.pk, resultados, "t1"),
    )
    t2 = threading.Thread(
        target=_troca_em_thread,
        args=(projeto_2.pk, professor_novo.pk, coordenador.pk, resultados, "t2"),
    )

    with mock.patch.object(Projeto, "save", save_com_atraso):
        t1.start()
        time.sleep(0.2)  # garante que T1 já leu a contagem antes de T2 começar
        t2.start()
        t1.join()
        t2.join()

    total_do_professor_novo = Projeto.objects.filter(
        orientador=professor_novo.usuario, etapa=Projeto.TCC_I
    ).count()

    assert total_do_professor_novo == services.LIMITE_PADRAO_VAGAS, (
        f"o teto de {services.LIMITE_PADRAO_VAGAS} vagas foi ultrapassado sob concorrência "
        f"real: {total_do_professor_novo} projetos no final para o professor novo. "
        f"Resultados de cada thread: {resultados}"
    )
    assert "recusado" in resultados["t1"] or "recusado" in resultados["t2"], (
        f"esperava que uma das duas trocas concorrentes fosse recusada pelo teto de vagas, e "
        f"nenhuma foi: {resultados}"
    )
    assert "trocado" in resultados["t1"] or "trocado" in resultados["t2"], (
        f"esperava que uma das duas trocas concorrentes fosse aceita (a vaga existia antes "
        f"das duas tentativas): {resultados}"
    )


# --------------------------------------------------------------------------
# Acréscimo 3 do controlador da T9: aceitar_opcao (T9) contra avancar_cascata
# (T8, chamada pelo Beat da T10 quando o prazo vence) sobre a MESMA
# Candidatura. Hoje só uma opção fica ENVIADA por vez — dois professores não
# disputam a mesma linha por vias normais —, mas os dois CAMINHOS DE CÓDIGO
# disputam, porque ambos travam `Candidatura` (mesma trava, mesma ordem:
# `aceitar_opcao`/`recusar_opcao`, apps/projetos/services.py, e
# `avancar_cascata`, também lá).
# --------------------------------------------------------------------------


def _aceita_opcao_em_thread(opcao_id, por_id, resultados, chave):
    """Roda `services.aceitar_opcao` numa conexão de banco própria — mesmo
    padrão de `_aceita_em_thread`, acima, adaptado para o caminho de
    resposta de uma `OpcaoCandidatura` específica (T9)."""
    connection.close()
    try:
        opcao = OpcaoCandidatura.objects.get(pk=opcao_id)
        por = Usuario.objects.get(pk=por_id)
        services.aceitar_opcao(opcao, por=por)
        resultados[chave] = "aceita"
    except ValidationError as erro:
        resultados[chave] = f"recusada: {erro.messages[0]}"
    finally:
        connection.close()


def _avanca_cascata_em_thread(candidatura_id, resultados, chave):
    """Roda `services.avancar_cascata` numa conexão de banco própria —
    simula o Beat da T10 chamando-a quando o prazo de uma opção vence,
    concorrendo com a resposta manual de um professor sobre a mesma
    candidatura."""
    connection.close()
    try:
        candidatura = Candidatura.objects.get(pk=candidatura_id)
        services.avancar_cascata(candidatura)
        resultados[chave] = "processada"
    finally:
        connection.close()


@pytest.mark.django_db(transaction=True)
def test_aceitar_opcao_e_avancar_cascata_concorrentes_nao_duplicam_desfecho(settings):
    """Acréscimo 3 do controlador da T9: o professor 1 aceita a opção 1 no
    exato instante em que o prazo dela vence e o Beat (T10) chama
    `avancar_cascata` sobre a mesma candidatura.

    Sem a trava de `Candidatura` que `aceitar_opcao` usa (mesma trava e
    mesma ordem de `avancar_cascata` — ambas em apps/projetos/services.py),
    as duas transações poderiam intercalar: `avancar_cascata` marcaria a
    opção 1 `EXPIRADA` e notificaria o professor 2 (a opção 2 viraria
    `ENVIADA`) enquanto `aceitar_opcao` ainda decide criar o `Projeto` a
    partir da MESMA opção 1 — um aluno com projeto criado a partir de uma
    opção que o próprio sistema já tinha marcado expirada, e um segundo
    professor notificado por engano sobre uma candidatura já resolvida.

    Mesmo mecanismo de atraso forçado de
    `test_duas_aceitacoes_simultaneas_no_ultimo_lugar_resultam_em_uma_recusa`,
    acima: a thread do aceite (`t_aceita`) começa primeiro e tem sua escrita
    do `Projeto` atrasada em 1s — tempo real para a thread do Beat
    (`t_avanca`) tentar (e bloquear tentando) travar a MESMA linha de
    `Candidatura` que `t_aceita` já travou. Com a trava certa, `t_avanca` só
    consegue ler o estado depois que `t_aceita` comita, e encontra
    `candidatura.status == ACEITA` — o guarda de status de `avancar_cascata`
    (apps/projetos/services.py) a faz não fazer nada.
    """
    settings.CELERY_TASK_ALWAYS_EAGER = True
    professor1 = _cria_professor(20)
    professor2 = _cria_professor(21)
    aluno = _cria_perfil_aluno(20)

    candidatura = services.registrar_candidatura(aluno, [(professor1, None), (professor2, None)])
    mail.outbox.clear()

    opcao1 = candidatura.opcoes.get(ordem=1)
    # Empurra o prazo para o passado: sem isso, o guarda de prazo de
    # `avancar_cascata` (Importante 1 da rodada de correção 2 da T8) faz a
    # thread do Beat não fazer nada, e a corrida nunca chega a acontecer.
    opcao1.prazo = timezone.now() - timedelta(seconds=1)
    opcao1.save(update_fields=["prazo"])

    resultados = {}
    save_original = Projeto.save

    def save_com_atraso(self, *args, **kwargs):
        # Atrasa só a GRAVAÇÃO do Projeto novo (INSERT, `self.pk is None`)
        # que `aceitar_opcao` decide criar — depois que a trava da
        # Candidatura já foi conseguida (é ela, não este atraso, quem
        # serializa as duas threads) e depois que `criar_projeto_sob_limite`
        # já decidiu que cabe.
        if self.pk is None:
            time.sleep(1.0)
        return save_original(self, *args, **kwargs)

    t_aceita = threading.Thread(
        target=_aceita_opcao_em_thread,
        args=(opcao1.pk, professor1.usuario.pk, resultados, "aceita"),
    )
    t_avanca = threading.Thread(
        target=_avanca_cascata_em_thread,
        args=(candidatura.pk, resultados, "avanca"),
    )

    with mock.patch.object(Projeto, "save", save_com_atraso):
        t_aceita.start()
        time.sleep(0.2)  # garante que a thread do aceite trava a candidatura primeiro
        t_avanca.start()
        t_aceita.join()
        t_avanca.join()

    candidatura.refresh_from_db()
    opcao1.refresh_from_db()
    opcao2 = candidatura.opcoes.get(ordem=2)

    assert resultados["aceita"] == "aceita", resultados
    assert candidatura.status == Candidatura.ACEITA
    assert opcao1.situacao == OpcaoCandidatura.ACEITA
    # `aceitar_opcao` já cancela as opções sem desfecho (opcao2 estava
    # AGUARDANDO) ao comitar — é ISSO que impede a cascata de fazer sentido
    # depois. A cascata NÃO avançou por cima do aceite: `avancar_cascata`, ao
    # conseguir a trava DEPOIS de `aceitar_opcao` já ter comitado, encontrou
    # `candidatura.status == ACEITA` (não `EM_CURSO`) e não tocou opcao2 —
    # ela chegou `CANCELADA` pelo aceite, nunca `ENVIADA` pela cascata.
    assert opcao2.situacao == OpcaoCandidatura.CANCELADA
    assert Projeto.objects.filter(aluno=aluno.usuario, orientador=professor1.usuario).exists()
    # Nem o professor 2 (a cascata não avançou) nem ninguém mais recebeu
    # e-mail nesta corrida — só o e-mail da manifestação original (T8),
    # limpo do outbox antes das threads começarem.
    assert mail.outbox == []


# --------------------------------------------------------------------------
# Importante 1 da rodada de correção 1 da T9: `cancelar_candidatura` ganhou
# `select_for_update` no acréscimo 4 do brief original, mas nenhum teste
# provava que a trava fazia diferença — a revisão mediu que removê-la NÃO
# derruba nenhum dos 134 testes do app nem dos 421 do projeto. Este teste é
# a prova que faltava: professor aceita a opção 1 no exato instante em que o
# aluno cancela a mesma candidatura.
# --------------------------------------------------------------------------


def _cancela_candidatura_em_thread(candidatura_id, aluno_usuario_id, resultados, chave):
    """Roda `services.cancelar_candidatura` numa conexão de banco própria —
    mesmo padrão de `_aceita_opcao_em_thread`, acima."""
    connection.close()
    try:
        candidatura = Candidatura.objects.get(pk=candidatura_id)
        por = Usuario.objects.get(pk=aluno_usuario_id)
        services.cancelar_candidatura(candidatura, por=por)
        resultados[chave] = "cancelada"
    except ValidationError as erro:
        resultados[chave] = f"recusada: {erro.messages[0]}"
    finally:
        connection.close()


@pytest.mark.django_db(transaction=True)
def test_aceitar_opcao_e_cancelar_candidatura_concorrentes_nao_deixam_projeto_orfao(settings):
    """Professor aceita a opção 1 no exato instante em que o aluno cancela a
    candidatura. Sem a trava de `Candidatura` em `cancelar_candidatura`
    (`select_for_update`, acréscimo 4 do brief original da T9), o `UPDATE`
    do cancelamento espera o aceite comitar e depois SOBRESCREVE `ACEITA`
    por `CANCELADA` — o `Projeto` criado pelo aceite sobra órfão de uma
    candidatura que o próprio sistema diz estar cancelada.

    Mesmo mecanismo de atraso forçado das duas provas acima: a thread do
    aceite (`t_aceita`) começa primeiro e tem a gravação do `Projeto`
    atrasada em 1s, dando tempo real para a thread do cancelamento
    (`t_cancela`) tentar (e bloquear tentando) travar a MESMA linha de
    `Candidatura`. Com a trava certa, `t_cancela` só lê o estado depois que
    `t_aceita` comita, encontra `candidatura.status == ACEITA` (não
    `EM_CURSO`) e é recusada pela checagem de status — sem tocar em nada.

    `settings.CELERY_TASK_ALWAYS_EAGER = True` (achado da Tarefa 13, ao
    reconstruir o ambiente do zero): este teste usa `django_db(transaction=True)`
    — a transação de `registrar_candidatura`, abaixo, COMITA de verdade, ao
    contrário dos testes com rollback padrão. Sem o modo eager, o `on_commit`
    de `_enviar_opcao` despacha `enviar_manifestacao.delay(...)` para o broker
    Redis real, e o `celery_worker` real do `docker-compose` processa a tarefa
    depois que o teardown do teste já truncou a tabela — `OpcaoCandidatura.
    DoesNotExist` no log do worker, medido rodando a suíte inteira contra um
    ambiente reconstruído do zero. Nenhuma asserção deste teste depende do
    e-mail; o modo eager só evita a mensagem no broker real, sem afetar a
    prova de concorrência que segue.
    """
    settings.CELERY_TASK_ALWAYS_EAGER = True
    professor = _cria_professor(30)
    aluno = _cria_perfil_aluno(30)

    candidatura = services.registrar_candidatura(aluno, [(professor, None)])
    opcao1 = candidatura.opcoes.get(ordem=1)

    resultados = {}
    save_original = Projeto.save

    def save_com_atraso(self, *args, **kwargs):
        if self.pk is None:
            time.sleep(1.0)
        return save_original(self, *args, **kwargs)

    t_aceita = threading.Thread(
        target=_aceita_opcao_em_thread,
        args=(opcao1.pk, professor.usuario.pk, resultados, "aceita"),
    )
    t_cancela = threading.Thread(
        target=_cancela_candidatura_em_thread,
        args=(candidatura.pk, aluno.usuario.pk, resultados, "cancela"),
    )

    with mock.patch.object(Projeto, "save", save_com_atraso):
        t_aceita.start()
        time.sleep(0.2)  # garante que a thread do aceite trava a candidatura primeiro
        t_cancela.start()
        t_aceita.join()
        t_cancela.join()

    candidatura.refresh_from_db()

    assert resultados["aceita"] == "aceita", resultados
    assert resultados["cancela"].startswith("recusada"), (
        f"o cancelamento concorrente deveria ser recusado (a candidatura já foi aceita "
        f"quando ele conseguiu ler o estado), e não foi: {resultados}"
    )
    assert candidatura.status == Candidatura.ACEITA, (
        f"a candidatura deveria continuar ACEITA — se o cancelamento sobrescreveu isso para "
        f"CANCELADA, sobra um Projeto órfão de uma candidatura cancelada. "
        f"status={candidatura.status}"
    )
    assert Projeto.objects.filter(aluno=aluno.usuario, orientador=professor.usuario).exists()
