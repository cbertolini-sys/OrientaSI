"""Testes do mural de temas (T7): `apps/projetos/services.py::temas_do_mural`
e a view `projetos:mural` — a tela onde o aluno vê os temas ativos antes de
se candidatar (a candidatura em si é a T8).

Cobertura pedida pelo Passo 1 do brief: o mural exige autenticação (anônimo é
redirecionado); mostra só temas `ativo=True`; filtra por área; marca quais
professores ainda têm vaga (ambiguidade 1 do ruling do controlador: vaga é
contada em `Projeto.TCC_I`, porque é a etapa com que `criar_projeto_sob_limite`
grava o `Projeto` quando uma candidatura é aceita — spec §3.7, linha 147:
"quando o professor aceita, nasce um `Projeto` com `etapa=TCC_I`"; `Candidatura`
não tem campo `etapa`). Acrescenta a prova de ausência de N+1 (ambiguidade 2):
duas medições, uma com 3 temas/3 professores e outra com 6/6, comparando os
números de consulta entre si — não contra um teto fixo.
"""

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from apps.comum.semestre import semestre_vigente
from apps.contas.models import Area, PerfilAluno, PerfilProfessor, Usuario
from apps.projetos import services
from apps.projetos.models import LimiteOrientacao, Projeto, Tema

# CPFs válidos (dígito verificador de apps/contas/validators.py), gerados
# fora dos já usados pelas demais suítes, para esta não colidir em UNIQUE(cpf).
CPFS = [
    "10000000019",
    "10123456703",
    "10246913495",
    "10370370147",
    "10493826840",
    "10617283583",
    "10740740253",
    "10864196938",
    "10987653628",
    "11111110301",
    "11234567040",
    "11358023786",
]


def _cria_professor(indice, nome):
    usuario = Usuario.objects.create_user(
        email=f"professor.mural{indice}@ufsm.br",
        password="x",
        nome_completo=nome,
        cpf=CPFS[indice],
    )
    return PerfilProfessor.objects.create(usuario=usuario, siape=f"300000{indice}")


def _cria_aluno(indice, nome):
    usuario = Usuario.objects.create_user(
        email=f"aluno.mural{indice}@ufsm.br",
        password="x",
        nome_completo=nome,
        papel=Usuario.ALUNO,
        cpf=CPFS[indice],
    )
    PerfilAluno.objects.create(usuario=usuario, matricula=f"20210001{indice:02d}")
    return usuario


def _cria_tema(professor, area, titulo, ativo=True):
    return Tema.objects.create(
        professor=professor,
        area=area,
        titulo=titulo,
        descricao=f"Descrição de {titulo}.",
        ativo=ativo,
    )


def _cria_projeto_tcc1(aluno_usuario, professor):
    """Projeto EM_ANDAMENTO em TCC_I, no semestre vigente — o que
    `vagas_ocupadas`/o mural contam (ambiguidade 1 do ruling)."""
    ano, periodo = semestre_vigente()
    return Projeto.objects.create(
        aluno=aluno_usuario,
        orientador=professor.usuario,
        etapa=Projeto.TCC_I,
        ano=ano,
        periodo=periodo,
    )


def _cpf_valido(semente):
    """CPF com dígitos verificadores válidos (mesmo algoritmo de
    `apps/contas/validators.py::_digito`), gerado a partir de qualquer
    inteiro — usado só pelo teste de equivalência abaixo, que precisa de
    muitos CPFs distintos dentro de uma única execução e não tem por que
    inflar a lista `CPFS` (usada pelas fábricas fixas do resto do arquivo)
    para isso."""

    def _digito(numero, peso_inicial):
        soma = sum(int(d) * p for d, p in zip(numero, range(peso_inicial, 1, -1), strict=True))
        resto = (soma * 10) % 11
        return 0 if resto == 10 else resto

    base = str(100_000_000 + semente * 1_234_567 % 900_000_000).zfill(9)
    d1 = _digito(base, 10)
    d2 = _digito(base + str(d1), 11)
    return base + str(d1) + str(d2)


