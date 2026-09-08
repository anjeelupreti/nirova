# syntax=docker/dockerfile:1.7
#
# The Nirova backend image.
#
# Two stages. The first builds a virtualenv; the second copies it into a clean
# runtime image. The split matters for two reasons: the build stage's pip
# cache, wheel downloads and any transient toolchain never reach the shipped
# image, and -- more usefully day to day -- the dependency layer is keyed only
# on `requirements.txt`, so editing Python source rebuilds in seconds instead
# of reinstalling Django.

# ---------------------------------------------------------------------------
# Stage 1: dependencies
# ---------------------------------------------------------------------------
FROM python:3.12-slim AS builder

# PYTHONDONTWRITEBYTECODE: .pyc files written at build time are dead weight in
# the layer; the runtime writes its own into a tmpfs-backed path anyway.
# PIP_DISABLE_PIP_VERSION_CHECK: one fewer network round trip per build.
ENV PYTHONDONTWRITEBYTECODE=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# A virtualenv rather than the system site-packages, so stage 2 can copy one
# self-contained directory and inherit nothing else from this stage.
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Copied alone, and before the source. This is the whole point of the ordering:
# the expensive layer below is invalidated only when the requirements change.
#
# Paths are prefixed with `backend/` because the build context is the
# repository root, shared with the web images so that they can reach
# infra/nginx/. The root .dockerignore keeps that context small.
COPY backend/requirements.txt .

# The cache mount keeps pip's downloaded wheels between builds *without*
# putting them in a layer. Every dependency here ships manylinux wheels
# (psycopg[binary] bundles libpq, argon2-cffi bundles its extension), so no
# compiler is installed and none is needed.
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install -r requirements.txt

# ---------------------------------------------------------------------------
# Stage 2: runtime
# ---------------------------------------------------------------------------
FROM python:3.12-slim AS runtime

# PYTHONUNBUFFERED: without it, container logs arrive in 8 KB blocks and a
# crash loses whatever was still in the buffer -- exactly the output you want.
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/opt/venv/bin:$PATH" \
    DJANGO_SETTINGS_MODULE=config.settings.prod

# `curl` is here for the container healthcheck and nothing else. Compose needs
# something *inside* the container that can prove the application answers, not
# merely that the process is alive.
RUN apt-get update \
    && apt-get install --no-install-recommends -y curl \
    && rm -rf /var/lib/apt/lists/*

# A non-root user. If the application is ever compromised it should not also
# own its own image; and the bind mounts in the development override then have
# a predictable owner rather than root-owned files appearing on the host.
RUN useradd --create-home --uid 10001 nirova

WORKDIR /app

COPY --from=builder /opt/venv /opt/venv
COPY --chown=nirova:nirova backend/ .

# `media/` is written at runtime and `staticfiles/` by collectstatic; both are
# created here so the first write does not fail on a read-only parent, and both
# are owned by the user that will write them.
RUN mkdir -p /app/media /app/staticfiles \
    && chown -R nirova:nirova /app/media /app/staticfiles \
    && chmod +x /app/docker-entrypoint.sh

USER nirova

EXPOSE 8000

ENTRYPOINT ["/app/docker-entrypoint.sh"]

# Three workers because the control plane and every tenant connection is
# blocking I/O against Postgres; threads let one worker keep serving while
# another waits. `--timeout 120` is generous on purpose: `bootstrap` aside,
# the reporting endpoints aggregate across a tenant and can be slow on a
# cold cache.
CMD ["gunicorn", "config.wsgi:application", \
     "--bind", "0.0.0.0:8000", \
     "--workers", "3", \
     "--threads", "4", \
     "--timeout", "120", \
     "--access-logfile", "-", \
     "--error-logfile", "-"]
