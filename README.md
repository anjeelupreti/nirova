# Nirova — Healthcare Operating System

A multi-tenant healthcare SaaS platform for Nepal: clinics, hospitals,
pharmacies, laboratories and diagnostic centres, from a single site up to a
multi-branch group.

> **Status: early.** The platform core is built and running — tenancy,
> identity, RBAC, the subscription and entitlement engine and the facility
> lifecycle — together with the clinical foundation: patients, appointments
> and the OPD queue. Pharmacy, laboratory, finance, HR and the hospital
> inpatient modules are not built yet.
>
> 17 of the specification's 132 sections are complete; see
> [`docs/IMPLEMENTATION_CHECKLIST.md`](docs/IMPLEMENTATION_CHECKLIST.md).

---

## The idea in one picture

```
PLATFORM OWNER            the SaaS business — one control-plane database
  └── ORGANIZATION        the customer, the tenant, the billing entity
                          — one dedicated database each
        └── FACILITY      a hospital, clinic, pharmacy, lab or warehouse
              └── DEPARTMENT
                    └── UNIT      a ward, a counter, a lab bench
```

The rule that shapes everything: **an organization is the customer; a hospital
is not.** A single-hospital customer is one organization containing one
facility, and grows into a chain without restructuring anything.

---

## Running it

**Requirements:** Docker, Python 3.12+, Node 20+.

```bash
# 1. Databases
docker compose -f infra/docker-compose.yml up -d

# 2. Backend
cd backend
python -m venv .venv
.venv/Scripts/python.exe -m pip install -r requirements.txt   # Windows
# source .venv/bin/activate && pip install -r requirements.txt  # macOS / Linux
cp .env.example .env

.venv/Scripts/python.exe manage.py migrate               # control plane
.venv/Scripts/python.exe manage.py seed_catalog          # plans, modules, add-ons
.venv/Scripts/python.exe manage.py seed_demo             # a demo tenant, end to end
.venv/Scripts/python.exe manage.py seed_clinical_demo    # patients, clinics, a queue
.venv/Scripts/python.exe manage.py runserver

# 3. Frontend
cd ../frontend
npm install
npm run dev          # http://localhost:5173
```

`seed_demo` builds a working customer by running the real code paths — it
raises facility change requests and approves them rather than inserting rows,
so a successful run is also a test of entitlements, quotas, approval routing,
segregation of duties and cross-database writes.

`seed_clinical_demo` does the same for the clinical path: it registers six
patients through duplicate detection and quota checks, builds three doctors'
schedules, books into them, and issues queue tokens — including a walk-in
emergency that correctly overtakes three booked patients.

### Demo accounts

Password for all three: `NirovaDemo!2026`

| Account | Role |
|---|---|
| `platform@nirova.test` | Platform staff — the SaaS console |
| `owner@manakamana.test` | Organization owner — approves facility changes |
| `manager@manakamana.test` | Operations manager — raises facility changes |

Signing in as the manager and the owner in turn walks the whole approval loop.

---

## Repository layout

```
backend/
  config/              settings, URLs, Celery
  apps/
    common/            base models, error envelope, permissions, pagination
    tenancy/           organizations, tenant databases, routing, provisioning
    catalog/           modules, features, plans, limits, add-ons
    subscriptions/     what each customer bought, and its lifecycle
    entitlements/      resolution engine and the quota guard
    metering/          usage events and rolled-up counters
    identity/          users, memberships, login history, devices
    provisioning/      facility change requests and approvals
    platform_api/      the platform owner's console API
    organization/      facilities, departments, units, configuration   [tenant]
    rbac/              roles, assignments, permission overrides        [tenant]
    audit/             audit log and entity version history            [tenant]
    patients/          patient master, identifiers, allergies, merge   [tenant]
    scheduling/        provider schedules, appointments, OPD queue     [tenant]
frontend/              React + Vite + TypeScript + shadcn/ui
docs/
  DEVELOPMENT_LOG.md          every change, and why it was made that way
  IMPLEMENTATION_CHECKLIST.md all 132 spec sections, with status
  adr/                        architecture decision records
infra/                 docker-compose for Postgres and Redis
```

Apps marked `[tenant]` live in each customer's own database. Everything else
lives in the shared control plane. The split is declared in
`config/settings/base.py` and enforced by `apps/tenancy/router.py`.

---

## The parts that carry the design

### Database per tenant

Each customer gets their own PostgreSQL database. A query that forgets its
tenant predicate returns *nothing* rather than another hospital's patients.
Full reasoning, including the costs, in
[ADR 0001](docs/adr/0001-database-per-tenant.md).

### Entitlements, not plan names

Nothing in the codebase checks `plan == "premium"`. Capabilities resolve
through four layers — plan, add-ons, temporary grants, contract overrides —
and every resolved number carries its provenance:

```
hospital   1/1   sources=['plan:professional', 'addon:extra_hospital×1']
```

So "why can this customer only open one hospital?" is answered by reading the
answer, not by reconstructing it.

### Facilities are requested, not created