def _professor_equivalencia(semente, nome):
    usuario = Usuario.objects.create_user(
        email=f"professor.equivalencia{semente}@ufsm.br",
        password="x",
        nome_completo=nome,
        cpf=_cpf_valido(semente),
    )
    return PerfilProfessor.objects.create(usuario=usuario, siape=f"5{semente:06d}")


def _aluno_equivalencia(semente, nome):
    usuario = Usuario.objects.create_user(
        email=f"aluno.equivalencia{semente}@ufsm.br",
        password="x",
        nome_completo=nome,
        papel=Usuario.ALUNO,
        cpf=_cpf_valido(semente),
    )
    PerfilAluno.objects.create(usuario=usuario, matricula=f"6{semente:06d}")
    return usuario


@pytest.fixture
def professor(db):
    return _cria_professor(0, "Professor Mural")


@pytest.fixture
def area(db):
    return Area.objects.create(nome="Engenharia de Software")


@pytest.fixture
def outra_area(db):
    return Area.objects.create(nome="Redes")


@pytest.fixture
def aluno(db):
    return _cria_aluno(1, "Aluno Mural")


# --- services.temas_do_mural -------------------------------------------------


@pytest.mark.django_db
def test_temas_do_mural_so_traz_temas_ativos(professor, area):
    professor.areas.add(area)
    ativo = _cria_tema(professor, area, "Tema ativo")
    _cria_tema(professor, area, "Tema inativo", ativo=False)

    resultado = list(services.temas_do_mural())

    assert [t.pk for t in resultado] == [ativo.pk]


@pytest.mark.django_db
def test_temas_do_mural_filtra_por_area(professor, area, outra_area):
    professor.areas.add(area)
    professor.areas.add(outra_area)
    da_area = _cria_tema(professor, area, "Tema da área")
    _cria_tema(professor, outra_area, "Tema de outra área")

    resultado = list(services.temas_do_mural(area=area))

    assert [t.pk for t in resultado] == [da_area.pk]


@pytest.mark.django_db
def test_temas_do_mural_marca_professor_com_vaga(professor, area):
    professor.areas.add(area)
    _cria_tema(professor, area, "Tema com vaga")

    resultado = list(services.temas_do_mural())

    assert len(resultado) == 1
    assert resultado[0].professor_tem_vaga is True


@pytest.mark.django_db
def test_temas_do_mural_marca_professor_sem_vaga_no_limite(professor, area):
    """3 projetos em TCC_I no semestre vigente esgotam o limite padrão
    (`LIMITE_PADRAO_VAGAS = 3`, apps/projetos/services.py) — a mesma
    constante que `criar_projeto_sob_limite` usa."""
    professor.areas.add(area)
    _cria_tema(professor, area, "Tema sem vaga")
    for indice in range(3):
        aluno_usuario = _cria_aluno(2 + indice, f"Aluno Limite {indice}")
        _cria_projeto_tcc1(aluno_usuario, professor)

    resultado = list(services.temas_do_mural())

    assert len(resultado) == 1
    assert resultado[0].professor_tem_vaga is False


@pytest.mark.django_db
def test_temas_do_mural_nao_conta_projeto_de_outro_professor(professor, area):
    """Prova que a anotação é por professor da LINHA, não uma contagem
    global: 3 projetos de OUTRO professor não derrubam a vaga deste."""
    professor.areas.add(area)
    _cria_tema(professor, area, "Tema com vaga")
    outro_professor = _cria_professor(1, "Outro Professor Mural")
    for indice in range(3):
        aluno_usuario = _cria_aluno(2 + indice, f"Aluno Outro {indice}")
        _cria_projeto_tcc1(aluno_usuario, outro_professor)

    resultado = list(services.temas_do_mural())

    assert len(resultado) == 1
    assert resultado[0].professor_tem_vaga is True


