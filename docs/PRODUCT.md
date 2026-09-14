# What Nirova is for

*Written 14 September 2026, after a pass over the running system as five
different people. The complaint that prompted it: "you become confused on where
to do what… it looks purposeless." That is a fair reading of the console, and
this document is the answer — what the product is for, who opens it every day,
what it must do for each of them, what it does today, and what is missing
before any of them could depend on it.*

---

## 1. The purpose, in one paragraph

**Nirova runs a Nepali healthcare business through its day, and answers for
that day afterwards.** Through the day: who is waiting, who is with which
doctor, which bed is free, what was dispensed from which batch, what the
patient owes and how they paid. Afterwards: what it cost, what it earned, who
opened whose record, what the tax office and the ministry are owed, and what
the stock ledger says versus what is on the shelf. Everything else the product
does is in service of those two sentences.

**What makes it different from a hospital "HMIS" tender build.** Four things,
and they are the pitch:

1. **Each customer's data is in its own database.** Not a `tenant_id` column —
   a physically separate database per organization. A clinic that has been
   burned by a shared system understands this immediately.
2. **Access is by care relationship, not by job title.** The vocabulary exists
   (`ACCESS_DESIGN.md`), break-glass is recorded and reviewed, and every record
   opened is logged against a name.
3. **It is Nepali by construction, not by translation.** Bikram Sambat dates
   and fiscal years, PAN/VAT invoices with gapless numbering, SSF and PF in
   payroll, eSewa and Khalti at the counter and in the patient's phone, and a
   patient application in Nepali.
4. **It is one system, not seven.** The prescription a doctor writes is the
   dispense the pharmacy makes, is the charge on the invoice, is the line in
   the stock ledger, is the figure in the sales report. That chain is the
   product; the screens are how people reach it.

**What it is not.** It is not a PACS, not a LIS instrument driver, not an
accounting package to replace a chartered accountant's software, and not an
insurance clearing house. It talks to those.

---

## 2. Who buys it

Five shapes of customer, in the order they are worth pursuing.

| | Who | What they must have | What they will not pay for |
|---|---|---|---|
| **A** | **Retail pharmacy** (1–3 counters) | Fast counter, batch and expiry, supplier and purchase, VAT invoice, daily cash-up | Wards, theatre, HR |
| **B** | **Clinic / polyclinic / dental** (2–15 chairs) | Appointments, queue, consultation notes, prescriptions, billing, a patient app | ICU, blood bank, payroll |
| **C** | **Diagnostic lab / imaging centre** | Order to sample to result to release, reference ranges, printable reports, referrer share | Beds, dispensing |
| **D** | **Hospital, 20–100 beds** | All of the above, plus wards, emergency, theatre, ICU, insurance claims, HR and payroll | Warehouse, distribution |
| **E** | **Group** — several of the above under one owner | Everything, plus cross-site reporting, per-site permissions, one bill | — |

The wedge is **A and B**: they decide in a week, they pay monthly, and they
are the ones currently running a paper register beside a pirated copy of
something. C and D are the revenue; E is the reference customer.

**The trap to avoid.** A hospital-shaped product shown to a pharmacy loses the
sale in ten seconds — a counter assistant who sees "Wards", "ICU" and "Theatre"
in the sidebar concludes it is not for them. This is why modularity is not a
pricing nicety: **it is how the same product reads as purpose-built to five
different buyers.**

---

## 3. The people who open it every day

This is the part the console currently gets wrong. Each of these is a person
with a shift, not a set of endpoints.

### Receptionist / front desk
**Their day.** Register arrivals, find the returning patient, book and move
appointments, take the consultation fee, answer "how long is the wait", print
a card, chase who did not attend.
**Today.** Patients, Appointments and Queue are all good; the queue board is
genuinely live.
**Missing.** One screen that *is* the front desk — arrivals, today's diary,
unpaid consultations and the phone list in one place, instead of three tabs.
Nothing tells them a patient has an unpaid balance before they send them in.

