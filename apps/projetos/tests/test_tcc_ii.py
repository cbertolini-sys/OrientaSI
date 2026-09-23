"""Testes do Bloco F: TCC II. Modelos (`Projeto.anterior`/`coorientador`,
`TermoPublicacao`) nesta primeira parte; serviços nas tarefas seguintes."""

from datetime import timedelta

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
    tema = Tema.objects.create(professor=professor, titulo=titulo, descricao="Descrição de teste.")
    tema.areas.set([area])
    return tema


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
def test_criar_tcc_ii_automatico_converte_integrityerror_em_validationerror(projeto_tcc_i):
    """ACHADO residual da revisão de código da correção C3/H5 (2026-09-22):
    H5 (`criar_tcc_ii_manual` recusa aluno com TCC I ativo) e o
    `select_for_update` novo em `aprovar_ata` fecham os vetores CONHECIDOS
    de colisão contra `projeto_ativo_unico_por_aluno_e_etapa`, mas esta
    função é chamada automaticamente — sem passar por formulário nenhum —
    e merece sua própria tradução de `IntegrityError`, não só depender das
    duas travas de entrada. Reproduz a colisão diretamente: um TCC II ativo
    já existe para o aluno quando `criar_tcc_ii_automatico` roda. Prova por
    mutação: remover o `try/except` desta função faz este teste reprovar
    com `IntegrityError` cru em vez de `ValidationError`."""
    Projeto.objects.create(
        aluno=projeto_tcc_i.aluno,
        orientador=projeto_tcc_i.orientador,
        etapa=Projeto.TCC_II,
        status=Projeto.EM_ANDAMENTO,
        ano=2026,
        periodo=1,
    )
    with pytest.raises(ValidationError):
        services.criar_tcc_ii_automatico(projeto_tcc_i)


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
def test_criar_tcc_ii_manual_recusa_aluno_com_tcc_i_ativo():
    """ACHADO H5/C3 da auditoria (2026-09-22): a docstring sempre disse "sem
    TCC I anterior no sistema", mas nada checava isso — um professor
    conseguia criar manualmente um TCC II para um aluno que já tinha um TCC
    I `EM_ANDAMENTO`. Semanas depois, quando a SUGRAD aprovasse a ata desse
    TCC I, `criar_tcc_ii_automatico` batia num `IntegrityError` (dois TCC
    II ativos para o mesmo aluno) — a ata ficava aprovada e o TCC I
    concluído SEM nenhum TCC II (achado C3). Prova por mutação: remover a
    checagem de `projeto_ativo_do_aluno` de `criar_tcc_ii_manual` faz este
    teste reprovar (o TCC II duplicado seria criado em vez de recusado)."""
    orientador = _professor(70, "Orientador Manual TCC I Ativo")
    aluno = _aluno(71, "Aluno Manual Com TCC I")
    tema = _tema(70, orientador)
    Projeto.objects.create(
        aluno=aluno,
        orientador=orientador.usuario,
        etapa=Projeto.TCC_I,
        status=Projeto.EM_ANDAMENTO,
        ano=2026,
        periodo=1,
    )
    with pytest.raises(ValidationError):
        services.criar_tcc_ii_manual(aluno.perfil_aluno, orientador, tema, por=orientador.usuario)
    assert not Projeto.objects.filter(aluno=aluno, etapa=Projeto.TCC_II).exists()


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
    tcc_i = services.criar_tcc_i_manual(
        aluno.perfil_aluno, orientador, tema, por=orientador.usuario
    )
    assert tcc_i.etapa == Projeto.TCC_I
    assert tcc_i.orientador_id == orientador.usuario_id
    assert tcc_i.tema_id == tema.id