@pytest.mark.django_db
def test_temas_do_mural_sem_n_mais_um(django_assert_num_queries):
    """Ambiguidade 2 do ruling: mede o mural com 3 temas de 3 professores,
    depois com 6 de 6, e afirma que o SEGUNDO número de consultas não é
    maior que o primeiro — a comparação entre dois tamanhos, não um teto
    fixo, é o que prova ausência de N+1."""
    for indice in range(3):
        professor = _cria_professor(indice, f"Professor N+1 {indice}")
        area = Area.objects.create(nome=f"Área N+1 {indice}")
        professor.areas.add(area)
        _cria_tema(professor, area, f"Tema N+1 {indice}")

    with CaptureQueriesContext(connection) as captura:
        list(services.temas_do_mural())
    numero_de_consultas_com_tres_temas = len(captura.captured_queries)

    for indice in range(3, 6):
        professor = _cria_professor(indice, f"Professor N+1 {indice}")
        area = Area.objects.create(nome=f"Área N+1 {indice}")
        professor.areas.add(area)
        _cria_tema(professor, area, f"Tema N+1 {indice}")

    with django_assert_num_queries(numero_de_consultas_com_tres_temas):
        list(services.temas_do_mural())


@pytest.mark.django_db
def test_temas_do_mural_bate_com_vagas_ocupadas_e_limite_do_professor():
    """Importante 1, rodada de correção 1: `temas_do_mural` é uma SEGUNDA
    implementação, em SQL, da mesma regra que `vagas_ocupadas`/
    `limite_do_professor` já calculam em Python (usadas de verdade por
    `criar_projeto_sob_limite`). Os testes de valor acima ("com 2 projetos,
    tem vaga") prendem a agregação a números literais — o que faltava era
    prender as DUAS implementações uma na outra, para que uma divergência
    silenciosa entre elas (a anotação SQL "parecer" certa mas contar algo
    diferente do que a função Python conta) reprove.

    Cada cenário abaixo é escolhido para derrubar uma forma específica de a
    anotação SQL divergir da função Python sem que nenhum teste de valor
    perceba:

    - `sem_projeto`: professor com tema mas nenhum `Projeto` — o caso mais
      simples, sem filtro nenhum em jogo.
    - `outro_semestre`: 3 projetos TCC_I, mas do semestre ANTERIOR — prova
      que a anotação filtra por (ano, periodo) exatos (spec §3.5), não só
      por etapa.
    - `outra_etapa`: 3 projetos TCC_II no semestre vigente — prova que a
      anotação filtra por etapa (só TCC_I conta), não só por semestre.
    - `limite_elevado`: `LimiteOrientacao` autoriza 5 vagas nesta etapa e
      semestre, com 4 projetos — prova que a anotação lê a autorização da
      coordenação (spec §3.6), não só o teto padrão de 3.
    - `autorizacao_de_outra_etapa`: a autorização existe, mas para TCC_II —
      não pode valer para a contagem de TCC_I; com 3 projetos TCC_I, o
      limite efetivo continua sendo o padrão (3).
    - `autorizacao_de_outro_semestre`: a autorização existe, mas para o
      semestre anterior — não pode valer para o semestre vigente; com 3
      projetos TCC_I no semestre vigente, o limite efetivo continua sendo o
      padrão (3).
    - `varios_temas_mesmo_professor`: 4 `Tema` do MESMO professor, com 2
      projetos — o erro clássico de JOIN que o revisor mediu: uma agregação
      sem `distinct` correto faria a contagem de projetos aparecer
      multiplicada pelo número de temas do professor (2 × 4 = 8, quando o
      valor certo é 2).

    O laço final não repete os valores computados aqui — ele pergunta a
    `services.vagas_ocupadas`/`services.limite_do_professor` para CADA
    professor que apareceu no mural, e afirma que a anotação da linha bate
    com a resposta dessas funções. Uma implementação que ignore semestre,
    etapa, ou `LimiteOrientacao` (as mutações que a rodada de correção 1
    testou contra a suíte anterior — `sem_semestre`, `sem_etapa`,
    `sem_limite_orientacao` — todas passavam 12/12 nos testes de valor)
    reprova aqui, porque discorda da função Python nos cenários acima.
    """
    ano, periodo = semestre_vigente()
    outro_ano = ano - 1

    coordenador = Usuario.objects.create_user(
        email="coordenador.equivalencia@ufsm.br",
        password="x",
        nome_completo="Coordenador Equivalência",
        cpf=_cpf_valido(999),
        is_coordenador=True,
        is_staff=True,
    )

    # sem_projeto
    p_sem_projeto = _professor_equivalencia(1, "Sem Projeto")
    area_1 = Area.objects.create(nome="Área Equivalência 1")
    p_sem_projeto.areas.add(area_1)
    _cria_tema(p_sem_projeto, area_1, "Tema Sem Projeto")

    # outro_semestre: 3 projetos TCC_I, mas no ano anterior
    p_outro_semestre = _professor_equivalencia(2, "Outro Semestre")
    area_2 = Area.objects.create(nome="Área Equivalência 2")
    p_outro_semestre.areas.add(area_2)
    _cria_tema(p_outro_semestre, area_2, "Tema Outro Semestre")
    for i in range(3):
        aluno_usuario = _aluno_equivalencia(10 + i, f"Aluno Outro Semestre {i}")
        Projeto.objects.create(
            aluno=aluno_usuario,
            orientador=p_outro_semestre.usuario,
            etapa=Projeto.TCC_I,
            ano=outro_ano,
            periodo=periodo,
        )

    # outra_etapa: 3 projetos TCC_II no semestre vigente
    p_outra_etapa = _professor_equivalencia(3, "Outra Etapa")
    area_3 = Area.objects.create(nome="Área Equivalência 3")
    p_outra_etapa.areas.add(area_3)
    _cria_tema(p_outra_etapa, area_3, "Tema Outra Etapa")
    for i in range(3):
        aluno_usuario = _aluno_equivalencia(20 + i, f"Aluno Outra Etapa {i}")
        Projeto.objects.create(
            aluno=aluno_usuario,
            orientador=p_outra_etapa.usuario,
            etapa=Projeto.TCC_II,
            ano=ano,
            periodo=periodo,
        )

    # limite_elevado: autorização de 5 vagas nesta etapa/semestre, 4 projetos
    p_limite_elevado = _professor_equivalencia(4, "Limite Elevado")
    area_4 = Area.objects.create(nome="Área Equivalência 4")
    p_limite_elevado.areas.add(area_4)
    _cria_tema(p_limite_elevado, area_4, "Tema Limite Elevado")
    LimiteOrientacao.objects.create(
        professor=p_limite_elevado,
        etapa=Projeto.TCC_I,
        ano=ano,
        periodo=periodo,
        limite=5,
        justificativa="Teste de equivalência.",
        autorizado_por=coordenador,
    )
    for i in range(4):
        aluno_usuario = _aluno_equivalencia(30 + i, f"Aluno Limite Elevado {i}")
        Projeto.objects.create(
            aluno=aluno_usuario,
            orientador=p_limite_elevado.usuario,
            etapa=Projeto.TCC_I,
            ano=ano,
            periodo=periodo,
        )

    # autorizacao_de_outra_etapa: autorização vale para TCC_II, não para TCC_I
    p_autorizacao_outra_etapa = _professor_equivalencia(5, "Autorização Outra Etapa")
    area_5 = Area.objects.create(nome="Área Equivalência 5")
    p_autorizacao_outra_etapa.areas.add(area_5)
    _cria_tema(p_autorizacao_outra_etapa, area_5, "Tema Autorização Outra Etapa")
    LimiteOrientacao.objects.create(
        professor=p_autorizacao_outra_etapa,
        etapa=Projeto.TCC_II,
        ano=ano,
        periodo=periodo,
        limite=5,
        justificativa="Teste de equivalência.",
        autorizado_por=coordenador,
    )
    for i in range(3):
        aluno_usuario = _aluno_equivalencia(40 + i, f"Aluno Autorização Outra Etapa {i}")
        Projeto.objects.create(
            aluno=aluno_usuario,
            orientador=p_autorizacao_outra_etapa.usuario,
            etapa=Projeto.TCC_I,
            ano=ano,
            periodo=periodo,
        )

    # autorizacao_de_outro_semestre: autorização vale para o ano anterior
    p_autorizacao_outro_semestre = _professor_equivalencia(6, "Autorização Outro Semestre")
    area_6 = Area.objects.create(nome="Área Equivalência 6")
    p_autorizacao_outro_semestre.areas.add(area_6)
    _cria_tema(p_autorizacao_outro_semestre, area_6, "Tema Autorização Outro Semestre")
    LimiteOrientacao.objects.create(
        professor=p_autorizacao_outro_semestre,
        etapa=Projeto.TCC_I,
        ano=outro_ano,
        periodo=periodo,
        limite=5,
        justificativa="Teste de equivalência.",
        autorizado_por=coordenador,
    )
    for i in range(3):
        aluno_usuario = _aluno_equivalencia(50 + i, f"Aluno Autorização Outro Semestre {i}")
        Projeto.objects.create(
            aluno=aluno_usuario,
            orientador=p_autorizacao_outro_semestre.usuario,
            etapa=Projeto.TCC_I,
            ano=ano,
            periodo=periodo,
        )

    # varios_temas_mesmo_professor: 4 temas do mesmo professor, 2 projetos —
    # o erro clássico de JOIN (sem `distinct`, renderia 8, não 2).
    p_varios_temas = _professor_equivalencia(7, "Vários Temas")
    area_7 = Area.objects.create(nome="Área Equivalência 7")
    p_varios_temas.areas.add(area_7)
    for i in range(4):
        _cria_tema(p_varios_temas, area_7, f"Tema Vários {i}")
    for i in range(2):
        aluno_usuario = _aluno_equivalencia(60 + i, f"Aluno Vários Temas {i}")
        Projeto.objects.create(
            aluno=aluno_usuario,
            orientador=p_varios_temas.usuario,
            etapa=Projeto.TCC_I,
            ano=ano,
            periodo=periodo,
        )

    resultado = list(services.temas_do_mural())
    assert (
        len(resultado) == 10
    ), "os 7 cenários acima somam 10 temas (4 do último, 1 cada dos 6 outros)"

    for tema in resultado:
        professor = tema.professor
        ocupadas_esperado = services.vagas_ocupadas(professor, Projeto.TCC_I, ano, periodo)
        limite_esperado = services.limite_do_professor(professor, Projeto.TCC_I, ano, periodo)

        assert tema.vagas_ocupadas_do_professor == ocupadas_esperado, (
            f'tema "{tema.titulo}" (professor {professor}): anotação disse '
            f"{tema.vagas_ocupadas_do_professor} vagas ocupadas, "
            f"vagas_ocupadas() disse {ocupadas_esperado}"
        )
        assert tema.limite_de_vagas_do_professor == limite_esperado, (
            f'tema "{tema.titulo}" (professor {professor}): anotação disse limite '
            f"{tema.limite_de_vagas_do_professor}, limite_do_professor() disse {limite_esperado}"
        )
        assert tema.professor_tem_vaga == (ocupadas_esperado < limite_esperado), (
            f'tema "{tema.titulo}" (professor {professor}): professor_tem_vaga='
            f"{tema.professor_tem_vaga}, mas vagas_ocupadas()={ocupadas_esperado} e "
            f"limite_do_professor()={limite_esperado} implicam "
            f"{ocupadas_esperado < limite_esperado}"
        )


