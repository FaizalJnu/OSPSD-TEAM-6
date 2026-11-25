# syntax=docker/dockerfile:1

# The storage service (HW1/HW2). Build from the repository root:
#   docker build -t storage .

FROM python:3.13-slim AS build
COPY --from=ghcr.io/astral-sh/uv:0.13.10 /uv /usr/local/bin/uv
RUN apt-get update \
 && apt-get install -y --no-install-recommends git \
 && rm -rf /var/lib/apt/lists/*

# Install into a fixed path with no links back to /src, so the final stage can copy
# the virtualenv alone and leave the source and build tools behind.
ENV UV_PROJECT_ENVIRONMENT=/opt/venv \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never
WORKDIR /src
COPY . .
RUN uv sync --locked --no-editable --no-dev --extra server

FROM python:3.13-slim
RUN useradd --system --uid 10001 --no-create-home app
COPY --from=build /opt/venv /opt/venv
ENV PATH=/opt/venv/bin:$PATH \
    PYTHONUNBUFFERED=1
USER app
EXPOSE 8000

# Liveness only: /health makes no provider call, so a provider outage never marks
# the container unhealthy. Traefik stops routing to a container that is unhealthy.
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=3)"]

CMD ["uvicorn", "storage_service.main:create_app", "--factory", \
     "--host", "0.0.0.0", "--port", "8000", \
     "--proxy-headers", "--forwarded-allow-ips=*"]
