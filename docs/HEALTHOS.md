# Nirova as a health OS: standards, data, and the single point

*Written 15 September 2026, against the running system. The brief: "analyse
international and national standards, data management, real-time communication
… cover every corner … a proper single point for every HealthOS needer … no
complaints should arise from clients about mismanagement, lack of proper
rules, zero system."*

This document is the audit and the plan. It is deliberately unflattering
where the product is thin: a gap named here is a gap somebody can close, and
one hidden here is a complaint arriving later from a customer.

Companions: [PRODUCT.md](PRODUCT.md) (who it is for, what each person needs),
[ACCESS_DESIGN.md](ACCESS_DESIGN.md) (who may read a record),
[IMPLEMENTATION_CHECKLIST.md](IMPLEMENTATION_CHECKLIST.md) (what is done).

---

## 1. What "a single point" has to mean

Not one screen. One **graph**: every participant — person, place, product,
service, document, payment, event — is a node the others can reach, with one
identity, one vocabulary, one clock, one audit trail, and one place each is
configured. A system fails the "single point" test when the same fact exists
twice with no arrow between the copies: a drug on a prescription that is not
the drug in the stock ledger, a bed on a board that is not the bed on the
bill, a doctor in the rota who is not the doctor on the report.

The five properties this document measures everything against:

| Property | The question a customer actually asks |
|---|---|
| **Connected** | "If I change it here, does it change everywhere it appears?" |
| **Coded** | "Will an insurer, a ministry, or another hospital understand this record?" |
| **Timely** | "Does the screen know before I do?" |
| **Accountable** | "Who did that, when, and on whose authority?" |
| **Configurable** | "Can *we* change it, without you?" |

---

## 2. Standards: what applies, where we stand

### 2.1 International

| Standard | What it governs | Where it binds us | State today | Gap and priority |
|---|---|---|---|---|
| **HL7 v2.x** | Messaging between hospital systems, analysers, PACS | Any lab analyser, any radiology modality, any referral to a bigger hospital | **None.** `lab_analyzer_interface` exists as a *plan feature* only (`catalog/keys.py`) | Needed before the first lab with an analyser. **P1 for C-type buyers** |
| **HL7 FHIR R4** | Modern API representation of clinical records | Patient app ecosystems, national exchanges, any integration a large customer asks for | **None built.** `fhir_api` is a sellable flag; `UUIDModel` was written with FHIR ids in mind (`common/models.py`) | A read-only FHIR facade over Patient, Encounter, Observation, MedicationRequest, DiagnosticReport. **P2** |
| **SNOMED CT** | Clinical terms (findings, procedures) | Structured diagnoses and problem lists | **None** | Optional second code beside ICD. **P3** (licensing cost; ICD first) |
| **ICD-10 / ICD-11** | Diagnoses, morbidity reporting | Ministry reporting, insurance claims, mortality returns | **Partial**: `Diagnosis.icd10_code` and `Condition.icd10_code` exist, optional, **no code table, no validation, no search** | Ship an ICD-10 reference table with search-as-you-type and a "code it" queue. **P1** |
| **LOINC** | Laboratory observation identifiers | Any result leaving the building; analyser interfacing | **None.** `TestDefinition.code` is local | Add `loinc_code` to `TestDefinition`, seeded for the common panel. **P2** |
| **DICOM / PACS** | Imaging storage and viewing | Any imaging centre | **None.** `dicom_pacs` is a plan flag; radiology results are narrative text | Study-level link-out to a PACS viewer first; not a PACS. **P2 for C** |
| **IHE XDS / XCA** | Document exchange between institutions | Referrals, discharge summaries between hospitals | **None** | After FHIR. **P4** |
| **ISO/IEC 27001, ISO 27799** | Information security management for health | Any tender, any group customer | **Practices, not certification**: MFA (`identity/mfa.py`), sealed secrets (`common/sealing.py`), per-tenant databases, full audit (`apps/audit`), break-glass review | Write the ISMS documents: asset register, risk log, access policy, incident and breach runbook, DR test record. **P1 — it is paperwork, and it wins tenders** |
| **ISO 13485 / IEC 62304** | Software as a medical device | Only if we ever compute a diagnosis or a dose | **Not applicable today** — deliberately: the system records decisions, it does not make them | Keep it that way until a clinical-decision feature is built, then this becomes a programme, not a sprint |
| **WCAG 2.2 AA** | Accessibility | Public-sector customers, and the right thing | **Partial**: semantic components, focus rings, contrast solved per palette (65 assertions) | Keyboard path through every clinical flow; screen-reader pass on the ward board. **P2** |
| **GDPR-shaped rights** | Access, rectification, erasure, portability | Any customer with foreign patients or donors | **Partial**: access log yes, export of one patient's record no, erasure no | A "give me everything about this patient" export, and a retention/erasure policy. **P2** |

