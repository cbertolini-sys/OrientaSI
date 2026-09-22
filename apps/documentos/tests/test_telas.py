"""Testes HTTP de `/painel/sugrad/` (Bloco E, spec §7). Portão de PAPEL, sem
lookup de posse — lista atas de qualquer projeto (mesmo padrão de
`painel_orientacoes`, Bloco B)."""

import pytest
from django.utils import timezone

from apps.bancas.models import Banca
from apps.contas.models import PerfilAluno, PerfilProfessor, Usuario
from apps.contas.validators import _digito
from apps.documentos import services
from apps.projetos.models import Projeto


def _cpf(indice):
    base = f"{750000000 + indice:09d}"
    d1 = _digito(base, 10)
    d2 = _digito(base + str(d1), 11)
    return base + str(d1) + str(d2)


@pytest.fixture
def ata_pendente(db):
    aluno = Usuario.objects.create_user(
        email="aluno.telasugrad@ufsm.br",
        password="x",
        nome_completo="Aluno Tela SUGRAD",
        papel=Usuario.ALUNO,
        cpf=_cpf(1),
    )
    PerfilAluno.objects.create(usuario=aluno, matricula="2026TELASUG1")
    orientador = Usuario.objects.create_user(
        email="orientador.telasugrad@ufsm.br",
        password="x",
        nome_completo="Orientador Tela SUGRAD",
        cpf=_cpf(2),
    )
    PerfilProfessor.objects.create(usuario=orientador, siape="TELASUG01")
    projeto = Projeto.objects.create(
        aluno=aluno,
        orientador=orientador,
        etapa=Projeto.TCC_I,
        status=Projeto.APROVADO,
        ano=2026,
        periodo=1,
    )
    Banca.objects.create(
        projeto=projeto,
        data_hora=timezone.now(),
        local="Sala 1",
        status=Banca.REALIZADA,
        nota=8.0,
        resultado=Projeto.APROVADO_COM_RESSALVAS,
    )
    return services.gerar_ata(projeto)


@pytest.fixture
def sugrad(db):
    return Usuario.objects.create_user(
        email="sugrad.tela@ufsm.br",
        password="x",
        nome_completo="SUGRAD",
        papel=Usuario.SUGRAD,
        cpf=None,
    )


@pytest.mark.django_db
def test_painel_lista_ata_pendente(client, ata_pendente, sugrad):
    client.force_login(sugrad)
    resposta = client.get("/painel/sugrad/")
    assert ata_pendente.numero in resposta.content.decode()


@pytest.mark.django_db
def test_painel_recusa_quem_nao_e_sugrad(client, ata_pendente):
    client.force_login(ata_pendente.projeto.orientador)
    resposta = client.get("/painel/sugrad/")
    assert resposta.status_code == 403


@pytest.mark.django_db
def test_aprovar_ata_view_redireciona(client, ata_pendente, sugrad):
    client.force_login(sugrad)
    resposta = client.post(f"/painel/sugrad/{ata_pendente.pk}/aprovar/")
    assert resposta.status_code == 302
    ata_pendente.projeto.refresh_from_db()
    assert ata_pendente.projeto.status == Projeto.CONCLUIDO


@pytest.mark.django_db
def test_aprovar_ata_view_recusa_get(client, ata_pendente, sugrad):
    """ACHADO H1 da auditoria (2026-09-22): esta era a ÚNICA view de
    transição de status do sistema alcançável por GET — sem proteção de
    CSRF (que o Django não aplica a métodos seguros), um `<img src>` ou um
    link-prefetcher bastavam para aprovar a ata enquanto a SUGRAD estivesse
    logada. Prova por mutação: remover `@require_POST` da view faz este
    teste reprovar (o GET aprovaria a ata em vez de dar 405)."""
    client.force_login(sugrad)
    resposta = client.get(f"/painel/sugrad/{ata_pendente.pk}/aprovar/")
    assert resposta.status_code == 405
    ata_pendente.projeto.refresh_from_db()
    assert ata_pendente.projeto.status != Projeto.CONCLUIDO


@pytest.mark.django_db
def test_aprovar_ata_view_duas_vezes_nao_da_500(client, ata_pendente, sugrad):
    """ACHADO H7: a view não capturava o `ValidationError` de uma revisão
    que já não está mais `PENDENTE`."""
    client.force_login(sugrad)
    primeira = client.post(f"/painel/sugrad/{ata_pendente.pk}/aprovar/")
    segunda = client.post(f"/painel/sugrad/{ata_pendente.pk}/aprovar/")
    assert primeira.status_code == 302
    assert segunda.status_code == 302


@pytest.mark.django_db
def test_devolver_ata_view_exige_comentario(client, ata_pendente, sugrad):
    client.force_login(sugrad)
    resposta = client.post(f"/painel/sugrad/{ata_pendente.pk}/devolver/", {"comentario": ""})
    assert resposta.status_code == 302
    ata_pendente.revisao.refresh_from_db()
    from apps.documentos.models import RevisaoSUGRAD

    assert ata_pendente.revisao.status == RevisaoSUGRAD.PENDENTE


@pytest.mark.django_db
def test_devolver_ata_view_recusa_get(client, ata_pendente, sugrad):
    """ACHADO H1: mesma trava em `devolver_ata_view` — antes só estava
    "protegida" por acidente (um GET produz um `QueryDict` vazio, que o
    formulário recusa por comentário em branco, mas isso nunca foi uma
    decisão de design)."""
    client.force_login(sugrad)
    resposta = client.get(f"/painel/sugrad/{ata_pendente.pk}/devolver/")
    assert resposta.status_code == 405
