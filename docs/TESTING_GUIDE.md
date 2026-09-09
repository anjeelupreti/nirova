# Testing Nirova

How to get the system running and then look at it as the people who use it.
Written to be followed top to bottom the first time, and dipped into afterwards.

Everything below uses the demo tenant, **`manakamana`** — a small hospital group
with four facilities, which is the shape most of the interesting behaviour needs.
A single-site clinic would show you almost none of it.

---

## 1. Get it running

**Needs** Docker. Nothing else, unless you want to run something on the host.

```bash
docker compose -f infra/docker-compose.yml up
```

Seven services: Postgres, Redis, the API, a Celery worker and scheduler, and
both React applications behind their own nginx. On a first run it also
migrates, seeds the plan catalogue, provisions a demo tenant and fills it with
a working hospital. About three and a half minutes from a machine with no
images; seconds afterwards.

| | |
|---|---|
| staff console | <http://localhost:5173> |
| patient application | <http://localhost:5174> |
| API, admin, OpenAPI | <http://localhost:8000> |

`docker compose -f infra/docker-compose.yml down -v` throws the data away and
the next `up` rebuilds it from nothing.

The tenant gets a **separate PostgreSQL database**. That is not a detail — it
is the isolation model, and it means a customer's clinical data is not
reachable from the control plane at all.

### Running it on the host instead

```bash
docker compose -f infra/docker-compose.yml up -d postgres redis

cd backend
python -m venv .venv
.venv/Scripts/python.exe -m pip install -r requirements.txt   # Windows
# source .venv/bin/activate && pip install -r requirements.txt  # macOS / Linux
cp .env.example .env

.venv/Scripts/python.exe manage.py bootstrap      # everything, in order
.venv/Scripts/python.exe manage.py runserver      # :8000

cd ../frontend && npm install && npm run dev      # :5173  staff console
cd ../patient  && npm install && npm run dev      # :5174  patient application
```

`bootstrap` replaces the twenty-line seed loop this guide used to print. It
runs them in the order `apps/tenancy/seeding.py` records — an order that was
**measured**, by running it against an empty database until it completed,
rather than reasoned about. The individual seeds still exist; see
`manage.py help`.

> **If you run the backend on the host, read this.** `TenantDatabase` stores
> host and port **per tenant**, so a tenant provisioned inside Docker records
> `host="postgres"`, which your machine cannot resolve:
>
> ```
> psycopg.OperationalError: [Errno 11001] getaddrinfo failed
> ```
>
> Nothing is broken; the row describes a network you are not on.
>
> ```bash
> manage.py retarget_tenants --host localhost --apply   # work on the host
> manage.py retarget_tenants --host postgres  --apply   # back to the stack
> ```
>
> **Only one mode can be active at a time**, and leaving a container running
> in the other one is how a whole afternoon disappears — see log 246. Stop
> the backend container while working host-side:
> `docker compose -f infra/docker-compose.yml stop backend worker scheduler`.

**Read the seed output, do not just watch it scroll.** The seeds narrate what
they expect beside what they got — that is the project's main verification
mechanism, and most bugs in the development log were found by a seed
contradicting itself rather than by a test failing.

Two applications, deliberately. The patient one is a separate build with its
own origin and its own auth store, so a clinician and a patient are different
kinds of subject structurally rather than by a conditional.

---

## 2. The tests

```bash
cd backend
.venv/Scripts/python.exe -m pytest -q                    # 179 tests, ~2m15s
.venv/Scripts/python.exe -m pytest -q -m "not seeds"     # the fast half, ~90s
```

They need the stack above running, and they need the tenant pointed at a host
this process can reach — see the box in section 1. The suite is **not hermetic
on purpose**: this project is database-per-tenant, and reproducing that against
a throwaway test database means reimplementing provisioning inside the harness
— and a harness that reimplements the thing it is testing does not test it.

Four things it does that matter:

- **Every seed runs twice.** Six defects have been found by the second run
  alone, including one seed that had been failing every Saturday since it was
  written.
