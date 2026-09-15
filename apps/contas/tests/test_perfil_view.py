"""Testes de integração da view `contas:perfil`: exige autenticação, permite
que quem tem `PerfilProfessor` escolha suas áreas de atuação e esconde esse
campo de quem não tem, cobre o caminho de erro de upload (extensão e
tamanho) e o defeito da revisão 1 (papel PROFESSOR sem `PerfilProfessor`).

Segunda volta (pedido explícito do usuário: "editar todos os campos quando
entro como professor ou coordenador ou aluno") acrescentou nome/e-mail/CPF
pra qualquer papel, matrícula pra quem tem `PerfilAluno` e SIAPE pra quem tem
`PerfilProfessor` — com unicidade excluindo a própria conta (senão salvar o
formulário sem mudar nada reprovaria contra si mesmo) e CPF opcional só pra
SUGRAD. `_dados_base`/`_dados_professor`/`_dados_aluno`, abaixo, montam um
POST válido a partir do estado atual do usuário, pra cada teste só sobrescrever
o campo que está exercitando sem precisar listar os outros quatro/cinco toda
vez.
"""

import io
import re

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse
from PIL import Image

from apps.contas.models import Area, PerfilAluno, PerfilProfessor, Usuario
from apps.contas.validators import _digito


def _gera_cpf(indice):
    """CPF sintético com dígitos verificadores válidos, faixa 400000000+ —
    livre das faixas já usadas por outros arquivos de teste (200000000+ em
    test_coordenacao.py, 300000000+ em test_navegacao.py, 500000000+ a
    950000000+ em apps/projetos, 600000000+/700000000+/800000000+ em
    apps/bancas e apps/documentos). Necessário aqui, e não só nos dois CPFs
    fixos herdados do arquivo original ("52998224725"/"16899535009", ambos
    válidos de verdade): os CPFs "de exemplo" que o arquivo original usava
    pra contas sem perfil ("87721295037") nunca passavam por `valida_cpf` —
    o validator do campo do MODEL só roda em `full_clean()`/`ModelForm`, não
    em `Usuario.objects.create_user().save()` — e `FormularioPerfil.clean_cpf`
    (novo, ver docstring do módulo) passou a validar o dígito verificador de
    verdade, quebrando esses CPFs de mentira."""
    base = f"{400000000 + indice:09d}"
    d1 = _digito(base, 10)
    d2 = _digito(base + str(d1), 11)
    return base + str(d1) + str(d2)


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


@pytest.fixture
def aluno(db):
    usuario = Usuario.objects.create_user(
        email="joao@ufsm.br",
        password="senha-bem-forte-123",
        nome_completo="João",
        cpf="16899535009",
        papel=Usuario.ALUNO,
    )
    PerfilAluno.objects.create(usuario=usuario, matricula="2026JOAO001")
    return usuario


def _dados_base(usuario):
    """POST válido só com os campos comuns a qualquer papel — o estado ATUAL
    do usuário, pra um teste que sobrescreve um campo não derrubar os outros
    na validação (nome_completo/email/cpf agora são obrigatórios pra quem não
    é SUGRAD)."""
    return {
        "nome_completo": usuario.nome_completo,
        "email": usuario.email,
        "cpf": usuario.cpf or "",
        "telefone": usuario.telefone,
    }


def _dados_professor(usuario):
    dados = _dados_base(usuario)
    dados["siape"] = usuario.perfil_professor.siape
    return dados


def _dados_aluno(usuario):
    dados = _dados_base(usuario)
    dados["matricula"] = usuario.perfil_aluno.matricula
    return dados


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
    # Só subáreas (`area` preenchido) são marcáveis — ver o queryset de
    # `FormularioPerfilProfessor.areas`, restrito a `area__isnull=False`.
    area_pai = Area.objects.create(nome="Área de Teste Pai")
    ia = Area.objects.create(nome="Área de Teste Um", area=area_pai)
    redes = Area.objects.create(nome="Redes", area=area_pai)
    client.force_login(professora)

    resposta = client.post(
        reverse("contas:perfil"),
        {**_dados_professor(professora), "telefone": "55999990000", "areas": [ia.pk, redes.pk]},
    )

    assert resposta.status_code == 302
    professora.refresh_from_db()
    assert set(professora.perfil_professor.areas.all()) == {ia, redes}
    assert professora.telefone == "55999990000"