@pytest.mark.django_db
def test_criar_tcc_i_manual_encerra_candidatura_em_curso_do_aluno():
    """ACHADO M11 da auditoria (2026-09-22): antes, `criar_tcc_i_manual`
    criava o `Projeto` e não tocava em `Candidatura` nenhuma — um aluno com
    uma opção `ENVIADA` a OUTRO professor, aguardando resposta, ficava com
    as duas coisas vivas ao mesmo tempo. A cascata continuava avançando por
    prazo e notificando o professor da fila sobre um aluno que já tinha
    orientador. Prova por mutação: remover o bloco que cancela a
    candidatura em `criar_tcc_i_manual` faz este teste reprovar (a
    candidatura continuaria `EM_CURSO`)."""
    from apps.projetos.models import Candidatura, OpcaoCandidatura

    professor_da_fila = _professor(103, "Professor Da Fila")
    orientador_manual = _professor(104, "Orientador Manual Equivalencia")
    aluno = _aluno(105, "Aluno Com Candidatura E TCC I Manual")
    tema_manual = _tema(103, orientador_manual)

    candidatura = services.registrar_candidatura(aluno.perfil_aluno, [(professor_da_fila, None)])
    assert candidatura.status == Candidatura.EM_CURSO

    services.criar_tcc_i_manual(
        aluno.perfil_aluno, orientador_manual, tema_manual, por=orientador_manual.usuario
    )

    candidatura.refresh_from_db()
    assert candidatura.status == Candidatura.CANCELADA
    opcao = candidatura.opcoes.get(ordem=1)
    assert opcao.situacao == OpcaoCandidatura.CANCELADA


@pytest.mark.django_db
def test_criar_tcc_i_manual_sem_candidatura_em_curso_nao_quebra():
    """Contraprova: um aluno SEM candidatura nenhuma continua funcionando
    normalmente (o `.first()` da busca por `EM_CURSO` retorna `None`, e a
    função segue direto para `criar_projeto_sob_limite`)."""
    orientador = _professor(106, "Orientador Manual Sem Candidatura")
    aluno = _aluno(107, "Aluno Sem Candidatura Manual")
    tema = _tema(106, orientador)
    tcc_i = services.criar_tcc_i_manual(
        aluno.perfil_aluno, orientador, tema, por=orientador.usuario
    )
    assert tcc_i.pk is not None


@pytest.mark.django_db
def test_criar_tcc_i_manual_recusa_aluno_desativado():
    """ACHADO L6 da auditoria (2026-09-22): defesa em profundidade — o
    fluxo normal (convite) nunca produz um `PerfilAluno` desativado
    selecionável, mas `FormularioCriarOrientacaoManual.aluno` lista TODO
    `PerfilAluno` sem filtrar `is_active`, e nada impedia criar uma
    orientação para uma conta que não consegue nem logar."""
    orientador = _professor(108, "Orientador Manual Aluno Inativo")
    aluno = _aluno(109, "Aluno Manual Inativo")
    aluno.is_active = False
    aluno.save(update_fields=["is_active"])
    tema = _tema(108, orientador)
    with pytest.raises(ValidationError):
        services.criar_tcc_i_manual(aluno.perfil_aluno, orientador, tema, por=orientador.usuario)


@pytest.mark.django_db
def test_criar_tcc_i_manual_recusa_professor_como_proprio_aluno():
    """ACHADO L6: defesa em profundidade contra `aluno == professor` —
    só alcançável se o mesmo `Usuario` tiver os dois perfis (admin/shell),
    já que o fluxo normal de convite nunca produz essa combinação.

    `papel=ALUNO` de propósito (em vez do papel padrão `PROFESSOR` de
    `_professor`): se o `Usuario` de teste tivesse `papel=PROFESSOR`, a
    checagem de papel (mais abaixo em
    `_garante_aluno_valido_para_orientacao_manual`) já rejeitaria sozinha, e
    este teste continuaria passando mesmo se a checagem de auto-orientação
    fosse removida por engano — a "checagem vizinha mascara a ausência da
    nova" que a Disciplina de Testes do CLAUDE.md pede para evitar."""
    from apps.contas.models import PerfilAluno, PerfilProfessor

    usuario = Usuario.objects.create_user(
        email="pessoa.dupla.perfil@ufsm.br",
        password="x",
        nome_completo="Pessoa Com Dois Perfis",
        papel=Usuario.ALUNO,
        cpf=_cpf(111),
    )
    PerfilAluno.objects.create(usuario=usuario, matricula="2026AUTOALUNO1")
    professor = PerfilProfessor.objects.create(usuario=usuario, siape="AUTOALUNO1")
    tema = _tema(110, professor)
    with pytest.raises(ValidationError):
        services.criar_tcc_i_manual(usuario.perfil_aluno, professor, tema, por=usuario)


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
        services.criar_tcc_i_manual(
            aluno_novo.perfil_aluno, orientador, tema, por=orientador.usuario
        )


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


