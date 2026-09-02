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
| Done | 33 of 132 | 432 |
| Outstanding | 99 | 670 |

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
- [x] MRR and ARR
- [x] Paying customer count
- [ ] New / expansion / contraction / churned MRR
- [ ] ARPU, lifetime value, acquisition cost
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

## §55 Finance / accounting `[~]`

- [x] Billable service catalogue
- [x] Tax treatment per service: exempt, zero-rated, standard
- [x] Decimal money throughout, half-up rounding
- [x] Nepali fiscal year handling
- [ ] Chart of accounts
- [ ] General ledger and journals
- [ ] Cash and bank
- [ ] Accounts receivable ageing
- [ ] Accounts payable
- [ ] Expense management
- [ ] Tax ledger and VAT return preparation
- [ ] Fixed assets and depreciation
- [ ] Budgets
- [ ] Cost and profit centres
- [ ] Bank reconciliation

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

## §57 Insurance / TPA `[~]`

- [x] Insurance as a payer category with its own price list
- [x] Policy number on the patient
- [ ] Insurer and TPA master
- [ ] Policy and coverage records
- [ ] Eligibility check
- [ ] Pre-authorisation
- [ ] Claims and claim lines
- [ ] Submitted, approved, rejected and deducted amounts
- [ ] Settlement tracking
- [ ] Claim ageing and rejection analytics

## §58 Hospital billing `[~]`

- [x] Registration and consultation charges
- [x] Procedure, laboratory and radiology charges
- [x] Corporate and insurance pricing
- [x] Discounts and partial payment
- [ ] Room and bed charges
- [ ] Nursing charges
- [ ] Theatre and ICU charges
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

## §59 HRMS `[ ]`

**Employee record**
- [ ] Employee master and employee code
- [ ] Photograph
- [ ] Personal details and next of kin
- [ ] Position and designation
- [ ] Department and unit assignment
- [ ] Grade and level
- [ ] Facility posting
- [ ] Reporting manager
- [ ] Employment type: permanent, contract, locum, visiting

**Credentials and history**
- [ ] Contract records with expiry
- [ ] Document management per employee
- [ ] Professional licence and council registration
- [ ] Qualifications and specialities
- [ ] Prior experience
- [ ] Training records
- [ ] Performance history

**Lifecycle**
- [ ] Transfer
- [ ] Promotion and demotion
- [ ] Separation and exit
- [ ] Final settlement

**Integration**
- [ ] Employee → user account linkage
- [ ] Employee → provider linkage for schedules, prescriptions and results
      (today these hold a bare `provider_uuid` awaiting this) 🔷

## §60 Organization structure `[~]`

- [x] Organization → facility → department → unit
- [ ] Position definitions
- [ ] Employee-to-position assignment
- [ ] Headcount and vacancies
- [ ] Position budget
- [ ] Reporting hierarchy and org chart
- [ ] Job descriptions
- [ ] Approval authority per position

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

## §62 Employee onboarding `[ ]`

- [ ] Offer acceptance
- [ ] Document collection
- [ ] Verification
- [ ] Employee record creation
- [ ] Role and permission assignment
- [ ] Position and facility assignment
- [ ] Shift assignment
- [ ] Payroll enrolment
- [ ] Asset assignment
- [ ] Orientation checklist

## §63 Shift and roster `[ ]`

- [ ] Shift definitions: fixed, rotating, split, flexible, overnight
- [ ] On-call shifts
- [ ] Emergency and holiday shifts
- [ ] Department-specific shifts
- [ ] Roster by employee, date, facility, department
- [ ] Duty assignment
- [ ] Rest-period rules
- [ ] Working-hour limits
- [ ] Overtime rules
- [ ] Leave conflict detection
- [ ] Minimum staffing enforcement
- [ ] Double-booking prevention
- [ ] Roster publication and swap requests

## §64 Attendance `[ ]`

- [ ] Biometric capture
- [ ] Face recognition
- [ ] RFID
- [ ] Mobile check-in with GPS and geofence
- [ ] Web check-in
- [ ] Present, late, early-exit, absent and half-day statuses
- [ ] Leave, holiday and weekend handling
- [ ] On-duty and on-call marking
- [ ] Overtime capture
- [ ] Regularisation requests
- [ ] Attendance reports

## §65 Leave `[ ]`

- [ ] Types: annual, sick, maternity, paternity, unpaid, emergency, study, special, custom
- [ ] Accrual rules
- [ ] Balance tracking
- [ ] Carry forward
- [ ] Encashment
- [ ] Application and approval workflow
- [ ] Blackout periods
- [ ] Delegation during leave
- [ ] Leave calendar

