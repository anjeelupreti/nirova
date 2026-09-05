# Who may see a patient's record

A design decision, written down because it is the kind of decision that is
expensive to reverse and dangerous to get wrong in either direction.

**Status:** decided, 5 September 2026. Phase 1 shipped — see
[PHASE1.md](PHASE1.md). Phase 2 planned — see [PHASE2_PLAN.md](PHASE2_PLAN.md).
**Supersedes:** the three options offered on 4 September, all of which were
wrong for reasons this document explains.

---

## The question

A patient of the Bhaktapur hospital, in tenant A. Can the Kathmandu pharmacy,
in the same tenant, see their data?

Measured on the running system: **yes, nearly all of it.** A `pharmacy_counter`
assistant scoped to one branch was served every patient in the organization,
all 23 prescriptions — 21 written at another facility, with drug lines — and
all 72 invoices. Refused only encounters, diagnostic orders, the ward census
and staff records.

---

## What I got wrong the first time

I offered three options: strict facility filtering, facility filtering with an
exception for undispensed prescriptions, or leaving it and relying on audit.

All three take **facility as the unit of access control.** That is the wrong
primitive, and three things found while researching this show why.

**A prescription is not tied to the pharmacy that dispenses it.**
`Prescription.facility` records where it was *written*. A patient may take a
prescription to any pharmacy — that is what a prescription is. There is no
"dispensable at" field, and adding one would be modelling a restriction that
does not exist in the world.

**Dispensing runs no safety checks at all.** `run_safety_checks` — allergies,
interactions, duplicate therapy — runs when a prescriber signs. Nothing runs
when a pharmacist dispenses. The pharmacist is the last line of defence
against a prescribing error, and in this system they have no net.

That reframes the whole question. **A pharmacist needs a patient's allergy list
and current medications.** Restricting their access without first giving them
that data would not make the system safer. It would make it more dangerous,
and it would look like an improvement.

**Facility is not how care works.** A consultant covers two sites. A patient is
admitted at one facility and followed up at another. An on-call doctor is
telephoned about a ward they have never set foot in. Every facility filter
strict enough to be worth having is one that a clinician will route around,
and routed-around controls are worse than absent ones because they produce
false confidence.

---

## What the field actually does

The established model in large systems — Epic, Cerner, the NHS Spine — is not
facility-based. It is **relationship-based**, with an emergency override.

The principles underneath it are the same ones in every health-data regime I
am aware of, whatever the jurisdiction: HIPAA's *minimum necessary*, GDPR's
*data minimisation*, ISO 27799, and Nepal's own Individual Privacy Act 2075,
which requires personal information held by an institution to be kept
confidential and used only for the purpose it was collected for.

> This document reasons from those principles. It is not legal advice, and a
> Nepali lawyer should review the finished controls before a real patient's
> record is in this system.

They come down to four rules.

**Need to know, not rank.** Access follows the job being done for *this*
patient, not seniority. A consultant has no business in the record of a patient
they are not treating.

**A care relationship is the basis for clinical access.** You may read the
record of a patient you are treating. The system knows who you are treating —
from admissions, appointments, orders and prescriptions — so it can decide this
without asking.

**Break glass, loudly.** Rigid access kills people. An unconscious patient
arrives and nobody has a relationship with them yet. So there must be an
override — available instantly, requiring a stated reason, logged, and
*reviewed by a human afterwards*. An override nobody reviews is not a control.

**Log the reads, not only the writes.** Where access cannot be narrowed, it
must be recorded. "Who looked at this record?" is the question a privacy
complaint opens with.

---

## The decision

Three changes to the model. None of them is a facility filter.

### 1. Data is tiered, and the tiers are separate permissions

Today `patient.read` grants everything about a person short of their
encounters. That conflates three different acts.

| Tier | What | Who, and why |
|---|---|---|
| **Identity** `patient.read` | Name, MRN, age, sex, phone, address, identifiers | Organization-wide. Every counter in the group has to be able to establish who is standing in front of them. Restricting this produces duplicate records, which is how somebody is given a drug they are allergic to. Logged. |
| **Safety** `patient.safety.read` *(new)* | Allergies, active medications, and the conditions that change dosing — pregnancy, renal impairment | Organization-wide for clinical and pharmacy roles. **Withholding this is the dangerous option.** Logged. |
| **Clinical** `patient.clinical.read` *(new)* | Encounters, notes, diagnoses, results, history, imaging | **Requires a care relationship, or break-glass.** This is the tier the privacy question is actually about. |

The safety tier is the part that makes the rest safe to restrict. It is
deliberately generous, and it is the smallest set of facts that prevents a
pharmacist killing somebody.

### 2. Browsing and looking up are different acts

This is the distinction that replaces facility filtering, and it is how
pharmacies actually work.

**Browsing a list** — "show me prescriptions" — is narrowed to what the caller
has a relationship with: written at their facility, ordered by them, for a
patient currently in their care.

**Looking up by reference** — "here is prescription RX-2026-000023" — is
allowed to anyone with `prescription.dispense`, and logged.

The reasoning is that the patient handed over the reference. That act *is* the
care relationship and *is* the consent. A pharmacy cannot enumerate every
prescription in the group, but when somebody presents one, it opens.

The same split applies to results, invoices and orders.

### 3. A care relationship is computed, not assigned

