"""Testes do Bloco F: TCC II. Modelos (`Projeto.anterior`/`coorientador`,
`TermoPublicacao`) nesta primeira parte; serviços nas tarefas seguintes."""

import pytest
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError
from django.utils import timezone

from apps.bancas import services as bancas_services
from apps.contas.models import Area, PerfilAluno, PerfilProfessor, Usuario
from apps.contas.validators import _digito
from apps.projetos import services
from apps.projetos.models import Projeto, Tema, TermoPublicacao


def _cpf(indice):
    """CPF sintético com dígitos verificadores válidos, faixa 800000000+ —
    livre (conferida por grep) para os testes do Bloco F."""
    base = f"{800000000 + indice:09d}"
    d1 = _digito(base, 10)
    d2 = _digito(base + str(d1), 11)
    return base + str(d1) + str(d2)


def _professor(indice, nome):
    usuario = Usuario.objects.create_user(
        email=f"professor.tccii.{indice}@ufsm.br",
        password="x",
        nome_completo=nome,
        cpf=_cpf(indice),
    )
    return PerfilProfessor.objects.create(usuario=usuario, siape=f"TCCII{indice:03d}")


def _aluno(indice, nome):
    usuario = Usuario.objects.create_user(
        email=f"aluno.tccii.{indice}@ufsm.br",
        password="x",
        nome_completo=nome,
        papel=Usuario.ALUNO,
        cpf=_cpf(indice),
    )
    PerfilAluno.objects.create(usuario=usuario, matricula=f"2026TCCII{indice:02d}")
    return usuario


def _tema(indice, professor, titulo="Tema TCC II de Teste"):
    area = Area.objects.create(nome=f"Área TCC II {indice}")
    return Tema.objects.create(
        professor=professor, area=area, titulo=titulo, descricao="Descrição de teste."
    )


@pytest.fixture
def projeto_tcc_i(db):
    orientador = _professor(1, "Orientador TCC II Modelo")
    aluno = _aluno(2, "Aluno TCC II Modelo")
    return Projeto.objects.create(
        aluno=aluno,
        orientador=orientador.usuario,
        etapa=Projeto.TCC_I,
        status=Projeto.CONCLUIDO,
        ano=2026,
        periodo=1,
    )


@pytest.mark.django_db
def test_projeto_tcc_ii_aponta_para_anterior(projeto_tcc_i):
    tcc_ii = Projeto.objects.create(
        aluno=projeto_tcc_i.aluno,
        orientador=projeto_tcc_i.orientador,
        etapa=Projeto.TCC_II,
        status=Projeto.EM_ANDAMENTO,
        anterior=projeto_tcc_i,
        ano=2026,
        periodo=2,
    )
    assert tcc_ii.anterior_id == projeto_tcc_i.id


@pytest.mark.django_db
def test_projeto_coorientador_recusa_interno_e_externo_juntos(projeto_tcc_i):
    coorientador = _professor(3, "Coorientador Duplo")
    with pytest.raises(IntegrityError):
        Projeto.objects.create(
            aluno=_aluno(4, "Aluno Coorientador Duplo"),
            orientador=projeto_tcc_i.orientador,
            etapa=Projeto.TCC_I,
            status=Projeto.EM_ANDAMENTO,
            coorientador=coorientador,
            coorientador_externo="Fulano Externo",
            ano=2026,
            periodo=1,
        )


@pytest.mark.django_db
def test_projeto_coorientador_aceita_so_um_ou_nenhum(projeto_tcc_i):
    coorientador = _professor(5, "Coorientador Único")
    projeto = Projeto.objects.create(
        aluno=_aluno(6, "Aluno Coorientador Único"),
        orientador=projeto_tcc_i.orientador,
        etapa=Projeto.TCC_I,
        status=Projeto.EM_ANDAMENTO,
        coorientador=coorientador,
        ano=2026,
        periodo=1,
    )
    assert projeto.coorientador_id == coorientador.id
    assert projeto.coorientador_externo == ""


@pytest.mark.django_db
def test_termo_publicacao_existencia_significa_assinado(projeto_tcc_i):
    termo = TermoPublicacao.objects.create(projeto=projeto_tcc_i)
    assert termo.assinado_em is not None


