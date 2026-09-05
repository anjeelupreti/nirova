# Access control, Phase 2 — development plan

**Status:** steps 0, 1 and 3 done. Nothing is enforced yet — step 2 is
what turns it on.
**Depends on:** [PHASE1.md](PHASE1.md) · **Design:** [ACCESS_DESIGN.md](ACCESS_DESIGN.md)

Phase 1 laid the vocabulary and closed a clinical safety gap. Phase 2 is the
substantive half: it decides who may open a patient's clinical record, and it
is the first change in this project that alters what clinicians see on an
ordinary working day.

---

## What this changes, in one paragraph

Today a clinician sees every patient at their facility and nobody anywhere
else. After Phase 2 they see **every patient they are treating, anywhere in the
organization** — and for anyone else they must break glass, which is instant,
takes a reason, and lands on somebody's review queue.

**It widens as much as it narrows.** A consultant covering two sites currently
cannot open their own patient's record at the other one without an
organization-scoped role. That is a real daily obstruction, and it is the
reason clinicians end up holding scopes far wider than their job needs.

---

## The one idea

Everything below is an implementation of a single sentence:

> **Clinical access follows a care relationship, and browsing is not the same
> act as looking something up.**

A *care relationship* is not administered — nobody maintains a list. It falls
out of records the system already keeps: admissions, appointments, orders,
prescriptions, ward assignments. That is the only kind of access control that
stays accurate, because it is a by-product of doing the work.

*Browsing* means asking for a list. It narrows to the relationship.
*Looking up* means naming a specific record — a prescription reference a
patient has handed over. It stays open to the role that needs it and is
logged, because **the patient presenting the reference is the relationship and
is the consent.**

---

## The good news from surveying the code

Every field the relationship check needs already exists and is already indexed.
Nothing new has to be recorded; it only has to be read.

| Source | Links a user to a patient by | Index |
|---|---|---|
| `Encounter` | `provider_uuid`, `status` | `(provider_uuid, -started_at)` |
| `Admission` | `patient`, `facility`, `status` | present |
| `Appointment` | `provider_uuid`, `scheduled_for`, `status` | present |
| `DiagnosticOrder` | `ordered_by_id`, `status` | present |
| `Prescription` | `prescriber_id`, `status` | `(prescriber_id, -prescribed_at)` |
| `NurseAssignment` | `nurse_id`, `admission`, `is_active` | `(nurse_id, assigned_date, shift)` |

---

## Step 0 — measure the sources *(done, 6 September 2026)*

The plan called for measuring `provider_uuid` coverage before enforcing
anything. It was the most useful hour of the phase, and it found worse than
sparseness.

| field | before | after |
|---|---|---|
| `Encounter.provider_uuid` | **20.5%** | 97.6% |
| `Appointment.provider_uuid` | 100%, **every id a placeholder** | 100%, all real |
| `DiagnosticOrder.ordered_by_id` | 100% | 100% |
| `Prescription.prescriber_id` | 98.3% | 98.4% |
| `NurseAssignment.nurse_id` | 100% | 100% |

Encounters at 20.5% is bad; appointments at 100% was worse. Every one of those
ids was `00000000-0000-4000-8000-…` — a provider who was not a user, not an
employee and not a member. Every appointment-based relationship would have
resolved to nobody, silently. **A sparse column announces itself; a full column
of ids that match nothing does not.**

Fixed at source — emergency arrivals and inpatient admissions now attribute a
provider, and the seed hires its doctors instead of inventing them — plus a
one-off repair of existing rows, since idempotent seeds will not rewrite what
they already wrote. Details in development log 173.

A test now asserts both halves as a floor: coverage, and that no id fails to
name somebody who can sign in.

**Step 4 is now safe to reach.**

---

## Steps

### Step 1 — `has_care_relationship` *(done, 6 September 2026)*

`apps/rbac/relationships.py`.

```
has_care_relationship(user_id, patient, authorization) -> Relationship | None
```

Returns *why*, not just *whether* — the reason is written onto the access log
and shown to the user ("you are seeing this because you admitted them"), and a
boolean cannot carry that.

True when any of these hold:

1. **An open encounter or admission** at a facility the caller's scope reaches.
2. The caller is the **prescriber, orderer, triaging clinician or note author**
   on any record for that patient that is still active.
3. The caller has an **appointment** with them — from 1 day before to 7 days
   after, so a clinician can prepare and can write up afterwards.
4. The caller is the **assigned nurse** on an active admission.
5. An **active break-glass grant** (step 3).

**Design notes.**

*Cached per request*, exactly as `get_authorization` already is. It touches six
tables and clinical reads are the hottest path in the application.

*Ordered cheapest-first and short-circuited.* Most calls are a clinician
opening a patient they admitted an hour ago, which the first check answers.

*Recency windows, not "ever".* A doctor who saw somebody in 2019 does not have
a relationship with them today. Default 90 days from the last touch,
configurable per organization.

*Auditor and organization-scoped clinical roles are exempt*, and the exemption
is explicit rather than a side effect. Oversight is the job.

### Step 2 — enforce `patient.clinical.read`

Granted in Phase 1, enforced here.

- A new permission class, `HasClinicalAccess`, which checks the permission and
  then the relationship.
- Applied to: encounters, clinical notes, diagnoses, vitals, diagnostic
  results, ICU observations, the inpatient record.
