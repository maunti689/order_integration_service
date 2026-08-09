FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /service

RUN groupadd --system app && useradd --system --gid app --create-home app

COPY pyproject.toml README.md ./
COPY app ./app
COPY provider_mock ./provider_mock
COPY migrations ./migrations
COPY alembic.ini ./
COPY scripts ./scripts
COPY docker ./docker

RUN pip install --upgrade pip && pip install . && chmod +x docker/entrypoint.sh

USER app

EXPOSE 8000
ENTRYPOINT ["./docker/entrypoint.sh"]
CMD ["api"]
