from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
CLAUDE = (RAIZ / "CLAUDE.md").read_text(encoding="utf-8")


def test_claude_md_nao_tem_markdown_escapado():
    """O arquivo veio de uma exportação que escapou o markdown: \\#\\# e \\*\\*."""
    for escapado in ["\\#", "\\*", "\\`"]:
        assert escapado not in CLAUDE, (
            f"CLAUDE.md contém markdown escapado ({escapado}), que renderiza a "
            "barra invertida à mostra."
        )


def test_claude_md_nomeia_as_apps_em_portugues():
    for app in ["apps/contas", "apps/projetos", "apps/bancas", "apps/documentos"]:
        assert app in CLAUDE, f"CLAUDE.md deve nomear {app}."
    for antiga in ["apps/accounts", "apps/projects", "apps/boards", "apps/documents"]:
        assert antiga not in CLAUDE, f"CLAUDE.md ainda cita o nome antigo {antiga}."


def test_claude_md_nao_manda_copiar_css_de_outro_projeto():
    assert "IntegraSI" not in CLAUDE
    assert "DaisyUI" in CLAUDE


def test_claude_md_registra_os_comandos_reais():
    for comando in ["docker compose up -d", "docker compose exec web pytest", "semear_sistema"]:
        assert comando in CLAUDE


def test_claude_md_manda_preparar_o_env_antes_de_subir():
    """Os serviços do docker-compose.yml declaram `env_file: .env`, e o `.env`
    não é versionado: num clone limpo, `docker compose up -d` falha antes de
    subir qualquer container. O README.md já trazia o `cp .env.example .env`;
    o CLAUDE.md, não (achado da revisão final)."""
    assert "cp .env.example .env" in CLAUDE


def test_claude_md_nao_manda_subir_com_profile_inexistente():
    """T4 removeu `profiles: [dev]` do serviço `tailwind` porque o comando
    oficial (`docker compose up -d`) não subia esse profile e a página era
    servida sem CSS. O comando de subida documentado não pode reintroduzir
    um `--profile dev` que o docker-compose.yml não usa mais."""
    assert "--profile dev" not in CLAUDE


def test_claude_md_documenta_a_guarda_do_semear_sistema():
    """`semear_sistema` recusa promover um novo coordenador quando o sistema
    já tem algum, e aponta o painel da coordenação como caminho para nomear
    os demais (achado da revisão 1 da Tarefa 12)."""
    assert "painel da coordenação" in CLAUDE


def test_claude_md_documenta_o_laranja_institucional_correto():
    """O laranja #D9530E reprova AA para texto (4.04:1); o tema usa #B8440B
    no token de texto e preserva #D9530E só para uso não-textual."""
    assert "#21376B" in CLAUDE
    assert "#B8440B" in CLAUDE


def test_claude_md_explica_que_professor_externo_e_bloco_d():
    assert "Bloco D" in CLAUDE


def test_claude_md_aponta_para_specs_e_plans():
    assert "docs/superpowers/specs/" in CLAUDE
    assert "docs/superpowers/plans/" in CLAUDE


def test_readme_existe_e_tem_comando_de_subida_real():
    readme = (RAIZ / "README.md").read_text(encoding="utf-8")
    assert "docker compose up -d" in readme
    assert "--profile dev" not in readme


def test_claude_md_descreve_a_excecao_ao_teto_de_vagas():
    """O CLAUDE.md dizia que o bloqueio em 3 é automático e absoluto. O Bloco B
    implementou uma exceção autorizada pela coordenação (LimiteOrientacao,
    apps/projetos/models.py). Documento que descreve regra mais rígida do que
    o sistema aplica faz alguém confiar numa trava que não existe."""
    assert "exceção" in CLAUDE
    assert "LimiteOrientacao" in CLAUDE
    assert "apps/projetos/models.py" in CLAUDE


def test_claude_md_descreve_apps_projetos_como_nao_vazia():
    """apps/projetos deixou de estar vazia neste bloco: temas, mural,
    candidatura em cascata e painel da coordenação moram lá agora."""
    assert "apps/projetos" in CLAUDE
    assert "vazia" not in _trecho_da_app_projetos()


def _trecho_da_app_projetos():
    inicio = CLAUDE.index("`apps/projetos`")
    fim = CLAUDE.index("`apps/bancas`")
    return CLAUDE[inicio:fim]


def test_claude_md_cita_celery_beat_na_arquitetura_de_containers():
    assert "celery_beat" in CLAUDE


def test_claude_md_lista_celery_beat_no_comando_de_subir_ambiente():
    """Achado da revisão da Tarefa 13: o teste acima passa mesmo se
    `celery_beat` só aparecer na seção de arquitetura — não protege contra
    esquecê-lo no bullet 'Subir ambiente', que é o primeiro lugar onde
    alguém procura o comando real. Isola esse trecho e cobra a citação ali
    também."""
    inicio = CLAUDE.index("**Subir ambiente:**")
    fim = CLAUDE.index("**Derrubar ambiente:**")
    assert "celery_beat" in CLAUDE[inicio:fim]


def test_claude_md_registra_a_alocacao_continua_e_a_divergencia_do_inicio_pdf():
    """Decisão de produto do Bloco B (spec §3.1): alocação por ordem de chegada,
    não por desempenho escolar — ao contrário do que o `inicio.pdf` pedia."""
    assert "inicio.pdf" in CLAUDE
    assert "desempenho" in CLAUDE


def test_claude_md_atualiza_o_ciclo_de_vida_do_projeto():
    """O modelo Projeto passou a existir neste bloco; só EM_ANDAMENTO é
    alcançável até o Bloco C trazer as demais transições."""
    assert "o modelo `Projeto` ainda não existe" not in CLAUDE
    assert "EM_ANDAMENTO" in CLAUDE


def test_claude_md_marca_o_bloco_b_como_concluido():
    assert "B — temas e alocação (concluído)" in CLAUDE


def test_claude_md_registra_disciplina_de_prova_por_mutacao():
    """Convenção de engenharia tirada do Bloco B para os blocos seguintes: uma
    checagem só está provada quando removê-la faz um teste reprovar."""
    assert "mutação" in CLAUDE


def test_readme_documenta_o_celery_beat():
    readme = (RAIZ / "README.md").read_text(encoding="utf-8")
    assert "celery_beat" in readme
