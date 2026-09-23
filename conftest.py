import hashlib
import importlib
import os
from collections.abc import Callable
from dataclasses import dataclass, replace
from types import SimpleNamespace

import pytest
from django.conf import settings
from django.test import Client
from django.utils import timezone


def carrega_settings(**ambiente):
    """Recarrega config.settings sob um ambiente diferente e devolve uma cópia.

    A cópia é necessária porque o bloco `finally` restaura o ambiente original
    e recarrega o mesmo módulo de novo (para não vazar estado para outros
    testes): se devolvêssemos o módulo em si, esse segundo reload sobrescreveria
    os valores antes mesmo de o chamador conseguir inspecioná-los.

    Vive no conftest desde a onda final: `tests/test_producao.py` e
    `tests/test_armazenamento.py` precisam do mesmo mecanismo (o segundo
    passou a exercitar o ramo de fallback do armazenamento), e uma segunda
    cópia da função divergiria como as três cópias de suíte de acessibilidade
    já divergiram.
    """
    anterior = dict(os.environ)
    os.environ.update(ambiente)
    try:
        import config.settings

        importlib.reload(config.settings)
        return SimpleNamespace(**vars(config.settings))
    finally:
        os.environ.clear()
        os.environ.update(anterior)
        import config.settings

        importlib.reload(config.settings)


# Ambiente mínimo que o bloco de produção do config/settings.py aceita: todas
# as variáveis que ele impõe via `obrigatorio()`. Qualquer teste que carregue
# os settings com AMBIENTE=producao parte daqui e sobrescreve o que lhe
# interessa — assim, acrescentar uma variável imposta atualiza todos os
# testes de produção de uma vez, em vez de quebrá-los um a um.
AMBIENTE_PRODUCAO = {
    "AMBIENTE": "producao",
    # Chave longa de propósito: `manage.py check --deploy` (W009) reprova
    # SECRET_KEY com menos de 50 caracteres ou pouca entropia.
    "SECRET_KEY": "chave-de-producao-fake-para-teste-com-mais-de-cinquenta-caracteres",
    "ALLOWED_HOSTS": "orientasi.ufsm.br",
    "URL_BASE": "https://orientasi.ufsm.br",
    "EMAIL_BACKEND": "django.core.mail.backends.smtp.EmailBackend",
    "EMAIL_HOST": "smtp.ufsm.br",
    "S3_ACCESS_KEY": "chave-de-acesso",
    "S3_SECRET_KEY": "chave-secreta",
}


def pytest_collection_modifyitems(session, config, items):
    """Liga DJANGO_ALLOW_ASYNC_UNSAFE só quando a sessão inclui algum teste que
    usa `page` (Playwright) — e só uma vez, na coleta, antes de qualquer
    fixture rodar.

    O driver síncrono do Playwright roda seu loop de eventos com um greenlet
    cooperativo na MESMA thread do teste, em vez de numa thread separada:
    `loop.run_until_complete` fica suspenso sempre que esse greenlet devolve o
    controle ao teste. O detector "chamada de banco em contexto async" do
    Django (`django.utils.asyncio.async_unsafe`) enxerga esse loop suspenso e
    conclui, errado, que há um event loop rodando na thread — e barra a
    criação do banco de teste (`SynchronousOnlyOperation`) mesmo sem nenhuma
    concorrência real: greenlets nunca executam dois ao mesmo tempo, então o
    acesso síncrono ao banco nos testes com `page` + `live_server` nunca
    corre risco de reentrância. `DJANGO_ALLOW_ASYNC_UNSAFE` é o escape hatch
    que o próprio Django documenta para exatamente este tipo de falso
    positivo do detector.

    Por que na coleta, e não numa fixture por teste (tentamos primeiro): o
    banco de teste é criado uma única vez por sessão (`django_db_setup`,
    fixture de escopo de sessão do pytest-django), na primeira vez que
    qualquer teste marcado `@pytest.mark.django_db` pede acesso ao banco — e
    a ordem de setup entre esse fixture interno e os fixtures de Playwright
    (`page`/`browser`/`playwright`, também de sessão inteira) não é garantida
    pelo pytest. Confirmamos isso na prática: uma fixture `autouse` que ligava
    a variável só quando `"page" in request.fixturenames` ainda deixava o
    `SynchronousOnlyOperation` estourar, porque a checagem do Django corria
    antes dela. Ligar a variável na coleta — antes de qualquer fixture — evita
    essa corrida por completo. O custo é que a variável fica ligada para a
    sessão inteira, não só para os testes de navegador; o ganho sobre o estado
    anterior (sempre ligada, mesmo sem nenhum teste de navegador na sessão) é
    que uma sessão sem nenhum `page` (ex.: `pytest tests/test_saude.py`,
    `pytest apps/`) nunca liga a variável.

    Preservação de valores pré-existentes: a variável só é definida se ainda
    não estiver presente. Um valor vindo de fora (ex.: CI com `DJANGO_ALLOW_ASYNC_UNSAFE=""`)
    é preservado — a string vazia é lida pelo Django como falso, sendo portanto
    a maneira de forçar a proteção ligada sem ser sobrescrita por este hook.
    """
    if any("page" in item.fixturenames for item in items):
        os.environ.setdefault("DJANGO_ALLOW_ASYNC_UNSAFE", "true")