@pytest.mark.django_db
def test_criar_tcc_ii_automatico_copia_aluno_e_orientador(projeto_tcc_i):
    tcc_ii = services.criar_tcc_ii_automatico(projeto_tcc_i)
    assert tcc_ii.aluno_id == projeto_tcc_i.aluno_id
    assert tcc_ii.orientador_id == projeto_tcc_i.orientador_id
    assert tcc_ii.etapa == Projeto.TCC_II
    assert tcc_ii.status == Projeto.EM_ANDAMENTO
    assert tcc_ii.anterior_id == projeto_tcc_i.id


@pytest.mark.django_db
def test_criar_tcc_ii_automatico_copia_coorientador(projeto_tcc_i):
    coorientador = _professor(7, "Coorientador Copiado")
    projeto_tcc_i.coorientador = coorientador
    projeto_tcc_i.save()
    tcc_ii = services.criar_tcc_ii_automatico(projeto_tcc_i)
    assert tcc_ii.coorientador_id == coorientador.id


@pytest.mark.django_db
def test_criar_tcc_ii_automatico_copia_tema(projeto_tcc_i):
    tema = _tema(8, projeto_tcc_i.orientador.perfil_professor)
    projeto_tcc_i.tema = tema
    projeto_tcc_i.save()
    tcc_ii = services.criar_tcc_ii_automatico(projeto_tcc_i)
    assert tcc_ii.tema_id == tema.id


@pytest.mark.django_db
def test_criar_tcc_ii_automatico_nao_checa_limite_de_vagas(projeto_tcc_i):
    """Mutação obrigatória (spec §3.1): este teste prova a AUSÊNCIA da
    checagem de vaga. Cria 3 outros TCC_II EM_ANDAMENTO para o mesmo
    orientador (o teto padrão) antes de chamar `criar_tcc_ii_automatico` —
    se a função checasse limite, este quarto TCC_II seria recusado."""
    from apps.comum.semestre import semestre_vigente

    ano, periodo = semestre_vigente()
    orientador = projeto_tcc_i.orientador
    for indice in (10, 11, 12):
        Projeto.objects.create(
            aluno=_aluno(indice, f"Aluno Vaga Cheia {indice}"),
            orientador=orientador,
            etapa=Projeto.TCC_II,
            status=Projeto.EM_ANDAMENTO,
            ano=ano,
            periodo=periodo,
        )
    tcc_ii = services.criar_tcc_ii_automatico(projeto_tcc_i)
    assert tcc_ii.pk is not None


@pytest.mark.django_db
def test_criar_tcc_ii_manual_cria_sem_anterior():
    orientador = _professor(20, "Orientador Manual")
    aluno = _aluno(21, "Aluno Manual")
    tema = _tema(20, orientador)
    tcc_ii = services.criar_tcc_ii_manual(
        aluno.perfil_aluno, orientador, tema, por=orientador.usuario
    )
    assert tcc_ii.anterior is None
    assert tcc_ii.etapa == Projeto.TCC_II
    assert tcc_ii.orientador_id == orientador.usuario_id
    assert tcc_ii.tema_id == tema.id


@pytest.mark.django_db
def test_criar_tcc_ii_manual_recusa_quem_nao_e_o_professor():
    orientador = _professor(22, "Orientador Manual Dois")
    outro = _professor(23, "Outro Professor Manual")
    aluno = _aluno(24, "Aluno Manual Dois")
    tema = _tema(22, orientador)
    with pytest.raises(PermissionDenied):
        services.criar_tcc_ii_manual(aluno.perfil_aluno, orientador, tema, por=outro.usuario)


@pytest.mark.django_db
def test_criar_tcc_ii_manual_recusa_tema_de_outro_professor():
    orientador = _professor(60, "Orientador Manual Tema Alheio")
    outro_professor = _professor(61, "Outro Professor Tema Alheio")
    aluno = _aluno(62, "Aluno Manual Tema Alheio")
    tema_alheio = _tema(60, outro_professor)
    with pytest.raises(PermissionDenied):
        services.criar_tcc_ii_manual(
            aluno.perfil_aluno, orientador, tema_alheio, por=orientador.usuario
        )