### Doctor (outpatient) / dentist
**Their day.** See the list; open the patient; read what happened last time in
ten seconds; examine; order labs; prescribe; sign the note; answer results that
came back overnight; write the referral.
**Today.** The consultation screen exists and is good. **`My workspace` is
empty for a doctor** — it lists approvals, which is a manager's idea — and the
sidebar offers them Emergency, Wards, ICU, Theatre, Blood bank, Attendance and
Facilities, which an outpatient doctor never touches.
**Missing, in order of how much it hurts:** a real clinician's workspace (my
clinic today, results to acknowledge, notes to sign, my inpatients);
**prescription templates and order sets** — nobody types "Amoxicillin 500 mg,
1 capsule three times daily for 5 days, after food" forty times a day;
a dental chart for a dentist, which is the whole record in that practice.

### Nurse
**Their day.** Take handover, know which of her patients needs seeing first,
record observations when they fall due, give and chart medicines, escalate a
deteriorating patient, hand over.
**Today.** **The nurse workspace is the best screen in the product** — her
patients, this shift, NEWS2, what is due, act inline. This is the model every
other role should be built to.
**Missing.** The medication administration record is thin: every bed reads "no
medicines charted". Task assignment between nurses. A handover that produces a
document.

### Pharmacist / counter assistant
**Their day.** Open the till; sell; dispense against prescriptions; check
expiry; receive stock; count; close the till and reconcile.
**Today.** The counter is excellent — scan-first, one keystroke to payment, a
real till session, returns and cash-up. Batch tracing now reaches every person
a batch touched.
**Missing.** Dispensing *against a prescription written in this system* is not
on the counter screen — the link the product is supposed to make. No
substitution prompt, no interaction warning at the counter, no customer
account for a regular.

### Laboratory technician
**Their day.** Collect, receive, run, enter results, flag criticals, release,
print.
**Today.** The whole path exists, including critical-value escalation.
**Missing.** Result entry is per-test typing; no analyser import, no result
templates, no delta check against the patient's last value.

### Cashier / accountant / owner
**Their day.** Take money, settle bills, chase debtors, close the day, watch
the margin, pay the staff, file the VAT.
**Today.** Billing, counter, finance, payroll and now the sales report are all
real. Invoices are gapless and BS-dated.
**Missing.** Receivables ageing is a report, not a workflow — nobody is
*assigned* to chase it. No dunning, no statements, no patient account
statement to hand over.

### Owner / administrator
**Their day.** Is today normal? Is anything stuck? Who is asking me for
something? Are we making money? Is anyone doing something they shouldn't?
**Today.** A dashboard with real figures, an approvals inbox, audit, access
review.
**Missing.** Anything forward-looking. Every number is "what happened"; none is
"what is about to happen".

### Patient
**Their day.** When is my appointment, what did the test say, what do I owe,
what am I taking, how do I pay.
**Today.** All five, in Nepali, in Bikram Sambat, with eSewa. This is the most
finished thing in the product.
**Missing.** Reminders that reach the phone (there is no SMS or email delivery
at all), and teleconsultation.

---

## 4. What stands out today

Said plainly, because a pitch needs it: database-per-tenant; an audit trail
with break-glass; a counter that a pharmacy would actually use at speed; a
nurse workspace built around a shift rather than a table; a batch traced from
the supplier's receipt to the person who took the medicine; Bikram Sambat and
Nepali throughout the patient app; wallet payments verified server to server;
385 tests that assert behaviour rather than coverage, including guards that
read the frontend and fail when the rail and the API disagree.

---

## 5. Where it is not yet dependable

The question asked was: *does this give accurate forecast, broadcast,
visualisation, data management and reliability?* Honestly, per area:

