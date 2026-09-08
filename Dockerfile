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
RUN AMBIENTE=producao SECRET_KEY=apenas-para-o-build ALLOWED_HOSTS=build \
    python manage.py collectstatic --noinput
CMD ["gunicorn", "config.wsgi:application", "--bind", "0.0.0.0:8000", "--workers", "3"]
