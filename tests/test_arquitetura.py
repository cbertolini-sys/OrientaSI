import ast
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parent.parent
APPS = sorted(p for p in (RAIZ / "apps").iterdir() if (p / "apps.py").exists())


def importa(caminho, alvo):
    arvore = ast.parse(caminho.read_text(encoding="utf-8"))
    for no in ast.walk(arvore):
        if isinstance(no, ast.ImportFrom) and no.module and alvo in no.module:
            return True
    return False


@pytest.mark.parametrize("app", APPS, ids=lambda p: p.name)
def test_models_nao_importa_services(app):
    arquivo = app / "models.py"
    if not arquivo.exists():
        pytest.skip(f"{app.name} ainda não tem models.py")
    assert not importa(arquivo, "services"), (
        f"{app.name}/models.py importa services: a regra de negócio deve ficar "
        "na camada de serviço, e o model não pode depender dela."
    )