@pytest.mark.django_db
def test_criar_tcc_ii_manual_recusa_professor_no_limite():
    from apps.comum.semestre import semestre_vigente

    orientador = _professor(25, "Orientador Manual Limite")
    tema = _tema(25, orientador)
    ano, periodo = semestre_vigente()
    for indice in (26, 27, 28):
        Projeto.objects.create(
            aluno=_aluno(indice, f"Aluno Limite Manual {indice}"),
            orientador=orientador.usuario,
            etapa=Projeto.TCC_II,
            status=Projeto.EM_ANDAMENTO,
            ano=ano,
            periodo=periodo,
        )
    aluno_novo = _aluno(29, "Aluno Manual Recusado")
    with pytest.raises(ValidationError):
        services.criar_tcc_ii_manual(
            aluno_novo.perfil_aluno, orientador, tema, por=orientador.usuario
        )


@pytest.mark.django_db
def test_criar_tcc_ii_manual_view_redireciona(client):
    orientador = _professor(30, "Orientador Manual View")
    aluno = _aluno(31, "Aluno Manual View")
    tema = _tema(30, orientador)
    client.force_login(orientador.usuario)
    resposta = client.post(
        "/orientacoes/criar/",
        {"etapa": Projeto.TCC_II, "aluno": aluno.perfil_aluno.pk, "tema": tema.pk},
    )
    assert resposta.status_code == 302
    assert Projeto.objects.filter(
        aluno=aluno, etapa=Projeto.TCC_II, orientador=orientador.usuario, tema=tema
    ).exists()


# TCC I manual (exceção nova à regra inegociável nº 8, CLAUDE.md) — mesma
# bateria de `criar_tcc_ii_manual` acima, provando que `criar_tcc_i_manual`
# espelha exatamente o mesmo comportamento, só com `etapa=Projeto.TCC_I`.
@pytest.mark.django_db
def test_criar_tcc_i_manual_cria_orientacao():
    orientador = _professor(80, "Orientador Manual TCC I")
    aluno = _aluno(81, "Aluno Manual TCC I")
    tema = _tema(80, orientador)
    tcc_i = services.criar_tcc_i_manual(aluno.perfil_aluno, orientador, tema, por=orientador.usuario)
    assert tcc_i.etapa == Projeto.TCC_I
    assert tcc_i.orientador_id == orientador.usuario_id
    assert tcc_i.tema_id == tema.id


@pytest.mark.django_db
def test_criar_tcc_i_manual_recusa_quem_nao_e_o_professor():
    orientador = _professor(82, "Orientador Manual TCC I Dois")
    outro = _professor(83, "Outro Professor Manual TCC I")
    aluno = _aluno(84, "Aluno Manual TCC I Dois")
    tema = _tema(82, orientador)
    with pytest.raises(PermissionDenied):
        services.criar_tcc_i_manual(aluno.perfil_aluno, orientador, tema, por=outro.usuario)


@pytest.mark.django_db
def test_criar_tcc_i_manual_recusa_tema_de_outro_professor():
    orientador = _professor(85, "Orientador Manual TCC I Tema Alheio")
    outro_professor = _professor(86, "Outro Professor TCC I Tema Alheio")
    aluno = _aluno(87, "Aluno Manual TCC I Tema Alheio")
    tema_alheio = _tema(85, outro_professor)
    with pytest.raises(PermissionDenied):
        services.criar_tcc_i_manual(
            aluno.perfil_aluno, orientador, tema_alheio, por=orientador.usuario
        )


@pytest.mark.django_db
def test_criar_tcc_i_manual_recusa_professor_no_limite():
    from apps.comum.semestre import semestre_vigente

    orientador = _professor(88, "Orientador Manual TCC I Limite")
    tema = _tema(88, orientador)
    ano, periodo = semestre_vigente()
    for indice in (89, 90, 91):
        Projeto.objects.create(
            aluno=_aluno(indice, f"Aluno Limite Manual TCC I {indice}"),
            orientador=orientador.usuario,
            etapa=Projeto.TCC_I,
            status=Projeto.EM_ANDAMENTO,
            ano=ano,
            periodo=periodo,
        )
    aluno_novo = _aluno(92, "Aluno Manual TCC I Recusado")
    with pytest.raises(ValidationError):
        services.criar_tcc_i_manual(aluno_novo.perfil_aluno, orientador, tema, por=orientador.usuario)


