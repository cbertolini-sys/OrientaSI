"""Testes de integração da view `contas:perfil`: exige autenticação, permite
que quem tem `PerfilProfessor` escolha suas áreas de atuação e esconde esse
campo de quem não tem, cobre o caminho de erro de upload (extensão e
tamanho) e o defeito da revisão 1 (papel PROFESSOR sem `PerfilProfessor`).
"""

import io
import re

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse
from PIL import Image

from apps.contas.models import Area, PerfilProfessor, Usuario


@pytest.fixture
def professora(db):
    usuario = Usuario.objects.create_user(
        email="ana@ufsm.br",
        password="senha-bem-forte-123",
        nome_completo="Ana",
        cpf="52998224725",
    )
    PerfilProfessor.objects.create(usuario=usuario, siape="1234567")
    return usuario


def _imagem_valida(nome="foto.png", formato="PNG"):
    """Uma imagem de verdade (1x1 px): `forms.ImageField` chama
    `PIL.Image.open()` antes de rodar os validators do projeto, então um
    arquivo com conteúdo inválido nunca chegaria a exercitar
    `valida_extensao_imagem`/`valida_tamanho_arquivo` — só o erro genérico do
    Django ("não é uma imagem válida"). Uma imagem real, com a extensão
    "errada" no nome, é o jeito de exercitar o validator de extensão do
    projeto especificamente."""
    buffer = io.BytesIO()
    Image.new("RGB", (1, 1)).save(buffer, format=formato)
    buffer.seek(0)
    return SimpleUploadedFile(nome, buffer.read(), content_type="image/png")


@pytest.mark.django_db
def test_perfil_exige_autenticacao(client):
    resposta = client.get(reverse("contas:perfil"))
    assert resposta.status_code == 302
    assert "/contas/login/" in resposta.url


@pytest.mark.django_db
def test_professor_seleciona_suas_areas(client, professora):
    ia = Area.objects.create(nome="Inteligência Artificial")
    redes = Area.objects.create(nome="Redes")
    client.force_login(professora)

    resposta = client.post(
        reverse("contas:perfil"),
        {"telefone": "55999990000", "areas": [ia.pk, redes.pk]},
    )

    assert resposta.status_code == 302
    professora.refresh_from_db()
    assert set(professora.perfil_professor.areas.all()) == {ia, redes}
    assert professora.telefone == "55999990000"


@pytest.mark.django_db
def test_professor_ve_campo_de_areas(client, professora):
    """Contraparte positiva de `test_aluno_nao_ve_campo_de_areas`: sem ela,
    `"areas" not in html` do teste do aluno provaria só que a palavra não
    aparece por acaso — não que o campo existe quando deveria."""
    Area.objects.create(nome="Redes")
    client.force_login(professora)
    html = client.get(reverse("contas:perfil")).content.decode()
    assert 'name="areas"' in html


@pytest.mark.django_db
def test_form_professor_tem_fieldset_e_legend_para_areas(client, professora):
    """Rede de segurança própria para o `<fieldset>`/`<legend>` do grupo de
    áreas: o axe-core NÃO aponta a ausência desse agrupamento (as regras
    `checkboxgroup`/`radiogroup` foram removidas do axe-core 4 — confirmado
    rodando `Axe().run` com as mesmas tags de `tests/test_acessibilidade.py`
    contra o markup sem `<fieldset>`: zero violações). Sem este teste, quem
    remover o `<fieldset>`/`<legend>` do template não quebra suíte nenhuma."""
    client.force_login(professora)
    html = client.get(reverse("contas:perfil")).content.decode()
    assert "<fieldset" in html
    assert "<legend" in html and "Áreas de atuação" in html


@pytest.mark.django_db
def test_get_do_professor_marca_areas_ja_escolhidas(client, professora):
    ia = Area.objects.create(nome="Inteligência Artificial")
    redes = Area.objects.create(nome="Redes")
    professora.perfil_professor.areas.add(ia)
    client.force_login(professora)

    html = client.get(reverse("contas:perfil")).content.decode()

    tag_ia = _abre_tag_do_input(html, "areas", ia.pk)
    tag_redes = _abre_tag_do_input(html, "areas", redes.pk)
    assert "checked" in tag_ia, f"área escolhida deveria vir marcada: {tag_ia}"
    assert "checked" not in tag_redes, f"área não escolhida não deveria vir marcada: {tag_redes}"


