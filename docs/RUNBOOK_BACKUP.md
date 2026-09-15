# Runbook: backup, restore, and the drill

*Written 15 September 2026, with the first restore drill recorded at the
bottom. [HEALTHOS.md](HEALTHOS.md) called an unproven restore the single
largest operational risk in this product, and it was: the backups were a
plan, and nobody had ever put one back.*

**The promise this runbook keeps.** One customer's data is one database
(ADR 0001). So one customer can be backed up, restored, exported or deleted
**without touching anybody else**, and a mistake in one hospital's data is
never repaired by rolling back another's.

---

## 1. What is backed up

| | Database | Holds | If it is lost |
|---|---|---|---|
| Control plane | `nirova_control` | Organizations, users, memberships, plans, subscriptions, usage | Nobody can sign in anywhere; tenant data survives but is unreachable |
| Per customer | `nirova_tenant_<slug>` | Everything clinical, financial and operational for that customer | That hospital's record is gone |

Also needed to bring a system back, and **not** covered by these scripts:
uploaded documents (object storage), the `.env` secrets, and the TLS
certificates. Back those up where they live; note the location here when the
first production host exists.

## 2. Taking a backup

```bash
# On the database host, or with the Postgres tools on PATH:
python backend/scripts/backup.py --out /backups/nirova

# Against the development stack, where Postgres is in a container:
python backend/scripts/backup.py --out /backups/nirova --container nirova-postgres
```

Each run writes `/backups/nirova/<UTC timestamp>/` containing one
`<database>.dump` per database (`pg_dump -Fc`) and a `manifest.json` with the
size and SHA-256 of each. Drill scratch databases (`*_drill`) are excluded —
the first run dumped one, 907 bytes of nothing, filed as though it were a
customer.

**Schedule.** Nightly, before midnight, plus before every deployment that runs
a migration. **Retention:** 7 daily, 5 weekly, 12 monthly. **Off-site:** copy
each night's folder to a second location; a backup on the same host is a
backup of the same fire.

## 3. Restoring one customer

```bash
# 1. Stop traffic for that customer (take the tenant out of the load balancer,
#    or set its subscription to suspended so the middleware refuses).
# 2. Restore beside the live database first, never over it:
createdb nirova_tenant_<slug>_restored
pg_restore --no-owner --no-privileges -d nirova_tenant_<slug>_restored <dump>

# 3. Check it (counts, and the figures somebody printed yesterday):
python backend/scripts/restore_drill.py \
    --dump <dump> --source nirova_tenant_<slug> --keep

# 4. Swap, keeping the old one until somebody has used the system:
psql -d postgres -c 'ALTER DATABASE "nirova_tenant_<slug>" RENAME TO "nirova_tenant_<slug>_broken";'
psql -d postgres -c 'ALTER DATABASE "nirova_tenant_<slug>_restored" RENAME TO "nirova_tenant_<slug>";'
```

**Never restore over a live database.** A restore into the live name is
irreversible the moment it starts; a restore beside it costs a rename.

## 4. The drill

```bash
python backend/scripts/restore_drill.py \
    --dump /backups/nirova/<timestamp>/nirova_tenant_<slug>.dump \
    --source nirova_tenant_<slug> --container nirova-postgres
```

It restores into `<source>_drill`, counts **every table in both databases**
with `count(*)` — not the planner's estimate, because a drill has to be
believable — reports any table that is missing, unexpected or different, drops
the scratch database, and exits non-zero on any difference.

**Run it monthly, and after any migration that rewrites data.** A green drill
is the only evidence that the backups are real.

## 5. Drill record

| Date | Database | Tables | Rows | Result | Notes |
|---|---|---|---|---|---|
| 2026-09-15 | `nirova_tenant_manakamana` (dev) | 180 | 7,779 | **PASSED** | First drill ever run. Found: the backup was including `_drill` scratch databases; `docker exec` needed the user and password passed in explicitly. |

Add a row every time. An empty table below this line means the promise in
section 1 is again only a plan.

## 6. What is still missing

- **Point-in-time recovery.** These are nightly snapshots; losing the host at
  16:00 loses the day. WAL archiving is the fix and is not set up.
- **An off-site copy**, and a restore drill *from* the off-site copy.
- **Uploaded documents and secrets**, as noted in section 1.
- **A customer-facing export** ("give us everything, we are leaving"), which is
  a different job from a backup and is on the Phase B list.