# --- view projetos:mural ------------------------------------------------


@pytest.mark.django_db
def test_mural_exige_autenticacao(client):
    resposta = client.get(reverse("projetos:mural"))
    assert resposta.status_code == 302
    assert resposta.url == f"/contas/login/?next={reverse('projetos:mural')}"


@pytest.mark.django_db
def test_mural_lista_apenas_temas_ativos(client, aluno, professor, area):
    professor.areas.add(area)
    ativo = _cria_tema(professor, area, "Tema Visível no Mural")
    _cria_tema(professor, area, "Tema Escondido do Mural", ativo=False)
    client.force_login(aluno)

    html = client.get(reverse("projetos:mural")).content.decode()

    assert ativo.titulo in html
    assert "Tema Escondido do Mural" not in html


@pytest.mark.django_db
def test_mural_serve_qualquer_papel_autenticado(client, professor, area):
    """A rota é autenticada mas não exclusiva do aluno (Passo 5 do brief):
    um professor logado também consegue abrir o mural."""
    professor.areas.add(area)
    _cria_tema(professor, area, "Tema Visto por Professor")
    client.force_login(professor.usuario)

    resposta = client.get(reverse("projetos:mural"))

    assert resposta.status_code == 200
    assert "Tema Visto por Professor" in resposta.content.decode()


