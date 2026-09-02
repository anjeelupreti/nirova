# Implementation Checklist

Every section of the master product specification, with its current status.
This is the map of what exists, what is next, and what has not been started.

**Legend**

| Mark | Meaning |
|---|---|
| ✅ | Built and verified against a running stack |
| 🟡 | Partially built — the foundation exists, listed gaps remain |
| ⬜ | Not started |
| 🔷 | Architecturally provided for — the seam exists, the module does not |

**Progress:** 17 of 132 sections complete, 10 partial.
The completed set is deliberately the platform core: every remaining module
depends on tenancy, identity, RBAC and entitlements, and building a vertical
first would mean rewriting it.

---

## Phase 0 — Platform core  ✅ complete

*Sections 0–17, 102–104, 128. This is the layer everything else stands on.*

| § | Section | Status | Notes |
|---|---|---|---|
| 0 | Product definition | ✅ | Organization = tenant; hospital/clinic/pharmacy = facility |
| 1 | System hierarchy | ✅ | Organization → Facility → Department → Unit |
| 2 | Platform owner / control plane | 🟡 | Dashboard, organizations, plans, subscriptions, approval queue. CRM, support, billing UI outstanding |
| 3 | Platform executive dashboard | 🟡 | Org counts, facility counts by type, MRR/ARR, request queue, infrastructure health. Product and technical KPIs outstanding |
| 4 | Customer health scoring | ⬜ | Usage counters exist to feed it |
| 5 | SaaS CRM | ⬜ | |
| 6 | Tenant onboarding | 🟡 | Provisioning, seeding and default departments work. Guided wizard and completion tracking outstanding |
| 7 | Subscription engine | ✅ | Plans, add-ons with quantity, versioning, lifecycle events, MRR history |
| 8 | Entitlement engine | ✅ | Four-layer resolution with provenance. No plan-name checks anywhere |
| 9 | Usage metering | ✅ | Append-only events, rolled-up counters, idempotency keys |
| 10 | Organization / tenant core | ✅ | Profile, PAN/VAT, fiscal config, branding, Nepal geography |
| 11 | Facility management | ✅ | All 8 types, request-and-approval lifecycle |
| 12 | Global context switcher | ✅ | `X-Organization` / `X-Facility` headers, validated server-side |
| 13 | Centralised management | 🟡 | Central admin and policy exist. Central HR/payroll/procurement await those modules |
| 14 | Configuration inheritance | ✅ | Platform → org → facility → department, with lockable values |
| 15 | Identity management | 🟡 | Password, JWT, lockout, devices, login history. MFA and SSO are modelled but not implemented |
| 16 | RBAC + ABAC | ✅ | 7-level scope ladder, per-user overrides, scope filters querysets |
| 17 | Segregation of duties | ✅ | Declared conflicts, checked at role save and at approval |
| 102 | Audit logging | ✅ | Append-only, in the tenant database, field-level diffs, secrets redacted |
| 103 | Data version history | ✅ | `EntityVersion` snapshots for records whose history must survive edits |
| 104 | Global search | ⬜ | Must filter by permission before returning results |
| 128 | Security | 🟡 | Tenant isolation, RBAC/ABAC, TLS-ready, audit, rate limiting outstanding |

---

## Phase 1 — Clinical foundation  🟡 in progress

*Sections 18–24, 85, 86. Everything clinical and most of billing depends on
the patient and encounter models, so these come before any vertical.*

| § | Section | Status | Notes |
|---|---|---|---|
| 18 | Clinic OS | 🟡 | Registration, patients, appointments and queue done. EMR, prescription and billing outstanding |
| 19 | Patient management | ✅ | Demographics, identifiers, allergies, conditions, duplicate detection, merge. All patient types supported including walk-in with no documents |
| 20 | Appointment management | ✅ | Provider schedules, slots, overbooking capacity, walk-in reserve, exceptions, cancellation, no-show, follow-up chains |
| 21 | Queue management | ✅ | Tokens per facility-day, triage priority, call / recall / skip, the four timestamps that make waiting time measurable |
| 22 | Clinical / EMR | ⬜ | Next: encounters, SOAP notes, vitals |
| 23 | Prescription | ⬜ | Allergy checking is already modelled — `blocks_prescribing` |
| 24 | Referral management | ⬜ | |
| 85 | Medical records / HIM | 🟡 | Merge, duplicate detection and version history exist. Indexing, release and retention outstanding |
| 86 | Consent management | 🟡 | Per-channel communication consent on the patient. Procedure and data consent outstanding |

