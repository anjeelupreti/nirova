# Implementation Checklist

Every section of the master specification, broken down to the level of
individual features. This is the planning document: **if a capability is not a
line here, it is not scoped.**

**Legend**

| Mark | Meaning |
|---|---|
| `[x]` | Built and verified against a running stack |
| `[~]` | Section partially built — the lines below say which parts |
| `[ ]` | Not started |
| 🔷 | Architecturally provided for — the seam exists, the feature does not |

**Progress**

| | Sections | Feature lines |
|---|---|---|
| Done | 46 of 132 | 684 |
| Outstanding | 86 | 605 |

Counted by feature rather than by section, because "Hospital OS" as a single
line hid that it is forty distinct capabilities. The section-level view
flattered the position; this one does not.

676 understates the remaining work: in the later phases some lines group
several features on one row (`Cath lab · dialysis · oncology …`). Those get
expanded when the phase is picked up, not before — writing sixty speculative
lines for a module nobody has scoped yet is planning theatre.

---

## How to read this

Sections are grouped into delivery phases ordered by dependency rather than by
the specification's numbering — the section numbers are kept so every line
maps back to the source document. A phase is not a sprint; several run in
parallel once their dependencies land.

🔷 means the model or the seam is in place, so the work is building on it
rather than redesigning around it.

---

# Phase 0 — Platform core ✅

*The layer everything else stands on.*

## §2 Platform owner / SaaS control plane `[~]`

- [x] Organizations register and list
- [x] Facilities visible across all customers without opening tenant databases
- [x] Users and memberships
- [x] Subscriptions
- [x] Plans, modules, features, add-ons
- [x] Feature flags and entitlements
- [x] Usage metering
- [x] Facility change-request approval queue
- [x] Platform audit of cross-tenant actions
- [x] Platform console UI: overview, customers, subscriptions, plans
- [ ] Billing the customer (invoices to organizations, not patients)
- [ ] Payments and dunning
- [ ] Revenue reporting (MRR movement, cohorts)
- [ ] Customer success workspace
- [ ] SaaS CRM (see §5)
- [ ] Support tickets and knowledge base
- [ ] System health and platform monitoring console
- [ ] API key management
- [ ] Storage and backup administration
- [ ] Release and migration console
- [ ] Announcements and product notifications

## §3 Platform executive dashboard `[~]`

**SaaS KPIs**
- [x] Total, active, trial, suspended, cancelled organizations
- [x] Facilities by type across the estate
- [x] MRR and ARR, normalised across billing intervals
- [x] Add-ons included and discounts applied
- [x] Expansion MRR separated from plan MRR, with its share
- [x] MRR by plan and by billing interval
- [x] Revenue concentration — the largest customers and their share
- [x] Trial value reported beside MRR, never inside it
- [x] Entitled-but-unbilled list: trials, grace, past due
- [x] Paying customer count
- [x] ARPU
- [ ] New / contraction / churned MRR movement
- [ ] Lifetime value and acquisition cost
- [ ] Gross and net revenue retention
- [ ] Revenue growth trend

**Product KPIs**
- [ ] Daily and monthly active users
- [ ] Feature and module adoption
- [ ] Session activity
- [ ] API usage
- [ ] Mobile and portal usage
- [ ] Transaction volumes by type

**Technical KPIs**
- [x] Tenant database health counts
- [x] Readiness probe
- [ ] Uptime and API latency
- [ ] Error rate and failed jobs
- [ ] Queue depth and worker health
- [ ] Storage and bandwidth
- [ ] Backup status
- [ ] Integration and notification delivery health

## §4 Customer health scoring `[ ]`

- [ ] Score combining login, adoption, volume, support and payment signals
- [ ] At-risk and churn-risk identification
- [ ] Low-adoption detection
- [ ] Payment-risk flagging
- [ ] Capacity-risk flagging
- [ ] Inactive organization detection
- [ ] Under-utilised module report
- [ ] Health trend over time

## §5 SaaS CRM `[ ]`

- [ ] Leads and prospects
- [ ] Opportunities and pipeline stages
- [ ] Demo requests
- [ ] Follow-ups and activities
- [ ] Contacts and organizations
- [ ] Quotes and proposals
- [ ] Contracts
- [ ] Sales representatives and territories
- [ ] Referral partners and resellers
- [ ] Conversion analytics

## §6 Tenant onboarding `[~]`

- [x] Organization creation
- [x] Tenant database provisioning, idempotent and resumable
- [x] System role seeding
- [x] Default department structure per facility type
- [x] Subscription attachment
- [ ] Guided onboarding wizard
- [ ] Completion percentage and setup checklist
- [ ] Missing-configuration detection
- [ ] Recommended next step
- [ ] Data import during onboarding
- [ ] Training and go-live handoff

## §7 Subscription engine `[x]`

- [x] Plans, versioned so existing customers keep signed terms
- [x] Modules and features per plan
- [x] Numeric limits per plan
- [x] Add-ons with quantity
- [x] Trial → active → past-due → grace → suspended → cancelled lifecycle
- [x] Subscription event stream (the basis for MRR movement)
- [x] Monthly, quarterly, half-yearly, annual and custom intervals
- [x] Discount percentage
- [ ] Coupons and promotions
- [ ] Upgrade and downgrade with proration
- [ ] Renewal automation
- [ ] Platform invoices, payments, refunds, credit notes

## §8 Entitlement engine `[x]`

- [x] Four-layer resolution: plan → add-ons → grants → contract overrides
- [x] Provenance recorded for every resolved value
- [x] Module entitlement checks
- [x] Feature flag checks
- [x] Numeric limit checks
- [x] Per-facility-type limits derived from the overall ceiling
- [x] Unknown keys fail closed (resolve to zero, never unlimited)
- [x] Enforcement modes: hard, soft, grace, metered
- [x] Temporary grants that expire on their own
- [x] Contract overrides that replace rather than add
- [x] Entitlement snapshots for audit

## §9 Usage metering `[x]`

- [x] Append-only usage events with idempotency keys
- [x] Rolled-up counters per period
- [x] Meter definitions with aggregation strategy
- [x] Users, facilities and patients metered
- [x] Overage tracking for billable meters
- [ ] Storage, API calls, SMS, email, WhatsApp and AI tokens wired to real sources
- [ ] Usage-based invoice line generation

## §10 Organization / tenant core `[x]`

- [x] Organization profile and legal identity
- [x] PAN, VAT, registration number
- [x] Contact and Nepal address hierarchy (province → ward)
- [x] Fiscal configuration
- [x] Branding: logo, colour, locale, timezone
- [x] Business type
- [x] Lifecycle: pending, trial, active, past-due, suspended, cancelled
- [x] Complete data isolation per tenant

## §11 Facility management `[x]`

- [x] Eight facility types
- [x] Code, name, type, status
- [x] Nepal geography
- [x] Contact details
- [x] Operating hours, including 24×7
- [x] Facility-level PAN and licence with expiry
- [x] Parent and child facilities (a warehouse serving branches)
- [x] Departments per facility
- [x] Units within departments
- [x] Control-plane registry mirror for quota and analytics
- [x] Drift reconciliation between registry and tenant

## §12 Global context switcher `[x]`

- [x] Organization switching via `X-Organization`
- [x] Facility narrowing via `X-Facility`
- [x] Server-side membership validation on switch
- [x] One session call returning organizations, permissions and entitlements
- [x] Context affects every routed query
- [ ] "All hospitals" / "all pharmacies" aggregate contexts
- [ ] Context persistence per user preference

## §13 Centralised organization management `[~]`

- [x] Central user administration
- [x] Central facility governance through change requests
- [x] Central policy with per-organization override
- [x] Central auditing
- [ ] Central HR, payroll, procurement and inventory (await those modules)
- [ ] Central price lists across facilities
- [ ] Central master data management

## §14 Configuration inheritance `[x]`

- [x] Platform default → organization → facility → department
- [x] Lockable values a facility cannot override
- [x] Effective dating
- [x] Namespaced keys
- [ ] Configuration UI
- [ ] Change history per setting

## §15 Identity management `[~]`

- [x] User accounts
- [x] Password authentication with Argon2
- [x] JWT access and refresh tokens
- [x] Failed-login tracking and lockout
- [x] Login history
- [x] Device records
- [x] Membership of several organizations
- [x] Platform support access, off by default and time-boxed
- [ ] MFA enrolment and verification (modelled, not implemented)
- [ ] SSO and OAuth
- [ ] Session listing and forced logout
- [ ] Password policy enforcement and rotation
- [ ] Failed-login alerting

## §16 RBAC + ABAC `[x]`

- [x] Permission catalogue declared in code
- [x] Roles as customer-editable data
- [x] Role inheritance
- [x] Twelve seeded system roles
- [x] Seven-level scope ladder: own → own patients → unit → department → facility → multi-facility → organization
- [x] Scope filters querysets rather than only refusing
- [x] Per-user permission grants
- [x] Per-user denials that beat role grants
- [x] Time-bounded role assignments
- [x] Maximum scope per role
- [ ] Role-assignment approval workflow (modelled, not wired)
- [ ] Permission set templates

## §17 Segregation of duties `[x]`

- [x] Conflicts declared on permissions
- [x] Design-time check when a role is saved
- [x] Runtime check at approval
- [x] Purchase create ≠ approve
- [x] Payroll process ≠ approve
- [x] Stock adjust ≠ approve
- [x] Refund create ≠ approve
- [x] Facility request ≠ approve
- [x] Result entry ≠ verification
- [x] Configurable per organization — a two-person clinic cannot segregate

## §102 Audit logging `[x]`

