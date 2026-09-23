"""Testes do Bloco F: `ItemCorrecao` (modelo nesta primeira parte, serviços
na Tarefa 4)."""

import pytest
from django.core.exceptions import PermissionDenied, ValidationError

from apps.bancas import services
from apps.bancas.models import ItemCorrecao
from apps.contas.models import PerfilAluno, PerfilProfessor, Usuario
from apps.contas.validators import _digito
from apps.projetos.models import Projeto


def _cpf(indice):
    base = f"{810000000 + indice:09d}"
    d1 = _digito(base, 10)
    d2 = _digito(base + str(d1), 11)
    return base + str(d1) + str(d2)


@pytest.fixture
def projeto_tcc_ii(db):
    orientador = Usuario.objects.create_user(
        email="professor.correcao.modelo@ufsm.br",
        password="x",
        nome_completo="Professor Correção Modelo",
        cpf=_cpf(1),
    )
    PerfilProfessor.objects.create(usuario=orientador, siape="CORR0001")
    aluno = Usuario.objects.create_user(
        email="aluno.correcao.modelo@ufsm.br",
        password="x",
        nome_completo="Aluno Correção Modelo",
        papel=Usuario.ALUNO,
        cpf=_cpf(2),
    )
    PerfilAluno.objects.create(usuario=aluno, matricula="2026CORR001")
    return Projeto.objects.create(
        aluno=aluno,
        orientador=orientador,
        etapa=Projeto.TCC_II,
        status=Projeto.APROVADO_COM_RESSALVAS,
        ano=2026,
        periodo=1,
    )


@pytest.mark.django_db
def test_item_correcao_nasce_nao_concluido(projeto_tcc_ii):
    item = ItemCorrecao.objects.create(projeto=projeto_tcc_ii, descricao="Ajustar a conclusão.")
    assert item.concluido is False


@pytest.mark.django_db
def test_criar_item_correcao(projeto_tcc_ii):
    item = services.criar_item_correcao(
        projeto_tcc_ii, descricao="Revisar a bibliografia.", por=projeto_tcc_ii.orientador
    )
    assert item.projeto_id == projeto_tcc_ii.id
    assert item.concluido is False


@pytest.mark.django_db
def test_criar_item_correcao_recusa_quem_nao_e_o_orientador(projeto_tcc_ii):
    outro = Usuario.objects.create_user(
        email="outro.correcao@ufsm.br", password="x", nome_completo="Outro Correção", cpf=_cpf(3)
    )
    with pytest.raises(PermissionDenied):
        services.criar_item_correcao(projeto_tcc_ii, descricao="x", por=outro)


@pytest.mark.django_db
def test_criar_item_correcao_recusa_tcc_i(projeto_tcc_ii):
    """ACHADO H4 da auditoria (2026-09-22): a restrição "checklist só existe
    para o TCC II" (CLAUDE.md) vivia só num `{% elif %}` de template — o
    serviço aceitava qualquer etapa. Prova por mutação: comentar a checagem
    de `_garante_checklist_aplicavel` faz este teste reprovar."""
    projeto_tcc_ii.etapa = Projeto.TCC_I
    projeto_tcc_ii.save(update_fields=["etapa"])
    with pytest.raises(ValidationError):
        services.criar_item_correcao(projeto_tcc_ii, descricao="x", por=projeto_tcc_ii.orientador)
    assert not ItemCorrecao.objects.filter(projeto=projeto_tcc_ii).exists()


@pytest.mark.django_db
def test_criar_item_correcao_recusa_fora_de_aprovado_com_ressalvas(projeto_tcc_ii):
    """ACHADO H4: o mesmo vale para o status — um item criado depois de
    `Aprovado`/`Concluído`/`Cancelado` nunca é reavaliado por
    `aprovar_projeto` e só confunde o aluno, que recebe um e-mail acionável
    sobre um TCC já fechado."""
    projeto_tcc_ii.status = Projeto.APROVADO
    projeto_tcc_ii.save(update_fields=["status"])
    with pytest.raises(ValidationError):
        services.criar_item_correcao(projeto_tcc_ii, descricao="x", por=projeto_tcc_ii.orientador)