- **Every role hits every parameterless endpoint**, failing on any 5xx. A 403
  is an answer; a 500 is a bug, and it hides behind permissions — *an endpoint
  only the right role can reach is an endpoint only the right role can crash.*
- **Every navigation entry must open for the role that sees it**, and every
  entry must be in the probe map. A screen missing from that map used to be
  skipped silently, which is how five screens sat unchecked for weeks
  (log 236).
- **Every guard is proved by reintroducing its defect.** A guard that has
  never been shown to fail is not a guard. Twice, that exercise showed the
  guard itself was broken.

### What the suite deliberately cannot do

`CREATE DATABASE` cannot run inside a transaction and pytest wraps every test
in one, so **provisioning is not driven by the suite**. The obvious fix,
`django_db(transaction=True)`, is the wrong one: `TransactionTestCase`
truncates every table in `databases` afterwards, and `databases="__all__"`
includes the demo tenant the rest of the suite reads. A test that passes by
destroying the fixture every other test depends on is worse than no test.

Provisioning is verified where it can be — `manage.py bootstrap` builds a
tenant from nothing on every container start, and `manage.py onboard` runs the
same service from the command line:

```bash
manage.py onboard probe --legal-name "Probe Clinic" --email a@b.test     --plan starter --owner-email owner@probe.test --owner-name "A Person"
```

### When a tenant says it is broken and is not

A transient database outage marks tenants `failed`, and until log 246 nothing
ever set them right again.

```bash
manage.py recheck_tenants           # what it would change
manage.py recheck_tenants --apply   # change it
```

It asks each tenant database the only question that matters — does it answer —
and corrects the status in **both** directions.

---

## 3. Who you can sign in as

**Staff console — <http://localhost:5173>.** Organization `manakamana`, password
**`NirovaDemo!2026`** for all of these.

| Account | Roles | What they are for |
|---|---|---|
| `owner@manakamana.test` | organization_admin | Sees everything. Use it to check what *should* be visible before deciding something is missing |
| `doctor@manakamana.test` | doctor *(department scope)* | The most interesting account. Narrow scope, clinical access |
| `prakash@manakamana.test` | doctor | A second clinician, for testing one doctor against another's patients |
| `pharmacy@manakamana.test` | pharmacist + pharmacy_manager | Can dispense |
| `counter@manakamana.test` | pharmacy_counter | Sells; **cannot** dispense |
| `manager@manakamana.test` | hr_manager + operations_manager | People and estate |

> **The `staff`-role accounts (`emp-0005@…`, `meena.joshi@…` and the rest) have
> no usable password.** `give_login` creates accounts without one deliberately —
> generating a password means delivering it somehow, and every way of delivering
> it is worse. To sign in as one for testing:
>
> ```bash
> .venv/Scripts/python.exe manage.py changepassword emp-0005@manakamana.test
> ```

**Patient application — <http://localhost:5174>.** Organization `manakamana`.

| Phone number | Patient | Password |
|---|---|---|
| `+977-9800000001` | Sita Tamang | `correct horse battery` |

**Only that one.** `seed_portal_demo` registers Sita with a known password; the
other portal accounts (Bishnu Maharjan, Anjali Gurung, Kamala Adhikari) exist
and are active but were registered with passwords the seed does not publish, so
they will refuse you. That refusal is worth seeing once — it is identical to the
one a non-existent account gets, deliberately, so the sign-in form cannot be
used to discover which phone numbers have accounts.

To get into one of the others, issue an invitation as a staff member and
register it the way a patient would:

```
POST /api/portal/accounts/invite/     as owner@   → returns an 8-digit code, once
POST /api/me/auth/  {"action": "register", "mrn": …, "code": …,
                     "identifier": …, "password": …}
```

The MRN and the code are both required and neither alone is enough. Five wrong
codes kills the invitation.

**The facilities**, which you will need for the header in §6:

