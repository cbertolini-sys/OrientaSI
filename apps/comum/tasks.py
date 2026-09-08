from celery import shared_task


@shared_task
def somar(a, b):
    """Tarefa de fumaça: prova que o worker está processando a fila."""
    return a + b
