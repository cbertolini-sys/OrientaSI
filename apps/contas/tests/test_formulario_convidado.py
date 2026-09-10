"""Testes do formulário de aceite de convite: unicidade de CPF/matrícula/SIAPE
(a rede que evita o IntegrityError de views.py chegando ao banco sem
necessidade) e os atributos de acessibilidade que a view/template dependem.
"""

import pytest

from apps.contas.forms import FormularioAlunoConvidado, FormularioProfessorConvidado
from apps.contas.models import PerfilAluno, PerfilProfessor, Usuario

DADOS_BASE = {
    "nome_completo": "Fulano de Tal",
    "cpf": "111.444.777-35",
    "telefone": "",
    "senha": "senha-bem-forte-123",
    "senha_confirmacao": "senha-bem-forte-123",
}


@pytest.mark.django_db
def test_cpf_duplicado_e_rejeitado_no_formulario():
    Usuario.objects.create_user(
        email="existente@ufsm.br",
        password="x",
        nome_completo="Existente",
        cpf="11144477735",
    )

    formulario = FormularioAlunoConvidado(data={**DADOS_BASE, "matricula": "1"})

    assert not formulario.is_valid()
    assert "cpf" in formulario.errors


@pytest.mark.django_db
def test_matricula_duplicada_e_rejeitada_no_formulario():
    usuario = Usuario.objects.create_user(
        email="jaexiste@ufsm.br",
        password="x",
        nome_completo="Já Existe",
        cpf="52998224725",
        papel=Usuario.ALUNO,
    )
    PerfilAluno.objects.create(usuario=usuario, matricula="12345")

    formulario = FormularioAlunoConvidado(data={**DADOS_BASE, "matricula": "12345"})

    assert not formulario.is_valid()
    assert "matricula" in formulario.errors


@pytest.mark.django_db
def test_siape_duplicado_e_rejeitado_no_formulario():
    usuario = Usuario.objects.create_user(
        email="japrof@ufsm.br",
        password="x",
        nome_completo="Já Professor",
        cpf="52998224725",
        papel=Usuario.PROFESSOR,
    )
    PerfilProfessor.objects.create(usuario=usuario, siape="999999")

    formulario = FormularioProfessorConvidado(data={**DADOS_BASE, "siape": "999999"})

    assert not formulario.is_valid()
    assert "siape" in formulario.errors


@pytest.mark.django_db
def test_cpf_com_pontuacao_e_aceito_e_normalizado():
    formulario = FormularioAlunoConvidado(data={**DADOS_BASE, "matricula": "1"})

    assert formulario.is_valid(), formulario.errors
    assert formulario.cleaned_data["cpf"] == "11144477735"


def test_campos_tem_autocomplete_para_wcag_1_3_5():
    """WCAG 2.1 AA 1.3.5 (Identify Input Purpose): o axe não detecta a ausência
    de autocomplete (só valida valores já presentes), por isso esta garantia
    precisa de um teste próprio, não da suíte de acessibilidade automatizada."""
    formulario = FormularioAlunoConvidado()

    assert formulario.fields["nome_completo"].widget.attrs["autocomplete"] == "name"
    assert formulario.fields["telefone"].widget.attrs["autocomplete"] == "tel"
    # A foto NÃO tem autocomplete, e isso é a asserção (revisão final): a
    # lista de "input purposes" do WCAG 2.1 não tem token para upload de
    # arquivo, e "photo" não é token do WHATWG — era atributo inválido,
    # contra o próprio critério 1.3.5 que este teste defende. Este teste
    # afirmava o contrário e por isso preservava o engano.
    assert "autocomplete" not in formulario.fields["foto"].widget.attrs
    assert formulario.fields["senha"].widget.attrs["autocomplete"] == "new-password"
    assert formulario.fields["senha_confirmacao"].widget.attrs["autocomplete"] == "new-password"


@pytest.mark.django_db
def test_campo_invalido_recebe_aria_invalid_e_aria_describedby():
    formulario = FormularioAlunoConvidado(data={})

    assert not formulario.is_valid()
    atributos = formulario.fields["nome_completo"].widget.attrs
    assert atributos["aria-invalid"] == "true"
    assert "erro-nome_completo" in atributos["aria-describedby"]


@pytest.mark.django_db
def test_texto_de_ajuda_e_referenciado_por_aria_describedby():
    formulario = FormularioAlunoConvidado()

    assert formulario.fields["cpf"].widget.attrs["aria-describedby"] == "ajuda-cpf"


@pytest.mark.django_db
def test_senha_parecida_com_o_nome_e_recusada():
    """`validate_password(senha)` era chamado sem o argumento `user` (achado
    da revisão final), o que deixa o `UserAttributeSimilarityValidator`
    inerte: qualquer pessoa podia usar o próprio nome como senha. O
    formulário monta um `Usuario` NÃO SALVO com o nome digitado e o e-mail do
    convite só para essa comparação."""
    dados = {
        **DADOS_BASE,
        "nome_completo": "Ana Silva",
        "senha": "anasilva1",
        "senha_confirmacao": "anasilva1",
        "matricula": "202400001",
    }
    formulario = FormularioAlunoConvidado(dados, email="ana.silva@ufsm.br")

    assert not formulario.is_valid()
    assert any("parecida" in str(erro) for erro in formulario.errors["__all__"])


@pytest.mark.django_db
def test_senha_parecida_com_o_email_do_convite_e_recusada():
    dados = {
        **DADOS_BASE,
        "senha": "fulanodetal2026",
        "senha_confirmacao": "fulanodetal2026",
        "matricula": "202400002",
    }
    formulario = FormularioAlunoConvidado(dados, email="fulanodetal@ufsm.br")

    assert not formulario.is_valid()
    assert any("parecida" in str(erro) for erro in formulario.errors["__all__"])
