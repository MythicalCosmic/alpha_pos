FROM python:3.14-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
        libpq5 \
        curl \
    && rm -rf /var/lib/apt/lists/*

# Build deps in a separate layer so the wheel cache is reused across rebuilds,
# then drop them so the final image stays small.
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
        libpq-dev \
    && pip install --no-cache-dir gunicorn \
    && true

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt \
    && apt-get purge -y --auto-remove build-essential libpq-dev \
    && rm -rf /var/lib/apt/lists/*

COPY . .

RUN python manage.py collectstatic --noinput 2>/dev/null || true

# Run as a non-root user; createUser ahead of chown so the container can
# write to the working directory but not poke at root-owned files.
RUN groupadd --system app && useradd --system --gid app --home /app --shell /usr/sbin/nologin app \
    && chown -R app:app /app

COPY --chown=app:app entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

USER app

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD curl --fail --silent http://127.0.0.1:8000/healthz || exit 1

ENTRYPOINT ["/entrypoint.sh"]