There is no "New Facility" endpoint. Opening, closing or converting a facility
is a **change request** that is evaluated against the plan, routed to whoever
has the authority to decide it, and executed only on approval.

```
raise ─→ evaluate ─→ route ─→ decide ─→ re-check ─→ execute
         quota,      derived   org or   entitlement  tenant DB
         module,     from the  platform still fits?  + registry
         churn       position
```

Routing is derived, never chosen by the requester: a change that fits inside
what the customer already pays for is theirs to make; one that changes the
commercial relationship goes to the platform, which can approve it *together
with* the capacity that makes it fit.

### Segregation of duties

Permissions declare their conflicts (`purchase.create` ⁄ `purchase.approve`,
`payroll.process` ⁄ `payroll.approve`). Conflicts are flagged when a role is
saved, and the same person cannot both raise and approve a record at runtime.

---

## API

Interactive schema at `/api/docs/` once the server is running.

| Endpoint | Purpose |
|---|---|
| `POST /api/auth/login/` | Exchange credentials for tokens |
| `GET /api/auth/session/` | User, organizations, permissions and entitlements in one call |
| `POST /api/auth/switch/` | Change the active organization |
| `GET /api/org/facilities/` | Facilities in the active organization |
| `GET /api/org/facilities/capacity/` | Per-type capacity, used and remaining |
| `POST /api/org/facility-requests/preview/` | What would happen, without doing it |
| `POST /api/org/facility-requests/` | Raise a change request |
| `POST /api/org/facility-requests/{ref}/decide/` | Organization-level decision |
| `GET /api/clinical/patients/search/?q=` | Find a patient by name, MRN, phone or document |
| `POST /api/clinical/patients/` | Register — returns 409 with candidates if a duplicate is likely |
| `POST /api/clinical/patients/{uuid}/merge/` | Merge a duplicate into this record |
| `GET /api/clinical/availability/?facility=` | Every session today, with remaining capacity |
| `POST /api/clinical/appointments/` | Book, re-checking slot capacity in the transaction |
| `GET /api/clinical/queue/?facility=` | The live queue, in the order patients will be seen |
| `POST /api/clinical/queue/call-next/` | Call the next waiting patient |
| `GET /api/platform/dashboard/` | SaaS metrics across all customers |
| `GET /api/platform/change-requests/queue/` | The platform approval queue |
| `POST /api/platform/change-requests/{ref}/decide/` | Platform decision, with capacity |

Every error uses one envelope, so clients branch on `code` rather than prose:

```json
{ "error": { "code": "quota_exceeded", "message": "…", "detail": { … } } }
```

---

## Operations

```bash
manage.py provision_tenant <slug>            # create and migrate one tenant DB
manage.py migrate_tenants                    # roll migrations across the fleet
manage.py reconcile_facility_registry        # detect control-plane/tenant drift
manage.py seed_catalog                       # (re)seed plans and add-ons
```

`migrate_tenants` collects failures rather than stopping, so one broken tenant
does not block the rest. Run `reconcile_facility_registry` on a schedule —
cross-database writes cannot be atomic, and this is what turns a silent
inconsistency into a report.

---

## Roadmap

Built:

- [x] Tenancy: per-tenant databases, routing, provisioning, context switching
- [x] Identity: users, memberships, JWT, lockout, device records
- [x] RBAC + ABAC with scopes, overrides and segregation of duties
- [x] Catalogue, subscriptions, entitlement resolution, usage metering
- [x] Facility lifecycle with request-and-approval
- [x] Audit log and entity version history
- [x] Platform owner console API
- [x] Patient master: identifiers, allergies, conditions, duplicate detection, merge
- [x] Appointments: provider schedules, slots, overbooking, walk-in reserve
- [x] Queue: triage priority, call / recall / skip, waiting-time measurement

Next, in dependency order:

- [ ] Encounters, vitals, SOAP notes
- [ ] Prescriptions with allergy and interaction checking
- [ ] Pharmacy OS: product master, batches, FEFO, expiry, POS
- [ ] Inventory and procurement
- [ ] Finance: chart of accounts, ledger, revenue cycle
- [ ] HRMS and Nepal payroll (SSF, PF, CIT, TDS)
- [ ] Hospital OS: IPD, beds, wards, theatre, emergency
- [ ] Laboratory (LIMS) and radiology (RIS/PACS)
- [ ] Analytics, reporting engine, command centres
- [ ] Mobile apps and offline mode

---

## Contributing

[`docs/IMPLEMENTATION_CHECKLIST.md`](docs/IMPLEMENTATION_CHECKLIST.md) maps
all 132 specification sections to their status, and lists the cross-cutting
invariants every new module must hold to.

Read [`docs/DEVELOPMENT_LOG.md`](docs/DEVELOPMENT_LOG.md) first — it records
why things are the way they are, including several decisions that look odd
until you know what they are defending against.

**Add an entry for every change.** A diff shows what changed; the log is the
only place that records why, and an undocumented judgement call is
indistinguishable from an accident six months later.