---

## Phase 2 — Pharmacy and inventory  ⬜

*Sections 37–52. The shortest path to revenue for standalone pharmacy
customers, and the module a hospital needs first.*

| § | Section | Status |
|---|---|---|
| 37 | Pharmacy OS (7 deployment shapes) | ⬜ |
| 38 | Product master | ⬜ |
| 39 | Batch management | ⬜ |
| 40 | Pharmacy inventory (18 transaction types) | ⬜ |
| 41 | FEFO with authorised override | ⬜ |
| 42 | Expiry management (9 thresholds) | ⬜ |
| 43 | Recall | ⬜ |
| 44 | Pharmacovigilance | ⬜ |
| 45 | Controlled / restricted medicines | ⬜ |
| 46 | Cold chain | ⬜ |
| 47 | Pharmacy POS | ⬜ |
| 48 | Pharmacy procurement | ⬜ |
| 49 | Wholesale / distribution | ⬜ |
| 50 | Inventory / supply chain platform | ⬜ |
| 51 | Inventory forecasting | ⬜ |
| 52 | Stock counting | ⬜ |

---

## Phase 3 — Finance and revenue cycle  ⬜

| § | Section | Status |
|---|---|---|
| 53 | Procurement management | ⬜ |
| 54 | Contract management | ⬜ |
| 55 | Finance / accounting | ⬜ |
| 56 | Revenue cycle management | ⬜ |
| 57 | Insurance / TPA | ⬜ |
| 58 | Hospital billing | ⬜ |
| 70 | Expense / claim management | ⬜ |

---

## Phase 4 — People  ⬜

| § | Section | Status |
|---|---|---|
| 59 | HRMS | ⬜ |
| 60 | Organization structure | 🟡 — facility/department/unit exist; position and headcount do not |
| 61 | Recruitment / ATS | ⬜ |
| 62 | Employee onboarding | ⬜ |
| 63 | Shift and roster | ⬜ |
| 64 | Attendance | ⬜ |
| 65 | Leave | ⬜ |
| 66 | Payroll | ⬜ |
| 67 | Compensation | ⬜ |
| 68 | Payroll rule engine | ⬜ |
| 69 | Nepal tax / statutory engine | ⬜ |
| 118 | Performance management | ⬜ |
| 119 | Training / learning | ⬜ |
| 120 | License / credential management | ⬜ |

---

## Phase 5 — Hospital OS  ⬜

| § | Section | Status |
|---|---|---|
| 25 | Hospital OS | ⬜ |
| 26 | IPD / admission | ⬜ |
| 27 | Bed / ward | ⬜ |
| 28 | Nursing | ⬜ |
| 29 | Emergency / casualty | ⬜ |
| 30 | ICU | ⬜ |
| 31 | Operation theatre | ⬜ |
| 32 | Specialty clinical services | 🔷 — facility/department/unit is the plug-in point |
| 84 | Mortuary | ⬜ |

---

## Phase 6 — Diagnostics  ⬜

| § | Section | Status |
|---|---|---|
| 33 | Lab / LIMS | ⬜ |
| 34 | Lab quality | ⬜ |
| 35 | Radiology / RIS / PACS | ⬜ |
| 36 | Blood bank | ⬜ |

---

## Phase 7 — Facility operations  ⬜