### 2.2 Nepal

| Requirement | Who enforces | State today | Gap and priority |
|---|---|---|---|
| **PAN/VAT invoice rules; gapless, immutable numbering; credit notes; BS fiscal year** | Inland Revenue Department | **Strong**: `billing/fiscal.py`, gapless numbering, credit notes instead of edits, dual-calendar dates | Keep; add the IRD-format sales register export. **P2** |
| **IRD-approved billing software (registration + audit trail requirements)** | IRD | **Unverified.** We behave like an approved system; we are not one | Materials pack and application; it is a checkbox in every serious sale. **P1 (commercial)** |
| **Health Insurance Board (HIB) claims** | HIB | **Modelled, not wired**: `apps/insurance` has payers, government schemes, policies, pre-authorisation, claims — but no HIB file format or portal submission | The HIB package/claim export in their format. **P1 for D-type buyers** |
| **HMIS / DHIS2 monthly returns** | MoHP (ministry) | **None.** The data exists; the returns do not | The standard monthly HMIS aggregates as a report and an export. **P1 — every hospital files these by hand today** |
| **Nepal Medical Council / Nursing Council registration** | NMC / NNC | **Good**: credentials with expiry block prescribing (`hr` credentials, seen on the profile) | Keep; add council-number validation format. **P3** |
| **SSF, PF, CIT, TDS payroll** | SSF, IRD | **Strong**: `apps/payroll`, statutory rates as data | Annual rate-change routine and the SSF e-return format. **P2** |
| **eSewa / Khalti / connectIPS; NRB rules** | NRB, providers | **Two of three**: eSewa and Khalti live, sealed keys, return flow | connectIPS and Fonepay for hospitals that bank differently. **P3** |
| **Individual Privacy Act 2075 / Rules 2077** | Government | **Partial**: consent flags for outreach, access logging, break-glass review, per-tenant isolation | Written retention schedule, a breach-notification runbook, and a patient-facing "who read my record" answer. **P1 — the law exists and nobody has read it to us yet** |
| **Drug Act / narcotics register** | DDA | **Partial**: `ControlSchedule` on products, batch tracing | The controlled-drug register as a printable statutory report. **P2** |
| **Bikram Sambat everywhere a date is legal** | Everyone | **Done**: dual calendar, per-user preference | — |

**The honest summary.** We are strong where Nepal is specific (tax, payroll,
payments, calendar, schemes) and weak where the world is standard (coding,
messaging, exchange). That is the right way round for the first fifty
customers and the wrong way round for the fifty after them.

---

## 3. The graph: every participant, and the arrows between them

