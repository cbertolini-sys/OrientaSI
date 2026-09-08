"""
Configuração ASGI do projeto config.

Expõe a chamada ASGI como uma variável no nível do módulo chamada ``application``.

Para mais informações sobre este arquivo, veja
https://docs.djangoproject.com/en/5.1/howto/deployment/asgi/
"""

import os

from django.core.asgi import get_asgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

application = get_asgi_application()
