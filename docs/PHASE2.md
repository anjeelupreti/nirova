# Access control, Phase 2

**Shipped 6 September 2026.** Commits `40b8fac` … `c58d229`.
**Plan:** [PHASE2_PLAN.md](PHASE2_PLAN.md) · **Design:** [ACCESS_DESIGN.md](ACCESS_DESIGN.md) · **Previous:** [PHASE1.md](PHASE1.md)
**Log:** entries 173–183.

Phase 1 laid the vocabulary and closed a clinical safety gap. Phase 2 decides
who may open a patient's clinical record — the first change in this project
that alters what a clinician sees on an ordinary working day.

**It is live and switched off.** Enforcement runs behind
`privacy.require_care_relationship`, which defaults to `false`. A single-site
clinic gets nothing from a care-relationship requirement and pays the
complexity — the same position §17 takes on segregation of duties, which a
two-person practice cannot enforce because there is nobody to segregate.

---

## The one idea

> Clinical access follows a **care relationship**, and **browsing is not the
> same act as looking something up**.

A care relationship is not administered — nobody maintains a list of who is
treating whom. It falls out of records the system already keeps: admissions,
appointments, orders, prescriptions, ward assignments. That is the only kind of
access control that stays accurate, because it is a by-product of doing the
work rather than a second job somebody has to remember.

---

## What shipped

### `has_care_relationship` — and it returns *why*

`apps/rbac/relationships.py`. Six sources, cheapest and likeliest first,
short-circuited: an open **encounter** they are the provider on, an
**admission** at a facility their scope reaches, a **prescription or order**
they wrote, an **appointment** from a day before to a week after, a **nursing
assignment** to the bed, and a **break-glass grant**.

It returns a reason, not a boolean. A boolean cannot be written onto an access
log or shown to the person reading the record, and *"you are seeing this
because you admitted them on Tuesday"* is what makes the control reviewable.

Exemptions are an **explicit branch** — owner, `audit.read`, clinical access at
organization scope. An exemption that is a side effect of a scope comparison
somewhere is one nobody knows exists until it is abused.

### `related_patient_ids` — the list-shaped counterpart

Asking "is it this one?" once per row is six queries per patient on a page of
fifty. Asking each source "which patients?" is six queries for the page. It
mirrors `accessible_facility_ids`, including returning `None` for *no
restriction* as distinct from an empty set meaning *nobody*.

Two code paths answering one question can drift, and a patient who appears in a
list but cannot be opened is a confusing bug rather than an obvious one.
Checked across every active member against every patient: **zero
disagreements**, now asserted by test.

### Break-glass

`BreakGlassGrant`. **It refuses nobody** — an unconscious patient arrives and
nobody has a relationship with them; any control that can stop that will
eventually kill somebody. The only refusals are about the *reason*, because an
unusable reason makes the review queue unusable and the queue is the whole
control.

- **A sentence, not a category.** "Emergency" is true of every override.
- **Four hours, ended by time.** Asking again inside the window returns the
  *same* grant with the *same* expiry — otherwise a record is held open
  indefinitely by re-asking.
- **Nobody reviews their own**, and querying or escalating without saying why
  is refused: the clinician will be asked about it, and *"the system flagged
  it"* is not something anybody can answer.
- **Uses counted at read time, not grant time** — a grant taken and never used
  usually means somebody clicked through a warning.
- **Revocable** by a reviewer, by moving the expiry to now — the same mechanism
  as ordinary expiry rather than a second one, so there is no `is_revoked` flag
  to keep in step.

### The review surface

`/api/privacy/` and a screen at `/privacy`. Every grant raises a `CRITICAL`
notification — the one category the notification centre refuses to let anybody
silence by preference.

**There is no endpoint that hides a grant.** No delete, no dismiss, no bulk
sign-off, and the screen says so: *a queue that can be emptied in one click is
not a control.* The unreviewed count leads, with the total under it, because
the ratio is what to read.

### Enforcement

`HasClinicalAccess` — the permission *and* the relationship, kept as two
classes. Collapsing them is exactly how a permission comes to mean "everybody
at this site", which is what the 4 September probe found.

Applied to encounters, prescriptions, diagnostic orders, patient results, ICU
stays and admissions. The refusal **names the way out**:

> You are not currently treating Ram Bahadur Shrestha. If this is an emergency,
> open the record by giving a reason — it will be recorded against your name
> and reviewed.

A bare 403 on a clinical record at three in the morning is how somebody decides
the system is broken and borrows a colleague's login.

