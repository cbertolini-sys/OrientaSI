FROM node:22-alpine AS css
WORKDIR /build
COPY package.json package-lock.json ./
# npm ci (nao npm install) trava a build na versao exata do lockfile: sem isto,
# a build de producao poderia resolver um patch do daisyUI diferente do que
# roda em dev, so porque o lockfile nao era copiado para o contexto do build.
RUN npm ci
COPY static/css/entrada.css ./static/css/entrada.css
COPY templates ./templates
COPY apps ./apps
RUN npx tailwindcss -i static/css/entrada.css -o static/css/orientasi.css --minify

FROM python:3.12-slim AS base
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
# WeasyPrint renderiza via Pango e Cairo: sem estas bibliotecas ele falha já na
# importação, e a falha só apareceria no Bloco E (spec §8.2).
RUN apt-get update && apt-get install -y --no-install-recommends \
      libpango-1.0-0 libpangoft2-1.0-0 libharfbuzz0b libcairo2 \
      libgdk-pixbuf-2.0-0 libjpeg62-turbo zlib1g curl \
 && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .

FROM base AS dev
COPY requirements-dev.txt .
RUN pip install --no-cache-dir -r requirements-dev.txt \
 && playwright install --with-deps chromium
CMD ["python", "manage.py", "runserver", "0.0.0.0:8000"]

FROM base AS prod
ENV AMBIENTE=producao
COPY --from=css /build/static/css/orientasi.css /app/static/css/orientasi.css
# entrada.css e a fonte do Tailwind, nao um arquivo a servir: seu "@import
# tailwindcss" nao e um caminho relativo real, e o pos-processador do
# WhiteNoise quebra tentando resolve-lo como se fosse um recurso. --ignore
# resolve na causa (o collectstatic nunca tenta coletar o arquivo), em vez de
# depender de removê-lo manualmente antes de cada invocação futura.
RUN AMBIENTE=producao SECRET_KEY=apenas-para-o-build ALLOWED_HOSTS=build \
    python manage.py collectstatic --noinput --ignore=entrada.css
CMD ["gunicorn", "config.wsgi:application", "--bind", "0.0.0.0:8000", "--workers", "3"]