```
                 ┌───────────────── ORGANIZATION (plan, modules, limits) ─────────────────┐
                 │                                                                        │
     FACILITY ── DEPARTMENT ── UNIT/WARD ── ROOM/BED          STOCK LOCATION ── BATCH ── PRODUCT
        │             │            │           │                    │             │         │
        │             │            │           └── BED ASSIGNMENT ──┼─────────────┼── STOCK ENTRY (ledger)
        │             │            │                     │          │             │
     SERVICE ── PRICE LIST ── CHARGE ── INVOICE ── PAYMENT │     DISPENSE ── PRESCRIPTION
        │                        │         │         │     │          │             │
        │                        │         │         │     │          │             │
   APPOINTMENT ── QUEUE TOKEN ── ENCOUNTER ─┴─────────┴─────┴──────────┘             │
        │                          │   │                                            │
      PATIENT ─────────────────────┘   ├── DIAGNOSIS (ICD-10) ── CONDITION ──────────┘
        │  │                           ├── DIAGNOSTIC ORDER ── RESULT ── CRITICAL ALERT
        │  ├── POLICY ── PRE-AUTH ── CLAIM ── PAYER/SCHEME
        │  ├── ADMISSION ── ROUND/OBSERVATION/TASK ── DISCHARGE SUMMARY
        │  ├── DOCUMENT (consent, report, scan)
        │  ├── CARE MESSAGE (staff discussion)          ← new, log 297
        │  └── PATIENT MESSAGE (SMS/email out)
        │
      USER ── MEMBERSHIP ── ROLE ── PERMISSION(scope) ── CARE RELATIONSHIP
        │        │
     EMPLOYEE ── CREDENTIAL ── ROSTER SHIFT ── ATTENDANCE ── LEAVE ── PAYSLIP
        │
      AUDIT EVENT (every write, every sensitive read)  ·  NOTIFICATION  ·  USAGE COUNTER
```

