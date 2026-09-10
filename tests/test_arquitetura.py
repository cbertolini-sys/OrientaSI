"""Trava as duas asserções que sustentam a convenção de `services.py` (spec
§4.2 e §10.1). Sem um teste que a defenda, a convenção vira comentário no
CLAUDE.md — a própria spec diz isso com estas palavras."""

import ast
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parent.parent
APPS = sorted(p for p in (RAIZ / "apps").iterdir() if (p / "apps.py").exists())

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
def test_views_nao_gravam_no_banco_diretamente(app):
    """A metade da regra que a spec pede (§4.2 e §10.1) e que não existia: o
    `README.md` já anunciava esta cobertura, e `views.py` consultava `Convite`
    e `Usuario` direto sem nada avisar. Ver `MUTACOES` acima para por que a
    asserção é sobre gravação, e não sobre importar `models`."""
    arquivo = app / "views.py"
    if not arquivo.exists():
        pytest.skip(f"{app.name} ainda não tem views.py")
    achados = mutacoes_diretas(arquivo)
    assert not achados, (
        f"{app.name}/views.py grava no banco diretamente ({', '.join(achados)}). "
        "Toda mutação passa por services.py, onde a regra de negócio é "
        "aplicada e testada (CLAUDE.md, regra 4)."
    )