`has_care_relationship(user, patient)` — true when any of these hold:

- the patient has an **open encounter or admission** at a facility the user's
  scope reaches;
- the user is the **prescriber, orderer, attending or assigned nurse** on any
  active record for that patient;
- the patient has an **appointment** with the user, today or in the near
  future;
- the patient has an **active prescription or order** presented at the user's
  facility;
- the user holds an active **break-glass grant** for that patient.

Nothing here has to be maintained by an administrator. It falls out of records
the system already keeps, which is the only kind of access control that stays
accurate.

### Break-glass

Any user with `patient.clinical.read` may override the relationship
requirement by giving a reason. The override:

- takes effect immediately — no approval step, because the case for it is an
  emergency;
- is time-boxed (4 hours) and applies to one named patient;
- writes an audit event at critical severity;
- raises a `CRITICAL` notification to whoever holds a new `privacy.review`
  permission;
- appears on a review list until somebody signs it off.

**A break-glass nobody reviews is theatre.** The review list is the control;
the override is just the mechanism.

---

## What changes, by role

| Role | Today | After |
|---|---|---|
| Pharmacy counter assistant | Every patient, every prescription, every invoice in the group | Every patient's **identity**; **safety data**; prescriptions **presented to them** or written at their facility; **their own facility's** invoices and sales |
| Pharmacist | Same as counter | Same, plus safety checks now actually run at dispensing |
| Doctor | Everything at their facility | Everything for patients **they are treating**, anywhere in the group; break-glass otherwise |
| Nurse | Everything at their facility | Everything for patients **on their ward**; break-glass otherwise |
| Receptionist | Patients, appointments, front-desk billing | Unchanged — identity tier, plus their facility's appointments and invoices |
| Accountant | Invoices organization-wide | Unchanged. Money is an organization-level function |
| Auditor | Read-only everywhere | Unchanged, and explicitly exempt from the relationship requirement — that is the job |

The doctor and nurse rows are a **widening** as well as a narrowing. Today a
consultant covering two sites cannot see their own patient at the other one
without an organization-scoped role. Under this model they can, because the
relationship follows the patient rather than the building.

---

## Implementation plan

### Phase 1 — the tiers and the business records *(no clinical risk)*

1. Add `patient.safety.read` and `patient.clinical.read` to the permission
   catalogue. Grant both to every role that holds `encounter.read` today, so
   **nothing changes behaviourally on this step.**
2. Grant `patient.safety.read` to `pharmacist` and `pharmacy_counter`.
3. **Run safety checks at dispensing.** `dispense()` calls
   `run_safety_checks(patient, lines)` and refuses on a blocking warning
   without a typed override reason — the same rule the prescriber already
   faces. *This must land before anything is restricted.*
4. Facility-filter the **business** lists — invoices, sales, dispenses, till
   sessions, stock — for facility-scoped roles, via `apply_scope_filter`.
   These carry no clinical safety argument.
5. Log prescription and invoice reads through `record_patient_access`.
6. `assign_role` refuses a facility-scoped assignment naming no facility.

*Verification: seeds prove a counter assistant still dispenses a clinic
prescription, still cannot see another facility's takings, and is now refused
a dispense that would kill somebody.*

### Phase 2 — relationship and break-glass

7. `has_care_relationship(user, patient)` in `apps/rbac`, computed from
   admissions, appointments, orders and prescriptions.
8. `BreakGlassGrant` — patient, user, reason, expiry, reviewed-by.
9. `patient.clinical.read` enforced against the relationship, with break-glass
   as the escape.
10. Prescription, result and order **lists** narrow to the relationship;
    **reference lookup** stays open to the dispensing role, and is logged.
11. `privacy.review` permission, review queue, `CRITICAL` notification on every
    break-glass.

*Verification: a doctor reaches their own patient at the other site; is refused
a stranger; breaks glass with a reason; the reason appears on the review queue
and in the privacy officer's inbox within one request.*

### Phase 3 — making it visible

12. "Who looked at my record" for the patient portal.
13. Access-pattern reporting: reads without a relationship, break-glass never
    reviewed, users whose read volume is an outlier.
14. Consent and record-release (§129), which needs all of the above.

---

## What I am accepting, and the risks

**Phase 1 alone does not close the finding.** After Phase 1, a counter
assistant still sees every patient's identity and safety data organization-wide
— by design — and can still look up any prescription by reference. The clinical
narrowing is Phase 2. I am sequencing it that way because **step 3 makes
dispensing safer immediately**, and shipping restrictions before the safety net
would trade a privacy problem for a clinical one.

**Relationship checks cost queries.** `has_care_relationship` runs on clinical
reads and touches four tables. It will be cached per request, the way
`get_authorization` already is.

**Break-glass will be used routinely if the relationship rules are too tight.**
That is the failure mode to watch: if the review queue fills with legitimate
overrides, the rules are wrong, not the people. The review queue is therefore
also the instrument for tuning the rules.

**A single-site clinic gets nothing from any of this and pays the complexity.**
The relationship requirement should be switchable per organization, defaulting
on for multi-facility tenants and off for single-facility ones — the same
position §17 already takes for segregation of duties, which a two-person clinic
cannot enforce.

**None of this is legal advice.** Have a Nepali lawyer read the finished
controls against the Individual Privacy Act 2075 before real patient data is
in this system.