@pytest.mark.django_db
def test_criar_tcc_i_manual_view_redireciona(client):
    orientador = _professor(93, "Orientador Manual TCC I View")
    aluno = _aluno(94, "Aluno Manual TCC I View")
    tema = _tema(93, orientador)
    client.force_login(orientador.usuario)
    resposta = client.post(
        "/orientacoes/criar/",
        {"etapa": Projeto.TCC_I, "aluno": aluno.perfil_aluno.pk, "tema": tema.pk},
    )
    assert resposta.status_code == 302
    assert Projeto.objects.filter(
        aluno=aluno, etapa=Projeto.TCC_I, orientador=orientador.usuario, tema=tema
    ).exists()


@pytest.mark.django_db
def test_criar_tcc_i_manual_notifica_aluno(settings, django_capture_on_commit_callbacks):
    from django.core import mail

    orientador = _professor(95, "Orientador Notif Manual TCC I")
    aluno = _aluno(96, "Aluno Notif Manual TCC I")
    tema = _tema(95, orientador)
    settings.CELERY_TASK_ALWAYS_EAGER = True
    with django_capture_on_commit_callbacks(execute=True):
        services.criar_tcc_i_manual(aluno.perfil_aluno, orientador, tema, por=orientador.usuario)
    assert len(mail.outbox) == 1
    assert mail.outbox[0].to == [aluno.email]


@pytest.mark.django_db
def test_assinar_termo_publicacao_cria_a_linha():
    orientador = _professor(40, "Orientador Termo")
    aluno = _aluno(41, "Aluno Termo")
    projeto = Projeto.objects.create(
        aluno=aluno,
        orientador=orientador.usuario,
        etapa=Projeto.TCC_II,
        status=Projeto.APROVADO_COM_RESSALVAS,
        ano=2026,
        periodo=1,
    )
    termo = services.assinar_termo_publicacao(projeto, por=aluno)
    assert termo.projeto_id == projeto.id


@pytest.mark.django_db
def test_assinar_termo_publicacao_recusa_quem_nao_e_o_aluno():
    orientador = _professor(42, "Orientador Termo Dois")
    aluno = _aluno(43, "Aluno Termo Dois")
    outro = _aluno(44, "Outro Aluno Termo")
    projeto = Projeto.objects.create(
        aluno=aluno,
        orientador=orientador.usuario,
        etapa=Projeto.TCC_II,
        status=Projeto.APROVADO_COM_RESSALVAS,
        ano=2026,
        periodo=1,
    )
    with pytest.raises(PermissionDenied):
        services.assinar_termo_publicacao(projeto, por=outro)


