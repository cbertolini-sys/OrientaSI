import secrets

from django.core.management.base import BaseCommand, CommandError
from django.db import IntegrityError, transaction

from apps.contas.models import Usuario


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
            # outra conta (o e-mail duplicado o get_or_create já resolve sem
            # tocar o banco duas vezes; CPF só o banco garante, via
            # unique=True em models.py). Comando operacional, rodado por
            # quem instala o sistema: um CommandError vira uma mensagem
            # limpa no terminal, sem stack trace — um IntegrityError cru não
            # diria a ela o que fazer a seguir.
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
        coordenadora, criada = Usuario.objects.get_or_create(
            email=opcoes["email_coordenador"],
            defaults={
                "nome_completo": opcoes["nome_coordenador"],
                "cpf": opcoes["cpf_coordenador"],
                "papel": Usuario.PROFESSOR,
                "password": "",
            },
        )
        if criada:
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
        # comando de bootstrap. Também não checamos `LIMITE_COORDENADORES`
        # (services.py): este comando promove no máximo uma conta, a indicada
        # em --email-coordenador, numa instalação nova com zero
        # coordenadores — não há como esbarrar no teto de 4 promovendo uma
        # única pessoa.
        if not coordenadora.is_coordenador:
            coordenadora.is_coordenador = True
            coordenadora.is_staff = True
            coordenadora.save(update_fields=["is_coordenador", "is_staff"])
            self.stdout.write(self.style.SUCCESS(f"{coordenadora.email} agora é coordenador(a)."))
        else:
            self.stdout.write(f"{coordenadora.email} já era coordenador(a).")