@pytest.mark.django_db
def test_assinar_termo_publicacao_recusa_tcc_i():
    """ACHADO H6 da auditoria (2026-09-22): a regra "só existe no TCC II"
    vivia só em `views.meu_tcc` (calculada para desenhar o botão, nunca
    consultada antes de chamar o serviço)."""
    orientador = _professor(97, "Orientador Termo TCC I")
    aluno = _aluno(98, "Aluno Termo TCC I")
    projeto = Projeto.objects.create(
        aluno=aluno,
        orientador=orientador.usuario,
        etapa=Projeto.TCC_I,
        status=Projeto.APROVADO_COM_RESSALVAS,
        ano=2026,
        periodo=1,
    )
    with pytest.raises(ValidationError):
        services.assinar_termo_publicacao(projeto, por=aluno)
    assert not TermoPublicacao.objects.filter(projeto=projeto).exists()


@pytest.mark.django_db
def test_assinar_termo_publicacao_recusa_fora_de_aprovado_com_ressalvas():
    """ACHADO H6: um aluno de TCC II ainda `Em Andamento` (antes da banca)
    não deveria conseguir assinar o termo prematuramente — isso satisfaria
    o gate de `aprovar_projeto` sem o aluno ter visto as ressalvas."""
    orientador = _professor(99, "Orientador Termo Cedo")
    aluno = _aluno(100, "Aluno Termo Cedo")
    projeto = Projeto.objects.create(
        aluno=aluno,
        orientador=orientador.usuario,
        etapa=Projeto.TCC_II,
        status=Projeto.EM_ANDAMENTO,
        ano=2026,
        periodo=1,
    )
    with pytest.raises(ValidationError):
        services.assinar_termo_publicacao(projeto, por=aluno)


@pytest.mark.django_db
def test_assinar_termo_publicacao_recusa_reenvio():
    """ACHADO H6: antes, um reenvio do formulário batia direto no
    `OneToOneField` de `TermoPublicacao.projeto` — `IntegrityError` cru,
    500 (`views.meu_tcc` não tinha `try/except` nesse POST)."""
    orientador = _professor(101, "Orientador Termo Duplo")
    aluno = _aluno(102, "Aluno Termo Duplo")
    projeto = Projeto.objects.create(
        aluno=aluno,
        orientador=orientador.usuario,
        etapa=Projeto.TCC_II,
        status=Projeto.APROVADO_COM_RESSALVAS,
        ano=2026,
        periodo=1,
    )
    services.assinar_termo_publicacao(projeto, por=aluno)
    with pytest.raises(ValidationError):
        services.assinar_termo_publicacao(projeto, por=aluno)
    assert TermoPublicacao.objects.filter(projeto=projeto).count() == 1


