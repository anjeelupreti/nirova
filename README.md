# Nirova — Healthcare Operating System

A multi-tenant healthcare SaaS platform for Nepal: clinics, hospitals,
pharmacies, laboratories and diagnostic centres, from a single site up to a
multi-branch group.

> **Status: early.** The platform core is built and running — tenancy,
> identity, RBAC, the subscription and entitlement engine and the facility
> lifecycle — together with the clinical core: patients, appointments, the
> OPD queue, encounters with vitals and SOAP notes, and prescribing with
> allergy and interaction checking, and outpatient billing through to
> payment, and laboratory and radiology ordering through to verified results.
> pharmacy stock with batches, FEFO and expiry control, and procurement
> from requisition through to stock. HR and the hospital inpatient
> modules are not built yet.
>
> 32 of the specification's 132 sections are complete; see
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
.venv/Scripts/python.exe manage.py seed_consultation_demo # three consultations
.venv/Scripts/python.exe manage.py seed_billing_demo     # prices, invoices, a refund
.venv/Scripts/python.exe manage.py seed_diagnostics_demo # lab orders, a critical result
.venv/Scripts/python.exe manage.py seed_pharmacy_demo    # stock, FEFO, a recall
.venv/Scripts/python.exe manage.py seed_procurement_demo # order to goods receipt
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
    encounters/        episodes of care, vitals, SOAP notes, diagnoses [tenant]
    prescriptions/     prescribing, and the safety checks around it    [tenant]
    billing/           services, prices, charges, invoices, payments    [tenant]
    diagnostics/       laboratory and radiology, ordered and reported   [tenant]
    pharmacy/          products, batches, stock ledger, FEFO, expiry    [tenant]
    procurement/       suppliers, requisitions, orders, goods receipt   [tenant]
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

### Prescribing safety warns, it never blocks

Allergies are checked with cross-sensitivity families, so a recorded
*penicillin* allergy flags *amoxicillin*. High and critical warnings require
an override reason, which is stored on the prescription permanently:

```
[critical] Amoxicillin - patient has a recorded severe allergy to Penicillin
           (Urticaria and facial swelling). Matched by same family (penicillin).
```

Refusing outright would get bypassed with a paper prescription, losing the
record entirely. Warning, capturing the reason, and keeping both is the
outcome that leaves evidence.

### Results are interpreted against the right population

A haemoglobin of 10.8 g/dL is low for an adult woman and normal for a child,
so reference ranges carry sex and an age band and the narrowest match wins:

```
Haemoglobin      10.8 g/dL    ref 11.5–15.5   <-- low
Potassium         6.9 mmol/L  ref 3.5–5.1     <-- critical_high
```

A critical value raises a `CriticalValueAlert` the moment it is *entered* —
not at verification — because it obliges someone to make a phone call, and
the record has to show who was told and when.

### Stock is a ledger, not a counter

There is no `quantity_on_hand` column. Every movement is an append-only entry
and the balance is their sum, so a discrepancy can always be replayed and
explained. Dispensing takes stock earliest-expiry-first, spanning batches:

```
DSP-2026-000001:
   40.000 from AMX-2024-A (expires 2026-09-27)
   20.000 from AMX-2025-B (expires 2027-03-31)
```

Naming a later batch while an earlier one has stock is refused until a reason
is given — then recorded on both the ledger entry and the dispensing line.

### Quotations are compared on cost per unit, not total

A supplier quoting 4,600 for 600 units (500 paid, 100 free) beats one quoting
4,300 for 500. Ranking on the totals picks the wrong one:

```
Himalayan Medico Supplies   total 4600.00  units 600 (free 100)  per unit 7.67
Nepal Pharma Distributors   total 4300.00  units 500 (free   0)  per unit 8.60
```

Choosing the dearer quotation is allowed and requires a stated reason —
an unexplained preference for a costlier supplier is what procurement fraud
looks like.

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
| `GET /api/clinical/patients/{uuid}/summary/` | Allergies, conditions, vitals and history in one call |
| `POST /api/clinical/encounters/` | Open an episode of care |
| `POST /api/clinical/encounters/{uuid}/vitals/` | Record observations, with abnormal flagging |
| `POST /api/clinical/encounters/{uuid}/notes/` | Write a SOAP note, optionally signing it |
| `POST /api/clinical/prescriptions/preview/` | Safety warnings without writing anything |
| `POST /api/clinical/prescriptions/` | Prescribe — 409 if a warning needs a reason |
| `GET /api/clinical/patients/{uuid}/medications/` | Everything the patient is currently taking |
| `POST /api/billing/charges/` | Capture a charge, priced for the patient's category |
| `POST /api/billing/invoices/` | Invoice the pending charges and issue it |
| `POST /api/billing/invoices/{uuid}/pay/` | Take a payment |
| `POST /api/billing/invoices/{uuid}/credit/` | Reverse with a credit note |
| `GET /api/billing/collection/?facility=` | End-of-day cash-up by payment method |
| `POST /api/diagnostics/orders/` | Order a test or scan |
| `POST /api/diagnostics/orders/{uuid}/collect/` | Record collection, allocate the barcode |
| `POST /api/diagnostics/orders/{uuid}/results/` | Enter results; criticals alert immediately |
| `POST /api/diagnostics/orders/{uuid}/verify/` | Verify and release — refused for the entering user |
| `GET /api/diagnostics/worklist/?facility=` | Department worklist, STAT first |
| `GET /api/diagnostics/turnaround/?facility=` | TAT performance and breach rate |
| `POST /api/pharmacy/stock/receive/` | Book a batch in |
| `GET /api/pharmacy/dispenses/allocate/` | Preview which batches FEFO would take |
| `POST /api/pharmacy/dispenses/` | Dispense — 409 if it would break FEFO without a reason |
| `GET /api/pharmacy/stock/expiring/` | Batches by expiry bucket, with value at cost |
| `GET /api/pharmacy/batches/{uuid}/exposure/` | Who received a recalled batch |
| `POST /api/pharmacy/counts/{uuid}/approve/` | Approve variances — refused for the counter |
| `POST /api/procurement/requisitions/` | Raise a request to buy |
| `GET /api/procurement/requisitions/{ref}/compare/` | Rank quotations on cost per unit |
| `POST /api/procurement/orders/` | Raise an order — 409 for a dearer quote with no reason |
| `POST /api/procurement/orders/{ref}/receive/` | Book a delivery in |
| `POST /api/procurement/receipts/{ref}/post/` | Create batches and post to stock |
| `GET /api/procurement/suppliers/{uuid}/performance/` | Lead time, fill rate, rejections |
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
- [x] Encounters: vitals with abnormal flagging, SOAP notes, sign and amend
- [x] Prescribing: versioned, allergy and interaction checked, overrides captured
- [x] Billing: layered pricing, gapless statutory numbering, credit notes, refunds
- [x] Diagnostics: lab and radiology ordering, population reference ranges,
      critical-value alerting, verification by a second person
- [x] Pharmacy: product master, batches, immutable stock ledger, FEFO with
      authorised override, expiry buckets, recall exposure, blind stock counts
- [x] Procurement: suppliers with licence enforcement, requisitions, quotation
      comparison, orders, goods receipt with quality check, supplier performance

Next, in dependency order:

- [ ] Pharmacy POS
- [ ] Referrals and the patient portal
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
