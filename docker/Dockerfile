# syntax=docker/dockerfile:1.7
ARG PYTHON_VERSION=3.12

# ---------------------------------------------------------------- base
FROM python:${PYTHON_VERSION}-slim-bookworm AS base
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PATH="/opt/venv/bin:$PATH"
# GDAL pulls in GEOS and PROJ for GeoDjango; gettext for compilemessages; Pango, HarfBuzz
# and fonts for WeasyPrint (PDF reports).
RUN apt-get update \
 && apt-get install -y --no-install-recommends gdal-bin gettext curl ca-certificates \
    libpango-1.0-0 libpangoft2-1.0-0 libharfbuzz-subset0 fonts-dejavu-core \
 && rm -rf /var/lib/apt/lists/*
COPY --from=ghcr.io/astral-sh/uv:0.8.0 /uv /usr/local/bin/uv
WORKDIR /app

# ---------------------------------------------------------------- tailwind CLI
FROM base AS tailwind
ARG TAILWIND_VERSION=v4.1.13
ARG TARGETARCH
RUN arch=$([ "$TARGETARCH" = "arm64" ] && echo arm64 || echo x64) \
 && curl -sSfL -o /usr/local/bin/tailwindcss \
    "https://github.com/tailwindlabs/tailwindcss/releases/download/${TAILWIND_VERSION}/tailwindcss-linux-${arch}" \
 && chmod +x /usr/local/bin/tailwindcss

# ---------------------------------------------------------------- dev
FROM tailwind AS dev
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv uv sync --frozen --group dev
COPY docker/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh
ENTRYPOINT ["/entrypoint.sh"]
CMD ["python", "manage.py", "runserver", "0.0.0.0:8000"]

# ---------------------------------------------------------------- prod
FROM tailwind AS assets
COPY assets ./assets
COPY static ./static
COPY templates ./templates
COPY apps ./apps
RUN tailwindcss -i assets/tailwind.css -o static/css/app.css --minify

FROM base AS prod
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv uv sync --frozen --no-dev
COPY . .
COPY --from=assets /app/static/css/app.css static/css/app.css
RUN DJANGO_SECRET_KEY=build DATABASE_URL=postgis://x:x@localhost/x \
    DJANGO_SETTINGS_MODULE=config.settings.prod \
    sh -c "python manage.py compilemessages && python manage.py collectstatic --noinput"
COPY docker/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh && useradd --create-home app && chown -R app /app
USER app
ENTRYPOINT ["/entrypoint.sh"]
CMD ["gunicorn", "config.wsgi:application", "--bind", "0.0.0.0:8000", "--workers", "3"]
