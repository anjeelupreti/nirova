# Access control, Phase 1

**Shipped 5 September 2026.** Commits `4ef5178`, `6516569`.
**Design:** [ACCESS_DESIGN.md](ACCESS_DESIGN.md) · **Log:** entries 169–172.
**Next:** [PHASE2.md](PHASE2.md).

The first of three phases narrowing who may see a patient's record. This one
lays the vocabulary, fixes a clinical safety gap that had to close before
anything could be restricted, and narrows the records that carry no safety
argument.

---

## Why this phase exists

On 4 September the running system was probed by signing in as a
`pharmacy_counter` assistant scoped to one branch. It was served **every
patient in the organization, all 23 prescriptions — 21 written at another
facility, with drug lines — and all 72 invoices.**

Three options were offered for fixing it. All three were wrong: they took
**facility as the unit of access control**, and researching the domain showed
that is the wrong primitive. `Prescription.facility` records where a
prescription was *written*, and a patient may take one to any pharmacy — that
is what a prescription is. A consultant covers two sites. A patient is admitted
at one facility and followed up at another.

Then a fourth thing turned up that reframed the question completely.

---

## The finding that changed the plan

**Dispensing ran no safety checks at all.**

`run_safety_checks` — allergies, interactions, duplicate therapy — has run when
a prescriber signs since this system was built. Nothing ran when a pharmacist
handed the box over. The person last in line between a prescribing error and a
patient had no net.

That inverts the sequencing. A pharmacist **needs** the allergy list.
Restricting their access without first giving them that data would not have
made the system safer; it would have made it more dangerous while looking like
an improvement. So the safety net had to land before any restriction did, and
that is why this phase leads with it.

### What it caught immediately

The seed suite failed on the first run after the check went in — correctly.

`seed_pharmacy_demo` was dispensing **amoxicillin to a patient with a severe
penicillin allergy recorded with urticaria and facial swelling.** On every run,
since the seed was written. Amoxicillin is a penicillin; the cross-reactivity
check caught it by drug family.

The scenario existed to demonstrate a *stock* rule — FEFO batch selection — and
had picked that patient and that drug by coincidence. **Nothing in the system
would have stopped that hand-over before this phase.**

The FEFO scenario now uses a patient it cannot harm, and the refusal has its
own narrated scenario, because it is worth watching happen.

---

## What shipped

### 1. Three data tiers, not one permission

`patient.read` used to grant everything about a person short of their
encounters. That conflated three different acts.

| Permission | Covers | Reach |
|---|---|---|
| `patient.read` | Name, MRN, age, sex, phone, address, identifiers | **Organization-wide.** Every counter has to establish who is in front of them. Restricting this produces duplicate records, which is how somebody is given a drug they are allergic to |
| `patient.safety.read` *(new)* | Allergies, active medicines, dosing-relevant conditions | **Organization-wide** for clinical and pharmacy roles. Deliberately generous — this is what makes restricting the rest safe |
| `patient.clinical.read` *(new)* | Encounters, notes, diagnoses, results, history | **Phase 2** puts this behind a care relationship |
| `privacy.review` *(new)* | Reviewing emergency access | For the break-glass queue Phase 2 builds |

Granted so that **Phase 1 changes no behaviour on this step** — every role
holding `encounter.read` received the clinical tier. The point was to have the
vocabulary before enforcing it.

Who holds them now:

| Role | Grants |
|---|---|
| `organization_admin` | all three (holds every permission by definition) |
| `doctor`, `nurse` | safety + clinical |
| `medical_director`, `auditor` | safety + clinical + `privacy.review` |
| `lab_technician` | safety |
| **`pharmacist`, `pharmacy_counter`** | **safety** — the one grant that is not behaviourally neutral |

### 2. Safety checking at the point of dispensing

`dispense()` now runs the same `run_safety_checks` the prescriber faces and
refuses without a typed reason when a warning is `HIGH` or `CRITICAL`.

- **Refused before the `Dispense` row is created**, so a hand-over stopped for
  safety leaves nothing behind to explain.
- **Its own exception class**, `SafetyOverrideRequired`, so a client can tell an
  allergy warning from an out-of-stock and put the warnings in front of the
  pharmacist rather than showing a generic failure.
- **It refuses; it does not forbid.** A typed reason overrides. Sometimes a drug
  is genuinely given despite a listed allergy — a mild childhood rash, a
  prescriber who has weighed it — and a control that cannot be overridden is one
  that gets worked around outside the system, where nobody can see it. Same
  shape as the FEFO override twenty lines below it.

### 3. Business records narrow to the facility

Invoices, counter sales, till sessions and dispensings now pass through
`apply_scope_filter`. These are a branch's own trading records, and unlike
clinical data there is no safety argument for a counter assistant at one branch
paging through another branch's takings. Organization-scoped roles —
accountant, auditor, owner — keep the whole view.