### Forecasting — **absent**
There is no projection anywhere in the product. `reorder_suggestions` compares
free stock to a **static** `reorder_level` typed by a person; it does not look
at consumption. Nothing predicts tomorrow's attendance, next month's revenue,
when a batch will run out, which bed will free up, or which invoices will age
past 90 days. Everything is a rear-view mirror.
**Needed:** consumption-based reorder (average daily usage × lead time +
safety), revenue and footfall projection from the trailing period with the
figure's own derivation shown, expiry-at-risk value, and cash-collection
forecast from the ageing curve.

### Broadcast and communication — **in-app only**
`NotificationChannel` declares EMAIL and SMS. **Nothing sends either.** A
critical lab value escalates to a bell icon that only exists while the person
is looking at the console. There is no announcement from the owner to staff, no
message from the platform to tenants, no reminder to a patient, and no chat
between a doctor and a nurse about a patient.
**Needed:** a delivery layer (email now, SMS via a Nepali gateway, web push),
tenant-wide announcements, platform→tenant broadcast, and a real-time channel
so the queue board, the bed board and notifications stop polling.

### Visualisation — **the system is good, its use is not**
There is a validated chart library (validated palette, table view on every
chart, dark mode, "no comparison" rather than a fake zero). But most screens
are still tables, the dashboard is the same for a matron and an accountant,
and there is no drill-through: a number never takes you to the rows behind it.
**Needed:** a composed dashboard per role; every figure clickable through to
its rows; saved filters; a trend on anything that has history.

### Data management — **strong at the core, weak at the edges**
Import exists with column mapping and duplicate review. Ledgers are
append-only where it matters. But: no self-service export of *everything* a
tenant owns, no retention or archival policy, no scheduled backup a customer
can see or restore from, no merge tooling beyond patients, and master data
(services, price lists, test catalogues) is edited without review or history in
most places.
**Needed:** "download everything" per tenant, verified restore, a data-owner
view of what is stored and for how long.

### Reliability — **unproven rather than bad**
One backend process, one worker, one database server, no queue retry policy,
no rate limiting, no circuit breaker around the wallet gateways, no health
budget or SLO, and no offline mode for a counter that loses its connection —
which in Nepal it will, daily.
**Needed:** retries and dead-lettering, rate limits, an honest status page,
and — the big one for a pharmacy — an offline-tolerant counter.

### Commercial machinery — **half-built, and the wrong half is missing**
The catalogue is real: `Module`, `Feature`, `Plan`, `PlanModule`,
`PlanFeature`, limits, entitlement resolution, metering. But the platform
console is **read-only** — plans can be seeded and read, never edited — and the
console **never asks whether a module is included**: `hasModule` exists in the
session hook and is called in exactly **zero** places. Every tenant sees every
module regardless of what they bought. There is no leads pipeline, no help
desk, no task board, no tenant communication, and no usage-based invoice.

---

## 6. The modular answer

**The rule, already written and not yet obeyed:** never branch on a plan's
name; ask whether a capability is entitled. What changes is that the *console*
starts asking, and the platform team can *edit* what the answer is.

### Module map

| Tier | Modules |
|---|---|
| **Core** (never sold separately) | identity and access, organization and facilities, patients, audit, notifications, settings |
| **Front office** | appointments, queue, consultation, patient portal |
| **Clinical** | inpatient (wards), emergency, theatre, ICU, nursing |
| **Diagnostics** | laboratory, radiology, blood bank |
| **Supply** | pharmacy dispensing, counter (POS), inventory, procurement |
| **Money** | billing, finance, insurance claims |
| **People** | HR, attendance, payroll |
| **Oversight** | reports, analytics, advanced analytics |
| **Add-ons** | telemedicine, API access, data import, multi-site |

### Plans

| Plan | For | Modules |
|---|---|---|
| **Counter** | retail pharmacy | core + supply + billing |
| **Practice** | clinic, dental, single doctor | core + front office + billing + light supply |
| **Diagnostics** | lab or imaging centre | core + diagnostics + billing |
| **Hospital** | 20–100 beds | everything but add-ons |
| **Group** | multi-site | everything, multi-site, API |

