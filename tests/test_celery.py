from apps.comum.tasks import somar


def test_tarefa_executa_em_modo_sincrono(settings):
    settings.CELERY_TASK_ALWAYS_EAGER = True
    assert somar.delay(2, 3).get() == 5


def test_app_celery_descobre_as_tarefas_das_apps():
    from config.celery import app

    assert "apps.comum.tasks.somar" in app.tasks