| Endpoint | Filtered on |
|---|---|
| `/api/billing/invoices/` | `invoice.read` |
| `/api/pos/sales/` | `sale.read` |
| `/api/pos/sessions/` | `till.open` |
| `/api/pharmacy/dispenses/` | `stock.read` |

### 4. Prescriptions deliberately are **not** filtered this way

There is a test asserting they are not, so nobody tidies it later.

A prescription may be presented at any pharmacy. `Prescription.facility`
records where it was *written*. Narrowing that list by facility would break
group dispensing, which is a real workflow. Phase 2 narrows it by **care
relationship** instead and keeps lookup by reference open — the patient handing
over the number is the relationship and is the consent.

### 5. Reads are logged

Prescription and invoice retrieval now call `record_patient_access`, which
patient retrieval has always used and these never did.

What somebody is being treated for is usually legible from what they have been
prescribed, and an itemised bill names every procedure and every test they had.

### 6. `assign_role` refuses a scope that reaches nothing

A facility-, unit-, department- or multi-facility-scoped assignment naming no
facility and no department was storable. It produced a user who **appeared to
hold a role and could see no rows** — a failure that looks like a working
assignment on the administration screen and like a broken product to the person
holding it.

It briefly became the *opposite* failure when `apply_scope_filter` arrived and
its fall-through returned everything (log 157). That was fixed, but the row
should never have been storable.

---

## The result, measured

The probe prints the database, the facility, the counter and the owner side by
side. A count on its own says nothing — 88 invoices is right or wrong depending
entirely on how many exist.

```
                in db  at pharmacy  counter  owner
  invoices        160           88       88    160
  sales            45           45       45     45
  dispensings      44           44       44     44
  prescriptions    60            -       60     60
```

The counter assistant no longer sees the clinic's invoices. **The
`prescriptions 60/60` row is the design, not a gap** — browse-narrowing is
Phase 2.

---

## A bug this phase produced, and what it taught

The first version of the dispensing filter **denied everything.**

It passed `prescription.dispense` to `apply_scope_filter` — a permission a
counter assistant does not hold — so the filter correctly returned nothing, and
the counter could not see its own dispensings. The endpoint gates reads on
`stock.read`.

> **The scope filter and the permission check have to name the same
> permission**, or the filter is answering a question nobody asked. And it fails
> *closed*, which surfaces as an empty list rather than an error — the hardest
> kind of wrong to notice.

`dispensings: 0` on its own told me nothing. `44 in db, 44 at the pharmacy, 0 to
the counter` told me immediately. The tests assert against database counts for
the same reason.

---

## Tests added

Six, in `backend/tests/test_invariants.py`. The selection rule is unchanged:
one test per thing that has actually gone wrong, not an attempt at coverage.

| Test | Guards |
|---|---|
| `test_dispensing_refuses_a_recorded_allergy_without_a_reason` | The safety net, and that it overrides rather than forbids |
| `test_a_scope_that_reaches_nothing_cannot_be_assigned` | The `assign_role` refusal |
| `test_business_lists_narrow_to_the_facility` | Asserted against database counts, not a fixed number |
| `test_prescriptions_are_deliberately_not_facility_filtered` | Stops a future tidy-up breaking group dispensing |
| `test_scope_filter_denies_when_it_reaches_no_facility` | Log 157, five scopes parametrised |
| `test_holders_of_agrees_with_resolve_authorization` | Log 164 |

**Suite: 59 tests, ~40 seconds**, seeds run twice through.

---

## What Phase 1 does *not* do

Stated plainly, because it would be easy to read the above as more than it is.

- A counter assistant **still sees every patient's identity and safety data**
  organization-wide. That is by design.
- A counter assistant **can still browse every prescription** in the
  organization. Phase 2 closes this.
- Encounters, diagnoses, results and history are still gated only by
  `encounter.read` at facility scope — `patient.clinical.read` is granted but
  **not yet enforced against anything**.
- There is **no break-glass**, so there is nothing to review yet.
- There is **no way for a patient to see who looked at their record.**

---

## Files

```
backend/apps/pharmacy/services.py          safety checks at dispensing
backend/apps/pharmacy/views.py             dispensings narrow
backend/apps/billing/views.py              invoices narrow, reads logged
backend/apps/pos/views.py                  sales and till sessions narrow
backend/apps/prescriptions/views.py        reads logged (list deliberately open)
backend/apps/rbac/permissions.py           the three new permissions
backend/apps/rbac/services.py              grants, and the assign_role refusal
backend/tests/test_invariants.py           six tests
backend/apps/pharmacy/management/commands/seed_pharmacy_demo.py
                                           FEFO moved off the allergic patient;
                                           the refusal gets its own scenario
docs/ACCESS_DESIGN.md                      the decision and its reasoning
```