@pytest.mark.django_db
def test_concluir_item_correcao_recusa_fora_de_aprovado_com_ressalvas(projeto_tcc_ii):
    """ACHADO H4: mesma checagem em `concluir_item_correcao` — um item de um
    projeto que já saiu do intervalo pós-banca não deveria ser mexível."""
    item = services.criar_item_correcao(
        projeto_tcc_ii, descricao="x", por=projeto_tcc_ii.orientador
    )
    projeto_tcc_ii.status = Projeto.APROVADO
    projeto_tcc_ii.save(update_fields=["status"])
    with pytest.raises(ValidationError):
        services.concluir_item_correcao(item, por=projeto_tcc_ii.orientador)
    item.refresh_from_db()
    assert item.concluido is False


@pytest.mark.django_db
def test_concluir_item_correcao(projeto_tcc_ii):
    item = services.criar_item_correcao(
        projeto_tcc_ii, descricao="Ajustar formatação.", por=projeto_tcc_ii.orientador
    )
    services.concluir_item_correcao(item, por=projeto_tcc_ii.orientador)
    item.refresh_from_db()
    assert item.concluido is True


@pytest.mark.django_db
def test_concluir_item_correcao_recusa_quem_nao_e_o_orientador(projeto_tcc_ii):
    item = services.criar_item_correcao(
        projeto_tcc_ii, descricao="x", por=projeto_tcc_ii.orientador
    )
    outro = Usuario.objects.create_user(
        email="outro.concluir@ufsm.br", password="x", nome_completo="Outro Concluir", cpf=_cpf(4)
    )
    with pytest.raises(PermissionDenied):
        services.concluir_item_correcao(item, por=outro)


@pytest.mark.django_db
def test_correcoes_view_lista_itens(client, projeto_tcc_ii):
    services.criar_item_correcao(
        projeto_tcc_ii, descricao="Item de teste da tela.", por=projeto_tcc_ii.orientador
    )
    client.force_login(projeto_tcc_ii.orientador)
    resposta = client.get(f"/bancas/{projeto_tcc_ii.pk}/correcoes/")
    assert "Item de teste da tela." in resposta.content.decode()


@pytest.mark.django_db
def test_correcoes_view_recusa_projeto_alheio_com_404(client, projeto_tcc_ii):
    outro = Usuario.objects.create_user(
        email="outro.correcoesview@ufsm.br",
        password="x",
        nome_completo="Outro Correções View",
        cpf=_cpf(5),
    )
    PerfilProfessor.objects.create(usuario=outro, siape="CORRVIEW1")
    client.force_login(outro)
    resposta = client.get(f"/bancas/{projeto_tcc_ii.pk}/correcoes/")
    assert resposta.status_code == 404


@pytest.mark.django_db
def test_concluir_item_view_apos_projeto_sair_de_ressalvas_nao_da_500(client, projeto_tcc_ii):
    """ACHADO H7 da auditoria (2026-09-22): a view de concluir item não
    capturava `ValidationError` — depois do guard de H4, um item de um
    projeto que já saiu de `APROVADO_COM_RESSALVAS` levanta `ValidationError`
    ao tentar concluir, e isso vazava como 500 em vez de uma mensagem."""
    item = services.criar_item_correcao(
        projeto_tcc_ii, descricao="Item que vai ficar obsoleto.", por=projeto_tcc_ii.orientador
    )
    projeto_tcc_ii.status = Projeto.APROVADO
    projeto_tcc_ii.save(update_fields=["status"])
    client.force_login(projeto_tcc_ii.orientador)
    resposta = client.post(f"/bancas/correcoes/{item.pk}/concluir/")
    assert resposta.status_code == 302
    item.refresh_from_db()
    assert item.concluido is False