| Code | Name | Type |
|---|---|---|
| `MKC-KTM` | Manakamana Clinic, Kathmandu | clinic |
| `MKL-KTM` | Manakamana Diagnostics, Kathmandu | laboratory |
| `MKH-BKT` | Manakamana Hospital, Bhaktapur | hospital |
| `MKP-KTM` | Manakamana Pharmacy, Kathmandu | pharmacy |

---

## 4. What to look at as each role

Sign in, then try the thing in the right-hand column. These are chosen because
each one is a decision somebody argued about, not because they exercise code.

### The organization owner

Start here to calibrate. Everything is visible, so anything you cannot see as
somebody else is a narrowing rather than a gap.

- **`/privacy`** — empty at first, and that is what it should look like.
- **`/notifications`** — "waiting for me" is the default tab, not "unread".
  Press *Mark all read* and watch the **waiting** count not move: catching up
  is not the same as doing the work.

### The doctor

- **`/`** — the worklist. Open encounters, triage-ordered, so the sickest
  patient is at the top rather than whoever booked first.
- Open a patient, then try one you are **not** treating. With enforcement on
  (§6) you are refused — and the refusal tells you how to proceed rather than
  just saying no.
- **Prescribe something a patient is allergic to.** The warning appears while
  you type; signing past it requires a typed reason, and the reason is stored
  on the prescription with your name on it.

### The pharmacist and the counter assistant

This pair is the sharpest test in the system, because they differ in one
permission and it changes almost everything.

- As **counter**: `/counter` sells fine. Now try to dispense — refused, no
  `prescription.dispense`.
- As **pharmacist**: **dispense amoxicillin to Ram Bahadur Shrestha.** He has a
  severe penicillin allergy recorded with facial swelling; amoxicillin is a
  penicillin. You are refused, by drug family, and a typed reason overrides.
  *Nothing stopped this hand-over before 5 September 2026.*
- **`/api/clinical/prescriptions/awaiting/`** — what is waiting at this counter.
  Empty until a patient presents one; open a prescription by reference and it
  appears.

### A patient

- **Test results** — a held critical result shows as a card saying a clinician
  will ring, never as a gap in the list.
- **Who saw my record** — staff are named. Somebody treating you will appear
  often; that is what treating you looks like, and the note above the list says
  so before the names do.
- **Sessions** — sign out everywhere, then reload. Sessions are rows, so
  revoking one stops it immediately.

---

## 5. Testing every role at once

The read sweep, as a command:

```bash
.venv/Scripts/python.exe manage.py seed_access_demo
```

It signs in as three roles, hits the API with real tokens, and prints a table
with enforcement off and on:

```
ENFORCEMENT OFF     patients  encounters  prescript  diagnostic  invoices
organization owner         7         123         63          76       160
doctor                     7          62         63          76       403
pharmacy counter           7         403         63         403        88

ENFORCEMENT ON
doctor                     7          22         22          19       403
pharmacy counter           7         403          0         403        88
```

**`0` and `403` mean opposite things** — one is an empty list you were allowed
to ask for, the other is a refusal. The table prints them differently for that
reason.

---

## 6. Testing the access control

Everything in Phase 2 sits behind one switch, **off by default**.

```bash
# On
.venv/Scripts/python.exe manage.py shell -c "
from apps.tenancy.models import Organization
from apps.tenancy.connections import context_for_organization
from apps.tenancy.context import tenant_context
org = Organization.objects.get(slug='manakamana')
with tenant_context(context_for_organization(org)):
    from apps.organization.config import set_config_value
    set_config_value('privacy', 'require_care_relationship', True)
    print('on')
"
```

Replace `True` with `False` to turn it off. Then:

**As the doctor,** open a patient you are treating — fine. Open one you are
not — refused, with the way out named.

**Break glass.** Give a reason; "emergency" is refused, because it is true of
every override and reviews to nothing. Then the record opens for four hours.

**As the owner,** go to **`/privacy`**. The override is waiting, a `CRITICAL`
notification arrived, and there is **no bulk sign-off** — every one is reviewed
individually with a conclusion attached. Try to review your own: refused.

**The two report panels** below the queue show reads with no current
relationship, and how much people read against the median for their role. Both
carry their own caveat above the list, and neither can be cleared — they are
prompts to go and ask somebody, not a queue to empty.