@pytest.mark.django_db
def test_mural_filtra_por_area_pela_tela(client, aluno, professor, area, outra_area):
    professor.areas.add(area)
    professor.areas.add(outra_area)
    da_area = _cria_tema(professor, area, "Tema Filtrado")
    de_outra_area = _cria_tema(professor, outra_area, "Tema de Outra Área")
    client.force_login(aluno)

    html = client.get(reverse("projetos:mural"), {"area": area.pk}).content.decode()

    assert da_area.titulo in html
    assert de_outra_area.titulo not in html


@pytest.mark.django_db
def test_mural_marca_texto_de_vaga_disponivel_e_esgotada(client, aluno, professor, area):
    # `aluno` (índice 1) e `professor` (índice 0) já ocupam CPFS[0] e
    # CPFS[1] — o professor e os alunos extras deste teste começam em 2.
    professor.areas.add(area)
    com_vaga = _cria_tema(professor, area, "Tema Com Vaga")
    outro_professor = _cria_professor(2, "Professor Sem Vaga")
    outro_professor.areas.add(area)
    sem_vaga = _cria_tema(outro_professor, area, "Tema Sem Vaga")
    for indice in range(3):
        aluno_usuario = _cria_aluno(3 + indice, f"Aluno Esgota {indice}")
        _cria_projeto_tcc1(aluno_usuario, outro_professor)
    client.force_login(aluno)

    html = client.get(reverse("projetos:mural")).content.decode()

    assert com_vaga.titulo in html
    assert sem_vaga.titulo in html
    assert "Vaga disponível" in html
    assert "Sem vaga no momento" in html


