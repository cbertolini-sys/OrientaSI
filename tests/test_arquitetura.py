"""Trava as duas asserções que sustentam a convenção de `services.py` (spec
§4.2 e §10.1). Sem um teste que a defenda, a convenção vira comentário no
CLAUDE.md — a própria spec diz isso com estas palavras."""

import ast
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parent.parent
APPS = sorted(p for p in (RAIZ / "apps").iterdir() if (p / "apps.py").exists())

# Apps com `urls.py` são apps com rotas registradas: alguma view precisa
# existir para atendê-las. Ao contrário de `APPS`, esta lista não encolhe se
# `views.py` for renomeado ou apagado — só encolheria se a própria rota fosse
# removida —, e é por isso que `test_o_arquivo_de_views_existe` usa ela como
# parametrização: apagar `views.py` de um app aqui dentro precisa REPROVAR o
# teste correspondente, não fazê-lo desaparecer da coleção.
APPS_COM_ROTAS = sorted(p for p in APPS if (p / "urls.py").exists())

# Métodos que gravam no banco. A regra escrita é sobre MUTAÇÃO, não sobre
# importar `models`: a spec §4.2 pede "nenhuma view importa `models` sem passar
# por `services`", mas tomada ao pé da letra essa formulação proibiria também a
# leitura para exibição — e a view do painel lê `Convite` para montar a tabela
# de convites enviados, o que é legítimo (não há regra de negócio numa lista
# ordenada por data). O que não pode acontecer numa view é ESCREVER: transição
# de status, criação de convite, promoção de coordenador. Toda gravação passa
# por `services.py` (CLAUDE.md, regra 4), onde a regra de negócio pode ser
# aplicada, testada e envolvida em transação.
#
# `set`/`add`/`remove`/`clear` entraram depois (pendência herdada da Fase 1):
# gravação de relação muitos-para-um-para-muitos, como
# `perfil.areas.set(...)` em `apps/contas/services.py`, é mutação como
# qualquer outra, e escapava desta lista — nada impedia que a mesma linha
# fosse escrita direto numa view.
#
# Quem precisar gravar dentro de uma view não deve driblar esta lista: deve
# escrever (ou chamar) a função de serviço correspondente.
MUTACOES = frozenset(
    {
        "save",
        "create",
        "update",
        "delete",
        "get_or_create",
        "update_or_create",
        "bulk_create",
        "bulk_update",
        "set",
        "add",
        "remove",
        "clear",
    }
)


def importa(caminho, alvo):
    arvore = ast.parse(caminho.read_text(encoding="utf-8"))
    for no in ast.walk(arvore):
        if isinstance(no, ast.ImportFrom) and no.module and alvo in no.module:
            return True
    return False


def mutacoes_diretas(caminho):
    """Chamadas de método com nome de gravação encontradas no arquivo."""
    arvore = ast.parse(caminho.read_text(encoding="utf-8"))
    achados = []
    for no in ast.walk(arvore):
        if (
            isinstance(no, ast.Call)
            and isinstance(no.func, ast.Attribute)
            and no.func.attr in MUTACOES
        ):
            achados.append(f"linha {no.lineno}: .{no.func.attr}()")
    return achados


def modulos_de_views(app):
    """Localiza o(s) módulo(s)-fonte das views do app.

    Hoje todo app com views usa um único `views.py`. Mas nada garante que
    continue assim: um app do Bloco B com cinco telas novas pode preferir
    organizá-las como pacote (`views/aluno.py`, `views/professor.py`, ...).
    Se esta função só soubesse procurar `views.py`, um app assim pareceria
    "sem views" para sempre, e a regra de mutação abaixo desativaria a si
    mesma em silêncio bem no caso em que mais importa — um pacote de views
    de verdade, com gravação de verdade dentro. Por isso ela percorre os
    módulos do pacote quando ele existe, em vez de só checar o arquivo único.

    Devolve lista vazia se o app ainda não tem nem `views.py` nem `views/`.
    """
    modulo = app / "views.py"
    if modulo.exists():
        return [modulo]
    pacote = app / "views"
    if pacote.is_dir() and (pacote / "__init__.py").exists():
        return sorted(pacote.rglob("*.py"))
    return []


@pytest.mark.parametrize("app", APPS, ids=lambda p: p.name)
def test_models_nao_importa_services(app):
    arquivo = app / "models.py"
    if not arquivo.exists():
        pytest.skip(f"{app.name} ainda não tem models.py")
    assert not importa(arquivo, "services"), (
        f"{app.name}/models.py importa services: a regra de negócio deve ficar "
        "na camada de serviço, e o model não pode depender dela."
    )


@pytest.mark.parametrize("app", APPS, ids=lambda p: p.name)
def test_views_nao_mutam_models_direto(app):
    """A camada de serviço só se sustenta se um teste a defender.

    A metade da regra que a spec pede (§4.2 e §10.1) e que não existia: o
    `README.md` já anunciava esta cobertura, e `views.py` consultava `Convite`
    e `Usuario` direto sem nada avisar. Ver `MUTACOES` acima para por que a
    asserção é sobre gravação, e não sobre importar `models` — e por que
    `set`/`add`/`remove`/`clear` entram na lista: a gravação de M2M
    (`perfil.areas.set(...)`) é mutação como qualquer outra, e era o caso
    concreto que escapava da versão anterior desta regra."""
    arquivos = modulos_de_views(app)
    if not arquivos:
        pytest.skip(f"{app.name} ainda não tem views.py nem pacote views/")
    achados = []
    for arquivo in arquivos:
        for achado in mutacoes_diretas(arquivo):
            achados.append(f"{arquivo.relative_to(app)} — {achado}")
    assert not achados, (
        f"{app.name} grava no banco diretamente na view ({', '.join(achados)}). "
        "Toda mutação passa por services.py, onde a regra de negócio é "
        "aplicada e testada (CLAUDE.md, regra 4)."
    )


@pytest.mark.parametrize("app", APPS_COM_ROTAS, ids=lambda p: p.name)
def test_o_arquivo_de_views_existe(app):
    """Falha alto se `views.py` sumir — a versão anterior de
    `test_views_nao_mutam_models_direto` pulava em silêncio quando o arquivo
    não existia, e um pacote `views/` no lugar do módulo desativaria a regra
    de mutação sem ninguém notar (nenhum teste ficava vermelho: a suíte só
    ficava com um caso a menos).

    Parametrizado sobre `APPS_COM_ROTAS` (apps com `urls.py`), não sobre
    "apps que hoje têm views.py": essa segunda opção pareceria certa, mas
    encolheria junto com a mutação que este teste existe para pegar —
    renomear `views.py` faria o próprio caso de teste desaparecer da coleção,
    o mesmo pulo silencioso, só que mais difícil de perceber que um "skipped"
    no relatório. `urls.py` não muda quando `views.py` some, então o caso de
    teste permanece e reprova de verdade."""
    tem_modulo = (app / "views.py").exists()
    tem_pacote = (app / "views").is_dir() and (app / "views" / "__init__.py").exists()
    assert tem_modulo or tem_pacote, (
        f"{app.name} tem urls.py (rotas registradas) mas não tem views.py nem "
        "um pacote views/ — rota sem view por trás, ou o módulo sumiu."
    )