def _abre_tag_do_input(html, nome_campo, valor):
    padrao = re.search(rf'<input[^>]*name="{nome_campo}"[^>]*value="{valor}"[^>]*>', html)
    assert padrao, f'<input name="{nome_campo}" value="{valor}"> não encontrado no HTML.'
    return padrao.group()


@pytest.mark.django_db
def test_aluno_nao_ve_campo_de_areas(client, db):
    aluno = Usuario.objects.create_user(
        email="joao@ufsm.br",
        password="senha-bem-forte-123",
        nome_completo="João",
        cpf="16899535009",
        papel=Usuario.ALUNO,
    )
    client.force_login(aluno)
    html = client.get(reverse("contas:perfil")).content.decode()
    assert "areas" not in html


@pytest.mark.django_db
def test_professor_sem_perfil_nao_quebra_o_get(client):
    """Achado da revisão 1: o papel padrão de `create_user`/`create_superuser`
    é PROFESSOR (`GerenciadorUsuario`), mas nada cria `PerfilProfessor`
    automaticamente — nem o `createsuperuser` que o `CLAUDE.md` manda rodar,
    nem a conta da coordenação (que a Tarefa 11 vai autenticar). Antes desta
    correção, este GET levantava `RelatedObjectDoesNotExist` (500)."""
    usuario = Usuario.objects.create_user(
        email="coord-sem-perfil@ufsm.br",
        password="senha-bem-forte-123",
        nome_completo="Coordenação Sem Perfil",
        cpf="87721295037",
        is_coordenador=True,
        is_staff=True,
    )
    client.force_login(usuario)

    resposta = client.get(reverse("contas:perfil"))

    assert resposta.status_code == 200
    assert 'name="areas"' not in resposta.content.decode()


@pytest.mark.django_db
def test_professor_sem_perfil_pode_salvar_telefone(client):
    usuario = Usuario.objects.create_user(
        email="coord-sem-perfil-post@ufsm.br",
        password="senha-bem-forte-123",
        nome_completo="Coordenação Sem Perfil",
        cpf="87721295037",
        is_coordenador=True,
        is_staff=True,
    )
    client.force_login(usuario)

    resposta = client.post(reverse("contas:perfil"), {"telefone": "55988887777"})

    assert resposta.status_code == 302
    usuario.refresh_from_db()
    assert usuario.telefone == "55988887777"


@pytest.mark.django_db
def test_post_com_extensao_de_foto_invalida_mostra_resumo_de_erros(client, professora):
    """Exercita `valida_extensao_imagem` (`apps/comum/validators.py`) através
    do formulário de verdade: o arquivo é uma imagem válida (Pillow aceita),
    só a extensão do nome (".gif") não está em `EXTENSOES_IMAGEM`."""
    client.force_login(professora)
    arquivo = _imagem_valida(nome="foto.gif")

    resposta = client.post(reverse("contas:perfil"), {"telefone": "", "foto": arquivo})

    assert resposta.status_code == 200
    assert 'id="resumo-erros"' in resposta.content.decode()
    professora.refresh_from_db()
    assert not professora.foto


@pytest.mark.django_db
def test_post_com_foto_acima_do_limite_mostra_resumo_de_erros(client, professora, settings):
    """Exercita `valida_tamanho_arquivo` através do formulário de verdade."""
    settings.TAMANHO_MAXIMO_UPLOAD_MB = 0
    client.force_login(professora)
    arquivo = _imagem_valida()

    resposta = client.post(reverse("contas:perfil"), {"telefone": "", "foto": arquivo})

    assert resposta.status_code == 200
    assert 'id="resumo-erros"' in resposta.content.decode()


@pytest.mark.django_db
def test_post_com_foto_valida_atualiza_a_foto_do_usuario(client, professora):
    """Exercita o ramo `if foto:` de `services.atualiza_perfil`, nunca antes
    testado por esta tela."""
    client.force_login(professora)
    arquivo = _imagem_valida()

    resposta = client.post(reverse("contas:perfil"), {"telefone": "", "foto": arquivo})

    assert resposta.status_code == 302
    professora.refresh_from_db()
    assert professora.foto.name