@pytest.mark.django_db
def test_professor_ve_campo_de_areas(client, professora):
    """Contraparte positiva de `test_aluno_nao_ve_campo_de_areas_nem_siape`:
    sem ela, `"areas" not in html` do teste do aluno provaria só que a
    palavra não aparece por acaso — não que o campo existe quando deveria."""
    Area.objects.create(nome="Redes")
    client.force_login(professora)
    html = client.get(reverse("contas:perfil")).content.decode()
    assert 'name="areas"' in html
    assert 'name="siape"' in html


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
    area_pai = Area.objects.create(nome="Área de Teste Pai")
    ia = Area.objects.create(nome="Área de Teste Um", area=area_pai)
    redes = Area.objects.create(nome="Redes", area=area_pai)
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
def test_aluno_ve_campo_de_matricula(client, aluno):
    client.force_login(aluno)
    html = client.get(reverse("contas:perfil")).content.decode()
    assert 'name="matricula"' in html


@pytest.mark.django_db
def test_aluno_nao_ve_campo_de_areas_nem_siape(client, aluno):
    client.force_login(aluno)
    html = client.get(reverse("contas:perfil")).content.decode()
    assert 'name="areas"' not in html
    assert 'name="siape"' not in html


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
        cpf=_gera_cpf(1),
        is_coordenador=True,
        is_staff=True,
    )
    client.force_login(usuario)

    resposta = client.get(reverse("contas:perfil"))

    assert resposta.status_code == 200
    assert 'name="areas"' not in resposta.content.decode()
    assert 'name="matricula"' not in resposta.content.decode()


@pytest.mark.django_db
def test_professor_sem_perfil_pode_salvar_telefone(client):
    usuario = Usuario.objects.create_user(
        email="coord-sem-perfil-post@ufsm.br",
        password="senha-bem-forte-123",
        nome_completo="Coordenação Sem Perfil",
        cpf=_gera_cpf(2),
        is_coordenador=True,
        is_staff=True,
    )
    client.force_login(usuario)

    resposta = client.post(
        reverse("contas:perfil"), {**_dados_base(usuario), "telefone": "55988887777"}
    )

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

    resposta = client.post(
        reverse("contas:perfil"), {**_dados_professor(professora), "foto": arquivo}
    )

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

    resposta = client.post(
        reverse("contas:perfil"), {**_dados_professor(professora), "foto": arquivo}
    )

    assert resposta.status_code == 200
    assert 'id="resumo-erros"' in resposta.content.decode()


@pytest.mark.django_db
def test_post_com_foto_valida_atualiza_a_foto_do_usuario(client, professora):
    """Exercita o ramo `if foto:` de `services.atualiza_perfil`, nunca antes
    testado por esta tela."""
    client.force_login(professora)
    arquivo = _imagem_valida()

    resposta = client.post(
        reverse("contas:perfil"), {**_dados_professor(professora), "foto": arquivo}
    )

    assert resposta.status_code == 302
    professora.refresh_from_db()
    assert professora.foto.name


@pytest.mark.django_db
def test_professor_edita_nome_email_cpf(client, professora):
    """Caminho positivo do pedido explícito do usuário: os três campos de
    identidade, antes só exibidos como texto solto, agora se gravam de
    verdade."""
    client.force_login(professora)

    resposta = client.post(
        reverse("contas:perfil"),
        {
            **_dados_professor(professora),
            "nome_completo": "Ana Paula",
            "email": "ana.paula@ufsm.br",
            "cpf": "529.982.247-25",
        },
    )

    assert resposta.status_code == 302
    professora.refresh_from_db()
    assert professora.nome_completo == "Ana Paula"
    assert professora.email == "ana.paula@ufsm.br"
    # `clean_cpf` remove a pontuação antes de gravar — mesmo comportamento
    # de `FormularioConvidado.clean_cpf`, no aceite do convite.
    assert professora.cpf == "52998224725"


@pytest.mark.django_db
def test_aluno_edita_matricula(client, aluno):
    client.force_login(aluno)

    resposta = client.post(
        reverse("contas:perfil"), {**_dados_aluno(aluno), "matricula": "2026JOAO002"}
    )

    assert resposta.status_code == 302
    aluno.refresh_from_db()
    assert aluno.perfil_aluno.matricula == "2026JOAO002"


@pytest.mark.django_db
def test_professor_edita_siape(client, professora):
    client.force_login(professora)

    resposta = client.post(
        reverse("contas:perfil"), {**_dados_professor(professora), "siape": "7654321"}
    )

    assert resposta.status_code == 302
    professora.refresh_from_db()
    assert professora.perfil_professor.siape == "7654321"