## §66 Payroll `[ ]`

**Earnings**
- [ ] Payroll periods
- [ ] Basic pay
- [ ] Allowances
- [ ] Overtime calculation
- [ ] Shift allowance
- [ ] Incentives and commission
- [ ] Bonus
- [ ] Benefits

**Deductions**
- [ ] General deductions
- [ ] SSF contributions
- [ ] Provident fund
- [ ] Citizen Investment Trust
- [ ] TDS
- [ ] Loans and advances
- [ ] Loss of pay

**Processing**
- [ ] Arrears and retroactive adjustment
- [ ] Salary hold
- [ ] Partial payment
- [ ] Payroll correction
- [ ] Final settlement
- [ ] Payslip generation
- [ ] Bank transfer file
- [ ] Process ≠ approve (permissions already declared) 🔷

## §67 Compensation `[ ]`

- [ ] Compensation plans
- [ ] Grades
- [ ] Salary bands with minimum, midpoint and maximum
- [ ] Component structure per grade
- [ ] Revision history

## §68 Payroll rule engine `[ ]`

- [ ] Formula-based components
- [ ] Eligibility rules
- [ ] Taxability rules
- [ ] Contribution rules
- [ ] Effective dating
- [ ] Expiry
- [ ] Employee-group targeting
- [ ] Facility, position and grade targeting
- [ ] Several concurrent payroll structures

## §69 Nepal tax and statutory engine `[ ]`

- [ ] PAN handling
- [ ] VAT configuration
- [ ] TDS slabs
- [ ] Taxable and exempt income classification
- [ ] Tax deductions
- [ ] Fiscal year with effective dating (base implementation exists in billing) 🔷
- [ ] SSF employer and employee contributions
- [ ] PF employer and employee contributions
- [ ] CIT
- [ ] Configurable without a code change
- [ ] Statutory report generation

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

## §26 IPD / admission `[ ]`

- [ ] Admission request
- [ ] Admission approval
- [ ] Bed assignment
- [ ] Planned, emergency, observation and referral admission
- [ ] Consultant and attending physician
- [ ] Care team
- [ ] Deposit and advance
- [ ] Insurance linkage
- [ ] Ward transfer
- [ ] Discharge summary
- [ ] Discharge against medical advice

## §27 Bed and ward `[ ]`

- [ ] Building → floor → ward → room → bed hierarchy
- [ ] Eight bed statuses
- [ ] Bed transfer
- [ ] Bed reservation
- [ ] Bed release
- [ ] Isolation beds
- [ ] Cleaning workflow and turnaround
- [ ] Occupancy analytics
- [ ] Bed turnover and average length of stay
- [ ] Revenue per bed
- [ ] ICU and ward utilisation

## §28 Nursing `[ ]`

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

- [x] Triage categories modelled
- [x] Emergency encounter type
- [x] Emergency queue priority
- [ ] Arrival registration for unidentified patients
- [ ] Triage workflow
- [ ] Resuscitation record
- [ ] Emergency medication administration
- [ ] Emergency billing
- [ ] Disposition: discharge, admit, refer
- [ ] Critical alerts

## §30 ICU `[ ]`

- [ ] ICU bed management
- [ ] Continuous monitoring
- [ ] Fluid balance
- [ ] Infusion management
- [ ] Ventilator data
- [ ] Monitor device integration
- [ ] ICU nursing
- [ ] Consultant rounds
- [ ] Critical alerts
- [ ] ICU notes and scoring

## §31 Operation theatre `[ ]`

- [ ] Procedure request
- [ ] Pre-operative assessment
- [ ] Approval
- [ ] Theatre scheduling
- [ ] Surgical team assignment
- [ ] Anaesthesia record
- [ ] Procedure record
- [ ] Implant tracking
- [ ] Consumable and drug consumption
- [ ] Recovery
- [ ] Documentation
- [ ] Theatre billing
- [ ] Utilisation, duration, delay and cancellation analytics

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
      key - `id` 42 is a different row in every tenant (log 090).
- [x] `Decimal` is rendered as a string, never a float, including from
      hand-built dict responses (log 089).
- [ ] A document number that must be unique tenant-wide carries the
      facility that issued it (log 088).
- [ ] A figure reported as revenue or margin is net of returns, with
      write-offs charged to the day that caused them (log 091).
- [ ] Every error uses the standard envelope, with a stable `code`.
- [ ] Every change gets an entry in `DEVELOPMENT_LOG.md`.

---

# Notes on the specification

The specification supplied was **truncated at section 132** (Customer
Support). Anything beyond that is unknown and not represented here — send the
remainder and this checklist will be extended.
