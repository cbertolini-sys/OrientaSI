"""
Configuração WSGI do projeto config.

Expõe a chamada WSGI como uma variável no nível do módulo chamada ``application``.

Para mais informações sobre este arquivo, veja
https://docs.djangoproject.com/en/5.1/howto/deployment/wsgi/
"""

import os

from django.core.wsgi import get_wsgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

application = get_wsgi_application()