**What is genuinely connected today** (the product's real claim): prescription
→ dispense → batch → stock ledger → charge → invoice → payment → sales and
finance reports; appointment → queue token → encounter → diagnosis → order →
result → critical alert → notification; admission → bed assignment → daily
accrual → discharge → summary; employee → roster → attendance → leave →
payslip; every one of those writes an audit event, and every sensitive read
writes an access record.

**Arrows that are missing or thin** (each is a customer complaint waiting):

1. **Referral in/out is not a first-class journey.** `apps/referrals` records
   one, but an incoming referral does not create an appointment, and an
   outgoing one carries no packaged record.
2. **Follow-up is a date, not a loop.** `follow_up_on` is written on discharge
   and on a consultation; nothing chases it, nothing lists "due this week",
   nobody is told when it passes.
3. **Room is not modelled.** Ward and bed are; a consultation room, a theatre
   list slot and a chair in a dental practice are not. Booking a *place* is
   therefore not possible.
4. **Service ↔ clinical act is one-way.** A charge knows its service; a
   service does not know which clinical act should raise it, so missed
   charges are found by eye.
5. **Warehouse is a stock location, not a warehouse.** No bin, no pick list,
   no goods-in staging, no inter-facility requisition workflow beyond
   transfer.
6. **Patient identity across facilities is per-tenant only.** Correct for
   privacy, a problem for a group with one patient at three sites; there is
   no group-level MPI.

---

## 4. Data management

### 4.1 Where data lives
- **One database per organization** (ADR 0001). Identity and the catalogue
  are control-plane; everything clinical, financial and operational is the
  tenant's own. This is the strongest single claim in the product.
- **Identifiers**: every row carries a UUID safe to expose; MRN, invoice
  number, order reference and admission reference are human identifiers with
  their own rules.

### 4.2 Master data, and who owns it
| Master | Where | Configurable by the customer? |
|---|---|---|
| Facilities, departments, wards, beds | `apps/organization`, `apps/inpatient` | Yes, in Settings |
| Services and price lists | `apps/billing` | Yes |
| Products, batches, locations | `apps/pharmacy` | Yes |
| Tests, panels, reference ranges | `apps/diagnostics` | Yes (Configuration) |
| Payers, schemes, policies | `apps/insurance` | Yes |
| Roles and permissions | `apps/rbac` | Yes, with a permission matrix |
| Templates (prescription, discharge, report) | `apps/prescriptions`, `apps/inpatient`, `apps/diagnostics` | Yes, mine/ours |
| **ICD-10, LOINC, SNOMED** | — | **No. Not present at all** |
| Organization settings | `organization/settings_registry.py` — **9 keys today** | Yes, but the list is short |

**The configurability gap is narrower than it looks and deeper than it
sounds.** Master data is editable; *behaviour* is not. There is no way for a
customer to say "a nurse may not close a stock count", "consultations expire
after 30 minutes", "this ward needs two-person sign-off", or "our discharge
needs a pharmacy clearance and a dietician's". Roles are configurable;
**workflow is hard-coded**. That is the next real configurability step, and
it is bigger than a settings page.

### 4.3 The warehouse question
There is no analytical store. Reports (13 of them) and dashboards read the
operational tables directly, which is correct at this size and will not hold:
a year of one hospital is a few million rows, and "revenue by department by
month for three years" against live tables will eventually be slow enough to
notice — and will do it during a demo.

**The proposal, in order:** (1) keep `DailySnapshot` growing (already built,
`apps/organization/today.py`); (2) add a nightly fact table per domain —
encounters, charges, payments, stock movements, admissions — keyed by day,
facility, department, payer; (3) point trend charts and ministry returns at
those; (4) only then consider a separate analytical database. Do not start
at (4).

### 4.4 Retention, erasure, backup
- **Retention**: `DocumentCategory` carries the *idea* of retention; nothing
  enforces one. No purge job exists.
- **Erasure**: not implemented. A patient asking to be forgotten cannot be
  served, and under the Privacy Act that request is coming.
- **Backup/restore**: not in the repository as a runbook or a test. **This is
  the single largest operational risk in the product** — per-tenant databases
  make backup simple and restore *specific*, and nobody has proven a restore.
- **Export**: per-report CSV/Excel exists; a whole-organization export (the
  "we are leaving" case) does not, and a customer who cannot leave will not
  join.

### 4.5 Data quality
Present: uniqueness and reference constraints throughout, gapless invoice
numbering, append-only ledgers (stock, results, observations), maker-checker
on results and payroll. Missing: a duplicate-patient merge *review* queue
(merging exists), a "coded / not coded" diagnosis queue, and a nightly
reconciliation report (ledger vs shelf, charges vs invoices, till vs bank).

---

## 5. Real-time and communication

| Channel | Built | Gap |
|---|---|---|
| **Live screens** | Doorbell over WebSocket: queue, beds, ED, lab, ICU, notifications, patient discussion. Carries "this changed", never data; polling kept as the safety net | Ward tasks and theatre lists do not ring yet |
| **Notifications** | In-app with categories; critical reaches people whatever their preferences; delivery rows per person per channel; email and SMS with sealed credentials | No escalation ladder ("if not acknowledged in 10 minutes, tell the consultant") |
| **Patient outreach** | Appointment reminders the evening before, result-ready notices, consent-aware, no PHI in SMS, deduplicated | No bill reminder, no recall for follow-up, no two-way replies |
| **Staff ↔ staff** | Patient discussion on the record, with mentions and urgency (log 297) | No ward-level or shift-level channel; no read receipts |
| **Broadcast** | Announcements to the whole organization, optionally emailed | No targeting by role, facility or department |
| **Vendor ↔ tenant** | — | **Nothing.** No in-product help desk, no announcement from us to customers, no ticket. It is in `PRODUCT.md` as Phase 12 and it is still the biggest hole in the commercial half |

---

## 6. Corner-by-corner: coverage and gaps

| Corner | Today | The gap that will draw a complaint |
|---|---|---|
| **Entry points** (walk-in, appointment, emergency, referral, portal) | Registration, appointments, queue, ED arrivals, portal booking | Referral-in does not become an appointment; no kiosk/self-check-in |
| **Appointments** | Diary, availability, booking, reschedule, no-show, reminders | No recurring/series booking; no room or equipment booking; waiting list |
| **Follow-ups** | A date on the encounter and the discharge | Nothing lists them, chases them, or reports the ones that lapsed |
| **History / track record** | One patient page: timeline, results, medications, account, messages, discussion | No printable "whole record" pack; no cross-facility view for a group |
| **Rooms and beds** | Wards, beds, states, assignments, transfers, census, occupancy | Rooms and chairs are not entities; no housekeeping/cleaning workflow beyond a bed state |
| **Cashier** | Till sessions, sales, returns, cash-up by method, online payments | No shift handover of a till between cashiers; no petty cash |
| **Stock and warehouse** | Products, batches, expiry, locations, ledger, counts, transfers, requisition→PO→receipt | No bins/pick lists, no supplier returns, no reorder suggestion (Phase 11) |
| **Services and pricing** | Services, price lists by payer and category, discounts with approval | No package/bundle pricing, which every maternity and surgery offer uses |
| **Prescriptions** | Structured lines, computed quantity, safety checks, templates, print | No e-prescription standard, no dispense-against-prescription at the counter |
| **Reports** | 13 registered, exportable, plus finance statements | No ministry HMIS returns; no report builder; no scheduled email |
| **Templates** | Prescription, order sets, discharge, narrative reports | No lab panel report template with per-result explanation; no consent forms |
| **Broadcasting** | Announcements | No targeting; no patient-facing broadcast (e.g. "outpatients closed Saturday") beyond notifications |
| **Visualisation** | Donuts, funnels, bullets, stacked progress, sparkline-less trends; contrast-validated palettes; table view behind every chart | No trend lines over weeks yet (snapshots only began today); no drill-through from chart to list |
| **Security** | MFA, sealed secrets, RBAC with scopes, care relationships, break-glass with review, full audit, per-tenant isolation | No ISMS paperwork, no penetration test, no session/device list for a user, no IP allow-listing for admin |

---

## 7. Routing and flow doctrine (what keeps it learnable)

Already settled and worth stating as rules, because every future screen has to
obey them:

1. **The rail is the work.** Anything opened twice a year is not in it.
2. **The avatar is you**: profile, settings, sign out — nothing else.
3. **Settings is one page with sections**, and the section is in the address.
4. **Boards are per persona, composed for a job**, inferred from capability,
   overridable, remembered.
5. **Every figure opens the list behind it.** A number you cannot act on is a
   poster.
6. **A failure is stated where it sits.** Absent ≠ zero ≠ refused.
7. **Live where it matters, polling as the safety net.**

What is still missing from the flow: a **global "what needs me" inbox** that
spans modules (approvals exist; tasks, follow-ups and messages do not join
them), and **cross-linking from any figure to the record that produced it**.

---

## 8. The plan, in the order it should be done

**Phase A — the standards that unblock sales (4–6 weeks).**
1. ICD-10 reference table, search, and a "code it" queue.
2. HMIS monthly returns as reports and exports.
3. HIB claim export in the board's format.
4. ISMS pack (policies, risk log, incident and breach runbooks) and an IRD
   approval application.
5. **Prove a restore.** Backup runbook, restore drill, recorded result.

**Phase B — the loops that close (4–6 weeks).**
6. Follow-up register: due, overdue, recall messages, and a report.
7. Referral in and out as journeys, with a packaged record.
8. Dispense against prescription at the counter; missed-charge reconciliation.
9. Escalation ladder on critical notifications.

**Phase C — the analytics spine (3–4 weeks).**
10. Nightly fact tables; trends over weeks; drill-through from every chart.
11. Report builder and scheduled delivery.

**Phase D — configurability beyond master data (4–6 weeks).**
12. Workflow rules per organization: required clearances, sign-off thresholds,
    expiry windows, escalation targets.
13. Form/field configuration for the few screens that vary by specialty.

**Phase E — interoperability (6–8 weeks).**
14. Read-only FHIR R4 facade; LOINC on tests; HL7 v2 ingest for analysers;
    PACS link-out.

**Phase F — the vendor desk** (already Phase 12 in `PRODUCT.md`): help desk,
tickets, targeted broadcast, usage and revenue analytics, leads.

---

## 9. How we will know it worked

Each of these is a test somebody outside the team can apply:

- A hospital files its **monthly HMIS return** from the product, unedited.
- An insurer accepts a **claim file** produced by the product without rework.
- A customer restores **yesterday's database** in front of us, and the figures
  match the report we printed yesterday.
- A doctor codes a diagnosis in **under five seconds** with search.
- A patient asks **"who read my record?"** and the front desk answers in one
  screen.
- A nurse's **follow-up list** is empty because everybody was chased.
- A new receptionist is productive in **one shift**, without training.
- Nobody can name a figure on a dashboard they **cannot open**.
