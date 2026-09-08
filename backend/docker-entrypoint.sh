#!/bin/sh
#
# What every backend container does before it becomes whatever it was asked to
# be. Runs for the API, the Celery worker and the beat scheduler alike, which
# is why the expensive parts are opt-in by environment variable rather than
# unconditional: three containers starting at once must not all try to seed the
# same database.
#
# `set -e` so a failed migration stops the container instead of producing a
# server that answers 500 to everything. A container that refuses to start is
# a legible failure; one that starts broken is not.
set -e

# ---------------------------------------------------------------------------
# Wait for the database
# ---------------------------------------------------------------------------
# Compose already gates us on `pg_isready` via `depends_on: service_healthy`,
# so in the normal path this returns on the first attempt. It is here for
# `docker run` without compose, and for the window where Postgres accepts
# connections during its own first-boot initialisation and then restarts.
if [ "${NIROVA_WAIT_FOR_DB:-60}" != "0" ]; then
    python manage.py bootstrap --wait-only \
        --wait-for-db "${NIROVA_WAIT_FOR_DB:-60}"
fi

# ---------------------------------------------------------------------------
# Migrate and seed
# ---------------------------------------------------------------------------
# Exactly one container in the stack sets NIROVA_BOOTSTRAP. The worker and the
# scheduler wait for it by depending on the API's healthcheck, so they never
# race it.
#
#   full    -- migrate, catalogue, demo tenant, and every demo seed
#   schema  -- migrate and the plan catalogue only; no demo data
#   (unset) -- nothing; assume somebody else has done it
#
# `--if-needed` still migrates and seeds the catalogue every time, because
# both are seconds when there is nothing to do and skipping them means a
# container that came up one migration behind and failed somewhere much
# less obvious. What it skips is the twenty-two demo seeds, and it decides
# by asking whether a populated demo tenant exists rather than by trusting
# a marker file that can outlive the database it describes.
case "${NIROVA_BOOTSTRAP:-}" in
    full)
        python manage.py bootstrap --if-needed --wait-for-db 60
        ;;
    schema)
        python manage.py bootstrap --if-needed --no-demo --wait-for-db 60
        ;;
esac

# ---------------------------------------------------------------------------
# Static files
# ---------------------------------------------------------------------------
# Only the Django admin and DRF's browsable API need these; the two React
# applications are built and served by their own containers. Skipped unless
# asked, because collectstatic on every start of every container is pure wait.
if [ "${NIROVA_COLLECTSTATIC:-}" = "1" ]; then
    python manage.py collectstatic --noinput --verbosity 0
fi

# `exec` so the real process becomes PID 1 and receives SIGTERM directly.
# Without it, this shell is PID 1, does not forward signals, and every
# `docker compose down` waits the full ten seconds before killing gunicorn.
exec "$@"
