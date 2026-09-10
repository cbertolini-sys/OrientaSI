"""`/perfil/` deixou de ter uma suíte de acessibilidade própria (T1 do Bloco B).

Os seis corpos de teste que viviam aqui (WCAG nas duas larguras, contagem de
`<h1>`, primeira tabulação, alvos de toque nas duas larguras, rolagem
horizontal) eram cópias literais das quatro suítes transversais
(`tests/test_acessibilidade.py`, `test_toque.py`, `test_responsivo.py`,
`test_teclado.py`) — a única diferença era autenticar antes de navegar. As
três cópias já haviam divergido em três direções: só esta rodava numa única
largura, esta e a de `/painel/` tinham ficado mais estritas que a régua
oficial (faltava a isenção de link inline em prosa de
`tests/test_toque.py::_eh_link_inline_em_prosa`), e nenhuma trazia o relatório
de "qual elemento estourou" que a suíte transversal ganhou.

A generalização de `ROTAS` (`conftest.py`) resolve isso: `Rota` aceita uma
`fabrica_usuario` opcional, e a fixture `rota` autentica e confirma a âncora
de identidade (URL final + `<h1>` "Meu perfil") antes de qualquer medição.
`/perfil/` agora entra na lista como

    Rota("/perfil/", "form", fabrica_usuario=cria_professor_para_rotas, h1="Meu perfil")

e é medida pelas quatro suítes transversais como qualquer outra rota — sem
cópia.

A variante testada é a do professor (com `<fieldset>`/`<legend>` do grupo de
áreas); a fábrica da variante do aluno (`cria_aluno_para_rotas`, também em
`conftest.py`) fica pronta para as telas autenticadas de aluno que o Bloco B
ainda vai acrescentar a `ROTAS` (candidatura, mural). Isso estreita a
cobertura de acessibilidade de `/perfil/` a uma única persona — a suíte
antiga cobria professor e aluno em paralelo; a nova, só professor. É uma
troca deliberada (menos uma cópia por tela nova, ao custo de uma persona por
tela existente), não um afrouxamento das regras em si.

O único teste desta suíte que não era cópia — a presença do
`<fieldset>`/`<legend>` do grupo de áreas — não morava aqui: já existe,
independente de Playwright/axe, em
`apps/contas/tests/test_perfil_view.py::test_form_professor_tem_fieldset_e_legend_para_areas`,
e continua intocado.
"""