@pytest.mark.django_db
def test_manter_o_proprio_email_nao_e_recusado(client, professora):
    """Regressão do auto-exclude: salvar o formulário sem mudar o e-mail não
    pode reprovar contra a própria conta. Prova por mutação (ver CLAUDE.md):
    tirar o `.exclude(pk=self.usuario.pk)` de `FormularioPerfil.clean_email`
    faz este teste reprovar (o e-mail "já existente" é o da própria
    `professora`)."""
    client.force_login(professora)

    resposta = client.post(reverse("contas:perfil"), _dados_professor(professora))

    # 302 (não 200 com o formulário de volta) já prova que a validação
    # passou — um e-mail recusado reprovaria a validação e re-renderizaria
    # a própria página (200), nunca redirecionaria.
    assert resposta.status_code == 302
    professora.refresh_from_db()
    assert professora.email == "ana@ufsm.br"


@pytest.mark.django_db
def test_email_duplicado_e_recusado(client, professora, aluno):
    client.force_login(professora)

    resposta = client.post(
        reverse("contas:perfil"), {**_dados_professor(professora), "email": aluno.email}
    )

    assert resposta.status_code == 200
    assert "Já existe uma conta cadastrada com este e-mail." in resposta.content.decode()
    professora.refresh_from_db()
    assert professora.email == "ana@ufsm.br"


@pytest.mark.django_db
def test_manter_o_proprio_cpf_nao_e_recusado(client, professora):
    """Mesma regressão de auto-exclude que `test_manter_o_proprio_email_nao_e_recusado`,
    agora para `FormularioPerfil.clean_cpf`."""
    client.force_login(professora)

    resposta = client.post(reverse("contas:perfil"), _dados_professor(professora))

    assert resposta.status_code == 302


@pytest.mark.django_db
def test_cpf_duplicado_e_recusado(client, professora, aluno):
    client.force_login(professora)

    resposta = client.post(
        reverse("contas:perfil"), {**_dados_professor(professora), "cpf": aluno.cpf}
    )

    assert resposta.status_code == 200
    assert "Já existe uma conta cadastrada com este CPF." in resposta.content.decode()


@pytest.mark.django_db
def test_cpf_vazio_e_recusado_para_professor(client, professora):
    """`FormularioPerfil.cpf` é `required=False` no campo (a conta da SUGRAD
    não tem CPF), mas `clean_cpf` reforça a obrigatoriedade pra quem não é
    SUGRAD — prova por mutação: remover essa checagem faz este teste
    reprovar."""
    client.force_login(professora)

    resposta = client.post(reverse("contas:perfil"), {**_dados_professor(professora), "cpf": ""})

    assert resposta.status_code == 200
    assert "CPF é obrigatório." in resposta.content.decode()


@pytest.mark.django_db
def test_sugrad_pode_deixar_cpf_vazio(client, db):
    sugrad = Usuario.objects.create_user(
        email="sugrad.perfil@ufsm.br",
        password="senha-bem-forte-123",
        nome_completo="SUGRAD",
        papel=Usuario.SUGRAD,
        cpf=None,
    )
    client.force_login(sugrad)

    resposta = client.post(reverse("contas:perfil"), _dados_base(sugrad))

    assert resposta.status_code == 302
    sugrad.refresh_from_db()
    assert not sugrad.cpf


@pytest.mark.django_db
def test_matricula_duplicada_e_recusada(client, aluno, db):
    outro = Usuario.objects.create_user(
        email="maria@ufsm.br",
        password="senha-bem-forte-123",
        nome_completo="Maria",
        cpf="98765432100",
        papel=Usuario.ALUNO,
    )
    PerfilAluno.objects.create(usuario=outro, matricula="2026MARIA001")
    client.force_login(aluno)

    resposta = client.post(
        reverse("contas:perfil"), {**_dados_aluno(aluno), "matricula": "2026MARIA001"}
    )

    assert resposta.status_code == 200
    assert "Já existe um aluno cadastrado com esta matrícula." in resposta.content.decode()


@pytest.mark.django_db
def test_siape_duplicado_e_recusado(client, professora, db):
    outro = Usuario.objects.create_user(
        email="carlos@ufsm.br",
        password="senha-bem-forte-123",
        nome_completo="Carlos",
        cpf=_gera_cpf(3),
    )
    PerfilProfessor.objects.create(usuario=outro, siape="9999999")
    client.force_login(professora)

    resposta = client.post(
        reverse("contas:perfil"), {**_dados_professor(professora), "siape": "9999999"}
    )

    assert resposta.status_code == 200
    assert "Já existe um professor cadastrado com este SIAPE." in resposta.content.decode()
