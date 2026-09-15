# Migração de dados (não de esquema): popula `Area` com a Tabela de Áreas
# do Conhecimento do CNPq/CAPES para Ciência da Computação — pedido
# explícito do usuário. `Area` é "vocabulário controlado... mantido pela
# coordenação" (spec §5.4, comentário do model em apps/contas/models.py),
# hoje só via /admin/ (não há tela própria de CRUD de área em nenhum bloco
# implementado) — uma migração de dados é o jeito certo de entregar essa
# lista pronta em QUALQUER ambiente que rodar `migrate` (dev, CI, produção),
# em vez de um script avulso que só existiria na memória de quem o rodasse
# uma vez.
#
# Terminologia (corrigida a pedido do usuário — a primeira versão desta
# migração invertia os nomes): a tabela oficial tem 4 ÁREAS, cada uma com
# uma ou mais SUBÁREAS (16 ao todo). Reaproveita `area` (self-FK) e `ordem`,
# acrescentados ao model na migração anterior (0006) especificamente para
# isto — as 4 ÁREAS entram como `Area` próprias (`area=None`), cada
# SUBÁREA aponta pra sua área via `area`, e `ordem` fixa a sequência 1..20
# exatamente como listada (área, depois suas subáreas, depois a próxima
# área) — o usuário pediu a ordem exata da lista original, não ordem
# alfabética.
#
# Contagem: a lista trazida pelo usuário soma 16 subáreas (4 + 2 + 6 + 4),
# não 15 como o texto dele mencionava de passagem — mantidas as 16
# exatamente como listadas (nenhuma foi descartada pra bater com o número
# "15"; é mais seguro entregar tudo que foi pedido de verdade e avisar da
# diferença do que adivinhar qual cortar).
from django.db import migrations

# Cada item: (nome da área, [subáreas, na ordem da lista]).
TAXONOMIA = [
    (
        "Teoria da Computação",
        [
            "Computabilidade e Modelos de Computação",
            "Linguagens Formais e Autômatos",
            "Análise de Algoritmos e Complexidade de Computação",
            "Lógicas e Semântica de Programas",
        ],
    ),
    (
        "Matemática da Computação",
        [
            "Matemática Simbólica",
            "Modelos Analíticos e de Simulação",
        ],
    ),
    (
        "Metodologia e Técnicas da Computação",
        [
            "Linguagens de Programação",
            "Engenharia de Software",
            "Banco de Dados",
            "Sistemas de Informação",
            "Processamento Gráfico",
            "Inteligência Artificial",
        ],
    ),
    (
        "Sistemas de Computação",
        [
            "Hardware",
            "Arquitetura de Sistemas de Computação",
            "Software Básico",
            "Teleinformática",
        ],
    ),
]


def popula_areas(apps, schema_editor):
    Area = apps.get_model("contas", "Area")
    ordem = 1
    for nome_area, subareas in TAXONOMIA:
        area, _ = Area.objects.get_or_create(
            nome=nome_area,
            defaults={
                "descricao": "Área de Ciência da Computação — Tabela de Áreas do "
                "Conhecimento CNPq/CAPES.",
                "ordem": ordem,
            },
        )
        if area.ordem != ordem:
            area.ordem = ordem
            area.save(update_fields=["ordem"])
        ordem += 1

        for nome_subarea in subareas:
            subarea, _ = Area.objects.get_or_create(
                nome=nome_subarea,
                defaults={
                    "descricao": f"Subárea de {nome_area} — Tabela de Áreas do "
                    "Conhecimento CNPq/CAPES.",
                    "area": area,
                    "ordem": ordem,
                },
            )
            if subarea.area_id != area.id or subarea.ordem != ordem:
                subarea.area = area
                subarea.ordem = ordem
                subarea.save(update_fields=["area", "ordem"])
            ordem += 1


def remove_areas(apps, schema_editor):
    # Reversão só das áreas desta migração — não apaga a tabela inteira, pra
    # não levar junto uma área que a coordenação tenha criado por fora
    # (`/admin/`) com um nome igual por coincidência é o único risco
    # residual, aceitável: nenhum destes 20 nomes é genérico o bastante pra
    # colidir por acaso.
    Area = apps.get_model("contas", "Area")
    nomes = []
    for nome_area, subareas in TAXONOMIA:
        nomes.append(nome_area)
        nomes.extend(subareas)
    Area.objects.filter(nome__in=nomes).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("contas", "0006_alter_area_options_area_area_area_ordem"),
    ]

    operations = [
        migrations.RunPython(popula_areas, remove_areas),
    ]
