"""Back up the control plane and every tenant database.

**Deliberately not a Django management command.** The day this matters is the
day Django does not start: a bad migration, a corrupted settings file, a host
that has lost the application but still has the database. A backup tool that
needs the application to run is a backup tool that is missing when it is
needed. This is plain Python and `pg_dump`.

**One file per database, custom format.** `pg_dump -Fc` restores selectively
and in parallel, and -- the reason that matters here -- a single tenant can be
restored without touching anybody else's data. That is the whole promise of a
database per customer, and it is only true if the backups are per customer
too.

**Every dump is checksummed and listed in a manifest.** A backup nobody can
verify is a hope. The manifest records what was dumped, when, how large it
was, and its SHA-256, so a restore can say "this is the file that was taken at
23:00 and it has not changed since".

Usage:

    python scripts/backup.py --out /backups/nirova            # host
    python scripts/backup.py --out /backups --container nirova-postgres

`--container` runs the Postgres tools inside a Docker container, which is how
the development stack is arranged; without it they must be on PATH.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import pathlib
import subprocess
import sys

CONTROL_DATABASE = "nirova_control"
TENANT_PREFIX = "nirova_tenant_"


def _in_container(container: str, env: dict, command: list) -> list:
    """`docker exec` starts as root and inherits nothing.

    Both are worth stating: the Postgres tools inside the image would connect
    as `root`, which is not a role, and the PG* variables set for this process
    do not cross into the container. The user and password are passed in
    explicitly rather than assumed.
    """
    if not container:
        return command
    return [
        "docker", "exec",
        "-e", f"PGPASSWORD={env.get('PGPASSWORD', '')}",
        container, *command, "-U", env.get("PGUSER", "postgres"),
    ]


def _psql_command(container: str, database: str, sql: str, env: dict) -> list:
    return _in_container(container, env, ["psql", "-tAqX", "-d", database, "-c", sql])


def _dump_command(container: str, database: str, env: dict) -> list:
    return _in_container(container, env, ["pg_dump", "-Fc", "--no-owner", "--no-privileges", "-d", database])


def environment(user: str, password: str, host: str, port: str) -> dict:
    env = dict(os.environ)
    env.setdefault("PGUSER", user)
    env.setdefault("PGPASSWORD", password)
    env.setdefault("PGHOST", host)
    env.setdefault("PGPORT", port)
    return env


def databases(container: str, env: dict) -> list:
    """The control plane and every tenant database, from the server itself.

    Asked of Postgres rather than of the control plane's `organization` table:
    a tenant whose row was deleted by accident still has a database, and that
    database is exactly the one somebody will need back.
    """
    # `_drill` is excluded: a restore drill leaves a scratch copy of a tenant
    # beside it, and the first run of this script dumped one -- 907 bytes of
    # nothing, filed as though it were a customer. A backup set that contains
    # its own test artefacts is one somebody restores by mistake.
    sql = (
        "SELECT datname FROM pg_database "
        f"WHERE datistemplate = false AND datname NOT LIKE '%\_drill' "
        f"AND (datname = '{CONTROL_DATABASE}' "
        f"OR datname LIKE '{TENANT_PREFIX}%') ORDER BY datname;"
    )
    out = subprocess.run(
        _psql_command(container, CONTROL_DATABASE, sql, env),
        env=env, capture_output=True, text=True, check=True,
    )
    return [line.strip() for line in out.stdout.splitlines() if line.strip()]


def take(database: str, destination: pathlib.Path, container: str, env: dict) -> dict:
    destination.parent.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256()
    size = 0
    with destination.open("wb") as handle:
        process = subprocess.Popen(
            _dump_command(container, database, env), stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env,
        )
        assert process.stdout is not None
        for chunk in iter(lambda: process.stdout.read(1024 * 256), b""):
            handle.write(chunk)
            digest.update(chunk)
            size += len(chunk)
        _, errors = process.communicate()
    if process.returncode != 0:
        destination.unlink(missing_ok=True)
        raise RuntimeError(f"pg_dump {database} failed: {errors.decode(errors='replace')[:400]}")
    if size == 0:
        destination.unlink(missing_ok=True)
        raise RuntimeError(f"pg_dump {database} produced an empty file")
    return {"database": database, "file": destination.name, "bytes": size, "sha256": digest.hexdigest()}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", required=True, help="Directory to write the backup into.")
    parser.add_argument("--container", default="", help="Run pg_dump inside this Docker container.")
    parser.add_argument("--user", default=os.environ.get("TENANT_DB_USER", "nirova"))
    parser.add_argument("--password", default=os.environ.get("TENANT_DB_PASSWORD", "nirova"))
    parser.add_argument("--host", default=os.environ.get("TENANT_DB_HOST", "localhost"))
    parser.add_argument("--port", default=os.environ.get("TENANT_DB_PORT", "5432"))
    parser.add_argument("--only", default="", help="One database name, for a drill.")
    arguments = parser.parse_args()

    env = environment(arguments.user, arguments.password, arguments.host, arguments.port)
    taken_at = dt.datetime.now(dt.timezone.utc)
    folder = pathlib.Path(arguments.out) / taken_at.strftime("%Y%m%dT%H%M%SZ")

    names = [arguments.only] if arguments.only else databases(arguments.container, env)
    if not names:
        print("no databases found -- refusing to write an empty backup", file=sys.stderr)
        return 2

    entries = []
    for name in names:
        entry = take(name, folder / f"{name}.dump", arguments.container, env)
        entries.append(entry)
        print(f"  {name:<32} {entry['bytes']:>12,} bytes  {entry['sha256'][:12]}")

    manifest = {
        "taken_at": taken_at.isoformat(),
        "host": arguments.host,
        "container": arguments.container or None,
        "databases": entries,
        "total_bytes": sum(entry["bytes"] for entry in entries),
    }
    (folder / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(f"\n{len(entries)} database(s), {manifest['total_bytes']:,} bytes -> {folder}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