| § | Section | Status |
|---|---|---|
| 71 | Asset management | ⬜ |
| 72 | Biomedical equipment | ⬜ |
| 73 | Maintenance management | ⬜ |
| 74 | CSSD / sterile services | ⬜ |
| 75 | Dietary | ⬜ |
| 76 | Housekeeping | ⬜ |
| 77 | Laundry | ⬜ |
| 78 | Security | ⬜ |
| 79 | Visitor management | ⬜ |
| 80 | Parking | ⬜ |
| 81 | Ambulance | ⬜ |
| 82 | Homecare | ⬜ |
| 83 | Medical camp | ⬜ |
| 121 | Facility license / compliance | ⬜ |

---

## Phase 8 — Quality and governance  ⬜

| § | Section | Status |
|---|---|---|
| 87 | Clinical quality management | ⬜ |
| 88 | Infection control | ⬜ |
| 89 | Accreditation / compliance | ⬜ |
| 90 | Incident management | ⬜ |
| 129 | Privacy | 🟡 — access logging and isolation exist; consent, retention and legal hold do not |

---

## Phase 9 — Engagement and automation  ⬜

| § | Section | Status |
|---|---|---|
| 91 | Patient CRM | ⬜ |
| 92 | Marketing / growth | ⬜ |
| 93 | Patient communication | ⬜ |
| 94 | Patient portal | ⬜ |
| 95 | Employee self-service | ⬜ |
| 96 | My workspace | ⬜ |
| 97 | Workflow engine | 🔷 — the facility approval workflow is the first concrete instance; generalise from it |
| 98 | Automation engine | ⬜ |
| 99 | Universal reminder engine | ⬜ |
| 100 | Task management | ⬜ |
| 101 | Notification centre | ⬜ |
| 122 | Document management | ⬜ |
| 123 | Template management | ⬜ |

---

## Phase 10 — Intelligence  ⬜

| § | Section | Status |
|---|---|---|
| 105 | Reporting engine | ⬜ |
| 106 | Business intelligence | ⬜ |
| 107 | Platform analytics | 🟡 — dashboard exists; churn, adoption and health do not |
| 108 | Organization analytics | ⬜ |
| 109 | Hospital analytics | ⬜ |
| 110 | Clinic analytics | ⬜ |
| 111 | Pharmacy analytics | ⬜ |
| 112 | HR analytics | ⬜ |
| 113 | Finance analytics | ⬜ |
| 114 | Operational intelligence | ⬜ |
| 115 | Exception management | ⬜ |
| 116 | Management command centre | ⬜ |
| 117 | Facility command centre | ⬜ |

---

## Phase 11 — Platform surface  ⬜

| § | Section | Status |
|---|---|---|
| 124 | Data import / migration | ⬜ |
| 125 | Interoperability (REST, FHIR, HL7, DICOM) | 🟡 — REST and OpenAPI exist; FHIR/HL7/DICOM do not |
| 126 | Mobile apps | ⬜ |
| 127 | Offline / degraded mode | ⬜ |
| 130 | Backup / disaster recovery | 🟡 — per-tenant databases make it per-customer; schedule and restore testing outstanding |
| 131 | Platform observability | 🟡 — health and readiness endpoints; no metrics pipeline |
| 132 | Customer support | ⬜ |

---

## Cross-cutting invariants

Rules that must hold in **every** module built from here. Each is already
enforced in the core; breaking one in a new module breaks the platform.

- [ ] Tenant data is reached only through the bound tenant context — never a
      hard-coded database alias.
- [ ] Transactions on tenant models use `tenant_atomic()`, never a bare
      `@transaction.atomic` — which silently opens on the control plane and
      leaves the writes unprotected (development log 044).
- [ ] Capability checks ask the entitlement service. Never `plan == "..."`.
- [ ] Every state-changing action writes an audit event.
- [ ] Every maker-checker pair declares `conflicts_with` on its permissions.
- [ ] Permission scope filters querysets; it does not only refuse requests.
- [ ] Records with clinical, financial or legal weight are versioned, not
      overwritten.
- [ ] Every error uses the standard envelope, with a stable `code`.
- [ ] Every change gets an entry in `DEVELOPMENT_LOG.md`.

---

## Notes on the spec

The specification supplied was **truncated at section 132** (Customer
Support). Sections beyond that are unknown and not represented here — send the
remainder and this checklist will be extended.