@pytest.mark.django_db
def test_concluir_item_view_redireciona(client, projeto_tcc_ii):
    item = services.criar_item_correcao(
        projeto_tcc_ii, descricao="Item pra concluir via view.", por=projeto_tcc_ii.orientador
    )
    client.force_login(projeto_tcc_ii.orientador)
    resposta = client.post(f"/bancas/correcoes/{item.pk}/concluir/")
    assert resposta.status_code == 302
    item.refresh_from_db()
    assert item.concluido is True


@pytest.mark.django_db
def test_criar_item_correcao_notifica_aluno(
    settings, django_capture_on_commit_callbacks, projeto_tcc_ii
):
    from django.core import mail

    settings.CELERY_TASK_ALWAYS_EAGER = True
    with django_capture_on_commit_callbacks(execute=True):
        services.criar_item_correcao(
            projeto_tcc_ii, descricao="Ajustar.", por=projeto_tcc_ii.orientador
        )
    assert len(mail.outbox) == 1
    assert mail.outbox[0].to == [projeto_tcc_ii.aluno.email]


def _submissao_fake(projeto, versao=1):
    from django.core.files.uploadedfile import SimpleUploadedFile

    from apps.projetos.models import Submissao

    return Submissao.objects.create(
        projeto=projeto,
        pdf=SimpleUploadedFile(
            "trabalho.pdf", b"%PDF-1.4 conteudo", content_type="application/pdf"
        ),
        editavel=SimpleUploadedFile(
            "trabalho.docx",
            b"conteudo docx",
            content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        ),
        versao=versao,
    )


@pytest.mark.django_db
def test_correcoes_view_mostra_reenvio_depois_da_banca(client, projeto_tcc_ii):
    """Achado do pedido do usuário (2026-09-22): sem esta pista na tela, o
    professor só descobria que faltava a versão revisada depois de clicar
    em "Aprovar projeto" e ser jogado de volta pra `/orientacoes/` com uma
    mensagem genérica — mesma classe de lacuna do achado H-1 da auditoria."""
    from django.utils import timezone

    from apps.bancas.models import Banca

    Banca.objects.create(
        projeto=projeto_tcc_ii,
        data_hora=timezone.now() - timezone.timedelta(hours=1),
        local="Sala 1",
        status=Banca.REALIZADA,
        nota=8.0,
        resultado=Projeto.APROVADO_COM_RESSALVAS,
    )
    _submissao_fake(projeto_tcc_ii, versao=2)
    client.force_login(projeto_tcc_ii.orientador)
    resposta = client.get(f"/bancas/{projeto_tcc_ii.pk}/correcoes/").content.decode()
    assert "Reenviado depois da banca" in resposta
    assert "Ainda é a versão anterior à banca" not in resposta


@pytest.mark.django_db
def test_correcoes_view_avisa_versao_anterior_a_banca(client, projeto_tcc_ii):
    from django.utils import timezone

    from apps.bancas.models import Banca
    from apps.projetos.models import Submissao

    banca = Banca.objects.create(
        projeto=projeto_tcc_ii,
        data_hora=timezone.now(),
        local="Sala 1",
        status=Banca.REALIZADA,
        nota=8.0,
        resultado=Projeto.APROVADO_COM_RESSALVAS,
    )
    submissao = _submissao_fake(projeto_tcc_ii, versao=1)
    Submissao.objects.filter(pk=submissao.pk).update(
        atualizada_em=banca.data_hora - timezone.timedelta(hours=1)
    )
    client.force_login(projeto_tcc_ii.orientador)
    resposta = client.get(f"/bancas/{projeto_tcc_ii.pk}/correcoes/").content.decode()
    assert "Ainda é a versão anterior à banca" in resposta
    assert "Reenviado depois da banca" not in resposta