- **Not** applied to identity or safety data. Those stay organization-wide, and
  Phase 1 exists to make that safe.

The refusal names the way out: *"You are not currently treating this patient.
Open their record in an emergency by giving a reason."* — not a bare 403. A
control whose refusal does not say what to do next is one people route around.

### Step 3 — break-glass *(done, 6 September 2026)*

`BreakGlassGrant` — patient, user, reason, granted at, expires at, reviewed by,
reviewed at, outcome.

- **Immediate.** No approval step. The case for it is an unconscious patient in
  a corridor.
- **Time-boxed**, 4 hours, one named patient.
- **Reason required**, free text, minimum length enforced — "emergency" is not
  a reason.
- Writes an audit event at **critical** severity.
- Raises a **`CRITICAL` notification** to holders of `privacy.review`, which the
  notification centre (§101) already delivers and already refuses to let anybody
  silence by preference.
- Appears on a review queue until signed off.

> **The review queue is the control. The override is only the mechanism.** A
> break-glass nobody reviews is theatre, and this is the step most likely to be
> quietly dropped for looking like paperwork.

### Step 4 — browse narrows, lookup stays open

| Endpoint | List | Lookup by reference |
|---|---|---|
| `/clinical/prescriptions/` | relationship | **open** to `prescription.dispense`, logged |
| `/diagnostics/orders/` | relationship | open to the performing lab, logged |
| `/clinical/encounters/` | relationship | relationship |
| `/billing/invoices/` | facility *(Phase 1)* | facility |

The prescription row is the whole point, and the reason Phase 1 deliberately
left that list unfiltered with a test saying so. A pharmacy cannot enumerate
every prescription in the group; when a patient presents one, it opens.

### Step 5 — the review surface

- A queue on the staff console for `privacy.review`: who broke glass, for whom,
  why, whether it has been signed off.
- Signing off records an outcome — appropriate, needs a word, escalate.
- The `CRITICAL` notification links straight to the thread.

### Step 6 — switchable per organization

A single-site clinic gets nothing from any of this and pays the complexity.
`require_care_relationship` as a config setting, defaulting **on** for
multi-facility organizations and **off** for single-facility ones.

This is the same position §17 already takes on segregation of duties, which a
two-person clinic cannot enforce because there is nobody to segregate.

---

## Verification

Following the project's method: seeds that run the real service layer and
narrate what they expect beside what they got.

`seed_access_demo` walks the cases that decide the design:

1. A doctor opens their own patient at **their own** facility. Allowed.
2. The same doctor opens **the same patient at the other site**. Allowed —
   and this is the widening, invisible unless it is stated.
3. The same doctor opens **a stranger**. Refused, with the sentence that says
   how to proceed.
4. They break glass. Allowed; the reason is recorded; a `CRITICAL` notification
   reaches the privacy officer **within the same request**.
5. The grant expires. The next read is refused again.
6. A pharmacy counter **lists** prescriptions — sees only the relationship.
7. The same counter **looks one up by reference** — sees it, and the read is
   logged against the patient.
8. An auditor reads everything and is never asked for a relationship.
9. A nurse opens a patient on their ward. Allowed. Opens one on another ward.
   Refused.

Plus invariant tests, one per rule, in the existing file.

**Plus a performance floor**, because this is the first change that could make
the application feel slow: the relationship check must not add more than one
round trip to a clinical read. Asserted with `assertNumQueries`, not measured
by feel.

---

## Order of work

| | Step | Risk |
|---|---|---|
| 1 | `has_care_relationship` + tests, called by nothing | none — dead code until step 2 |
| 2 | Break-glass model, service, notification | none — nothing enforces yet |
| 3 | Review queue and screen | none |
| 4 | **Enforce on encounters only**, behind the org switch, default **off** | contained |
| 5 | Turn it on for the demo tenant; run the seeds; watch what breaks | the real test |
| 6 | Extend to results, ICU, inpatient | contained |
| 7 | Narrow the prescription and order lists | contained |

**Steps 1–3 change nothing that is running.** The whole risk sits in step 5,
and it is deliberately reached with the escape hatch, the review queue and the
notification already built — so the first time a clinician is refused, the way
out exists and somebody is watching it.

---

## What I expect to go wrong

Written down now so it is recognised rather than rationalised.

**Break-glass will be used routinely.** If the review queue fills with
legitimate overrides, **the rules are wrong, not the people.** The queue is the
instrument for tuning the relationship windows, and the temptation will be to
read it as a discipline problem instead.

**The 90-day recency window is a guess.** A patient on annual review has a
12-month cycle. Expect to make it per-speciality or drop it in favour of
"encounter still open, or seen since the last discharge".

**Emergency departments may need a standing exemption.** A patient arriving by
ambulance has no relationship with anyone. Triage may need to create one on
arrival rather than making every ED read a break-glass — otherwise the queue
fills with the one case everybody agrees is fine.

~~**`provider_uuid` may be sparsely populated**~~ — *measured and fixed, see
Step 0. It was worse than predicted: not merely sparse but, for appointments,
fully populated with ids that named nobody.*

---

## Not in Phase 2

- Patient-facing "who looked at my record" — Phase 3.
- Access-pattern analytics — Phase 3.
- Consent and record release (§129) — needs all of the above first.
- Sealed envelopes: records a patient asks to be hidden from specific staff.
  Real, and out of scope until the ordinary case works.
