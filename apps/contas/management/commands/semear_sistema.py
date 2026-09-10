import secrets

from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError
from django.db import IntegrityError, transaction

from apps.contas.models import Usuario
from apps.contas.validators import valida_cpf


class Command(BaseCommand):
    help = (
        "Cria a conta única da SUGRAD e o primeiro coordenador do sistema. "
        "Resolve o ovo-e-galinha: só a coordenação envia convites, mas alguém "
        "precisa ser a primeira. Roda uma única vez, numa instalação nova, "
        "antes de qualquer convite. É idempotente: rodar de novo com os "
        "mesmos argumentos não duplica nada nem rebaixa quem já é "
        "coordenador(a) por outro caminho."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--email-coordenador",
            required=True,
            help="E-mail do primeiro coordenador (login).",
        )
        parser.add_argument(
            "--nome-coordenador",
            required=True,
            help="Nome completo do primeiro coordenador.",
        )
        parser.add_argument(
            "--cpf-coordenador",
            required=True,
            help="CPF do primeiro coordenador, 11 dígitos, sem pontuação.",
        )
        parser.add_argument(
            "--email-sugrad",
            required=True,
            help="E-mail da conta única da SUGRAD (login).",
        )

    def handle(self, *args, **opcoes):
        try:
            self._semear(opcoes)
        except IntegrityError as erro:
            # O caso mais provável na prática: o CPF informado já pertence a
            # outra conta (e-mail duplicado não chega mais aqui — a busca do
            # coordenador é __iexact, ver `_semear_coordenador`; CPF só o
            # banco garante, via unique=True em models.py). Comando
            # operacional, rodado por quem instala o sistema: um
            # CommandError vira uma mensagem limpa no terminal, sem stack
            # trace — um IntegrityError cru não diria a ela o que fazer a
            # seguir.
            raise CommandError(
                "Não foi possível semear o sistema: o CPF informado para o "
                "coordenador provavelmente já pertence a outra conta."
            ) from erro

    @transaction.atomic
    def _semear(self, opcoes):
        self._semear_sugrad(opcoes)
        self._semear_coordenador(opcoes)

    def _semear_sugrad(self, opcoes):
        # A chave de busca é o PAPEL, não o e-mail: a constraint
        # `conta_sugrad_unica` (models.py) também trava por papel — só pode
        # existir uma conta SUGRAD no sistema, qualquer que seja o e-mail.
        # Buscar por papel é o que torna rodar o comando de novo, mesmo com
        # um --email-sugrad diferente, um no-op sobre a conta já semeada, em
        # vez de uma tentativa de criar uma segunda que o banco recusaria.
        sugrad, criada = Usuario.objects.get_or_create(
            papel=Usuario.SUGRAD,
            defaults={
                "email": opcoes["email_sugrad"],
                "nome_completo": "SUGRAD",
                # Deliberado, não um esquecimento: SUGRAD é um setor, não uma
                # pessoa. A constraint `cpf_obrigatorio_para_pessoas`
                # (models.py) abre exatamente esta exceção para papel=SUGRAD.
                "cpf": None,
                "password": "",
            },
        )
        if criada:
            senha = secrets.token_urlsafe(16)
            sugrad.set_password(senha)
            sugrad.save(update_fields=["password"])
            self.stdout.write(self.style.SUCCESS(f"Conta SUGRAD criada: {sugrad.email}"))
            self.stdout.write(f"Senha inicial da SUGRAD: {senha}")
            self.stdout.write("Anote-a agora: ela não será exibida de novo.")
        else:
            self.stdout.write(f"Conta SUGRAD já existe: {sugrad.email}")

    def _semear_coordenador(self, opcoes):
        # `valida_cpf` está declarado em `Usuario.cpf.validators`, mas um
        # validator de model só roda em `full_clean()` — e nem
        # `Usuario.objects.create()` nem `GerenciadorUsuario._criar` chamam
        # `full_clean`. Resultado (achado da revisão final): o CPF nunca era
        # verificado por este comando, e o `README.md` mandava semear com
        # `--cpf-coordenador 00000000000`, que é uma das
        # `SEQUENCIAS_INVALIDAS` do próprio validator — o primeiro
        # coordenador do sistema nascia com CPF inválido, seguindo a
        # documentação. A validação é chamada explicitamente aqui, antes de
        # qualquer escrita, e a mensagem sai limpa no terminal.
        cpf = opcoes["cpf_coordenador"].strip()
        try:
            valida_cpf(cpf)
        except ValidationError as erro:
            raise CommandError(f"CPF do coordenador inválido: {erro.messages[0]}") from erro

        # E-mail é a chave natural de login: normalizamos e buscamos por
        # `__iexact`, como `services.convidar` e
        # `GerenciadorUsuario.get_by_natural_key` já fazem em todo o projeto
        # (achado da revisão 1). Um `get_or_create(email=opcoes[...])` sem
        # isto compara com sensibilidade a maiúsculas: rodar o comando de
        # novo com outra grafia da mesma conta ("Coord@ufsm.br" depois
        # "coord@ufsm.br") não encontraria a conta existente, tentaria criar
        # outra e colidiria no unique=True do banco — um IntegrityError que o
        # `except` em `handle()` relataria, errado, como CPF duplicado.
        email = opcoes["email_coordenador"].strip().lower()
        coordenadora = Usuario.objects.filter(email__iexact=email).first()
        ja_e_coordenador = coordenadora is not None and coordenadora.is_coordenador

        # Regra de negócio inegociável nº 2 (CLAUDE.md): no máximo 4
        # coordenadores, e quem nomeia coordenadores DEPOIS do primeiro é o
        # painel da coordenação (`services.promover_a_coordenador`, que
        # aplica `LIMITE_COORDENADORES`), não este comando. Sem esta guarda,
        # rodar `semear_sistema` de novo, num sistema já em uso, com um
        # --email-coordenador diferente, criava e promovia incondicionalmente
        # mais uma pessoa — um quinto coordenador não esbarraria em teto
        # nenhum, porque este comando nunca o consulta (achado da revisão 1:
        # o cenário é alcançável — troca de responsável, reinstalação
        # parcial, script de bootstrap reaproveitado — não teórico). O caso
        # idempotente segue liberado: só recusamos um alvo NOVO quando já
        # existe alguém coordenando; o próprio alvo, se já for coordenador,
        # nunca cai aqui.
        if not ja_e_coordenador and Usuario.objects.filter(is_coordenador=True).exists():
            raise CommandError(
                "O sistema já tem coordenador(a). semear_sistema cria apenas "
                "o primeiro, numa instalação nova; para nomear mais alguém, "
                "use o painel da coordenação."
            )

        criada = coordenadora is None
        if criada:
            coordenadora = Usuario.objects.create(
                email=email,
                nome_completo=opcoes["nome_coordenador"],
                cpf=cpf,
                papel=Usuario.PROFESSOR,
                password="",
            )
            senha = secrets.token_urlsafe(16)
            coordenadora.set_password(senha)
            coordenadora.save(update_fields=["password"])
            self.stdout.write(self.style.SUCCESS(f"Conta criada: {coordenadora.email}"))
            self.stdout.write(f"Senha inicial da coordenação: {senha}")
            self.stdout.write("Anote-a agora: ela não será exibida de novo.")

        if coordenadora.papel != Usuario.PROFESSOR:
            # A constraint `coordenador_e_professor` (models.py) recusaria o
            # save() logo abaixo com um IntegrityError opaco. Falhamos aqui,
            # cedo e com mensagem clara: o e-mail informado já pertence a uma
            # conta de outro papel (ALUNO, por exemplo) e essa conta não pode
            # virar coordenadora.
            raise CommandError(
                f"{coordenadora.email} já existe com papel "
                f"{coordenadora.get_papel_display()}; coordenador precisa ser PROFESSOR."
            )

        # Aqui, em qualquer outro lugar do sistema, chamaríamos
        # `services.promover_a_coordenador` — é a mesma operação que o painel
        # da coordenação usa. Não dá: aquela função exige um `por` que já
        # seja coordenador (`permissions.pode_promover`), e este comando
        # existe exatamente porque ainda não existe NENHUM coordenador — é o
        # ovo-e-galinha que a Tarefa 12 resolve. Por isso os campos são
        # atribuídos diretamente aqui, fora da camada de serviço, só neste
        # comando de bootstrap; a guarda acima é que garante que isto só
        # acontece para o primeiro coordenador do sistema.
        if not coordenadora.is_coordenador:
            coordenadora.is_coordenador = True
            coordenadora.is_staff = True
            coordenadora.save(update_fields=["is_coordenador", "is_staff"])
            self.stdout.write(self.style.SUCCESS(f"{coordenadora.email} agora é coordenador(a)."))
        else:
            self.stdout.write(f"{coordenadora.email} já era coordenador(a).")