Every plan carries limits (facilities, users, patients, storage) and every
module can be added to any plan for a price. **Pricing, modules, features and
limits are all editable by the platform team in the console** — that is the
work, not the model.

---

## 7. The platform space we need

Not a read-only admin. The vendor's own operating system:

- **Catalogue editor** — modules, features, limits, plans, prices, trials,
  versions. A plan change must never silently strip a live tenant: changes are
  versioned and applied on renewal unless explicitly migrated.
- **Tenant lifecycle** — provision, trial, activate, suspend, restore, migrate
  plan, with the effect on entitlements visible before it is applied.
- **Usage and revenue** — MRR, churn, trials converting, usage against limits,
  who is about to hit one (which is a sales signal, not an alarm).
- **Leads and pipeline** — a kanban from enquiry to demo to trial to paid, fed
  by the public registration form.
- **Help desk** — tickets from tenants, assignment, SLA, and the reply going
  back into the tenant's own console.
- **Broadcast** — an announcement to every tenant, or to one plan, or to one
  organization, shown in their console and sent by email.
- **Tasks** — the vendor's own board: onboarding a customer, a data import, a
  training session.

---

## 8. The workspace doctrine

**Every role gets a workspace built like the nurse's.** One screen that opens
on the person's own day, shows what is due, and acts in place:

- **Front desk** — arrivals, today's diary, unpaid consultations, calls to make.
- **Doctor** — my clinic now, results to acknowledge, notes to sign, my
  inpatients, referrals waiting.
- **Nurse** — as built.
- **Pharmacy** — prescriptions waiting to dispense, short stock, expiring, the
  till.
- **Laboratory** — collected, awaiting result, criticals unacknowledged.
- **Accounts** — money in today, unpaid invoices ageing, claims rejected.
- **Owner** — the day against yesterday, what is stuck, what needs a decision.

And the sidebar becomes **their day in order**, not the module list: the
current rail shows a dentist the ICU. The rail must be assembled from the
person's role, their permissions, and the tenant's modules — all three.

---

## 9. Templates — clear for the patient, complete for the record

A prescription and a report are the two documents a clinician produces dozens
of times a day, and both are typed from scratch today.

**A prescription template** carries: drug, strength, form, dose, route,
frequency (with the plain-words rendering the patient app already has),
duration, quantity to dispense, PRN indication, instructions, and follow-up.
Saved per doctor and per organization ("URTI, adult", "Post-extraction"), and
applied as a starting point, never silently.

**A report template** carries: the sections, the normal-findings sentence for
each, the fields that must be filled, and the footer the hospital is required
to print. Laboratory result entry gets the same treatment through panels.

**Two audiences, one document.** What the patient reads — plain words, Nepali,
how many and when — and what the record keeps — codes, quantities, who signed
it, when, against which encounter.

---

## 10. What gets built, in order

Each phase ends with something a customer can see.

**Phase 7 — Modular, and sellable.** Catalogue editor in the platform console;
module gating enforced in the rail, the routes and the API; plan change with a
preview of what it adds and removes; the tenant sees what they have and what
they could add.

**Phase 8 — Workspaces and the rail.** A workspace per role on the nurse's
pattern; the sidebar assembled from role + permission + module; drill-through
from every dashboard figure.

**Phase 9 — Templates and clinical depth.** Prescription templates and order
sets; report templates; the medication administration record completed; the
dental chart.

**Phase 10 — Reach.** Email and SMS delivery; announcements; patient
reminders; a real-time channel for the boards and notifications; internal
messaging about a patient.

**Phase 11 — Forward-looking.** Consumption-based reorder; revenue, footfall
and collection projection; expiry-at-risk; every projection carrying its own
derivation.

**Phase 12 — The vendor's own desk.** Leads, help desk, tasks, tenant
broadcast, usage and revenue analytics.

Reliability work — retries, rate limits, backup and restore, the offline
counter — is not a phase. It is a standing item, and the offline counter is
scheduled inside Phase 10 because a pharmacy in Nepal will not buy a counter
that stops when the line drops.