### Browse narrows, lookup does not

```
switch OFF    doctor 63   owner 63   counter 63
switch ON     doctor 22   owner 63   counter  0
by reference  doctor 200  counter 200
```

The last line is the point. A pharmacy counter assistant can enumerate
**nothing** and can still open the exact prescription handed to them —
presenting the reference *is* the relationship and *is* the consent.

---

## What the phase found on the way

Five things, none of which were the work I set out to do.

**A column that looked full.** Step 0 measured the relationship sources before
enforcing anything. `Encounter.provider_uuid` was 20.5% populated, which is
bad. Appointments were **100% populated with placeholder ids naming nobody**,
which is worse — every appointment-based relationship would have resolved to
nobody, silently. A sparse column announces itself; a full column of ids that
match nothing is only wrong the moment something compares it to something else.
Now 97.6% and 100%, zero orphans. *(Log 173.)*

**My own second attempt was worse than the first.** Matching doctors to
employees by first name matched "Dr. Prakash Rana" to Prakash Adhikari — a
different person — and attributed one clinician's patients to another. The seed
now hires its doctors instead of guessing. *(Log 173.)*

**A null is not "no match", it is "match the nulls".** A caller with no user id
would have matched every unattributed encounter and collected a relationship
with each of those patients — reachable, because a portal principal has no
`uuid` at all. Third time this project has met that shape. *(Log 176.)*

**A doctor could not use the application.** 124 permission checks default to
`Scope.FACILITY`; `doctor`, `nurse` and `lab_technician` all carry
`max_scope = department`, a ceiling. A doctor was refused **seven of nine**
clinical endpoints, including the patient list. And the missing queryset
narrowing on scheduling was invisible precisely *because* the check refused
everybody who would have needed it — a broken control hiding a missing one.
*(Log 181.)*

**A permission class that was listed and never ran.** `PatientResultsView` is a
plain `APIView`, and DRF runs object permissions only from `get_object()`. The
class read exactly like enforcement and did nothing: 200 with the switch on,
200 with it off. *(Log 183.)*

---

## What is enforced, and what is not

| | |
|---|---|
| Encounters, prescriptions, diagnostic orders, patient results, ICU stays | relationship enforced |
| Admissions | class attached, but **cannot refuse** — see below |
| Patient identity and safety data | organization-wide **by design**, Phase 1 |
| Invoices, sales, till sessions, dispensings | facility-filtered, Phase 1 |

**The admission check cannot refuse anybody**, and this is a design finding
rather than an oversight. `_admission` grants a relationship for any live
admission the caller's facility scope reaches, and the queryset shows only
those — so every admission somebody can see is one they have a relationship
with. Measured: five live admissions, two in scope, zero without a
relationship. For inpatients, **facility scope is the relationship**, and it
should be. It starts mattering the day `_admission` narrows to a ward.

---

## Verification, and its limits

**81 tests**, including 12 new invariant tests for this phase, and the seed
suite twice through.

The switch is now **on for the `manakamana` demo tenant**, which is
multi-facility and therefore the case this is for.

**The seed suite used not to test this**, and now does. Every other seed runs
at the service layer, below the permission classes — so a green suite proved
enforcement did not break the domain logic and nothing about who can open what.
`seed_access_demo` drives the real API as real users in both switch positions
and prints a table of what each role sees.

It found a real gap on its first run: **diagnostic orders were narrowed on
`retrieve` and not on `list`.** The object check refused a stranger's order
while the list still showed all 76 — and a list of orders is a list of who is
being investigated for what. That survived four commits of careful work and a
hand-written probe of the same endpoint, because the probe asked "can I open a
stranger's order?" and nobody asked "how many can I see?" 

---

## Outstanding

- **119 `HasPermission.of` call sites** still on the strict facility default.
  They gate writes and administrative actions where a facility floor is often
  right, and each needs the question asked individually.
- **The recency window is a guess.** Ninety days covers an outpatient episode;
  a patient on annual review has a twelve-month cycle. Expect it to become
  per-speciality.
- **Emergency departments may need a standing exemption.** A patient arriving
  by ambulance has a relationship with nobody, and a queue that fills with the
  one case everybody agrees is fine is a queue nobody reads.

---

## The thing to watch

If the review queue fills with legitimate overrides, **the rules are wrong, not
the people.** The queue is the instrument for tuning the relationship windows,
and the temptation will be to read it as a discipline problem instead.