@pytest.fixture(autouse=True)
def midia_temporaria(settings, tmp_path):
    """Nenhum teste escreve em media/ nem no bucket: cada teste recebe um diretório próprio."""
    settings.MEDIA_ROOT = tmp_path / "media"
    settings.STORAGES = {
        **settings.STORAGES,
        "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    }


# Regras do axe-core (WCAG 2.1 A/AA), larguras e seletor de alvos interativos
# usados por toda suíte de acessibilidade/toque baseada em Playwright — tanto
# a suíte global sobre rotas anônimas (tests/test_acessibilidade.py,
# test_toque.py) quanto qualquer suíte de rota autenticada (a partir da T10,
# ver `autentica_no_navegador` abaixo). Centralizados aqui (revisão 1 da T10)
# para não haver uma segunda cópia por tarefa: antes desta extração,
# apps/contas/tests/test_perfil_acessibilidade.py duplicava as três
# constantes de tests/test_acessibilidade.py e tests/test_toque.py.
REGRAS_AXE = {"runOnly": {"type": "tag", "values": ["wcag2a", "wcag2aa", "wcag21aa"]}}
LARGURAS_TESTADAS = [1280, 360]
SELETOR_INTERATIVOS = (
    "a, button, input:not([type=hidden]), select, textarea, summary, "
    "[tabindex]:not([tabindex='-1']), "
    "[role=button], [role=link], [role=checkbox], [role=tab], [role=menuitem]"
)


@pytest.fixture
def autentica_no_navegador(page, live_server):
    """Fábrica: devolve uma função que autentica `page` (Playwright) como o
    `Usuario` que ela recebe.

    Extraída para cá na revisão 1 da T10: `/perfil/` foi a primeira rota
    autenticada do projeto, e sua suíte de acessibilidade
    (`apps/contas/tests/test_perfil_acessibilidade.py`) precisava navegar já
    logada — as suítes globais (`tests/test_acessibilidade.py` e companhia)
    navegam sempre anônimas, então não serviam. Qualquer suíte de
    acessibilidade de uma rota autenticada futura (T11 em diante) deve reusar
    esta fábrica em vez de reimplementar login + injeção de cookie.

    Mecanismo: `django.test.Client().force_login(usuario)` grava a sessão
    diretamente no banco de teste, sem passar pelo formulário de login; o
    cookie de sessão resultante (`settings.SESSION_COOKIE_NAME`) é injetado
    no contexto do Playwright, para que a navegação real do navegador chegue
    com a sessão já aberta.
    """

    def _autentica(usuario):
        cliente = Client()
        cliente.force_login(usuario)
        cookie = cliente.cookies[settings.SESSION_COOKIE_NAME]
        page.context.add_cookies(
            [{"name": settings.SESSION_COOKIE_NAME, "value": cookie.value, "url": live_server.url}]
        )
        return page

    return _autentica


@dataclass(frozen=True)
class Rota:
    """Uma rota submetida às cinco verificações transversais (axe nas duas
    larguras, exatamente um `<h1>` visível, ausência de rolagem horizontal a
    360px, alvo de toque nas duas larguras, e primeira tabulação no "Pular
    para o conteúdo").

    `fabrica_usuario` é o que permite cobrir tela autenticada sem duplicar a suíte:
    quando presente, a fixture `rota` autentica no navegador antes de medir. `h1`,
    junto com a própria URL final, é a âncora de identidade (confira a fixture `rota`
    abaixo) — sem ela, uma rota quebrada passa medindo a tela de login, defeito que
    este projeto já teve duas vezes: uma na própria fixture `rota` (ver linha ~340,
    corrigida para igualdade exata `page.url == url_esperada`) e outra em
    `apps/contas/tests/test_coordenacao_acessibilidade.py::_confirma_que_esta_no_painel`
    (cuja suíte duplicada nasceu exatamente deste problema antes desta generalização).

    `caminho` aceita uma STRING (rota estática) ou um CALLABLE que recebe o
    `Usuario` devolvido por `fabrica_usuario` e retorna o caminho (rodada de
    correção 2 da T6): uma rota com `<id>` de banco na URL — `/temas/<id>/editar/`
    é a única hoje — não existe antes de a fábrica rodar, então não cabe numa
    string fixa nesta lista. O mecanismo não é uma aposta em rotas futuras: o
    resto do plano do Bloco B só produz caminhos estáticos (`/candidatura/`,
    `/orientacoes/`, `/painel/orientacoes/`). Ele existe para que a PRÓXIMA rota
    dinâmica, quando houver, não precise sair desta lista para uma suíte
    própria — que foi o que aconteceu com `/temas/<id>/editar/` e custou um alvo
    de toque de 24px passar despercebido. A
    fixture `rota`, abaixo, resolve o callable logo após autenticar, e a
    ÂNCORA DE IDENTIDADE (igualdade exata de URL, depois `<h1>`) continua
    exigida do mesmo jeito sobre o caminho já resolvido — sem isso, uma rota
    dinâmica quebrada teria a mesma brecha que a comparação por igualdade
    exata já fecha para as estáticas (ver o parágrafo da fixture sobre
    `endswith`). Uma Rota com `caminho` callable exige `fabrica_usuario`
    (é dela que vem o `Usuario` usado para montar o caminho).
    """

    caminho: str | Callable[[object], str]
    seletor: str
    fabrica_usuario: Callable | None = None
    h1: str | None = None
    # Só preenchido quando duas Rotas compartilham `caminho` (ex.: /perfil/ como
    # professor e como aluno, HTML genuinamente diferente na mesma URL) — desambigua
    # o id que `ids=lambda r: ...` (fixture `rota`, abaixo) gera para o pytest, que do
    # contrário colidiria (duas entradas "/perfil/" seriam indistinguíveis nos
    # relatórios e no -k).
    persona: str | None = None


def cria_professor_para_rotas():
    """Fábrica da variante professor de `/perfil/`: professor com `PerfilProfessor`
    e ao menos uma `Area` cadastrada, para a suíte medir a variante do formulário
    que traz o `<fieldset>`/`<legend>` do grupo de áreas.

    A área criada é também ASSOCIADA ao professor (`perfil.areas.add`, T6):
    sem isso, o professor desta fábrica não declara nenhuma área de atuação, e
    `/temas/meus/` (T6) — cujo campo `area` só lista as áreas que o professor
    declarou — mediria um `<select>` vazio, uma página degenerada em vez da
    tela real."""
    from apps.contas.models import Area, PerfilProfessor, Usuario

    usuario = Usuario.objects.create_user(
        email="professor-das-rotas@ufsm.br",
        password="x",
        nome_completo="Professor das Rotas",
        cpf="98765432100",
    )
    perfil = PerfilProfessor.objects.create(usuario=usuario, siape="1000001")
    area = Area.objects.create(nome="Área das Rotas")
    perfil.areas.add(area)
    return usuario


def cria_coordenador_para_rotas():
    """Fábrica de `/painel/`: professor promovido a coordenador (ver
    apps/contas/tests/test_coordenacao_acessibilidade.py).

    `PerfilProfessor` acrescentado na rodada de correção 1 da T12 (Menor):
    a docstring já prometia "professor promovido a coordenador", mas até
    aqui a fábrica não criava o perfil — a navegação mais densa que
    `base.html` produz para esse papel (coordenador que também é professor:
    "Painel da coordenação", "Painel de orientações", "Meus temas",
    "Minhas orientações", "Mural de temas", "Meu perfil" e "Sair", seis
    botões além do nome) nunca era medida por `ROTAS`. A revisão testou esse
    cenário à parte, em `tests/test_navegacao.py`, e ele passa — não era
    defeito vivo, só cobertura ausente nas cinco suítes transversais.
    """
    from apps.contas.models import PerfilProfessor, Usuario

    usuario = Usuario.objects.create_user(
        email="coordenador-das-rotas@ufsm.br",
        password="x",
        nome_completo="Coordenador das Rotas",
        cpf="12345678909",
        is_coordenador=True,
        is_staff=True,
    )
    PerfilProfessor.objects.create(usuario=usuario, siape="1000000")
    return usuario


def cria_aluno_para_rotas():
    """Fábrica da variante aluno de `/perfil/` — o HTML difere de verdade da
    variante professor (sem o `<fieldset>`/`<legend>` do grupo de áreas), por isso
    as duas entram em `ROTAS` separadamente.

    NÃO é a fábrica de `/temas/` (mural, T7): o mural precisa de temas e de
    professores com/sem vaga para medir os dois badges, e semear isso aqui
    acrescentaria estado irrelevante à medição de `/perfil/` — mesmo motivo
    pelo qual `cria_professor_para_rotas` não ganhou um `Tema` (ver a
    docstring de `cria_professor_com_tema_para_rotas`). A fábrica do mural é
    `cria_aluno_com_mural_para_rotas`, abaixo."""
    from apps.contas.models import PerfilAluno, Usuario

    usuario = Usuario.objects.create_user(
        email="aluno-das-rotas@ufsm.br",
        password="x",
        nome_completo="Aluno das Rotas",
        cpf="11144477735",
        papel=Usuario.ALUNO,
    )
    PerfilAluno.objects.create(usuario=usuario, matricula="202399999")
    return usuario


def cria_professor_com_tema_para_rotas():
    """Fábrica de `/temas/<id>/editar/` (rodada de correção 2 da T6) e de
    `/temas/meus/` (acréscimo de escopo da T7): professor com
    `PerfilProfessor`, uma `Area` declarada, e DOIS temas seus já cadastrados
    — um ativo e um inativo.

    O pk do tema ATIVO é anexado ao próprio `Usuario` devolvido
    (`usuario.tema_id_para_rota`) porque a fixture `rota` só tem acesso ao que
    `fabrica_usuario()` RETORNA — ela não pode devolver um segundo objeto
    (tema) sem mudar o contrato de toda `ROTAS`. É esse atributo que o
    `caminho` callable da Rota, abaixo, lê para montar `/temas/<id>/editar/`
    depois que a fábrica já rodou.

    O segundo tema, inativo, existe só para a suíte de `/temas/meus/`: antes
    desta correção, aquela rota era medida com `cria_professor_para_rotas`,
    que não cria nenhum `Tema` — a suíte de acessibilidade rodava inteira
    contra a tela VAZIA (achado da revisão da T6, relatado no brief desta
    T7: "TEM 'Temas cadastrados': True / TEM botao Desativar: False / TEM
    estado vazio: True"). O botão `btn btn-outline btn-sm` de desativar (só
    aparece para tema ativo), o `badge badge-neutral` de tema inativo e o
    layout da lista com dois itens nunca passavam pelo axe, pelo alvo de
    toque ou pela responsividade — exatamente o markup que mais muda quando
    a lista cresce. Com um tema de cada estado, os dois ramos do template
    (`{% if tema.ativo %}`/`{% if not tema.ativo %}` em
    templates/projetos/meus_temas.html) entram na medição.

    Não foi semeado em `cria_professor_para_rotas` (a fábrica que `/perfil/`
    também usa, na variante professor): fazer isso acrescentaria um `Tema`
    irrelevante à medição de `/perfil/`, que não lista temas."""
    from apps.contas.models import Area, PerfilProfessor, Usuario
    from apps.projetos.models import Tema

    usuario = Usuario.objects.create_user(
        email="professor-tema-das-rotas@ufsm.br",
        password="x",
        nome_completo="Professor Tema das Rotas",
        cpf="70000000230",
    )
    perfil = PerfilProfessor.objects.create(usuario=usuario, siape="1000002")
    area = Area.objects.create(nome="Área do Tema das Rotas")
    perfil.areas.add(area)
    tema = Tema.objects.create(
        professor=perfil,
        titulo="Tema das Rotas",
        descricao="Descrição do tema das rotas, para a tela de edição não ficar vazia.",
    )
    tema.areas.set([area])
    tema_inativo = Tema.objects.create(
        professor=perfil,
        titulo="Tema Inativo das Rotas",
        descricao="Descrição do tema inativo das rotas, para o badge entrar na medição.",
        ativo=False,
    )
    tema_inativo.areas.set([area])
    usuario.tema_id_para_rota = tema.pk
    return usuario


def cria_aluno_com_mural_para_rotas():
    """Fábrica de `/temas/` (mural, T7 — acrescentada na rodada de correção
    1): aluno autenticado, mais dois temas ATIVOS de DOIS professores
    distintos — um com vaga, um sem —, para que os dois estados do badge
    (`badge-success`/`badge-neutral`) entrem na medição.

    Achado da revisão da rodada de correção 1: a `Rota` de `/temas/` media a
    fábrica `cria_aluno_para_rotas`, que não semeia nenhum `Tema` — a suíte
    inteira rodava contra o mural VAZIO, sem `<li>` nenhum, o mesmo padrão de
    defeito que o acréscimo de escopo original da T7 já havia consertado
    para `/temas/meus/` (ver `cria_professor_com_tema_para_rotas`, acima). A
    responsabilidade é do brief da T7, não de quem implementou: o Passo 5
    ditou a fábrica `cria_aluno_para_rotas` para esta rota, e o próprio
    acréscimo de escopo — três parágrafos abaixo, na mesma página — já
    condenava esse padrão para `/temas/meus/` sem que a contradição fosse
    percebida a tempo de valer também para o mural.

    O professor SEM vaga recebe 3 `Projeto` em TCC_I no semestre vigente —
    o teto padrão (`LIMITE_PADRAO_VAGAS = 3`, apps/projetos/services.py),
    sem nenhuma autorização de `LimiteOrientacao` — para que
    `professor_tem_vaga` seja `False` só para o tema dele.

    Não semeada em `cria_aluno_para_rotas`: ela também alimenta a variante
    aluno de `/perfil/`, e semear temas/projetos lá acrescentaria estado
    irrelevante àquela medição — mesmo motivo pelo qual
    `cria_professor_para_rotas` não ganhou um `Tema` na T6."""
    from apps.comum.semestre import semestre_vigente
    from apps.contas.models import Area, PerfilAluno, PerfilProfessor, Usuario
    from apps.projetos.models import Projeto, Tema

    usuario = Usuario.objects.create_user(
        email="aluno-mural-das-rotas@ufsm.br",
        password="x",
        nome_completo="Aluno Mural das Rotas",
        cpf="20000000027",
        papel=Usuario.ALUNO,
    )
    PerfilAluno.objects.create(usuario=usuario, matricula="202399998")

    area = Area.objects.create(nome="Área do Mural das Rotas")

    professor_com_vaga = PerfilProfessor.objects.create(
        usuario=Usuario.objects.create_user(
            email="professor-mural-com-vaga-das-rotas@ufsm.br",
            password="x",
            nome_completo="Professor Mural Com Vaga das Rotas",
            cpf="20765432102",
        ),
        siape="1000003",
    )
    professor_com_vaga.areas.add(area)
    tema_com_vaga = Tema.objects.create(
        professor=professor_com_vaga,
        titulo="Tema Com Vaga das Rotas",
        descricao="Descrição do tema com vaga das rotas, para o badge-success entrar na medição.",
    )
    tema_com_vaga.areas.set([area])

    professor_sem_vaga = PerfilProfessor.objects.create(
        usuario=Usuario.objects.create_user(
            email="professor-mural-sem-vaga-das-rotas@ufsm.br",
            password="x",
            nome_completo="Professor Mural Sem Vaga das Rotas",
            cpf="21530864267",
        ),
        siape="1000004",
    )
    professor_sem_vaga.areas.add(area)
    tema_sem_vaga = Tema.objects.create(
        professor=professor_sem_vaga,
        titulo="Tema Sem Vaga das Rotas",
        descricao="Descrição do tema sem vaga das rotas, para o badge-neutral entrar na medição.",
    )
    tema_sem_vaga.areas.set([area])
    ano, periodo = semestre_vigente()
    cpfs_orientandos = ["22296296386", "23061728465", "23827160537"]
    for indice, cpf in enumerate(cpfs_orientandos):
        aluno_orientando = Usuario.objects.create_user(
            email=f"aluno-orientando-mural-das-rotas-{indice}@ufsm.br",
            password="x",
            nome_completo=f"Aluno Orientando Mural das Rotas {indice}",
            cpf=cpf,
            papel=Usuario.ALUNO,
        )
        Projeto.objects.create(
            aluno=aluno_orientando,
            orientador=professor_sem_vaga.usuario,
            etapa=Projeto.TCC_I,
            ano=ano,
            periodo=periodo,
        )
    return usuario


def _gera_cpf_das_rotas(indice):
    """Mesmo mecanismo de `_gera_cpf` nos arquivos de teste de
    `apps/projetos/tests/` (dígito verificador calculado, não digitado à
    mão), com faixa própria (810000000+) para a fábrica de `/orientacoes/`
    (T9) não colidir com nenhum CPF literal já usado pelas fábricas acima."""
    from apps.contas.validators import _digito

    base = f"{810000000 + indice:09d}"
    d1 = _digito(base, 10)
    d2 = _digito(base + str(d1), 11)
    return base + str(d1) + str(d2)


def cria_professor_com_manifestacao_para_rotas():
    """Fábrica de `/orientacoes/` (T9, fila do professor + orientandos
    atuais — a segunda metade acrescentada na rodada de correção 1):
    professor com `PerfilProfessor`, DUAS manifestações de interesse
    pendentes (`OpcaoCandidatura` `situacao=ENVIADA`), de dois alunos
    diferentes — uma com tema escolhido, uma sem — e UM `Projeto`
    `EM_ANDAMENTO` no semestre vigente, para que as três seções condicionais
    do template (`{% if opcao.tema %}`, a lista de manifestações e a lista
    de orientandos) entrem na medição, mesmo motivo pelo qual
    `cria_professor_com_tema_para_rotas` (T6) semeia um tema ativo e um
    inativo em vez de só um.

    Duas `Candidatura`s distintas (uma por aluno), cada uma com sua única
    opção `ENVIADA` apontando para o MESMO professor: nada na regra de
    negócio impede um professor de ter mais de uma manifestação pendente ao
    mesmo tempo, vinda de alunos diferentes — só uma `OpcaoCandidatura` por
    `Candidatura` fica `ENVIADA` de cada vez (a cascata, T8), não uma por
    professor.
    """
    from apps.comum.semestre import semestre_vigente
    from apps.contas.models import Area, PerfilAluno, PerfilProfessor, Usuario
    from apps.projetos.models import Candidatura, OpcaoCandidatura, Projeto, Submissao, Tema

    usuario = Usuario.objects.create_user(
        email="professor-orientacoes-das-rotas@ufsm.br",
        password="x",
        nome_completo="Professor Orientações das Rotas",
        cpf=_gera_cpf_das_rotas(0),
    )
    perfil = PerfilProfessor.objects.create(usuario=usuario, siape="1000005")
    area = Area.objects.create(nome="Área das Orientações das Rotas")
    perfil.areas.add(area)
    tema = Tema.objects.create(
        professor=perfil,
        titulo="Tema das Orientações das Rotas",
        descricao="Descrição do tema das orientações das rotas.",
    )
    tema.areas.set([area])

    ano, periodo = semestre_vigente()
    agora = timezone.now()
    prazo = agora + timezone.timedelta(days=7)

    for indice, tema_da_opcao in [(1, tema), (2, None)]:
        aluno = Usuario.objects.create_user(
            email=f"aluno-orientacoes-das-rotas-{indice}@ufsm.br",
            password="x",
            nome_completo=f"Aluno Orientações das Rotas {indice}",
            cpf=_gera_cpf_das_rotas(indice),
            papel=Usuario.ALUNO,
        )
        perfil_aluno = PerfilAluno.objects.create(usuario=aluno, matricula=f"20263999{indice:02d}")
        candidatura = Candidatura.objects.create(aluno=perfil_aluno, ano=ano, periodo=periodo)
        OpcaoCandidatura.objects.create(
            candidatura=candidatura,
            ordem=1,
            professor=perfil,
            tema=tema_da_opcao,
            situacao=OpcaoCandidatura.ENVIADA,
            enviada_em=agora,
            prazo=prazo,
        )

    # Um orientando ATUAL (acréscimo de escopo da rodada de correção 1):
    # sem isto, a suíte de acessibilidade mediria só a metade nova do
    # template no estado VAZIO (`{% else %}` de "Orientandos atuais"), nunca
    # o `<li>` de verdade — mesma classe de defeito que a rodada de correção
    # 1 da T7 já corrigiu para o mural (`cria_aluno_com_mural_para_rotas`).
    orientando = Usuario.objects.create_user(
        email="aluno-orientacoes-orientando-das-rotas@ufsm.br",
        password="x",
        nome_completo="Aluno Orientações Orientando das Rotas",
        cpf=_gera_cpf_das_rotas(3),
        papel=Usuario.ALUNO,
    )
    PerfilAluno.objects.create(usuario=orientando, matricula="2026399903")
    projeto_orientando = Projeto.objects.create(
        aluno=orientando,
        orientador=usuario,
        tema=tema,
        etapa=Projeto.TCC_I,
        status=Projeto.EM_ANDAMENTO,
        ano=ano,
        periodo=periodo,
    )
    Submissao.objects.create(
        projeto=projeto_orientando,
        pdf="submissoes/rota-orientacoes.pdf",
        editavel="submissoes/rota-orientacoes.docx",
    )

    # Segundo orientando, SEM submissão (Bloco C): a fábrica original (rodada
    # de correção 1 do Bloco B) só criava um `Projeto` — nenhum dos dois
    # ramos do `{% if projeto.submissao %}` ficaria descoberto se todo
    # orientando desta fábrica tivesse envio.
    orientando_sem_envio = Usuario.objects.create_user(
        email="aluno-orientacoes-sem-envio-das-rotas@ufsm.br",
        password="x",
        nome_completo="Aluno Orientações Sem Envio das Rotas",
        cpf=_gera_cpf_das_rotas(4),
        papel=Usuario.ALUNO,
    )
    PerfilAluno.objects.create(usuario=orientando_sem_envio, matricula="2026399904")
    Projeto.objects.create(
        aluno=orientando_sem_envio,
        orientador=usuario,
        tema=tema,
        etapa=Projeto.TCC_I,
        status=Projeto.EM_ANDAMENTO,
        ano=ano,
        periodo=periodo,
    )
    return usuario


def cria_aluno_sem_candidatura_para_rotas():
    """Fábrica de `/candidatura/` na variante MONTAR (T11): aluno com
    `PerfilAluno` e sem nenhuma `Candidatura` — a tela mostra o formulário de
    até três opções. Semeia um `Tema` ativo (professor com uma `Area`
    declarada) para o `<select>` das três opções não ficar vazio — mesma
    lição de `cria_aluno_com_mural_para_rotas`, acima, sobre não medir uma
    tela com lista vazia."""
    from apps.contas.models import Area, PerfilAluno, PerfilProfessor, Usuario
    from apps.projetos.models import Tema

    usuario = Usuario.objects.create_user(
        email="aluno-candidatura-das-rotas@ufsm.br",
        password="x",
        nome_completo="Aluno Candidatura das Rotas",
        cpf=_gera_cpf_das_rotas(4),
        papel=Usuario.ALUNO,
    )
    PerfilAluno.objects.create(usuario=usuario, matricula="2026399904")

    area = Area.objects.create(nome="Área da Candidatura das Rotas")
    professor = PerfilProfessor.objects.create(
        usuario=Usuario.objects.create_user(
            email="professor-candidatura-das-rotas@ufsm.br",
            password="x",
            nome_completo="Professor Candidatura das Rotas",
            cpf=_gera_cpf_das_rotas(5),
        ),
        siape="1000006",
    )
    professor.areas.add(area)
    tema = Tema.objects.create(
        professor=professor,
        titulo="Tema da Candidatura das Rotas",
        descricao="Descrição do tema da candidatura das rotas.",
    )
    tema.areas.set([area])
    return usuario


def cria_aluno_com_candidatura_para_rotas():
    """Fábrica de `/candidatura/` na variante ACOMPANHAR (T11): aluno com uma
    `Candidatura` `EM_CURSO` cujas três opções cobrem os três ramos
    condicionais do template `projetos/candidatura.html` de uma vez — mesma
    lição de `cria_professor_com_manifestacao_para_rotas`, acima, sobre
    semear os dois lados de um `{% if %}` em vez de só o estado vazio:

    - opção 1 `RECUSADA`, com justificativa (só aqui o trecho "Justificativa
      da recusa" aparece);
    - opção 2 `ENVIADA` — a que `opcao_atual` aponta —, sem tema ("Sem tema
      específico");
    - opção 3 `AGUARDANDO` (ainda não alcançada pela cascata).
    """
    from apps.comum.semestre import semestre_vigente
    from apps.contas.models import Area, PerfilAluno, PerfilProfessor, Usuario
    from apps.projetos.models import Candidatura, OpcaoCandidatura, Tema

    usuario = Usuario.objects.create_user(
        email="aluno-candidatura-acompanha-das-rotas@ufsm.br",
        password="x",
        nome_completo="Aluno Candidatura Acompanha das Rotas",
        cpf=_gera_cpf_das_rotas(6),
        papel=Usuario.ALUNO,
    )
    perfil_aluno = PerfilAluno.objects.create(usuario=usuario, matricula="2026399905")

    area = Area.objects.create(nome="Área da Candidatura Acompanha das Rotas")
    professores = []
    for indice in range(7, 10):
        professor = PerfilProfessor.objects.create(
            usuario=Usuario.objects.create_user(
                email=f"professor-candidatura-acompanha-das-rotas-{indice}@ufsm.br",
                password="x",
                nome_completo=f"Professor Candidatura Acompanha das Rotas {indice}",
                cpf=_gera_cpf_das_rotas(indice),
            ),
            siape=f"100000{indice}",
        )
        professor.areas.add(area)
        professores.append(professor)

    tema_recusado = Tema.objects.create(
        professor=professores[0],
        titulo="Tema Recusado da Candidatura das Rotas",
        descricao="Descrição do tema recusado da candidatura das rotas.",
    )
    tema_recusado.areas.set([area])

    ano, periodo = semestre_vigente()
    agora = timezone.now()
    candidatura = Candidatura.objects.create(
        aluno=perfil_aluno, ano=ano, periodo=periodo, opcao_atual=2
    )
    OpcaoCandidatura.objects.create(
        candidatura=candidatura,
        ordem=1,
        professor=professores[0],
        tema=tema_recusado,
        situacao=OpcaoCandidatura.RECUSADA,
        justificativa="Já atingi o limite de orientandos nesta área.",
        respondida_em=agora,
    )
    OpcaoCandidatura.objects.create(
        candidatura=candidatura,
        ordem=2,
        professor=professores[1],
        tema=None,
        situacao=OpcaoCandidatura.ENVIADA,
        enviada_em=agora,
        prazo=agora + timezone.timedelta(days=7),
    )
    OpcaoCandidatura.objects.create(
        candidatura=candidatura,
        ordem=3,
        professor=professores[2],
        tema=None,
        situacao=OpcaoCandidatura.AGUARDANDO,
    )
    return usuario


def cria_aluno_com_projeto_para_rotas():
    """Fábrica de `/meu-tcc/` (Bloco C): aluno com `Projeto` `EM_ANDAMENTO`
    no semestre vigente e uma `Submissao` já enviada — para que o ramo "já
    enviou, versão N" do template entre na medição, não só o formulário
    vazio (mesma lição de `cria_professor_com_manifestacao_para_rotas`,
    acima: semear os dois lados de um `{% if %}`, não só o estado inicial).

    Sem `Area`: `meu_tcc.html` não usa área nenhuma — diferente das fábricas
    de tema/mural, que precisam de uma `Area` para o professor declarar."""
    from apps.comum.semestre import semestre_vigente
    from apps.contas.models import PerfilAluno, PerfilProfessor, Usuario
    from apps.projetos.models import Projeto, Submissao

    usuario = Usuario.objects.create_user(
        email="aluno-meutcc-das-rotas@ufsm.br",
        password="x",
        nome_completo="Aluno Meu TCC das Rotas",
        cpf=_gera_cpf_das_rotas(10),
        papel=Usuario.ALUNO,
    )
    PerfilAluno.objects.create(usuario=usuario, matricula="2026399910")

    professor = PerfilProfessor.objects.create(
        usuario=Usuario.objects.create_user(
            email="professor-meutcc-das-rotas@ufsm.br",
            password="x",
            nome_completo="Professor Meu TCC das Rotas",
            cpf=_gera_cpf_das_rotas(11),
        ),
        siape="1000010",
    )

    ano, periodo = semestre_vigente()
    projeto = Projeto.objects.create(
        aluno=usuario,
        orientador=professor.usuario,
        etapa=Projeto.TCC_I,
        ano=ano,
        periodo=periodo,
    )
    Submissao.objects.create(
        projeto=projeto,
        pdf="submissoes/rota-teste.pdf",
        editavel="submissoes/rota-teste.docx",
    )
    return usuario


def cria_coordenador_com_painel_orientacoes_para_rotas():
    """Fábrica de `/painel/orientacoes/` (T12): coordenador autenticado, mais
    dois `Projeto` de professores DIFERENTES — um com tema, um sem (os dois
    ramos de `{% if projeto.tema %}` do template) — e um `LimiteOrientacao`
    concedido a um deles, para que a seção "Limites concedidos" também entre
    na medição — mesma lição de `cria_professor_com_manifestacao_para_rotas`
    (T9) sobre não deixar um ramo inteiro do template fora da suíte."""
    from apps.comum.semestre import semestre_vigente
    from apps.contas.models import Area, PerfilAluno, PerfilProfessor, Usuario
    from apps.projetos.models import LimiteOrientacao, Projeto, Tema

    coordenador = Usuario.objects.create_user(
        email="coordenador-painel-orientacoes-das-rotas@ufsm.br",
        password="x",
        nome_completo="Coordenador Painel Orientações das Rotas",
        cpf=_gera_cpf_das_rotas(20),
        is_coordenador=True,
        is_staff=True,
    )

    area = Area.objects.create(nome="Área do Painel de Orientações das Rotas")
    professor1 = PerfilProfessor.objects.create(
        usuario=Usuario.objects.create_user(
            email="professor-painel-orientacoes-1-das-rotas@ufsm.br",
            password="x",
            nome_completo="Professor Painel Orientações 1 das Rotas",
            cpf=_gera_cpf_das_rotas(21),
        ),
        siape="1000010",
    )
    professor1.areas.add(area)
    professor2 = PerfilProfessor.objects.create(
        usuario=Usuario.objects.create_user(
            email="professor-painel-orientacoes-2-das-rotas@ufsm.br",
            password="x",
            nome_completo="Professor Painel Orientações 2 das Rotas",
            cpf=_gera_cpf_das_rotas(22),
        ),
        siape="1000011",
    )
    professor2.areas.add(area)
    tema = Tema.objects.create(
        professor=professor1,
        titulo="Tema do Painel de Orientações das Rotas",
        descricao="Descrição do tema do painel de orientações das rotas.",
    )
    tema.areas.set([area])

    ano, periodo = semestre_vigente()
    aluno1 = Usuario.objects.create_user(
        email="aluno-painel-orientacoes-1-das-rotas@ufsm.br",
        password="x",
        nome_completo="Aluno Painel Orientações 1 das Rotas",
        cpf=_gera_cpf_das_rotas(23),
        papel=Usuario.ALUNO,
    )
    PerfilAluno.objects.create(usuario=aluno1, matricula="2026399910")
    Projeto.objects.create(
        aluno=aluno1,
        orientador=professor1.usuario,
        tema=tema,
        etapa=Projeto.TCC_I,
        status=Projeto.EM_ANDAMENTO,
        ano=ano,
        periodo=periodo,
    )

    aluno2 = Usuario.objects.create_user(
        email="aluno-painel-orientacoes-2-das-rotas@ufsm.br",
        password="x",
        nome_completo="Aluno Painel Orientações 2 das Rotas",
        cpf=_gera_cpf_das_rotas(24),
        papel=Usuario.ALUNO,
    )
    PerfilAluno.objects.create(usuario=aluno2, matricula="2026399911")
    Projeto.objects.create(
        aluno=aluno2,
        orientador=professor2.usuario,
        tema=None,
        etapa=Projeto.TCC_I,
        status=Projeto.EM_ANDAMENTO,
        ano=ano,
        periodo=periodo,
    )

    LimiteOrientacao.objects.create(
        professor=professor2,
        etapa=Projeto.TCC_I,
        ano=ano,
        periodo=periodo,
        limite=4,
        justificativa="Sobrecarga temporária autorizada para a suíte de rotas.",
        autorizado_por=coordenador,
    )
    return coordenador


def cria_professor_com_banca_agendada_para_rotas():
    """Fábrica de `/bancas/agendar/<id>/`, `/bancas/<id>/editar/` e
    `/bancas/<id>/resultado/` (Bloco D): professor orientador com um
    `Projeto` `EM_ANDAMENTO` com `Submissao`, e uma `Banca` `AGENDADA` já
    criada sobre ele. Os dois `pk`s que as rotas precisam (`projeto.pk` para
    agendar, `banca.pk` para editar/resultado) são anexados ao `Usuario`
    devolvido — mesmo mecanismo de `usuario.tema_id_para_rota` em
    `cria_professor_com_tema_para_rotas` (T6): a fixture `rota` só recebe o
    que `fabrica_usuario()` retorna, então não há outro jeito de entregar um
    segundo `pk` a ela."""
    from apps.bancas.services import agendar_banca
    from apps.comum.semestre import semestre_vigente
    from apps.contas.models import PerfilAluno, PerfilProfessor, Usuario
    from apps.projetos.models import Projeto, Submissao

    orientador = Usuario.objects.create_user(
        email="professor-banca-das-rotas@ufsm.br",
        password="x",
        nome_completo="Professor Banca das Rotas",
        cpf=_gera_cpf_das_rotas(30),
    )
    PerfilProfessor.objects.create(usuario=orientador, siape="1000020")

    aluno = Usuario.objects.create_user(
        email="aluno-banca-das-rotas@ufsm.br",
        password="x",
        nome_completo="Aluno Banca das Rotas",
        cpf=_gera_cpf_das_rotas(31),
        papel=Usuario.ALUNO,
    )
    PerfilAluno.objects.create(usuario=aluno, matricula="2026399920")

    ano, periodo = semestre_vigente()
    projeto = Projeto.objects.create(
        aluno=aluno,
        orientador=orientador,
        etapa=Projeto.TCC_I,
        status=Projeto.EM_ANDAMENTO,
        ano=ano,
        periodo=periodo,
    )
    Submissao.objects.create(
        projeto=projeto, pdf="submissoes/rota-banca.pdf", editavel="submissoes/rota-banca.docx"
    )

    membro1 = Usuario.objects.create_user(
        email="membro1-banca-das-rotas@ufsm.br",
        password="x",
        nome_completo="Membro Um Banca das Rotas",
        cpf=_gera_cpf_das_rotas(32),
    )
    perfil_membro1 = PerfilProfessor.objects.create(usuario=membro1, siape="1000021")

    banca = agendar_banca(
        projeto,
        data_hora=timezone.now() + timezone.timedelta(days=7),
        local="Sala das Rotas",
        membros=[{"professor": perfil_membro1}, {"nome_externo": "Externo das Rotas"}],
        por=orientador,
    )

    orientador.projeto_id_para_rota = projeto.pk
    orientador.banca_id_para_rota = banca.pk
    return orientador


def cria_sugrad_com_ata_pendente_para_rotas():
    """Fábrica de `/painel/sugrad/` (Bloco E): conta SUGRAD com uma `Ata`
    `PENDENTE` já gerada, para a lista do painel não ficar vazia na
    medição."""
    from apps.bancas.services import agendar_banca, registrar_resultado
    from apps.comum.semestre import semestre_vigente
    from apps.contas.models import PerfilAluno, PerfilProfessor, Usuario
    from apps.projetos.models import Projeto, Submissao
    from apps.projetos.services import aprovar_projeto

    sugrad = Usuario.objects.create_user(
        email="sugrad-das-rotas@ufsm.br",
        password="x",
        nome_completo="SUGRAD das Rotas",
        papel=Usuario.SUGRAD,
        cpf=None,
    )

    orientador = Usuario.objects.create_user(
        email="orientador-ata-das-rotas@ufsm.br",
        password="x",
        nome_completo="Orientador Ata das Rotas",
        cpf=_gera_cpf_das_rotas(33),
    )
    PerfilProfessor.objects.create(usuario=orientador, siape="1000022")

    aluno = Usuario.objects.create_user(
        email="aluno-ata-das-rotas@ufsm.br",
        password="x",
        nome_completo="Aluno Ata das Rotas",
        cpf=_gera_cpf_das_rotas(34),
        papel=Usuario.ALUNO,
    )
    PerfilAluno.objects.create(usuario=aluno, matricula="2026399921")

    ano, periodo = semestre_vigente()
    projeto = Projeto.objects.create(
        aluno=aluno,
        orientador=orientador,
        etapa=Projeto.TCC_I,
        status=Projeto.EM_ANDAMENTO,
        ano=ano,
        periodo=periodo,
    )
    Submissao.objects.create(
        projeto=projeto, pdf="submissoes/rota-ata.pdf", editavel="submissoes/rota-ata.docx"
    )

    membro1 = Usuario.objects.create_user(
        email="membro1-ata-das-rotas@ufsm.br",
        password="x",
        nome_completo="Membro Um Ata das Rotas",
        cpf=_gera_cpf_das_rotas(35),
    )
    perfil_membro1 = PerfilProfessor.objects.create(usuario=membro1, siape="1000023")
    membro2 = Usuario.objects.create_user(
        email="membro2-ata-das-rotas@ufsm.br",
        password="x",
        nome_completo="Membro Dois Ata das Rotas",
        cpf=_gera_cpf_das_rotas(36),
    )
    perfil_membro2 = PerfilProfessor.objects.create(usuario=membro2, siape="1000024")

    banca = agendar_banca(
        projeto,
        data_hora=timezone.now(),
        local="Sala das Rotas",
        membros=[{"professor": perfil_membro1}, {"professor": perfil_membro2}],
        por=orientador,
    )
    registrar_resultado(
        banca,
        nota=8.5,
        resultado=Projeto.APROVADO_COM_RESSALVAS,
        comentario="Boa apresentação.",
        por=orientador,
    )

    aprovar_projeto(projeto, por=orientador)

    return sugrad


def cria_professor_para_criar_orientacao_para_rotas():
    """Fábrica de `/orientacoes/criar/` (Bloco F; rota renomeada de
    `/temas/tcc-ii/criar/` no acréscimo posterior que uniu TCC I/TCC II na
    mesma tela — pedido explícito do usuário, exceção à regra inegociável
    nº 8 do CLAUDE.md): só precisa de um professor com `PerfilProfessor` —
    a tela não depende de nenhum aluno pré-existente (o `<select>` lista
    todo `PerfilAluno`, e a suíte não precisa que a lista tenha itens pra
    medir a tela)."""
    from apps.contas.models import PerfilProfessor, Usuario

    usuario = Usuario.objects.create_user(
        email="professor-criar-orientacao-das-rotas@ufsm.br",
        password="x",
        nome_completo="Professor Criar Orientação das Rotas",
        cpf=_gera_cpf_das_rotas(37),
    )
    PerfilProfessor.objects.create(usuario=usuario, siape="1000025")
    return usuario


def cria_professor_com_correcao_para_rotas():
    """Fábrica de `/bancas/<projeto_id>/correcoes/` (Bloco F): professor
    orientador com um `Projeto` TCC_II `Aprovado com Ressalvas` e um
    `ItemCorrecao` já criado, pra medir o ramo "concluído"/"não concluído"
    do template."""
    from apps.bancas.models import ItemCorrecao
    from apps.comum.semestre import semestre_vigente
    from apps.contas.models import PerfilAluno, PerfilProfessor, Usuario
    from apps.projetos.models import Projeto

    orientador = Usuario.objects.create_user(
        email="professor-correcao-das-rotas@ufsm.br",
        password="x",
        nome_completo="Professor Correção das Rotas",
        cpf=_gera_cpf_das_rotas(38),
    )
    PerfilProfessor.objects.create(usuario=orientador, siape="1000026")

    aluno = Usuario.objects.create_user(
        email="aluno-correcao-das-rotas@ufsm.br",
        password="x",
        nome_completo="Aluno Correção das Rotas",
        cpf=_gera_cpf_das_rotas(39),
        papel=Usuario.ALUNO,
    )
    PerfilAluno.objects.create(usuario=aluno, matricula="2026399922")

    ano, periodo = semestre_vigente()
    projeto = Projeto.objects.create(
        aluno=aluno,
        orientador=orientador,
        etapa=Projeto.TCC_II,
        status=Projeto.APROVADO_COM_RESSALVAS,
        ano=ano,
        periodo=periodo,
    )
    ItemCorrecao.objects.create(projeto=projeto, descricao="Item das rotas.")

    orientador.projeto_id_para_rota = projeto.pk
    return orientador


def cria_projeto_catalogavel_para_rotas():
    """Fábrica de `/catalogo/` (Bloco G): um TCC_II Concluído completo
    (tema, submissão, termo, ata aprovada) — sem isso a suíte mediria a
    lista vazia, uma tela degenerada em vez da real (mesmo raciocínio de
    `cria_sugrad_com_ata_pendente_para_rotas`, Bloco E)."""
    from apps.bancas.models import Banca
    from apps.contas.models import Area, PerfilAluno, PerfilProfessor, Usuario
    from apps.documentos.models import Ata, RevisaoSUGRAD
    from apps.projetos.models import Projeto, Submissao, Tema, TermoPublicacao

    orientador = Usuario.objects.create_user(
        email="orientador-catalogo-das-rotas@ufsm.br",
        password="x",
        nome_completo="Orientador Catálogo das Rotas",
        cpf=_gera_cpf_das_rotas(40),
    )
    perfil_orientador = PerfilProfessor.objects.create(usuario=orientador, siape="1000027")
    aluno = Usuario.objects.create_user(
        email="aluno-catalogo-das-rotas@ufsm.br",
        password="x",
        nome_completo="Aluno Catálogo das Rotas",
        cpf=_gera_cpf_das_rotas(41),
        papel=Usuario.ALUNO,
    )
    PerfilAluno.objects.create(usuario=aluno, matricula="2026399923")
    area = Area.objects.create(nome="Área Catálogo das Rotas")
    tema = Tema.objects.create(
        professor=perfil_orientador,
        titulo="Tema Catálogo das Rotas",
        descricao="Descrição do tema catalogado.",
    )
    tema.areas.set([area])
    projeto = Projeto.objects.create(
        aluno=aluno,
        orientador=orientador,
        tema=tema,
        etapa=Projeto.TCC_II,
        status=Projeto.CONCLUIDO,
        ano=2026,
        periodo=1,
    )
    Submissao.objects.create(
        projeto=projeto,
        pdf="submissoes/rota-catalogo.pdf",
        editavel="submissoes/rota-catalogo.docx",
    )
    TermoPublicacao.objects.create(projeto=projeto)
    banca = Banca.objects.create(
        projeto=projeto,
        data_hora=timezone.now(),
        local="Sala Catálogo das Rotas",
        status=Banca.REALIZADA,
        nota=9.0,
        resultado=Projeto.APROVADO_COM_RESSALVAS,
    )
    ata = Ata.objects.create(
        projeto=projeto, banca=banca, numero="999/2026", pdf="atas/rota-catalogo.pdf"
    )
    RevisaoSUGRAD.objects.create(ata=ata, status=RevisaoSUGRAD.APROVADA, decidida_em=timezone.now())
    return aluno


def cria_banca_agendada_para_calendario_das_rotas():
    """Fábrica de `/calendario/` (Bloco G): uma `Banca` `AGENDADA` no
    futuro, pra suíte medir a tela com pelo menos um item."""
    from apps.bancas.models import Banca
    from apps.contas.models import PerfilAluno, PerfilProfessor, Usuario
    from apps.projetos.models import Projeto

    orientador = Usuario.objects.create_user(
        email="orientador-calendario-das-rotas@ufsm.br",
        password="x",
        nome_completo="Orientador Calendário das Rotas",
        cpf=_gera_cpf_das_rotas(42),
    )
    PerfilProfessor.objects.create(usuario=orientador, siape="1000028")
    aluno = Usuario.objects.create_user(
        email="aluno-calendario-das-rotas@ufsm.br",
        password="x",
        nome_completo="Aluno Calendário das Rotas",
        cpf=_gera_cpf_das_rotas(43),
        papel=Usuario.ALUNO,
    )
    PerfilAluno.objects.create(usuario=aluno, matricula="2026399924")
    projeto = Projeto.objects.create(
        aluno=aluno,
        orientador=orientador,
        etapa=Projeto.TCC_I,
        status=Projeto.AGUARDANDO_DEFESA,
        ano=2026,
        periodo=1,
    )
    Banca.objects.create(
        projeto=projeto,
        data_hora=timezone.now() + timezone.timedelta(days=5),
        local="Sala Calendário das Rotas",
        status=Banca.AGENDADA,
    )
    return aluno


# Lista única de rotas submetidas às cinco suítes transversais
# (tests/test_acessibilidade.py, test_toque.py, test_responsivo.py,
# test_teclado.py, test_rotas.py). Acrescentar uma rota aqui é o que submete uma
# página nova às cinco verificações de uma vez — toda tarefa que criar uma página nova (pública
# ou autenticada, via `fabrica_usuario`) acrescenta sua rota a esta lista (spec §10.1).
ROTAS = [
    Rota("/", "h1"),
    Rota("/convite/rota-para-teste-de-acessibilidade/", "form"),
    Rota("/contas/login/", "form"),
    Rota("/contas/password_reset/", "form"),
    # done/complete são páginas estáticas (sem formulário, sem estado) —
    # cobertura de graça, sem precisar de fixture nenhuma. password_reset_confirm
    # fica de fora: exige um uidb64/token real e válido, que só existe depois de
    # um fluxo de recuperação de senha de verdade (ver
    # apps/contas/tests/test_autenticacao.py,
    # test_fluxo_completo_de_recuperacao_de_senha_ate_novo_login).
    Rota("/contas/password_reset/concluido/", "h1"),
    Rota("/contas/reset/concluido/", "h1"),
    # As rotas abaixo substituem as suítes que viviam inteiras em
    # apps/contas/tests/test_perfil_acessibilidade.py (removido) e
    # test_coordenacao_acessibilidade.py (T1 do Bloco B): eram cópias dos
    # mesmos cinco corpos de teste desta suíte, só que autenticadas na mão.
    # /perfil/ entra duas vezes: o HTML da variante professor (com o
    # <fieldset>/<legend> do grupo de áreas) difere de verdade do da variante
    # aluno, então uma cobertura só varreria metade das personas de verdade.
    Rota(
        "/perfil/",
        "form",
        fabrica_usuario=cria_professor_para_rotas,
        h1="Meu perfil",
        persona="professor",
    ),
    Rota(
        "/perfil/",
        "form",
        fabrica_usuario=cria_aluno_para_rotas,
        h1="Meu perfil",
        persona="aluno",
    ),
    Rota(
        "/painel/",
        "form",
        fabrica_usuario=cria_coordenador_para_rotas,
        h1="Painel da coordenação",
    ),
    # `fabrica_usuario` trocada de `cria_professor_para_rotas` para
    # `cria_professor_com_tema_para_rotas` no acréscimo de escopo da T7:
    # a fábrica antiga não cria nenhum `Tema`, e a suíte inteira media a
    # tela VAZIA (nem o badge "Inativo", nem o botão "Desativar" — ver a
    # docstring da fábrica nova). Com ela, a rota mede um tema ativo e um
    # inativo de uma vez.
    Rota(
        "/temas/meus/",
        "form",
        fabrica_usuario=cria_professor_com_tema_para_rotas,
        h1="Meus temas",
    ),
    # `fabrica_usuario` trocada de `cria_aluno_para_rotas` para
    # `cria_aluno_com_mural_para_rotas` na rodada de correção 1: a fábrica
    # antiga não cria nenhum `Tema`, e a suíte inteira media o mural VAZIO —
    # mesma classe de defeito que a correção acima já havia fechado para
    # `/temas/meus/` (ver a docstring da fábrica nova).
    Rota(
        "/temas/",
        "h1",
        fabrica_usuario=cria_aluno_com_mural_para_rotas,
        h1="Mural de temas",
    ),
    # Caminho dinâmico (rodada de correção 2 da T6): o <id> só existe depois
    # de `cria_professor_com_tema_para_rotas` rodar, então `caminho` é um
    # callable que lê `usuario.tema_id_para_rota` (ver a fábrica) em vez de
    # uma string fixa. Substitui `apps/projetos/tests/test_temas_acessibilidade.py`
    # (removido nesta rodada): era a cópia à mão que só rodava o axe — 1 das
    # 5 verificações —, e foi por isso que um alvo de toque de 24px nesta
    # tela passou despercebido até a revisão.
    Rota(
        lambda usuario: f"/temas/{usuario.tema_id_para_rota}/editar/",
        "form",
        fabrica_usuario=cria_professor_com_tema_para_rotas,
        h1="Editar tema",
    ),
    # Fila do professor (T9): duas manifestações pendentes (com e sem tema)
    # e um orientando atual, para que os ramos condicionais das duas seções
    # do template (fila e "orientandos atuais") entrem na medição — ver a
    # docstring de `cria_professor_com_manifestacao_para_rotas`.
    Rota(
        "/orientacoes/",
        "form",
        fabrica_usuario=cria_professor_com_manifestacao_para_rotas,
        h1="Minhas orientações",
    ),
    # Tela do aluno (T11): duas variantes da MESMA URL, com HTML
    # genuinamente diferente (mesmo padrão de /perfil/, acima) — "montar"
    # (sem candidatura em curso, mostra o formulário) e "acompanhar" (com
    # uma em curso, mostra as opções e o botão de cancelar). Sem a segunda
    # variante, a suíte mediria só a metade do template que
    # `cria_aluno_sem_candidatura_para_rotas` alcança — mesma lição de
    # `cria_aluno_com_mural_para_rotas`/`cria_professor_com_manifestacao_para_rotas`,
    # acima, sobre não deixar um ramo inteiro do template fora da medição.
    Rota(
        "/candidatura/",
        "form",
        fabrica_usuario=cria_aluno_sem_candidatura_para_rotas,
        h1="Minha candidatura",
        persona="montar",
    ),
    Rota(
        "/candidatura/",
        "form",
        fabrica_usuario=cria_aluno_com_candidatura_para_rotas,
        h1="Minha candidatura",
        persona="acompanhar",
    ),
    # Painel da coordenação para ajustar orientações (T12): entra na MESMA
    # lista das demais, não numa suíte própria — já aconteceu duas vezes
    # neste bloco (T6, T9) de uma rota isolada em suíte própria esconder um
    # defeito de acessibilidade que as cinco verificações transversais
    # pegariam.
    Rota(
        "/painel/orientacoes/",
        "form",
        fabrica_usuario=cria_coordenador_com_painel_orientacoes_para_rotas,
        h1="Painel de orientações",
    ),
    Rota(
        "/meu-tcc/",
        "form",
        fabrica_usuario=cria_aluno_com_projeto_para_rotas,
        h1="Meu TCC",
    ),
    Rota(
        lambda usuario: f"/bancas/agendar/{usuario.projeto_id_para_rota}/",
        "form",
        fabrica_usuario=cria_professor_com_banca_agendada_para_rotas,
        h1="Agendar banca",
    ),
    Rota(
        lambda usuario: f"/bancas/{usuario.banca_id_para_rota}/editar/",
        "form",
        fabrica_usuario=cria_professor_com_banca_agendada_para_rotas,
        h1="Editar banca",
    ),
    Rota(
        lambda usuario: f"/bancas/{usuario.banca_id_para_rota}/resultado/",
        "form",
        fabrica_usuario=cria_professor_com_banca_agendada_para_rotas,
        h1="Registrar resultado",
    ),
    Rota(
        "/painel/sugrad/",
        "form",
        fabrica_usuario=cria_sugrad_com_ata_pendente_para_rotas,
        h1="Painel SUGRAD",
    ),
    Rota(
        "/orientacoes/criar/",
        "form",
        fabrica_usuario=cria_professor_para_criar_orientacao_para_rotas,
        h1="Criar nova orientação",
    ),
    Rota(
        lambda usuario: f"/bancas/{usuario.projeto_id_para_rota}/correcoes/",
        "form",
        fabrica_usuario=cria_professor_com_correcao_para_rotas,
        h1="Correções — Aluno Correção das Rotas",
    ),
    Rota(
        "/catalogo/",
        "form",
        fabrica_usuario=cria_projeto_catalogavel_para_rotas,
        h1="Catálogo de TCCs",
    ),
    Rota(
        "/calendario/",
        "h1",
        fabrica_usuario=cria_banca_agendada_para_calendario_das_rotas,
        h1="Calendário de Apresentações",
    ),
    Rota(
        "/sobre/",
        "h1",
        h1="Sobre o OrientaSI",
    ),
]


@pytest.fixture
def convite_das_rotas(db):
    """A rota de convite da suíte precisa de um convite válido para responder 200.

    NÃO é autouse: se fosse, o usuário que ela cria colidiria em CPF e e-mail com as
    fixtures de apps/contas/tests/, e a suíte inteira quebraria por IntegrityError.
    Só quem pede `rota` recebe esta semeadura.
    """
    from apps.contas.models import Convite, Usuario

    coordenadora = Usuario.objects.create_user(
        email="coord-das-rotas@ufsm.br",
        password="x",
        nome_completo="Coordenação",
        cpf="39053344705",
        is_coordenador=True,
        is_staff=True,
    )
    Convite.objects.create(
        email="convidado-fixture@ufsm.br",
        papel=Usuario.ALUNO,
        token_hash=hashlib.sha256(b"rota-para-teste-de-acessibilidade").hexdigest(),
        criado_por=coordenadora,
        expira_em=timezone.now() + timezone.timedelta(days=7),
    )


def _id_da_rota(r):
    """Nome de exibição de uma `Rota` no relatório do pytest e no `-k`.

    Para `caminho` estático, a própria URL — como sempre foi. Para `caminho`
    dinâmico (callable, rodada de correção 2 da T6: rotas com `<id>` de
    banco), a URL só existe depois de autenticar e rodar a fábrica, então
    usamos o `h1` esperado como nome — estável e legível, ao contrário do
    `repr` de uma função (`<function ... at 0x...>`)."""
    if isinstance(r.caminho, str):
        nome = r.caminho
    else:
        # Sem espaços: `-k` trata espaço como separador de expressão e recusa o
        # id inteiro ("Editar tema" vira erro de sintaxe), enquanto os ids de
        # caminho estático sobrevivem a um `-k` completo. Normalizar mantém a
        # legibilidade e a paridade com eles (rodada de correção 3 da T6).
        nome = (r.h1 or "rota-dinamica").lower().replace(" ", "-")
    return f"{nome}[{r.persona}]" if r.persona else nome


@pytest.fixture(params=ROTAS, ids=_id_da_rota)
def rota(request, convite_das_rotas, page, live_server, autentica_no_navegador):
    """Devolve a rota já aberta no navegador, autenticada quando ela exige.

    A checagem de âncora roda uma única vez aqui, no viewport padrão — ela prova qual
    página está aberta, não como ela se comporta em cada largura. São duas asserções,
    nesta ordem, ambas antes de qualquer outra verificação (restricoes-globais.md): a
    URL final tem que ser exatamente a URL pedida (pega redirecionamento para o login
    que a autenticação não conseguiu evitar) e o texto do `<h1>` tem que bater com o
    esperado (pega a página errada que por acaso responde na mesma URL, ex.: um 404
    customizado). Os testes de toque e responsividade mudam a largura e chamam
    `page.reload()` por conta própria: se a fixture recarregasse, a largura que o
    teste definiu se perderia.

    A comparação de URL é **igualdade exata** com `live_server.url + caminho`, não
    `str.endswith(caminho)`: `login_required` redireciona para
    `/contas/login/?next=/painel/`, e essa URL também *termina* em `/painel/` — o
    parâmetro `next` reproduz o caminho pedido no fim da string. Um `endswith` passaria
    por engano exatamente no caso que existe para pegar (confirmado quebrando de
    propósito na Tarefa 1, revisão 1 — ver relatório). Isso vale IGUAL para caminho
    dinâmico: a igualdade exata roda sobre o caminho já resolvido, não sobre o
    callable — nunca foi relaxada para `endswith` (rodada de correção 2 da T6).

    `r.caminho` pode ser um callable (rota com `<id>` de banco — ver a
    docstring de `Rota`); quando é, ele só é resolvido AQUI, depois que
    `fabrica_usuario()` já rodou e devolveu o `Usuario` que o callable
    precisa. `dataclasses.replace` devolve uma cópia da `Rota` com o campo
    `caminho` já resolvido (string), para que os testes que recebem esta
    fixture (`test_toque.py`, `test_responsivo.py`, `test_teclado.py`) leiam
    `rota.caminho` como uma URL de verdade nas mensagens de falha, nunca como
    o `repr` de uma função.
    """
    r = request.param
    usuario = r.fabrica_usuario() if r.fabrica_usuario is not None else None
    if usuario is not None:
        autentica_no_navegador(usuario)
    caminho = r.caminho(usuario) if callable(r.caminho) else r.caminho
    r = replace(r, caminho=caminho)
    page.goto(f"{live_server.url}{r.caminho}")
    if r.h1:
        url_esperada = f"{live_server.url}{r.caminho}"
        assert page.url == url_esperada, (
            f"{r.caminho} deveria terminar a navegação em {url_esperada!r}, e a URL final foi "
            f"{page.url!r} — provável redirecionamento para o login (autenticação não pegou)."
        )
        texto = page.inner_text("h1")
        assert r.h1 in texto, (
            f"{r.caminho} deveria mostrar <h1> com {r.h1!r}, e mostrou {texto!r}. "
            "A suíte pode estar medindo a página errada (ex.: um redirecionamento "
            "para o login que a autenticação não pegou)."
        )
    return r