### The facility header

Facility-scoped behaviour needs `X-Facility` with a facility **UUID**:

```bash
curl -s http://localhost:8000/api/billing/invoices/ \
  -H "Authorization: Bearer <token>" \
  -H "X-Organization: manakamana" \
  -H "X-Facility: <facility uuid>" | head -c 300
```

Get a token by signing in at `/api/auth/login/`, and a facility UUID from
`/api/org/facilities/`.

---

## 6b. The screens added since this guide was written

Worth a look because each one closed a gap where the product simply could not
do something.

**Staff access** — Organization → Staff access, as the owner. Invite a
colleague, grant them a role, revoke it, deactivate them. Before this there
was no way to add a second member of staff at all; every account in every
database came from a seed script (log 235).

Two things to try deliberately:

- Sign in as `manager@manakamana.test` (operations manager). They can see the
  staff list and **cannot** open the role list — `user.read` and `role.assign`
  are different permissions and it shows.
- As the owner, look at the role list. Roles you may not grant are listed with
  *what puts them out of reach*. A facility manager sees seven grantable roles
  and nine refused, each naming the permissions it carries that they do not
  hold.

**Configuration → System** — the time zone, the financial year, the currency,
the standard tax rate and the privacy switch. Before this, `ConfigSetting` had
no endpoint at all: the privacy switch could only be turned on from a Django
shell (log 243).

Set the time zone to `Asia/Dubai` and reload any screen with a timestamp on
it. Everything shifts by an hour and three quarters, because Kathmandu is
+05:45 and Dubai is +04:00 — which is the gap a Gulf ward was reading its drug
administration times across (log 241). Put it back with **Back to the
default**, which removes the row rather than writing the default value, so the
badge returns to `default` rather than `set`.

**Detail panels** — Queue, Portal accounts, the counter's sales list, pharmacy
stock, and facility change requests. Click a row. Every field in those panels
was already arriving on the list request and was rendered nowhere: the chief
complaint on a queue token, `locked_until` on a portal account, a whole
receipt behind a sale, and `reserved` versus `available` on a batch — the
difference between "we have forty" and "we can dispense twenty-eight".

---

## 7. When something looks wrong

**Compare against the database, not against your expectation.** A count on its
own says nothing — 88 invoices is right or wrong depending entirely on how many
exist. Every access finding in the development log was measured as *in the
database / at this facility / what this role sees / what the owner sees*, side
by side, and several looked like bugs until the fourth column was added.

**Check the switch before reporting a refusal.** Most "why can't I see this"
questions are `privacy.require_care_relationship` being on.

**A 403 and an empty list are different bugs.** The first is a permission, the
second is a queryset.

**Read `docs/DEVELOPMENT_LOG.md` for the area you are in.** Nearly every
surprising behaviour in this system is deliberate and has an entry explaining
what it prevents.

---

## 8. Known limits of this guide

Stated so you do not spend an afternoon on them.

- **The `staff` accounts cannot sign in** without `changepassword` first.
- **Newly invited users cannot sign in either**, and that is deliberate: an
  invitation sets no password, because nothing can email one and a password
  somebody else typed for you is not a credential. Use `changepassword`.
- **Stock transfers have a service and no screen.** `dispatch_transfer`,
  `receive_transfer` and `cancel_transfer` work and are tested; there is no
  endpoint, so the only way to try one is `manage.py shell` (log 248).
- **`prescription.approve` guards a workflow that does not exist.**
  `PrescriptionStatus` has no approval state. The permission is either a
  feature to build or a catalogue entry to delete, and that is a product
  decision rather than a bug.
- **The write endpoints have not been swept** the way the read endpoints have.
  A write sweep needs valid payloads per endpoint and has not been built.
- **No SMS or email.** Invitation codes are handed over at the desk because
  nothing can send them; that is §93, not a fault.
- **The suite needs the stack running.** There is no hermetic mode, on purpose.
- **English only.** Both applications.
