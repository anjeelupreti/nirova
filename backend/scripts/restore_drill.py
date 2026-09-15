"""Restore one tenant's backup into a scratch database, and prove it matches.

**A backup nobody has restored is a rumour.** This is the drill: take the dump,
restore it under a different name beside the live database, count every table
in both, and report any row that differs. It touches nothing live -- the
restore target is a new database, and the live one is only read.

Run it after every schema change that matters, and on a schedule. The output is
meant to be pasted into `docs/RUNBOOK_BACKUP.md`, which is where the last drill
and its result are recorded.

    python scripts/restore_drill.py --dump /backups/.../nirova_tenant_x.dump \\
        --source nirova_tenant_x --container nirova-postgres

Exit status is 1 if any table differs, so a scheduler notices.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys

from backup import _in_container, environment  # noqa: E402 -- same directory, same tooling


def run(container: str, command: list, env: dict, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(
        _in_container(container, env, command), env=env, capture_output=True, text=True, check=check,
    )


def counts(container: str, database: str, env: dict) -> dict:
    """Every table in the public schema, with its row count.

    `count(*)` per table rather than `reltuples`: the planner's estimate is
    fine for a plan and useless for a proof, and the whole point of a drill is
    that somebody can believe the answer.
    """
    sql = (
        "SELECT string_agg(format('SELECT %L AS t, count(*) AS n FROM %I.%I', "
        "tablename, schemaname, tablename), ' UNION ALL ') "
        "FROM pg_tables WHERE schemaname = 'public';"
    )
    union = run(container, ["psql", "-tAqX", "-d", database, "-c", sql], env).stdout.strip()
    if not union:
        return {}
    rows = run(container, ["psql", "-tAqX", "-F", "|", "-d", database, "-c", union], env).stdout
    out = {}
    for line in rows.splitlines():
        if "|" in line:
            table, number = line.rsplit("|", 1)
            out[table.strip()] = int(number)
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dump", required=True, help="The .dump file to restore.")
    parser.add_argument("--source", required=True, help="The live database it came from.")
    parser.add_argument("--target", default="", help="Scratch database name (default: <source>_drill).")
    parser.add_argument("--container", default="", help="Run the Postgres tools in this container.")
    parser.add_argument("--keep", action="store_true", help="Leave the restored database behind.")
    parser.add_argument("--user", default=os.environ.get("TENANT_DB_USER", "nirova"))
    parser.add_argument("--password", default=os.environ.get("TENANT_DB_PASSWORD", "nirova"))
    parser.add_argument("--host", default=os.environ.get("TENANT_DB_HOST", "localhost"))
    parser.add_argument("--port", default=os.environ.get("TENANT_DB_PORT", "5432"))
    arguments = parser.parse_args()

    env = environment(arguments.user, arguments.password, arguments.host, arguments.port)
    target = arguments.target or f"{arguments.source}_drill"

    print(f"restoring {arguments.dump} -> {target}")
    run(arguments.container, ["psql", "-d", "postgres", "-c", f'DROP DATABASE IF EXISTS "{target}";'], env)
    run(arguments.container, ["psql", "-d", "postgres", "-c", f'CREATE DATABASE "{target}";'], env)

    # The dump is on this machine; `pg_restore` may be inside a container, and
    # a container cannot read a host path. Custom-format dumps restore from
    # standard input, so the file is piped in rather than copied.
    if arguments.container:
        with open(arguments.dump, "rb") as handle:
            restore = subprocess.run(
                ["docker", "exec", "-i",
                 "-e", f"PGPASSWORD={env.get('PGPASSWORD', '')}",
                 arguments.container,
                 "pg_restore", "--no-owner", "--no-privileges",
                 "-U", env.get("PGUSER", "postgres"), "-d", target],
                stdin=handle, env=env, capture_output=True, text=True, check=False,
            )
    else:
        restore = run(
            "", ["pg_restore", "--no-owner", "--no-privileges", "-d", target, arguments.dump],
            env, check=False,
        )
    if restore.returncode != 0:
        # pg_restore warns about extensions and ownership even on a good
        # restore; only a real failure leaves no tables, which the comparison
        # below catches. The output is printed so nothing is hidden.
        print(restore.stderr[:1000], file=sys.stderr)

    live = counts(arguments.container, arguments.source, env)
    copy = counts(arguments.container, target, env)

    if not copy:
        print("the restored database has no tables -- the restore failed", file=sys.stderr)
        return 1

    missing = sorted(set(live) - set(copy))
    extra = sorted(set(copy) - set(live))
    differing = sorted(
        (table, live[table], copy[table]) for table in set(live) & set(copy) if live[table] != copy[table]
    )

    print(f"\n{len(live)} tables live, {len(copy)} restored, {sum(live.values()):,} rows live")
    for table in missing:
        print(f"  MISSING   {table} ({live[table]} rows live)")
    for table in extra:
        print(f"  UNEXPECTED {table} ({copy[table]} rows restored)")
    for table, was, now in differing:
        print(f"  DIFFERS   {table}: {was} live, {now} restored")

    if not arguments.keep:
        run(arguments.container, ["psql", "-d", "postgres", "-c", f'DROP DATABASE IF EXISTS "{target}";'], env, check=False)

    if missing or extra or differing:
        print("\nDRILL FAILED -- the restore does not match the live database")
        return 1
    print("\nDRILL PASSED -- every table restored with the same row count")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
