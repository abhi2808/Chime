# Chime API. Build from the repo root: docker build -f backend/Dockerfile .
FROM python:3.12-slim

COPY --from=ghcr.io/astral-sh/uv:0.11 /uv /bin/uv

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    PYTHONUNBUFFERED=1

# The app resolves relative paths against the folder above backend/, so /app is the
# "repo root" inside the image: DATABASE_URL=sqlite:///data/chime.db lands in /app/data.
WORKDIR /app/backend

# Dependencies first, so a code change does not reinstall them. psycopg comes along so the
# compose "postgres" profile works without a rebuild.
COPY backend/pyproject.toml backend/uv.lock ./
RUN uv sync --frozen --no-dev --extra postgres --no-install-project

COPY backend/ ./

# data/ is a volume and would hide a tag map copied there, so it lives beside it instead.
COPY data/tag_map.yaml /app/config/tag_map.yaml

ENV PATH="/app/backend/.venv/bin:$PATH" \
    TAG_MAP_PATH=/app/config/tag_map.yaml

RUN useradd --system --uid 10001 chime \
    && mkdir -p /app/data \
    && chown chime /app/data
USER chime

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=4)"

# One worker, always: the live loop runs in-process, and two workers would be two pollers
# fighting over the same session (see ENABLE_SCHEDULER). Migrations run before it serves.
# --proxy-headers so redirects and secure cookies see the https Caddy terminated.
CMD ["sh", "-c", "alembic upgrade head && exec uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 1 --proxy-headers --forwarded-allow-ips='*'"]