@pytest.mark.django_db
def test_mural_area_invalida_mostra_tudo_e_relata_o_erro(client, aluno, professor, area):
    """M7, rodada de correção 1: `?area=abc` não é um pk válido —
    `FormularioFiltroMural` fica inválido, e `views.mural` já cai para
    `area=None` nesse caso (`formulario.cleaned_data["area"] if
    formulario.is_valid() else None`). "Área inválida ⇒ mostra tudo" é a
    decisão de produto que faltava um teste prendendo: sem este teste, uma
    mudança que passasse a devolver 400/500 num `area` que não é um inteiro
    não reprovaria nada.

    Também confere que o erro aparece no HTML — tanto o do campo (via
    `contas/_campo.html`, que já renderiza `campo.errors`) quanto o resumo
    acrescentado no M8."""
    professor.areas.add(area)
    tema = _cria_tema(professor, area, "Tema Visível Apesar do Filtro Inválido")
    client.force_login(aluno)

    resposta = client.get(reverse("projetos:mural"), {"area": "abc"})

    assert resposta.status_code == 200
    html = resposta.content.decode()
    assert tema.titulo in html
    assert "Faça uma escolha válida" in html
    assert "Não foi possível aplicar o filtro" in html


@pytest.mark.django_db
def test_mural_mostra_estado_vazio_sem_temas(client, aluno):
    client.force_login(aluno)

    html = client.get(reverse("projetos:mural")).content.decode()

    assert "Nenhum tema" in html