- [x] Append-only, held in the tenant's own database
- [x] Login, logout, failed login
- [x] Create, update, delete
- [x] Sensitive views (patient record access)
- [x] Approvals and rejections
- [x] Refunds, stock adjustments, prescription changes, patient merges
- [x] Actor, timestamp, IP, device, session, facility
- [x] Field-level before/after with secret redaction
- [x] Request correlation id
- [x] Platform-actor distinction (acting on a customer's behalf)
- [ ] Export and print logging
- [ ] Audit log UI and search
- [ ] Immutability enforced by database grant (documented, not applied)

## §103 Data version history `[x]`

- [x] `EntityVersion` snapshots
- [x] Clinical notes versioned at signature
- [x] Prescriptions versioned at signature and revision
- [x] Invoices versioned at issue
- [x] Diagnostic orders versioned at release
- [x] Patient merges versioned
- [ ] Version comparison UI
- [ ] Configuration and compensation versioning

## §128 Security `[~]`

- [x] Physical tenant isolation — one database per customer
- [x] RBAC and ABAC
- [x] Argon2 password hashing
- [x] Secret redaction in audit payloads
- [x] SQL-injection guard on provisioning identifiers
- [x] Production security settings (HSTS, secure cookies, no-sniff)
- [ ] MFA
- [ ] Encryption at rest
- [ ] Secure file storage
- [ ] API rate limiting
- [ ] Export control
- [ ] Key and secret management

---

# Phase 1 — Clinical core ✅

## §19 Patient management `[x]`

**Identity**
- [x] Patient master with organization-wide MRN
- [x] Name held as parts — Nepali names do not split on whitespace
- [x] Devanagari name
- [x] Gender including a third option
- [x] Date of birth, estimated flag, stated-age fallback
- [x] Multiple identifiers: citizenship, national ID, passport, insurance card, external MRN
- [x] Identifier verification state

**Demographics and contact**
- [x] Blood group, marital status, occupation, nationality, ethnicity, religion
- [x] Nepal address: province, district, municipality, ward, tole
- [x] Temporary address distinct from permanent
- [x] Contact and alternate contact
- [x] Guardian details and minor detection
- [x] Family linkage

**Clinical**
- [x] Allergies with severity, reaction and status
- [x] Chronic conditions with ICD-10
- [x] Clinical alerts surfaced above everything

**Commercial**
- [x] Categories: general, corporate, insurance, government, staff, charity, foreign
- [x] Corporate account and insurance policy number

**Data quality**
- [x] Duplicate detection with weighted scoring
- [x] Merge with full history transfer
- [x] Merge log holding the evidence
- [x] Merge-chain resolution (`resolve()`)
- [x] Sensitive-access logging on every read

**Outstanding**
- [ ] Patient photograph capture
- [ ] Document attachments
- [ ] Patient portal linkage
- [ ] Deceased record handling

## §20 Appointment management `[~]`

- [x] Provider schedules with weekday patterns
- [x] Slot generation and capacity
- [x] Deliberate overbooking through slot capacity
- [x] Walk-in reserve held back from online booking
- [x] Schedule exceptions: leave, holidays, extra sessions
- [x] Booking with double-book prevention
- [x] Cancellation with reason
- [x] No-show distinct from cancellation
- [x] Follow-up linkage
- [x] Priority
- [x] Waiting-time and consultation-time measurement
- [x] Facility-wide availability for a date
- [ ] Rescheduling flow (field exists)
- [ ] Recurring appointments
- [ ] Waitlist
- [ ] Online and patient-portal booking
- [ ] Room assignment
- [ ] Appointment reminders

## §21 Queue management `[x]`

- [x] Token issue with department prefix
- [x] Daily numbering per facility
- [x] Priority queue
- [x] Emergency override of routine order
- [x] Call next
- [x] Recall with a skip threshold
- [x] Skip without discarding the patient
- [x] Start and complete service
- [x] Registration, waiting, consultation and completion timestamps
- [x] Statistics with average and longest wait
- [x] Live queue screen
- [ ] Public queue display board
- [ ] Kiosk self check-in
- [ ] Estimated wait calculation

## §22 Clinical / EMR `[x]`

**Encounter**
- [x] Encounter as the unit of clinical work
- [x] Nine encounter types — shaped for inpatient before it exists
- [x] Statuses including awaiting-results
- [x] Chief complaint in the patient's words
- [x] Five-level triage
- [x] Disposition and follow-up

**Observations**
- [x] Vitals recorded as sets, not individual observations
- [x] Abnormal flagging against adult reference ranges
- [x] Room-air qualifier on oxygen saturation
- [x] BMI derivation

**Documentation**
- [x] SOAP notes as four structured fields
- [x] Signing that locks the record
- [x] Amendments that sit beside the original
- [x] Diagnoses with ICD-10 and certainty
- [x] One primary diagnosis per encounter
- [x] Promotion of a diagnosis to an ongoing condition

**Workflow**
- [x] Clinical summary — allergies, conditions, vitals and history in one call
- [x] Doctor worklist ordered by triage then arrival

**Outstanding**
- [ ] Specialty-specific templates
- [ ] Nursing notes as a distinct flow
- [ ] Care plans
- [ ] Encounter attachments
- [ ] Paediatric and neonatal vitals ranges

## §23 Prescription `[x]`

**The prescription**
- [x] Versioned — a revision supersedes, never edits
- [x] Medicine denormalised onto the line
- [x] Generic and brand
- [x] Strength, form, dose, route, frequency, duration
- [x] Fifteen dosing frequencies as written in Nepal
- [x] PRN with a required indication
- [x] Quantity computed where it is computable
- [x] Patient instructions
- [x] Prescriber registration number
- [x] Signing and validity period
- [x] Per-line discontinuation with reason
- [x] Substitution permission per line

**Safety**
- [x] Allergy checking with cross-sensitivity families
- [x] Drug interaction checking
- [x] Duplicate-medicine detection
- [x] Override capture with a mandatory reason
- [x] Merged-record resolution before checking
- [x] Active medication list across prescriptions

**Outstanding**
- [ ] Refill handling
- [ ] Price and availability at the point of prescribing
- [ ] Electronic transmission to a pharmacy
- [ ] Licensed interaction database (a small curated set today)

## §24 Referral management `[ ]`

- [ ] Doctor → doctor
- [ ] Clinic → hospital
- [ ] Hospital → specialist
- [ ] Internal department referral
- [ ] External referral
- [ ] Referrer and destination
- [ ] Reason and urgency
- [ ] Status tracking
- [ ] Appointment linkage
- [ ] Result and feedback loop
- [ ] Referral letter generation

## §85 Medical records / HIM `[~]`

- [x] Duplicate patient detection
- [x] Record merge with evidence
- [x] Completeness enforcement — an encounter cannot close empty
- [ ] Record indexing
- [ ] Record request and release
- [ ] Document scanning and classification
- [ ] Retention policy
- [ ] Legal hold
- [ ] Correction requests

## §86 Consent management `[~]`

- [x] Communication consent per channel
- [ ] Consent form templates
- [ ] Procedure, surgery and anaesthesia consent
- [ ] Data and privacy consent
- [ ] Guardian consent
- [ ] Digital signature
- [ ] Witness recording
- [ ] Consent versioning and withdrawal

---

# Phase 2 — Money ✅ (outpatient)

## §55 Finance / accounting 🔷

**Foundations**
- [x] Billable service catalogue
- [x] Tax treatment per service: exempt, zero-rated, standard
- [x] Decimal money throughout, half-up rounding
- [x] Nepali fiscal year handling

**Chart of accounts**
- [x] Five account types, with the normal balance held as data so no posting
      function has to remember which side a debit is
- [x] A tree: parents group, leaves take postings, and postability is computed
      from the tree rather than declared
- [x] Control keys — the rest of the system finds an account by what it is
      *for*, so an accountant can renumber the whole chart
- [x] A starter chart, built idempotently, that adds only what is missing
- [x] Control accounts marked, so nobody posts a manual journal into
      receivables by hand
- [ ] Per-facility sub-charts and consolidation

**The ledger**
- [x] Double entry, with the balance enforced by a database constraint on the
      entry rather than by the service layer alone
- [x] A line is a debit or a credit, never both and never neither
- [x] Nothing is edited or deleted; a mistake is reversed by a contra entry
      that names it, and both stay
- [x] Document date and posting date kept separate
- [x] A journal names the document that caused it, uniquely — posting the same
      invoice twice is impossible however many times a job runs
- [x] Cost centre and party on every line, so the subledgers exist
- [x] Opening balances, with the difference going to retained earnings
- [ ] Recurring journals and templates
- [ ] Multi-currency

**Periods**
- [x] Twelve periods per Nepali fiscal year, named for the Bikram Sambat month
- [x] Open, soft-closed and locked
- [x] Closing refuses while drafts remain — a draft in a closed period can
      never be posted anywhere
- [x] A document dated in a closed month posts into the next open one and
      keeps its own date
- [x] Reopening demands a reason and is audited; a locked period never reopens
- [ ] Year-end closing entries into retained earnings

**Posting from the rest of the system**
- [x] Invoices: receivables debited, revenue credited gross, VAT credited
      separately, discount as an expense rather than netted off
- [x] Credit notes posted as the same entry with every side swapped
- [x] Payments, with cash to the drawer and everything else to the bank
- [x] Refunds recognised by sign and posted in the opposite direction
- [x] Supplier invoices to inventory, not to expense
- [x] Expenses, with the VAT split out
- [x] Payroll: gross as cost, net and every deduction as separate liabilities
- [ ] Stock movements and cost of goods sold at the point of sale
- [ ] Patient deposits and their application to invoices

**Reading the books**
- [x] Trial balance, summed from the lines so it is a real check
- [x] Account ledger with an opening balance and a running balance
- [x] Income and expenditure
- [x] Balance sheet, using the accumulated surplus rather than the year's
- [x] VAT return with output and input kept apart
- [ ] Comparative periods and budget variance
- [ ] Cash flow statement

**Reconciliation**
- [x] Receivables ageing computed from the invoices, independently of the
      ledger
- [x] Payables ageing, with disputes marked
- [x] The receivables control account compared against the subledger, naming
      the invoices that were never posted
- [x] Bank statement kept as its own record, never imported into the ledger
- [x] Matching refuses when the amounts differ — a tolerance would hide the
      transposed figures reconciliation exists to find
- [x] Unmatched reported in both directions, because they mean different
      things
- [ ] Statement import from a bank file
- [ ] Automatic match suggestions

**Still to build**
- [ ] Fixed assets and depreciation
- [ ] Budgets
- [ ] Profit centres beyond the cost-centre tag
- [ ] Credit note application against specific invoices

## §56 Revenue cycle management `[x]`

- [x] Service → charge → invoice → payment → settlement
- [x] Charge capture separate from invoicing, so inpatient can accumulate
- [x] Price captured onto the charge at the time
- [x] Layered price resolution by payer category and facility
- [x] Price provenance reported
- [x] Discount ceilings with approval above them
- [x] Gapless statutory invoice numbering per fiscal year
- [x] Numbers allocated at issue, not at draft
- [x] Immutable issued invoices
- [x] Credit notes sharing the numbering sequence
- [x] Several payments per invoice
- [x] Eleven payment methods including Nepali wallets
- [x] Refunds under segregation of duties
- [x] Patient account statement
- [x] End-of-day cash-up by method
- [ ] Deposits and advances
- [ ] Packages
- [ ] Write-offs
- [ ] Receivable ageing report

## §57 Insurance / TPA 🔷

**Payers**
- [x] Insurer, TPA, government scheme, corporate and embassy as distinct
      kinds — an insurer carries the risk, a TPA administers somebody else's,
      and the Board pays fixed packages; one model with optional fields would
      have unreachable branches
- [x] A TPA names the insurer whose risk it administers
- [x] Submission window and settlement days per payer, because they differ
      wildly and a generic thirty is wrong in both directions
- [x] Pre-authorisation requirement and its threshold, per payer
- [x] Insurance as a payer category with its own price list
- [ ] Payer contract documents and tariff schedules

**Policies**
- [x] An interval, so cover is judged on the date of service
- [x] Dependants: the principal named, and the relationship
- [x] Sum insured, with null meaning uncapped rather than zero
- [x] Utilisation as a cache over the claims, rebuilt rather than incremented
- [x] Deductible, co-payment and per-category sub-limits
- [x] Exclusions and waiting periods
- [ ] Family floater sharing one sum insured across members
- [ ] Card scan and OCR at reception

**Eligibility**
- [x] Checked against the date of service, never against today
- [x] A sentence per policy saying why it does or does not apply
- [x] An estimate applied in the payer's own order: sub-limits, deductible,
      co-payment, then the remaining sum insured
- [x] Every reduction carries its reason, so the patient can be told the split
- [ ] Live eligibility against a payer's API

**Pre-authorisation**
- [x] A request with a planned treatment, diagnosis, dates and an estimate
- [x] An approval for less than was asked is its own state, because
      "approved" does not say the hospital is carrying the difference
- [x] An expiry date, defaulted rather than left blank
- [x] Warnings before the treatment: expiring soon, and spending past the
      approved amount
- [x] The approval is consumed when the claim goes out
- [x] A facility-wide list of approvals about to become worthless
- [ ] Extension requests against an existing approval

**Claims**
- [x] Built from an issued invoice, with the lines copied rather than
      referenced — the invoice is statutory and cannot change
- [x] Refused for an invoice with no patient: a counter sale has nobody for an
      insurer to check
- [x] Refused when the policy belongs to a different patient
- [x] One claim per invoice per payer, enforced by constraint
- [x] Claimed, approved, deducted and settled as four separate amounts
- [x] Patient liability computed and stored at submission, because the terms
      may change afterwards and the patient was quoted a number
- [x] Submission refused past the payer's window, and without a required
      pre-authorisation
- [x] Resubmission counted rather than overwriting
- [x] Queried as its own state — neither processing nor rejected
- [x] Appeal as its own state, so the appeal rate is countable
- [x] Part settlements accumulate; over-settlement refused
- [x] Write-off is explicit and carries a reason
- [x] Every state change appends an event; the history is the claim
- [ ] Claim document attachments and payer file formats

**Deductions**
- [x] A fixed vocabulary of fifteen reasons, served by the API rather than
      hard-coded in the client
- [x] A deduction without a reason is refused, by constraint and by service
- [x] Per line, with the category it falls under
- [x] Ranked analysis by reason and by category — the point of the module
- [ ] Automatic sub-limit checking against the policy at submission

**Government schemes**
- [x] Packages with a fixed amount per condition, effective-dated
- [x] Margin against what the treatment actually cost, in either direction
- [ ] Per-scheme claim formats and the Board's portal
- [ ] Annual episode caps enforced

**Analytics**
- [x] Claim ageing against each payer's own promised days
- [x] Approval rate, rejection rate, resubmission count and median days to
      answer, per payer
- [x] Written-off totals per payer
- [ ] Denial trend over time, and per-doctor deduction attribution

## §58 Hospital billing `[~]`

- [x] Registration and consultation charges
- [x] Procedure, laboratory and radiology charges
- [x] Corporate and insurance pricing
- [x] Discounts and partial payment
- [x] Room and bed charges, accrued nightly and idempotently
- [x] Theatre consumption and implants charged to the encounter
- [ ] Nursing charges
- [ ] Diet charges
- [ ] Package billing
- [ ] Deposits against admission

---

# Phase 3 — Diagnostics ✅

## §33 Laboratory / LIMS `[x]`

**Catalogue**
- [x] Test definitions
- [x] Panels with component analytes
- [x] Population-specific reference ranges — sex, age band, pregnancy
- [x] Critical thresholds per population
- [x] Numeric, text, coded and qualitative result types

**Workflow**
- [x] Order placement with clinical indication
- [x] Indication mandatory above routine priority
- [x] Specimen collection with accession numbering
- [x] Receipt into the laboratory as a distinct step
- [x] Specimen rejection that keeps the order visible
- [x] Result entry with automatic interpretation
- [x] Verification by a second person, enforced
- [x] Release to the patient record
- [x] Result amendment by supersession

**Operations**
- [x] Turnaround measurement, total and laboratory-only
- [x] TAT breach detection
- [x] Department worklist ordered STAT-first
- [x] Charge capture on order

**Outstanding**
- [ ] Barcode printing and scanning
- [ ] Analyser interfacing
- [ ] Outsourced test management (flagged, not managed)
- [ ] Home collection
- [ ] Result PDF and report layout

## §34 Laboratory quality `[~]`

- [x] Critical-value alerting as an event, not a flag
- [x] Notification record: who was told, how, when
- [x] Acknowledgement with action taken
- [x] Minutes-outstanding metric
- [x] Rejection tracking
- [x] Amendment audit trail
- [ ] Quality control runs and rules
- [ ] QC charts (Levey-Jennings)
- [ ] Analyser calibration
- [ ] Reagent and lot tracking
- [ ] Failed QC handling
- [ ] External quality assessment

## §35 Radiology / RIS / PACS `[~]`

- [x] Modality-specific ordering: X-ray, CT, MRI, ultrasound, mammography, ECG, echo, endoscopy
- [x] Modality worklist
- [x] Narrative reporting
- [x] Verification and release
- [x] Radiology gated as a separate module from laboratory
- [ ] DICOM
- [ ] PACS integration
- [ ] Image viewer
- [ ] Reporting templates
- [ ] Critical findings workflow distinct from laboratory criticals
- [ ] Scheduling against modality capacity

## §36 Blood bank `[ ]`

- [ ] Donor registry
- [ ] Donation and collection
- [ ] Blood grouping
- [ ] Component separation
- [ ] Transfusion-transmissible infection screening
- [ ] Storage and inventory
- [ ] Reservation
- [ ] Cross-matching
- [ ] Issue and return
- [ ] Expiry management
- [ ] Transfusion record
- [ ] Adverse reaction reporting

---

# Phase 4 — Pharmacy and supply chain ✅ (core)

## §37 Pharmacy deployment shapes `[~]`

- [x] Clinic pharmacy
- [x] Hospital pharmacy — same model, different facility type
- [ ] Retail pharmacy (needs POS)
- [ ] Chain pharmacy (needs inter-branch transfer)
- [ ] Central pharmacy
- [ ] Pharmacy warehouse
- [ ] Wholesale and distribution

## §38 Product master `[x]`

- [x] Product code, generic, brand, strength
- [x] Fourteen dosage forms
- [x] Manufacturer and country of origin
- [x] Therapeutic class
- [x] Category: medicine, consumable, device, surgical, reagent
- [x] Barcode
- [x] Base unit and pack size
- [x] Six storage conditions including cold chain
- [x] Five control schedules
- [x] Prescription requirement
- [x] Reorder level, minimum, maximum
- [x] Lead time
- [x] Formulary membership
- [ ] Tax category per product
- [ ] Product images
- [ ] Substitution groups

## §39 Batch management `[x]`

- [x] Batch number, manufacture and expiry dates
- [x] Supplier and receipt reference
- [x] Per-batch purchase price, selling price and MRP
- [x] Six statuses: active, quarantine, expired, recalled, damaged, disposed
- [x] Quarantine reason and recall reference
- [x] MRP ceiling validation
- [ ] Free quantity on receipt
- [ ] Per-batch discount and tax
- [ ] Shelf and bin assignment on the batch

## §40 Pharmacy inventory `[x]`

- [x] Immutable append-only stock ledger
- [x] Twenty movement types
- [x] Running balance on every entry
- [x] Cached balance rebuildable from the ledger
- [x] Row-level locking against concurrent dispensing
- [x] Negative-balance protection
- [x] Stock location hierarchy: store → shelf → bin
- [x] Quarantine locations
- [x] Cost captured per movement
- [ ] Inter-facility transfers
- [ ] Stock reservation flow (field exists)
- [ ] Serial number tracking

## §41 FEFO `[x]`

- [x] Earliest-expiry-first allocation
- [x] Allocation spanning several batches
- [x] Expired, quarantined and recalled stock excluded
- [x] Override refused without a reason
- [x] Override captures reason, user and approver
- [x] Override recorded on both ledger and dispensing line
- [x] Override logged at WARNING
- [x] Allocation preview endpoint

## §42 Expiry management `[x]`

- [x] Eight thresholds: 365, 180, 120, 90, 60, 30, 15, 7 days
- [x] Expired bucket
- [x] Value at cost per bucket
- [x] Sweep that both blocks dispensing and writes off
- [x] `is_dispensable` checks status and date together
- [ ] Expiry by supplier, branch and category
- [ ] Expiry trend
- [ ] Return-to-supplier flow
- [ ] Discount-to-clear workflow

## §43 Recall `[~]`

- [x] Batch quarantine with recall reference
- [x] Removal from the FEFO offer
- [x] Patient exposure report drawn from the ledger
- [x] Remaining stock by location
- [ ] Recall notice record
- [ ] Multi-facility stock isolation
- [ ] Supplier notification
- [ ] Return and destruction records
- [ ] Recall closure and audit

## §44 Pharmacovigilance `[~]`

- [x] Allergies structured and checked at prescribing
- [x] Reaction and severity recorded
- [ ] Adverse event reporting
- [ ] Suspected medicine and batch linkage
- [ ] Reporter details
- [ ] Investigation and follow-up
- [ ] Outcome
- [ ] Regulatory report preparation

## §45 Controlled medicines `[~]`

- [x] Five control schedules on the product
- [x] Prescription requirement enforced
- [ ] Authorised dispenser restriction
- [ ] Approval before dispensing
- [ ] Quantity limits
- [ ] Enhanced separate ledger
- [ ] Dispensing history report
- [ ] Periodic reconciliation with a witness

## §46 Cold chain `[~]`

- [x] Storage condition on the product
- [x] Cold-chain products identified
- [ ] Temperature and humidity ranges
- [ ] Sensor and device registry
- [ ] Readings
- [ ] Threshold breach detection
- [ ] Breach alerts
- [ ] Corrective action record
- [ ] Equipment maintenance linkage

## §47 Pharmacy POS `[~]`

**Selling**
- [x] Over-the-counter sale to a walk-in
- [x] Prescription-only medicine refused without a prescription
- [x] Prescription sale linked to the prescription record
- [x] Patient-linked sale
- [x] Corporate, insurance and staff sale (may leave a balance)
- [x] Credit sale - balance permitted only for credit sale types
- [x] Basket quoted before commit, with server-side rounding
- [x] Shortfalls reported at quote time, before payment
- [x] Sale refused when the shelf is short
- [x] Barcode matched exactly and first
- [x] Generic and brand search
- [x] Batch chosen by FEFO, one item spanning several batches
- [x] Batch selection at the counter, overriding FEFO with an audit trail
- [x] Line discount as a percentage, taken before tax
- [x] Selling above printed MRP refused
- [x] VAT per product, defaulting to exempt
- [ ] Discount above a threshold requiring approval
- [ ] Package and combo pricing
- [ ] Loyalty and repeat-customer lookup

**Tender**
- [x] Cash, card, eSewa, Khalti, IME Pay, Fonepay, bank transfer
- [x] Partial and multiple payment on one sale
- [x] A tender with no amount settles the remaining balance
- [x] Change computed, offered on cash only
- [x] Quick-tender note buttons
- [x] Overpayment refused rather than absorbed
- [ ] Wallet payment confirmed against the provider's API
- [ ] Cash drawer integration (hardware)

**Receipt**
- [x] Receipt composed server-side so a reprint matches the original
- [x] Statutory invoice number per facility, per fiscal year
- [x] Batch and expiry printed per line
- [x] Browser print
- [ ] Thermal printer (ESC/POS) output
- [ ] SMS and e-mail receipt

**Till session**
- [x] Open a till with a counted float
- [x] One open session per till enforced
- [x] Takings by payment method, computed from payment rows
- [x] Blind cash count - expected figure withheld until after counting
- [x] Variance must be explained before the till closes
- [x] Second person signs the count off (maker-checker)
- [x] Variance logged as a warning for review
- [ ] Cash pickup and mid-shift drop
- [ ] Shift handover between cashiers

**Returns and voids**
- [x] Partial return by line and quantity
- [x] Refund is a proportion of what was actually charged
- [x] Returns raised by the cashier, approved by someone else
- [x] Restock or write off decided by the approver, not the requester
- [x] Write-off posts to the ledger as a write-off, not a silent loss
- [x] Credit note against the original invoice
- [x] Refund recorded as a negative payment so the day nets
- [x] Void a whole sale, approved by someone other than the seller
- [x] Return refused with a stated reason
- [ ] Return window policy (time limit)
- [ ] Exchange (return and re-sell in one transaction)

**Reporting**
- [x] Day summary: gross, returns, net revenue
- [x] Margin net of returns, with write-offs charged to the day
- [x] Top-selling products
- [x] Cost captured per line at the time of sale
- [ ] Cashier performance and per-till comparison
- [ ] Hourly sales profile

## §48 Pharmacy procurement `[~]`

- [x] Demand aggregation from reorder levels
- [x] Reorder generation into a requisition
- [x] Purchase requisition
- [x] Requisition approval, refused for the requester
- [x] Supplier quotations
- [x] Quotation comparison on blended cost per unit
- [x] Purchase order
- [x] Order approval, refused for whoever raised it
- [x] Dearer quotation requires a stated reason
- [x] Goods receipt note
- [x] Quality check with per-line rejection
- [x] Batch creation from receipt, traceable to the delivery
- [x] Supplier invoice matching (reported, not blocking)
- [ ] Request for quotation issued to suppliers
- [ ] Accounts payable posting
- [ ] Purchase returns to supplier

## §49 Wholesale and distribution `[ ]`

- [ ] Customer pharmacies and dealers
- [ ] Institutional customers
- [ ] Sales territories and representatives
- [ ] Distributor and wholesale price lists
- [ ] Customer credit limits and terms
- [ ] Sales orders
- [ ] Dispatch and delivery
- [ ] Proof of delivery
- [ ] Sales returns
- [ ] Batch traceability to customer

## §50 Inventory / supply chain platform `[~]`

- [x] Several locations per facility
- [x] Location hierarchy
- [x] Batch and expiry tracking
- [x] FEFO
- [x] Quarantine
- [x] Consumption and returns as movement types
- [ ] Shared across lab, theatre, ICU and wards — the model supports it, not wired
- [ ] Serial numbers
- [ ] FIFO where FEFO does not apply
- [ ] Stock reservation
- [ ] Inter-location transfer workflow
- [ ] Disposal workflow

## §51 Inventory forecasting `[~]`

- [x] Consumption rate over a trailing window
- [x] Days of cover
- [x] Reorder point respecting lead time
- [x] Stock-out-before-delivery flagging
- [x] Suggested order quantity
- [ ] Weekly and monthly consumption breakdown
- [ ] Safety stock calculation
- [ ] Economic order quantity
- [ ] Demand trend and seasonality
- [ ] Overstock and dead-stock alerts
- [ ] Transfer suggestions between branches

## §52 Stock counting `[x]`

- [x] Full, cycle, ABC and spot counts
- [x] Blind counting by default
- [x] Expected quantities frozen at open
- [x] Variance calculation
- [x] Recount supersedes the first count
- [x] Mandatory variance explanation
- [x] Approval by someone other than the counter
- [x] Adjustment posting on approval
- [ ] Directed count sequencing
- [ ] Count scheduling

---

# Phase 5 — People `[ ]`

## §59 HRMS `[~]`

**Employee record**
- [x] Employee master and employee code
- [x] Photograph (URL; upload pipeline outstanding)
- [x] Personal details, address and next of kin
- [x] Emergency contact flagged when missing
- [x] Position and designation
- [x] Department assignment
- [x] Grade and level (on the position)
- [x] Facility posting
- [x] Reporting manager, distinct from the position hierarchy
- [x] Employment type: permanent, probation, contract, locum, visiting,
      intern, trainee, part-time, daily wage
- [x] Citizenship, PAN, blood group, bank details
- [x] Probation end date, confirmation, and an overdue-probation flag
- [ ] Unit assignment below department
- [ ] Photograph upload and storage

**Credentials and history**
- [x] Contract records with expiry, superseded rather than edited
- [x] Allowances per contract, with a computed gross
- [x] Document register per employee, with mandatory and expiry flags
- [x] Professional licence and council registration
- [x] Credential verification recorded separately from the claim
- [x] Verification refused for the credential's own holder
- [x] Unverified registration blocks practice, not only an expired one
- [x] Qualifications and specialities
- [x] Prior experience with verification state
- [x] Skills at an assessed level, distinct from paper
- [x] Expiring-credential report, including what has already lapsed
- [x] Expiring-contract report
- [ ] Training records
- [ ] Performance history
- [ ] Document file upload and storage

**Lifecycle**
- [x] Hire, opening the employment history at the beginning
- [x] Confirm after probation
- [x] Transfer between facilities
- [x] Department change
- [x] Promotion and demotion
- [x] Reporting-line change
- [x] Event type derived from what changed, so a promotion cannot be
      mislabelled as a transfer
- [x] Suspend and reinstate
- [x] Separation: resignation, termination, retirement
- [x] Separation closes active contracts
- [x] The record survives separation, because everything they did points at it
- [ ] Notice-period tracking
- [ ] Exit interview
- [ ] Final settlement
- [ ] Clearance checklist

**Integration**
- [x] Employee → user account linkage, one employee per login
- [x] Login provisioning: account, membership, seat check, role assignment
- [x] Employee → provider linkage — `Employee.for_user()` resolves the bare
      `provider_uuid` carried by scheduling, encounters and prescriptions
- [x] Prescribing refused on a lapsed or unverified registration
- [x] Council registration printed on the prescription from the verified record
- [ ] Scheduling refused for a provider who may not practise
- [ ] Result authorisation checked against the authoriser's registration
- [ ] Revoking the login on separation (deliberately manual today)

**Reporting**
- [x] Headcount by employment type and department
- [x] Vacancies from budgeted positions
- [x] Turnover from the event log, by separation type
- [x] Team-of, walking the reporting tree to any depth
- [ ] Org chart visualisation
- [ ] Headcount trend over time

## §60 Organization structure `[~]`

- [x] Organization → facility → department → unit
- [x] Position definitions with code, title, grade and facility
- [x] Employee-to-position assignment
- [x] Headcount and vacancies, floored at zero for over-filled posts
- [x] Position budget (budgeted headcount)
- [x] Reporting hierarchy on the position, so it survives someone leaving
- [x] Job descriptions
- [x] Clinical / provider / requires-a-licence flags per position
- [ ] Org chart visualisation
- [ ] Approval authority per position
- [ ] Position budget in money as well as headcount

## §61 Recruitment / ATS `[ ]`

- [ ] Manpower request
- [ ] Vacancy
- [ ] Job posting
- [ ] Candidate records
- [ ] Application tracking
- [ ] Screening
- [ ] Interview scheduling and panels
- [ ] Evaluation and scoring
- [ ] Selection
- [ ] Offer
- [ ] Joining
- [ ] Handoff to onboarding

## §62 Employee onboarding `[~]`

- [x] Employee record creation
- [x] Position and facility assignment
- [x] Login provisioning with a seat check against the plan
- [x] Role and permission assignment at hire
- [x] Document register (metadata; upload outstanding)
- [x] Credential verification
- [x] Contract issue
- [ ] Offer acceptance
- [ ] Document upload and collection tracking
- [ ] Shift assignment
- [ ] Payroll enrolment
- [ ] Asset assignment
- [ ] Orientation checklist

## §63 Shift and roster `[~]`

- [x] Shift definitions: fixed, rotating, split, flexible, overnight, on-call
- [x] Overnight shifts, with crossing midnight stated rather than inferred
- [x] Paid hours per shift, net of the scheduled break
- [x] Grace period and half-day threshold per shift
- [x] Department- and facility-specific shifts
- [x] On-call marking on a roster entry
- [x] Roster by employee, date, facility, department
- [x] Rest-period rule enforced between consecutive shifts
- [x] Leave conflict detection at rostering time
- [x] Double-booking prevented, in the service and by a database constraint
- [x] Roster publication, distinct from drafting
- [x] Weekly roster grid with Saturday shaded
- [ ] Minimum staffing enforcement
- [ ] Working-hour limits per week
- [ ] Overtime rules beyond the shift duration
- [ ] Swap requests
- [ ] Rotating-pattern generation

## §64 Attendance `[~]`

- [x] Web check-in and check-out
- [x] Source recorded per mark: biometric, face, RFID, mobile, web, manual
- [x] Earliest arrival and latest departure win, so a re-scan does not reset
      the day
- [x] GPS coordinates and a geofence verdict stored for a mobile mark
- [x] Present, late, early-exit, absent and half-day statuses
- [x] Status derived from the facts, never asserted — approving leave after
      the absence changes the day without anyone editing it
- [x] Leave, holiday and weekly-off handling, with Saturday as the weekly off
- [x] Lateness measured against the shift, after its grace period
- [x] Overtime measured against paid shift hours, net of the break
- [x] An unfinished day (in, never out) distinguished from a short day
- [x] Regularisation requests, keeping the original times
- [x] Regularisation refused for the person who asked
- [x] Attendance summary by status and by person, lateness summed not averaged
- [ ] Biometric, face and RFID device integration
- [ ] Mobile app capture
- [ ] Bulk import from a device
- [ ] On-duty marking for work done off site

## §65 Leave `[~]`

- [x] Configurable types: annual, sick, maternity, paternity, bereavement,
      unpaid, and any the organization adds
- [x] Per-type rules: entitlement, notice, document threshold, maximum
      consecutive days, minimum service, negative balance
- [x] Balance from an append-only ledger, never a stored counter
- [x] Ledger reasons enumerated so a balance can be explained, not just stated
- [x] Annual entitlement granted idempotently — a job that runs twice does not
      double everybody's holiday
- [x] Application and approval workflow
- [x] Approval refused for the applicant
- [x] Overlapping requests refused
- [x] Weekly offs and public holidays excluded from the deduction
- [x] Optional holidays deliberately *not* excluded
- [x] Working days frozen at application, so a later festival cannot change a
      decided request
- [x] Insufficient balance refused, or taken unpaid as an explicit choice
- [x] Cancellation returns the days as a new entry, not a deletion
- [x] Delegation recorded on the request
- [x] Leave calendar across a facility
- [ ] Monthly accrual (the field exists; the job does not)
- [ ] Carry forward at year end
- [ ] Encashment
- [ ] Blackout periods
- [ ] Half-day handling beyond a single flag

## §66 Payroll `[~]`

**Setup**
- [x] Pay components: earning, deduction, employer contribution, tax,
      reimbursement
- [x] Calculation bases: fixed, percent of basic, percent of gross, per day,
      per hour, engine formula
- [x] Taxable and non-taxable components
- [x] Components that count towards the contribution base, distinct from gross
- [x] Pro-rated and non-pro-rated components
- [x] Salary structures, with per-structure rate overrides
- [x] Employee payroll profile: structure, scheme, tax regime, declarations
- [ ] Component visibility rules per employee grade
- [ ] Loan and advance recovery

**Running**
- [x] Open a run for a facility and period
- [x] One live run per facility per period enforced
- [x] Calculate from real attendance and leave
- [x] Recalculation replaces rather than appends
- [x] Payable days from attendance, with weekly offs and holidays paid
- [x] Unpaid leave and absence reduce pay
- [x] Part-period pro-rating for joiners and leavers
- [x] Employee with no contract held, with a stated reason
- [x] Employee on hold excluded from pay but present in the run
- [x] Submit for approval
- [x] Approval refused for whoever calculated it
- [x] Approved run immutable; corrections are a supplementary run
- [x] Cancel an unpaid run with a reason
- [ ] Off-cycle and bonus runs
- [ ] Arrears and retrospective adjustment

**Payslips**
- [x] Payslip per employee with the employee's details snapshotted
- [x] Line per component with basis, rate and base amount
- [x] Explanation string per line
- [x] Attendance figures snapshotted onto the payslip
- [x] Tax derivation stored on the payslip
- [x] Employees see their own payslips without `salary.read`
- [x] Only approved runs visible to the employee
- [ ] PDF payslip
- [ ] E-mail distribution

**Payment**
- [x] Payment batches, so a run can be paid in tranches
- [x] Bank file rows, naming what cannot be paid
- [x] Confirm payment separately from generating the file
- [x] Run marked paid only when every payslip is
- [ ] Bank format export (CSV/XML per bank)
- [ ] Cash and cheque payment recording

**Reporting**
- [x] Run summary by component
- [x] Statutory return: tax and contributions reported separately
- [x] Total cost to the organization, distinct from net pay
- [ ] Month-on-month comparison
- [ ] Departmental salary cost
- [ ] Year-to-date per employee

## §67 Compensation `[ ]`

- [ ] Compensation plans
- [ ] Grades
- [ ] Salary bands with minimum, midpoint and maximum
- [ ] Component structure per grade
- [ ] Revision history

## §68 Payroll rule engine `[~]`

- [x] Components configurable per organization, not hard-coded
- [x] Calculation basis per component
- [x] Structure-level rate and amount overrides
- [x] Sequenced calculation, so tax runs after every earning is known
- [x] Statutory components flagged and undeletable from a structure
- [ ] Conditional components (applies only when a condition holds)
- [ ] Formula expressions beyond the built-in bases
- [ ] Simulation: what a change would cost before applying it

## §69 Nepal tax and statutory engine `[~]`

- [x] Income-tax slabs as effective-dated data, per fiscal year
- [x] Individual and married-couple regimes with different thresholds
- [x] Progressive banding — each band taxes only the income inside it
- [x] Annualisation before the progressive rate is applied
- [x] Months-remaining projection for a mid-year joiner
- [x] Social Security Fund: 11% employee, 20% employer, on basic
- [x] Provident Fund and Citizen Investment Trust schemes
- [x] The 1% social security tax waived for SSF contributors
- [x] Retirement deduction capped by the lower of a flat ceiling and one
      third of assessable income
- [x] Life and health insurance premiums deductible, capped separately
- [x] Remote-area allowance by category
- [x] Disability exemption as a multiple of the first band
- [x] Full derivation stored on the payslip
- [x] Falls back to the most recent year on file rather than computing zero
- [ ] Gratuity accrual
- [ ] Annual TDS return (E-TDS) export
- [ ] SSF monthly contribution return export
- [ ] Withholding on non-employee payments

## §70 Expense and claims `[ ]`

- [ ] Travel, medical, communication and training claims
- [ ] Purchase reimbursement
- [ ] Petty cash
- [ ] Advance and settlement
- [ ] Request → approval → evidence → settlement → accounting
- [ ] Policy limits

## §118 Performance management `[ ]`

- [ ] Goals
- [ ] KPIs
- [ ] Appraisal cycles
- [ ] Competency framework
- [ ] Manager review
- [ ] Self review
- [ ] Peer feedback
- [ ] Rating
- [ ] Development plans
- [ ] Clinical quality kept separate from revenue KPIs

## §119 Training and learning `[ ]`

- [ ] Training catalogue
- [ ] Enrolment
- [ ] Attendance
- [ ] Completion and certificates
- [ ] Certificate expiry
- [ ] Mandatory training tracking
- [ ] Compliance training: infection control, fire safety, CPR, data privacy

## §120 Licence and credential management `[ ]`

- [ ] Council registration
- [ ] Licence records
- [ ] Speciality certification
- [ ] Expiry tracking
- [ ] Renewal workflow
- [ ] Verification
- [ ] Supporting documents
- [ ] Alerts at 180, 90, 30 and 7 days
- [ ] Block on practising with an expired licence

---

# Phase 6 — Hospital OS `[ ]`

## §26 IPD / admission `[~]`

**Admitting**
- [x] Admission linked to an inpatient encounter, so notes, prescriptions and
      orders work unchanged
- [x] Admission sources: OPD, emergency, referral, transfer, direct, birth
- [x] Admission without a bed — `pending`, which is a real state
- [x] Ward chosen, first assignable bed taken automatically
- [x] A second live admission for the same patient refused
- [x] Admission against a merged patient record refused
- [x] Consultant, admitting diagnosis, expected discharge
- [x] Attendant name, phone and relationship
- [x] Deposit expected
- [x] Medico-legal case flagged, with a police-informed timestamp
- [ ] Admission request and bed booking ahead of arrival
- [ ] Insurance pre-authorisation

**During the stay**
- [x] Transfer between beds and wards, recorded as an interval
- [x] Nursing rounds with shift, intake, output and pain score
- [x] Fluid balance over a window, cumulative
- [x] Nursing escalation flagged and listable
- [x] Length of stay counted in nights
- [x] Overstay detected against the expected discharge date
- [ ] Doctor's ward-round notes distinct from nursing
- [ ] Care plans
- [ ] Diet orders passed to the kitchen

**Leaving**
- [x] Discharge initiated as a distinct state, so turnaround time is
      measurable
- [x] Five named clearances, each with a person and a blocking reason
- [x] Outstanding balance and uninvoiced charges block a discharge
- [x] Override behind its own permission, with a stated reason, audited
- [x] Death and LAMA skip the balance check
- [x] Outcomes recorded distinctly: discharged, died, LAMA, absconded,
      transferred out
- [x] Discharge summary, advice and follow-up date
- [x] The encounter closes with the admission
- [x] The bed is released to cleaning, not to available
- [ ] Discharge summary template and printing
- [ ] Death certificate
- [ ] LAMA form capture

**Money**
- [x] Daily accrual per admission, per day, per kind
- [x] Idempotent — re-running charges nothing again
- [x] Backfill for a missed night or a mid-stay migration
- [x] Rate captured on the bed assignment, so a stay across two wards is
      charged correctly day by day
- [x] Accruals post real billing charges, traceable both ways
- [x] Discharge-day accruals reversed and their charges cancelled
- [x] A bed with no rate is reported, not silently free
- [x] Stay total by category, with uninvoiced and outstanding separated
- [ ] Interim billing during a long stay
- [ ] Deposit applied at discharge
- [ ] Package and per-procedure pricing

## §27 Bed and ward `[~]`

- [x] Wards by type: general, private, semi-private, deluxe, ICU, NICU, PICU,
      HDU, maternity, isolation, burns, psychiatric, day care, emergency
- [x] Beds with code, bay, floor and building
- [x] Bed physical status separate from occupancy: available, occupied,
      reserved, cleaning, maintenance, blocked
- [x] Gender-restricted beds, enforced at admission and at transfer
- [x] Bed facilities: oxygen, suction, monitor, ventilator, isolation
- [x] Per-bed daily rate and billable service
- [x] Nurse-to-patient ratio per ward, and nurses needed computed from it
- [x] Real-time occupancy per ward and per facility, computed not stored
- [x] Occupancy measured against total beds, so broken beds read as a
      maintenance problem
- [x] Bed board with occupants in one request
- [x] Census: in house, waiting, admitted today, discharged today, overstaying
- [x] Outcomes report with mortality, LAMA and average length of stay
- [ ] Bed reservation ahead of an admission
- [ ] Housekeeping workflow and turnaround timing
- [ ] Ward transfer between facilities

## §28 Nursing `[~]`

- [ ] Ward census
- [ ] Nurse assignment
- [ ] Nursing rounds
- [ ] Vitals capture (reuses §22) 🔷
- [ ] Care plans
- [ ] Nursing notes
- [ ] Intake and output
- [ ] Medication administration record
- [ ] Administration schedule and verification
- [ ] Patient observations
- [ ] Risk assessment: falls, pressure ulcers
- [ ] Nursing tasks
- [ ] Shift handover
- [ ] Escalation to a doctor

## §29 Emergency / casualty `[~]`

**Arrival**
- [x] Arrival registration, with mode: ambulance, walk-in, police, referral,
      air ambulance
- [x] Registration of an unidentified patient as the *default* path
- [x] A real patient record with an MRN, not a placeholder
- [x] Physical description, so staff and relatives can recognise them
- [x] Identification later, merging into an existing record
- [x] Everything written while unnamed follows the merge
- [x] `arrived_unidentified` kept separate from `is_unidentified`, so
      identification does not erase how they arrived
- [x] Minutes-unidentified as an operational number
- [x] Medico-legal flagging with a police-informed timestamp
- [ ] Identity band printing
- [ ] Mass-casualty / incident mode

**Triage**
- [x] Five-level triage with target times as data
- [x] Triage appends — the history is the record
- [x] Deterioration detected and flagged
- [x] Re-triage does not restart the wait clock
- [x] Vitals captured with each assessment, frozen to that assessment
- [x] Breach detection, still true after the patient is seen
- [x] Minutes-to-breach, negative once over
- [x] Board ordered by category then arrival, untriaged last
- [ ] Triage decision support / scoring aids

**Treatment**
- [x] Mark-seen, with the arrival-to-seen gap as the headline number
- [x] Critical pathways: STEMI, stroke, sepsis, trauma, arrest, obstetric,
      paediatric, poisoning, burns
- [x] Pathway clocks measured from arrival, not from activation
- [x] Recognition time reported separately from door-to-intervention
- [x] Stand-down recorded rather than deleted
- [x] Resuscitation record, timestamped on creation, never edited
- [x] Shocks, drugs, rhythms, airway and ROSC as typed entries
- [x] Elapsed time from the first entry
- [x] Emergency prescribing and orders through the existing encounter
- [ ] Emergency drug administration against a resus trolley's stock
- [ ] Standing-order protocols

**Disposition**
- [x] Discharged, admitted, referred, LWBS, LAMA, absconded, died, brought
      dead
- [x] Admission requires the admission reference
- [x] Referral requires a destination
- [x] The encounter closes with the attendance
- [ ] Direct admission from the board into a bed

**Performance**
- [x] Median and longest wait
- [x] Breach rate overall and per category
- [x] Left-without-being-seen rate
- [x] Arrivals by mode and by category
- [x] Pathway performance: activations, recognition, door-to-intervention,
      target met
- [x] Unidentified and medico-legal counts
- [ ] Hourly arrival profile for staffing
- [ ] Time-to-first-analgesia and other condition-specific measures

## §30 ICU 🔷

**The stay**
- [x] An ICU episode is an interval on the admission, not a flag — a patient
      goes ward → ICU → ward → ICU, and each episode has its own severity,
      support days and outcome
- [x] The unit borrows the ward's beds; there is one bed board
- [x] Several units per hospital (general, cardiac, neonatal, HDU) with their
      own boards and their own numbers
- [x] Admission route recorded: emergency, ward deterioration, post-operative,
      referral, direct
- [x] Weight and height on the stay, because vasopressors are dosed per kilo
      and a weight from two years ago is a dosing error
- [x] Outcome as a fixed set, with transferred-out and left-against-advice
      kept separate from died and stepped-down
- [x] APACHE II on admission, stored with its components
- [x] Ceiling of care and resuscitation status, named and timestamped
- [ ] Bed-day billing at the ICU tariff through the existing accrual
- [ ] Nurse-to-patient ratio enforced against the roster

**Observations**
- [x] Append-only; nothing is edited
- [x] A row per observation round, not per measurement
- [x] GCS stored in its three parts, with "verbal not testable" as its own
      fact — a sedated patient is not a moribund one
- [x] GCS total returns nothing when a part is missing, rather than summing
      what is present and reading as sicker
- [x] Measured MAP kept separate from the estimate derived from the cuff
- [x] RASS as a signed value, pupils, pain, glucose, lactate
- [x] Device readings marked as device-sourced and unvalidated until a person
      confirms them; the row survives either way
- [x] Trend endpoint per parameter, for a shape rather than a number
- [ ] Live monitor feed (the ingestion contract exists; no driver yet)

**Fluid balance**
- [x] A ledger of volumes in and out; the balance is computed, never stored
- [x] Broken down by route — two litres positive from maintenance fluid and
      two litres positive from anuria are the same figure and opposite
      problems
- [x] Corrections reverse an entry rather than editing it
- [x] Cumulative balance per ICU day — the figure nobody has and the one that
      matters
- [x] Urine in ml/kg/hr, or nothing when no weight is recorded
- [ ] A configurable unit day (07:00–07:00) for the charted 24-hour block

**Infusions**
- [x] A rate change is an event; the current rate is the last row
- [x] Volume infused computed from the rate history, never a counter
- [x] Volume returns nothing for a rate that integrates to a dose rather than
      millilitres
- [x] The rate's unit stored with it — mcg/kg/min and mg/hr are not
      interchangeable
- [x] A titratable infusion must say what it is titrated to
- [x] Prescribed maximum enforced at the bedside
- [x] Every change carries its reason, so "what was she on when the pressure
      dropped" has an answer
- [ ] Syringe-driver integration and volume-remaining alarms

**Ventilation**
- [x] Set values and measured values as separate fields — the gap between
      them is a leak or a stiff lung
- [x] Modes ordered from full support to none
- [x] Invasive kept distinct from NIV and high-flow, and forced for the modes
      where it cannot be true
- [x] PF ratio and driving pressure computed, or nothing when a half is
      missing
- [x] Blood gas alongside the settings
- [x] Ventilator-hours and ventilator-days from the charted record
- [x] An impossible FiO2 is refused with a sentence naming the likely mistake
- [ ] Weaning protocol and spontaneous-breathing-trial records

**Lines and tubes**
- [x] An interval from insertion to removal, so line-days exist as a
      denominator
- [x] Emergency insertions flagged and given a change date automatically
- [x] Removal records whether infection was suspected
- [x] Overdue and still-in emergency lines surfaced per patient
- [x] Device-days and infections per thousand device-days, per type
- [ ] Dressing-change and line-care task scheduling

**The daily round**
- [x] One consultant round per ICU day, enforced
- [x] FASTHUG as data, served to the client rather than hard-coded in a form
- [x] An unanswered item is unanswered, not false
- [x] An item answered "no" must say why
- [x] Sedation hold and weaning trial asked every day
- [x] Family update recorded
- [x] Per-item compliance across the unit, because the items fail differently
- [ ] Multidisciplinary notes (physio, dietetics, microbiology) on the round

**Scoring**
- [x] SOFA computed daily from what is charted, with components frozen
- [x] Missing systems named — a score with gaps is stored and flagged, never
      silently scored as normal
- [x] Vasopressor support beats blood pressure in the cardiovascular
      component
- [x] A sedated patient's GCS excluded rather than scored as brain failure
- [x] Oliguria can beat the creatinine, which lags a day behind the kidney
- [x] Severity trajectory per day, with partial days marked
- [ ] APACHE II calculated rather than entered; SAPS III

**Alerts**
- [x] Raised at the moment of charting, not by a sweep
- [x] Per-unit defaults as data, with per-patient overrides that must say why
- [x] Alerts never self-clear — a night of self-clearing desaturations is what
      a morning review needs to see
- [x] Alerts from unvalidated device data marked as such
- [x] The alert text names the ceiling of care when the patient is not for
      resuscitation
- [x] Acknowledgement names a person, a time and optionally what was done
- [x] Time-to-acknowledge reported, because it says whether the alerting is
      trusted
- [ ] Escalation to a pager or phone when nobody acknowledges

**Step-down and the unit**
- [x] Blockers as sentences, labelled clinical or record
- [x] Step-down refused by default, overridable with the reasons written into
      the audit trail
- [x] Running infusions stopped when the stay closes
- [x] Board ordered by unacknowledged critical alerts, then severity — never
      by bed number
- [x] Stale charting shown as a state rather than an empty column
- [x] Mortality reported beside the outcome-unknown count
- [x] Readmission within 48 hours, the number that says whether step-down is
      too early
- [ ] Occupancy and refused-admission tracking

## §31 Operation theatre 🔷

**The theatre itself**
- [x] Theatre as a room with a code, unique per facility
- [x] Session start and finish, so utilisation has a denominator
- [x] Turnaround minutes per room — a gap the length of the cleaning time is
      not waste, and a gap twice that is
- [x] Specialty and equipment notes
- [x] Laminar flow flagged, because it decides which cases may run there
- [ ] Per-day session patterns (a room staffed on alternate afternoons)

**Requesting and approving**
- [x] Procedure request from an encounter, by a named surgeon
- [x] Indication, planned procedure, procedure code
- [x] Laterality as a required decision, never a blank — left/right/bilateral
      or explicitly not applicable
- [x] ASA grade and the planned duration the surgeon estimates
- [x] Day case flagged at request, because it decides whether a bed is needed
- [x] Urgency: elective, scheduled, urgent, emergency
- [x] Approval by somebody other than the requester
- [x] The waiting list: approved, no slot — the gap between the clinical
      decision and the operational one
- [ ] Pre-operative assessment clinic and fitness sign-off
- [ ] Consent capture against the case

**Scheduling**
- [x] A slot is a start and an end, never one without the other
- [x] Overlap detection against the room's other cases
- [x] Turnaround respected — the next case cannot start while the room is
      being cleaned
- [x] Double-booking possible only with `theatre.override`, and recorded
- [x] The day list per room, in order, with the idle gap between cases
- [x] Overrun measured against the surgeon's own estimate
- [ ] Surgeon and anaesthetist availability checked across rooms
- [ ] Drag-to-reschedule on the list

**The team**
- [x] Named roles: surgeon, assistant, anaesthetist, scrub, circulating,
      technician, perfusionist
- [x] One primary surgeon and one anaesthetist per case, enforced
- [x] Licensed roles go through the same practice check that refuses a
      prescription — nobody operates on a lapsed registration
- [x] `team_gaps` names the roles a case is still missing
- [x] Registration number recorded on the case, not looked up later
- [ ] Rota integration, so the assignment offers who is on duty

**The surgical safety checklist**
- [x] The WHO three phases — sign in, time out, sign out — as data, not as a
      React component
- [x] Each item answered yes or no by a named person at a recorded moment
- [x] Unanswered items recorded as unanswered rather than blocking
- [x] Negative answers surfaced; concerns recorded in words
- [x] A phase may be skipped, but only with a reason
- [x] `incision_without_timeout` — the finding the model exists to surface,
      computed from the time-out's timestamp against the incision's
- [x] Never enforced: a system that blocks the incision gets bypassed in a
      week, and then there is no record at all
- [x] Facility-wide safety audit: operations, breaches, breach rate, cases to
      review

**The case as it runs**
- [x] Timings: sent for, wheels in, anaesthesia, incision, closure, wheels
      out, left recovery
- [x] Start delay against the booked time
- [x] Operating minutes and theatre minutes reported separately — the room is
      always occupied longer than the operation takes
- [x] Performed procedure recorded separately from the planned one
- [x] Findings, complications, blood loss, specimens, post-op instructions
- [ ] Structured operation note templates per procedure

**Anaesthesia**
- [x] Technique and airway, intubation attempts, difficult airway flagged
- [x] Fluids in and urine out
- [x] Lowest systolic and lowest SpO₂ — the two numbers a later review asks for
- [x] Adverse events, reversal, post-operative analgesia plan
- [ ] Intra-operative observation charting at intervals

**Recovery**
- [x] Arrival and discharge from recovery, with minutes in recovery
- [x] Aldrete and pain scores
- [x] Nausea, shivering, complications
- [x] Where the patient went: ward, ICU, HDU, home
- [ ] Discharge criteria enforced as a checklist

**Consumption and implants**
- [x] Consumables, drugs, blood and implants recorded against the case
- [x] Batch consumed from theatre stock through the existing ledger
- [x] An implant demands a serial number — a recall asks which patients have
      one, and a product code cannot answer that
- [x] A serial already recorded against another patient is refused
- [x] Implanted site recorded
- [x] The recall register: serial → patient, MRN, phone, date, procedure
- [x] Cost by kind, implants reported separately
- [ ] Loan-set tracking and return

**Billing**
- [x] Each consumption raises a charge on the encounter
- [x] Unbilled items counted, so nothing quietly stays free
- [ ] Procedure and theatre-time charges from a tariff
- [ ] Package pricing for a whole procedure

**Cancellation**
- [x] A countable reason rather than free text
- [x] Avoidable cancellations distinguished from unavoidable ones — the
      number a theatre committee acts on
- [x] Postponement kept separate from cancellation
- [x] The slot is released

**Analytics**
- [x] Booked and used utilisation reported separately — a room booked to 90%
      that operates for 60% is not the same as one running perfectly
- [x] Cases starting late, and the average delay
- [x] Overruns against the surgeon's estimate
- [x] Cancellations by reason, with the avoidable share
- [x] Safety audit across the facility
- [ ] Surgeon-level and procedure-level duration benchmarks

## §32 Specialty clinical services 🔷

- [x] Facility → department → unit is the plug-in point
- [x] Common patient, encounter, billing, clinical and inventory spine
- [ ] Cath lab · dialysis · diabetes care · oncology · cardiology
- [ ] Paediatrics · obstetrics and gynaecology · dental · physiotherapy
- [ ] Dermatology · ophthalmology · ENT · psychiatry
- [ ] Nutrition · rehabilitation · day care · pain management

## §84 Mortuary `[ ]`

- [ ] Deceased record
- [ ] Time and date of death
- [ ] Ward of origin
- [ ] Identification
- [ ] Mortuary location assignment
- [ ] Release to an authorised person
- [ ] Documentation
- [ ] Audit trail

---

# Phase 7 — Facility operations `[ ]`

## §53 Procurement management `[~]`
- [x] Requisition, quotation, comparison and supplier selection
- [x] Purchase order, goods receipt and quality check
- [x] Supplier master: PAN/VAT, contacts, credit terms, drug licence
- [x] Licence expiry blocks ordering, re-checked at approval
- [x] Supplier performance measured from receipts — lead time variance, fill
      rate, rejection rate, overdue orders
- [x] Procurement screens: work queue, requisitions, orders,
      deliveries, suppliers
- [ ] RFQ issued to suppliers
- [ ] Supplier contracts
- [ ] Supplier invoice and payment posting
- [ ] Purchase returns
- [ ] Price history analytics

## §54 Contract management `[ ]`
- [ ] Contracts for suppliers, employees, doctors, insurers, vendors, equipment, maintenance, rent, corporate customers
- [ ] Start, end, renewal, value, terms, attachments
- [ ] Renewal reminders and approval

## §71 Asset management `[ ]`
- [ ] Register across medical, IT, furniture, vehicles, lab, ICU, theatre, buildings
- [ ] Purchase, serial, warranty, location, custodian, condition
- [ ] Depreciation · maintenance · disposal

## §72 Biomedical equipment `[ ]`
- [ ] Equipment master · preventive and corrective maintenance · calibration
- [ ] Service contracts · vendors · warranty · downtime · parts · service history
- [ ] Safety checks · certification · expiry

## §73 Maintenance management `[ ]`
- [ ] Preventive, corrective, emergency and calibration work
- [ ] Schedule → work order → technician → parts → cost → completion → verification

## §74 CSSD `[ ]`
- [ ] Instrument sets · sterilisation cycles · tray preparation · autoclave
- [ ] Cycle numbering · department request · issue · return · failed cycle · reprocessing · audit

## §75 Dietary `[ ]`
- [ ] Diet orders · types · allergies · meal schedule · kitchen · preparation
- [ ] Delivery · consumption · special diets · ingredient inventory · cost

## §76 Housekeeping `[ ]`
- [ ] Cleaning schedules · area assignment · tasks · room status
- [ ] Ward, washroom and infection-sensitive cleaning · inspection · escalation

## §77 Laundry `[ ]`
- [ ] Linen inventory · collection · washing · processing · issue · return
- [ ] Damage · loss · departmental consumption

## §78 Security `[ ]`
- [ ] Security staff · patrols · incidents · access points · restricted areas
- [ ] Lost and found · CCTV reference · escalation

## §79 Visitor management `[ ]`
- [ ] Registration · patient linkage · ID verification · pass issue
- [ ] Access duration · department restriction · check-in and out · history

## §80 Parking `[ ]`
- [ ] Vehicle and slot registry · entry and exit · visitor and staff parking · payment · occupancy

## §81 Ambulance `[ ]`
- [ ] Ambulance master · driver and crew · availability · dispatch
- [ ] Trip, pickup and destination · equipment · fuel · maintenance · revenue

## §82 Homecare `[ ]`
- [ ] Homecare patients · visit scheduling · staff assignment · services
- [ ] Medication · vitals · notes · billing · follow-up · mobile app

## §83 Medical camps `[ ]`
- [ ] Camp definition, location, date, staff, services
- [ ] Registration · screening · consultation · medicines · lab · referral · follow-up · analytics

## §121 Facility licence and compliance `[~]`
- [x] Facility licence number and expiry on the facility
- [ ] Pharmacy, laboratory and equipment certification
- [ ] Fire certification · insurance · accreditation · renewal tracking

---

# Phase 8 — Quality and governance `[ ]`

## §87 Clinical quality `[ ]`
- [ ] Clinical incidents · near misses · patient safety incidents · sentinel events
- [ ] Root cause analysis · corrective and preventive action
- [ ] Quality indicators · mortality and morbidity review · readmission · complications · clinical audit

## §88 Infection control `[ ]`
- [ ] Infection events · isolation · surveillance · hand hygiene · PPE
- [ ] Cleaning audits · antibiotic consumption · indicators · outbreak tracking · investigation

## §89 Accreditation and compliance `[ ]`
- [ ] Configurable frameworks · standards · checklists · evidence
- [ ] Policies and SOPs · responsible owner · status · audit · corrective action · review cycle

## §90 Incident management `[ ]`
- [ ] Incidents across patient, employee, medicine, equipment, facility, security, IT, finance, inventory
- [ ] Classification · investigation · assignment · corrective action · approval · closure

## §129 Privacy `[~]`
- [x] Physical tenant isolation
- [x] Access logging on sensitive reads
- [x] Data minimisation in audit diffs
- [ ] Sensitive clinical data controls
- [ ] Consent enforcement
- [ ] Data retention
- [ ] Record release
- [ ] Export authorisation
- [ ] Privacy requests
- [ ] Legal hold

---

# Phase 9 — Engagement and automation `[ ]`

## §91 Patient CRM `[ ]`
- [ ] Feedback · satisfaction · complaints · compliments · surveys
- [ ] Loyalty · follow-up · campaigns · segmentation · communication history

## §92 Marketing and growth `[ ]`
- [ ] Campaigns · offers · health packages · events · camps
- [ ] Referral, SMS and email campaigns · segmentation · lead management · conversion

## §93 Patient communication `[ ]`
- [ ] SMS, email, WhatsApp, push and in-app channels
- [ ] Templates: appointment, reminder, follow-up, prescription, lab result, invoice, payment, campaign, feedback, emergency
- [ ] Delivery tracking

## §94 Patient portal `[ ]`
- [ ] Profile · appointments · queue position · medical history
- [ ] Prescriptions · laboratory · radiology · invoices · payment · insurance
- [ ] Follow-ups · documents · telemedicine · family accounts

## §95 Employee self-service `[ ]`
- [ ] Profile · attendance · leave · roster · shift · payslip
- [ ] Loans · advances · claims · documents · performance · training · announcements

## §96 My workspace `[~]`
- [x] Doctor worklist — open encounters, triage-ordered
- [x] Laboratory worklist — STAT-first
- [ ] My tasks · approvals · notifications · reminders · schedule
- [ ] Nurse workspace: assigned patients, vitals, medication, handover
- [~] Pharmacist workspace: dispensing, stock, expiry and reorder screens
      built; POS and stock counts outstanding
- [ ] HR and finance workspaces
- [ ] Recent activity

## §97 Workflow engine `[~]`
- [x] Facility change requests as the first concrete instance
- [x] Derived approval routing
- [x] Multi-level approval
- [x] Conditions attached to an approval
- [ ] Generalised trigger / condition / step / approver model
- [ ] SLA and escalation
- [ ] Notification actions
- [ ] Workflow designer

## §98 Automation engine `[ ]`
- [ ] Rule definition (when / then)
- [ ] Stock below reorder → raise a requisition
- [ ] Contract expiring → notify HR
- [ ] Follow-up due → notify the patient
- [ ] Critical result approved → notify the physician and escalate

## §99 Universal reminder engine `[ ]`
- [ ] Appointment · follow-up · expiry · stock count · low stock
- [ ] Contract · licence · probation · payroll · payment · claim
- [ ] Maintenance · calibration · accreditation · subscription · tax filing · document expiry

## §100 Task management `[ ]`
- [ ] Owner · department · facility · priority · deadline · SLA · status
- [ ] Checklist · attachments · comments · escalation · audit

## §101 Notification centre `[ ]`
- [ ] Critical, warning, approval, task, reminder and information categories
- [ ] Central inbox across modules
- [ ] Read state and preferences

## §122 Document management `[ ]`
- [ ] Upload · versioning · metadata · owner · category
- [ ] Access control · expiry · approval · archive · retention · search

## §123 Template management `[ ]`
- [ ] Invoice · prescription · lab report · discharge · referral
- [ ] Salary slip · purchase order · receipt · consent · email · SMS · WhatsApp
- [ ] Tenant-specific branding

---

# Phase 10 — Intelligence `[ ]`

## §104 Global search `[ ]`
- [ ] Patient, employee, doctor, medicine, supplier, invoice, appointment, prescription, admission, lab, radiology, document
- [ ] Permission filtering applied before results are returned

## §105 Reporting engine `[ ]`
- [ ] Standard report library
- [ ] Custom builder: dataset → fields → filters → grouping → measures → sorting → visualisation
- [ ] PDF, Excel, CSV and print export
- [ ] Scheduled reports

## §106 Business intelligence `[ ]`
- [ ] Platform, organization, facility, department, unit, role, individual and transaction levels

## §107 Platform analytics `[~]`
- [x] Customers, facilities and revenue snapshot
- [ ] Plans · churn · features · modules · usage · API · storage · support · adoption · health

## §108–§113 Domain analytics `[ ]`
- [ ] Organization: revenue, profit, expense, cash, AR, AP, payroll, inventory, patients, facility comparison
- [ ] Hospital: OPD, IPD, emergency, ICU, theatre, lab and radiology volumes; waiting, TAT, discharge time, length of stay, occupancy
- [ ] Clinic: appointments, no-shows, doctor utilisation, consultation time, retention
- [ ] Pharmacy: sales, growth, basket, category, margin, stock value, expiry, dead stock, turnover, supplier
- [ ] HR: headcount, payroll, overtime, absence, attrition, cost, distribution, recruitment, training
- [ ] Finance: revenue, expense, cash flow, profit, AR, AP, tax, payroll liability, department and facility profitability

## §114 Operational intelligence `[ ]`
- [ ] What is happening · why · what changed · what is at risk · what will happen · what to do
- [ ] Narrative recommendations that show their reasoning

## §115 Exception management `[~]`
- [x] Stock-out risk with lead-time awareness
- [x] Expiry risk
- [x] Laboratory TAT breach
- [x] Quota and capacity risk
- [ ] Overstock · stock variance · revenue decline · expense spike
- [ ] Refund, discount and cash anomalies
- [ ] Staffing shortage · waiting-time breach · insurance ageing · payroll anomaly · equipment downtime

## §116–§117 Command centres `[ ]`
- [ ] Organization command centre with drillable KPIs
- [ ] Hospital, clinic and pharmacy facility command centres

---

# Phase 11 — Platform surface `[ ]`

## §124 Data import and migration `[ ]`
- [ ] Excel, CSV and API import
- [ ] Opening stock and opening balances
- [ ] Patients, employees, medicines, suppliers, customers, historical data
- [ ] Upload → mapping → validation → duplicate detection → preview → import → error report → audit

## §125 Interoperability `[~]`
- [x] REST API
- [x] OpenAPI schema and interactive docs
- [x] JWT authentication
- [ ] OAuth
- [ ] Webhooks
- [ ] FHIR
- [ ] HL7
- [ ] DICOM
- [ ] IRD / CBMS
- [ ] Payment gateways and banks
- [ ] SMS, WhatsApp and email providers
- [ ] Biometric, RFID and barcode devices
- [ ] Printers, laboratory analysers, PACS
- [ ] Accounting, insurance and government systems

## §126 Mobile apps `[ ]`
- [ ] Doctor · nurse · pharmacist · executive · employee · patient

## §127 Offline / degraded mode `[ ]`
- [ ] Local capability for registration, queue, appointment, vitals, prescription and POS
- [ ] Local transaction store
- [ ] Sync engine
- [ ] Idempotent, auditable synchronisation

## §130 Backup and disaster recovery `[~]`
- [x] Per-tenant databases make backup and restore per customer
- [x] Backup metadata fields on the tenant record
- [ ] RPO and RTO definition
- [ ] Backup schedule and retention
- [ ] Offsite backup and replication
- [ ] Restore testing

## §131 Platform observability `[~]`
- [x] Health and readiness endpoints
- [x] Tenant database status reporting
- [ ] API, database and queue health
- [ ] Background job monitoring
- [ ] Error log aggregation
- [ ] Infrastructure, storage, backup, integration, notification, search and sync monitoring

## §132 Customer support `[ ]`
- [ ] Tickets · priority · SLA · category · agent · escalation
- [ ] Internal notes · customer response · attachments · resolution
- [ ] Knowledge base · training

---

# Cross-cutting invariants

Rules that must hold in **every** module. Each is enforced in the core;
breaking one in a new module breaks the platform.

- [ ] Tenant data is reached only through the bound tenant context — never a
      hard-coded database alias.
- [ ] Transactions on tenant models open on the tenant database
      (`tenant_atomic`), never the control plane (log 044).
- [ ] Capability checks ask the entitlement service. Never `plan == "..."`.
- [ ] Every state-changing action writes an audit event.
- [ ] Every maker-checker pair declares `conflicts_with` on its permissions.
- [ ] Permission scope filters querysets; it does not only refuse requests.
- [ ] Records with clinical, financial or legal weight are versioned, not
      overwritten.
- [ ] A value shown to a clinician is formatted so it cannot be misread —
      trailing zeros never stripped before a decimal point (log 073).
- [ ] Every read of a patient's clinical history resolves the merge chain
      (`patient.resolve()`). A merged record has no allergies — they moved to
      the survivor — so an unresolved read reports a dangerous *clean* (log 054).
- [ ] Money is `Decimal` everywhere — never `float` — and rounds half-up.
- [ ] Quantities that must reconcile are held as an append-only ledger, with
      any cached total rebuildable from it (log 077).
- [ ] Where a reversal is recorded both as a status change *and* as a
      compensating row, exactly one of the two feeds any total (log 064).
- [ ] A figure compared across options is normalised first — cost per
      unit, not total spend, when the quantities differ (log 086).
- [x] Foreign keys are published as `uuid`, never as an integer primary
      key - `id` 42 is a different row in every tenant (log 090, 095).
      Audited at runtime across every serializer; re-runs clean.
- [x] `Decimal` is rendered as a string, never a float, including from
      hand-built dict responses (log 089).
- [ ] A document number that must be unique tenant-wide carries the
      facility that issued it (log 088).
- [ ] A figure reported as revenue or margin is net of returns, with
      write-offs charged to the day that caused them (log 091).
- [x] A change to somebody's posting writes history, never overwrites it
      (log 097).
- [x] A credential that expires is checked at the moment it matters, not
      in an audit — and unverified counts as blocking (log 097).
- [x] Nobody verifies, approves or attests their own record (log 097).
- [x] A balance that people dispute is the sum of an append-only ledger,
      never a stored counter (log 101).
- [x] A status that depends on later decisions is derived, not stored as
      gospel (log 101).
- [ ] Two figures compared against each other measure the same thing —
      clock time against paid hours manufactured a day's overtime for
      every employee (log 102).
- [x] A statutory rate is data, not code — the law changes yearly and a
      deployment is not a way to obey it (log 104).
- [x] A figure people will dispute carries its own derivation (log 104).
- [x] Rounding happens once, at the end, never per line (log 104).
- [x] Occupancy of anything is an interval, never a flag — "who was in
      that bed on the 14th?" has to be answerable (log 107).
- [x] A recurring charge is idempotent per period, enforced by a unique
      constraint rather than by the job running once (log 107).
- [ ] `get_queryset` returns a queryset. Computing a filter in Python is
      fine; returning the list is a 500 under DRF (log 109).
- [x] More than one aggregate over more than one relation needs
      `distinct=True` on every one — the first is always right, which is
      why the bug survives review (log 112).
- [x] A recurring price is normalised to a month before it is summed, and
      a trial is never counted as revenue (log 111).
- [x] A fact about what *happened* and a fact about what is *true now*
      are different fields. The giveaway is a count that reads zero when
      you know it should not (log 116).
- [x] A clock starts when the event started, not when somebody noticed
      it — otherwise the measurement hides the delay (log 115).
- [ ] Every error uses the standard envelope, with a stable `code`.
- [ ] Every change gets an entry in `DEVELOPMENT_LOG.md`.

---

# Notes on the specification

The specification supplied was **truncated at section 132** (Customer
Support). Anything beyond that is unknown and not represented here — send the
remainder and this checklist will be extended.
