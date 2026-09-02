# ADR 0001 — One database per tenant

**Status.** Accepted · 2026-09-02
**Supersedes.** Nothing
**Related.** [ADR 0002 — Where identity lives](0002-identity-placement.md)

## Context

The platform is a multi-tenant healthcare operating system. A tenant is a
healthcare *organization* — a customer. Inside one tenant sit facilities
(hospitals, clinics, pharmacies, laboratories, warehouses), their staff, and
their patients' medical records.

Three properties matter more here than in an ordinary SaaS product:

1. **The data is medical.** A cross-tenant leak is not an embarrassment; it is
   a disclosure of identifiable health information belonging to people who
   never chose this platform.
2. **Customers are institutions.** Hospitals ask, in procurement, where their
   data physically sits, who can reach it, and how it is restored. "It is in a
   shared table with a tenant column" is a hard answer to defend.
3. **Tenant sizes differ by orders of magnitude.** A single-doctor clinic and a
   twelve-hospital group are both customers. One noisy tenant should not
   degrade the rest.

## Options considered

### A. Shared schema, `organization_id` on every row

The industry default. One database, one set of tables, a tenant discriminator
column, usually with PostgreSQL row-level security as a backstop.

- **For:** cheapest to run; one migration; trivial cross-tenant analytics;
  connection pooling is a solved problem.
- **Against:** isolation is a property of *every query being correct, forever*.
  One missing `WHERE` clause in one report, one ORM `.all()` in a background
  job, one raw SQL string in a hurried hotfix — and one hospital reads
  another's patients. RLS reduces this but does not remove it: policies are
  bypassed by superuser connections, and are easy to forget on new tables.

### B. Schema per tenant

One PostgreSQL schema per organization, selected with `search_path`. The
`django-tenants` approach.

- **For:** good isolation; single connection pool; per-tenant table sets.
- **Against:** migrations must iterate every schema (so does option C);
  thousands of schemas strain `pg_catalog` and slow migrations; still one
  database, so backup, restore and residency remain all-or-nothing.

### C. Database per tenant  ← chosen

One PostgreSQL database per organization, plus a single control-plane database
for the SaaS business itself.

- **For:**
  - Isolation is *physical*. A query that forgets its tenant predicate returns
    nothing, because the rows are not in that database.
  - Backup, restore, export and deletion are per customer. "Give us our data"
    and "delete our data" are one command, not a filtered dump.
  - A large customer can be moved to their own database server by changing one
    row in `TenantDatabase` — no application change.
  - Residency, retention and encryption can differ per customer where a
    contract demands it.
- **Against:** the costs in the next section, which are real and were accepted
  deliberately.

## Decision

Adopt **database per tenant**.

- The **control plane** (`default`) holds the SaaS business: organizations,
  the tenant registry, plans, subscriptions, entitlements, usage, identity,
  and facility change requests.
- Each **tenant database** holds one customer's operations: facilities,
  departments, roles, audit log, and — as the product grows — patients,
  encounters, stock and money.
- `apps.tenancy.router.TenantDatabaseRouter` enforces the split at query time
  and at migration time.

## Consequences

### Accepted costs

**No cross-database transactions.** A facility must be written to the tenant
database *and* mirrored into the control-plane registry, and those two writes
cannot be atomic. Mitigated by:

- nesting both transactions so an application-level failure rolls back both;
- ordering writes so the surviving state after an infrastructure failure is the
  safe one — a registry row without a facility over-counts quota (visible,
  fixable), while a facility without a registry row is invisible capacity;
- `reconcile_facility_registry`, which detects and reports drift.

**No cross-database foreign keys.** `RoleAssignment.user_id` is a bare UUID.
Referential integrity there is the application's responsibility, and the
denormalised `user_email` exists so the common read needs no second hop.

**Migrations fan out.** `migrate_tenants` rolls every tenant and collects
failures rather than stopping, so one broken tenant does not block the fleet.
Schema changes must be backward compatible for the duration of a rollout.

**Connection pressure.** Each tenant is a separate connection pool.
`apps.tenancy.connections` registers connections lazily and only for tenants
actually touched by a process. At scale this needs PgBouncer in transaction
mode; that is a deployment concern, not an application one.

**Cross-tenant reporting is harder.** Solved by projecting the small amount of
non-clinical data the platform genuinely needs — the facility registry and
usage counters — into the control plane. Nothing patient-identifiable is
projected, and nothing ever will be.

### What this buys

The failure mode of a forgotten tenant predicate changes from *silent
cross-tenant disclosure* to *an empty result set*. For a system holding
medical records, that trade is worth every cost listed above.

## Revisiting

Reconsider if tenant count passes roughly 5,000 — the point at which
per-database overhead and migration fan-out start to dominate operational cost.
The likely answer then is not a rewrite but a split: the long tail of small
tenants onto shared infrastructure, large institutional customers keeping
dedicated databases. The router already makes that possible, since the
connection for a tenant is data (`TenantDatabase`), not configuration.