@pytest.fixture
def projeto_tcc_ii_com_ressalvas(db):
    """`aprovar_projeto` chama `gerar_ata` ao final (Bloco E), que exige uma
    `Banca` `REALIZADA` do projeto — sem ela, `Banca.DoesNotExist` mascara
    a checagem de gate que este arquivo quer provar (mesmo achado do Bloco
    E em `test_aprovacao.py::projeto_com_ressalvas`)."""
    from apps.bancas.models import Banca

    orientador = _professor(60, "Orientador Gate")
    aluno = _aluno(61, "Aluno Gate")
    projeto = Projeto.objects.create(
        aluno=aluno,
        orientador=orientador.usuario,
        etapa=Projeto.TCC_II,
        status=Projeto.APROVADO_COM_RESSALVAS,
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
    return projeto


@pytest.mark.django_db
def test_aprovar_projeto_tcc_ii_recusa_com_item_pendente(projeto_tcc_ii_com_ressalvas):
    bancas_services.criar_item_correcao(
        projeto_tcc_ii_com_ressalvas,
        descricao="Pendente.",
        por=projeto_tcc_ii_com_ressalvas.orientador,
    )
    services.assinar_termo_publicacao(
        projeto_tcc_ii_com_ressalvas, por=projeto_tcc_ii_com_ressalvas.aluno
    )
    with pytest.raises(ValidationError):
        services.aprovar_projeto(
            projeto_tcc_ii_com_ressalvas, por=projeto_tcc_ii_com_ressalvas.orientador
        )


@pytest.mark.django_db
def test_aprovar_projeto_tcc_ii_recusa_sem_termo(projeto_tcc_ii_com_ressalvas):
    item = bancas_services.criar_item_correcao(
        projeto_tcc_ii_com_ressalvas,
        descricao="Vai ser concluído.",
        por=projeto_tcc_ii_com_ressalvas.orientador,
    )
    bancas_services.concluir_item_correcao(item, por=projeto_tcc_ii_com_ressalvas.orientador)
    with pytest.raises(ValidationError):
        services.aprovar_projeto(
            projeto_tcc_ii_com_ressalvas, por=projeto_tcc_ii_com_ressalvas.orientador
        )


@pytest.mark.django_db
def test_aprovar_projeto_tcc_ii_aprova_com_tudo_pronto(projeto_tcc_ii_com_ressalvas):
    item = bancas_services.criar_item_correcao(
        projeto_tcc_ii_com_ressalvas,
        descricao="Vai ser concluído.",
        por=projeto_tcc_ii_com_ressalvas.orientador,
    )
    bancas_services.concluir_item_correcao(item, por=projeto_tcc_ii_com_ressalvas.orientador)
    services.assinar_termo_publicacao(
        projeto_tcc_ii_com_ressalvas, por=projeto_tcc_ii_com_ressalvas.aluno
    )
    services.aprovar_projeto(
        projeto_tcc_ii_com_ressalvas, por=projeto_tcc_ii_com_ressalvas.orientador
    )
    projeto_tcc_ii_com_ressalvas.refresh_from_db()
    assert projeto_tcc_ii_com_ressalvas.status == Projeto.APROVADO


@pytest.mark.django_db
def test_aprovar_projeto_view_com_item_pendente_nao_da_500(client, projeto_tcc_ii_com_ressalvas):
    bancas_services.criar_item_correcao(
        projeto_tcc_ii_com_ressalvas,
        descricao="Pendente.",
        por=projeto_tcc_ii_com_ressalvas.orientador,
    )
    services.assinar_termo_publicacao(
        projeto_tcc_ii_com_ressalvas, por=projeto_tcc_ii_com_ressalvas.aluno
    )
    client.force_login(projeto_tcc_ii_com_ressalvas.orientador)
    resposta = client.post(f"/orientacoes/{projeto_tcc_ii_com_ressalvas.pk}/aprovar/")
    assert resposta.status_code == 302
    projeto_tcc_ii_com_ressalvas.refresh_from_db()
    assert projeto_tcc_ii_com_ressalvas.status == Projeto.APROVADO_COM_RESSALVAS


@pytest.mark.django_db
def test_criar_tcc_ii_automatico_notifica_aluno(
    settings, django_capture_on_commit_callbacks, projeto_tcc_i
):
    from django.core import mail

    settings.CELERY_TASK_ALWAYS_EAGER = True
    with django_capture_on_commit_callbacks(execute=True):
        services.criar_tcc_ii_automatico(projeto_tcc_i)
    assert len(mail.outbox) == 1
    assert mail.outbox[0].to == [projeto_tcc_i.aluno.email]


@pytest.mark.django_db
def test_criar_tcc_ii_manual_notifica_aluno(settings, django_capture_on_commit_callbacks):
    from django.core import mail

    orientador = _professor(70, "Orientador Notif Manual")
    aluno = _aluno(71, "Aluno Notif Manual")
    tema = _tema(70, orientador)
    settings.CELERY_TASK_ALWAYS_EAGER = True
    with django_capture_on_commit_callbacks(execute=True):
        services.criar_tcc_ii_manual(aluno.perfil_aluno, orientador, tema, por=orientador.usuario)
    assert len(mail.outbox) == 1
    assert mail.outbox[0].to == [aluno.email]