@pytest.fixture
def projeto_tcc_ii_com_ressalvas(db):
    """`aprovar_projeto` chama `gerar_ata` ao final (Bloco E), que exige uma
    `Banca` `REALIZADA` do projeto — sem ela, `Banca.DoesNotExist` mascara
    a checagem de gate que este arquivo quer provar (mesmo achado do Bloco
    E em `test_aprovacao.py::projeto_com_ressalvas`).

    `data_hora` da banca fica no passado (1h atrás) de propósito: o
    terceiro gate de `aprovar_projeto` (versão final revisada) compara
    `Submissao.atualizada_em` contra essa data, e o "tudo pronto" precisa
    de folga real para a submissão revisada, criada DEPOIS deste fixture,
    ficar claramente depois — sem folga, os dois `auto_now`/`timezone.now()`
    no mesmo teste poderiam empatar por sorte de timing."""
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
        data_hora=timezone.now() - timedelta(hours=1),
        local="Sala 1",
        status=Banca.REALIZADA,
        nota=8.0,
        resultado=Projeto.APROVADO_COM_RESSALVAS,
    )
    return projeto


def _envia_versao_revisada(projeto):
    """Cria a `Submissao` do projeto já como reenvio pós-banca — mesmo
    arquivo fake usado pelos testes de `apps/projetos/tests/test_submissao.py`."""
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
        versao=2,
    )


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
    _envia_versao_revisada(projeto_tcc_ii_com_ressalvas)
    services.aprovar_projeto(
        projeto_tcc_ii_com_ressalvas, por=projeto_tcc_ii_com_ressalvas.orientador
    )
    projeto_tcc_ii_com_ressalvas.refresh_from_db()
    assert projeto_tcc_ii_com_ressalvas.status == Projeto.APROVADO


@pytest.mark.django_db
def test_aprovar_projeto_tcc_ii_recusa_sem_versao_revisada(projeto_tcc_ii_com_ressalvas):
    """Checklist concluído e termo assinado não bastam — sem nenhuma
    `Submissao`, o aluno nunca depositou nada, corrigido ou não."""
    item = bancas_services.criar_item_correcao(
        projeto_tcc_ii_com_ressalvas,
        descricao="Vai ser concluído.",
        por=projeto_tcc_ii_com_ressalvas.orientador,
    )
    bancas_services.concluir_item_correcao(item, por=projeto_tcc_ii_com_ressalvas.orientador)
    services.assinar_termo_publicacao(
        projeto_tcc_ii_com_ressalvas, por=projeto_tcc_ii_com_ressalvas.aluno
    )
    with pytest.raises(ValidationError):
        services.aprovar_projeto(
            projeto_tcc_ii_com_ressalvas, por=projeto_tcc_ii_com_ressalvas.orientador
        )
    projeto_tcc_ii_com_ressalvas.refresh_from_db()
    assert projeto_tcc_ii_com_ressalvas.status == Projeto.APROVADO_COM_RESSALVAS


@pytest.mark.django_db
def test_aprovar_projeto_tcc_ii_recusa_submissao_anterior_a_banca(projeto_tcc_ii_com_ressalvas):
    """A `Submissao` existe, mas nunca foi reenviada depois da banca — é a
    mesma versão pré-defesa que a banca já avaliou, não a corrigida."""
    from apps.projetos.models import Submissao

    projeto = projeto_tcc_ii_com_ressalvas
    submissao = _envia_versao_revisada(projeto)
    # Força `atualizada_em` (auto_now) para ANTES da banca, sem passar pelo
    # `save()` normal, que sempre grava "agora".
    Submissao.objects.filter(pk=submissao.pk).update(
        atualizada_em=projeto.bancas.get().data_hora - timedelta(hours=1)
    )
    item = bancas_services.criar_item_correcao(
        projeto, descricao="Vai ser concluído.", por=projeto.orientador
    )
    bancas_services.concluir_item_correcao(item, por=projeto.orientador)
    services.assinar_termo_publicacao(projeto, por=projeto.aluno)
    with pytest.raises(ValidationError):
        services.aprovar_projeto(projeto, por=projeto.orientador)
    projeto.refresh_from_db()
    assert projeto.status == Projeto.APROVADO_COM_RESSALVAS


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
