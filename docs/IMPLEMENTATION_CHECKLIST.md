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
| 🔷 | Built to depth and running, with named lines still outstanding |

**Progress**

| | Sections | Feature lines |
|---|---|---|
| Built `[x]` | 22 | 1,386 |
| Built to depth 🔷 | 11 | — |
| Partial `[~]` | 51 | 3 |
| Not started `[ ]` | 42 | 691 |
| **Done** | **33 of 127** | **1,386 of 2,080** |
| **Outstanding** | **94** | **691** |

*Counted by script on 11 September 2026, after the console rebuild (§273) and
the palette, navigation, role-editor and persona work that followed it (§274).*

**The line count jumped from 1,212 to 2,057 and that is not progress, it is
scope arriving.** The previous figure was a hand count taken on 6 September;
the difference is partly the three new sections and partly that a hand count
of two thousand checkboxes is not a count. It is a script now
(`^- \[x\]` and its siblings), so the next recount is comparable to this one.

The section total moved from 132 to **127** for a duller reason: 132 is the
specification's numbering, and this file groups some of it — `§108–§113 Domain
analytics` is one heading covering six. Nothing was dropped.

Counted by feature rather than by section, because "Hospital OS" as a single
line hid that it is forty distinct capabilities. The section-level view
flattered the position; this one does not.

693 understates the remaining work: in the later phases some lines group
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
- [x] **One live subscription per organization**, as a partial unique
      constraint over the entitled statuses. Nothing enforced this, and the
      demo tenant ended up on `enterprise` *and* `professional` at once:
      entitlement resolution picked the narrower and the hospital module
      silently vanished, while the subscription screen showed a healthy active
      plan. A duplicate row that reads as valid is worse than a missing one
      (log 272)
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

- [x] Platform default → organization → facility → department. **Stored
      since the module was built; nothing read it until 6 September 2026** —
      this line was `[x]` on the strength of the table's shape. The resolver
      is `apps/organization/config.py`
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

## §16 RBAC + ABAC `[~]`

- [x] Permission catalogue declared in code
- [x] Roles as customer-editable data
- [x] Role inheritance
- [x] Fifteen seeded system roles
- [x] Seven-level scope ladder: own → own patients → unit → department → facility → multi-facility → organization
- [x] Scope decides whether a request is refused
- [~] **Scope narrows what an allowed request returns.** The mechanism
      now exists — `apply_scope_filter` in `apps/common/permissions.py` —
      and `Scope.OWN` is enforced through it. It is applied to three
      endpoints so far: employees, attendance and payslips
- [x] Every branch of `apply_scope_filter` returns explicitly, and the
      fall-through denies. It shipped ending `return queryset`, which
      handed back the whole organization for a `DEPARTMENT` grant, a
      `UNIT` grant, and a facility-scoped grant naming no facility. See
      log 157: that last case inverted the defect below from fail-closed
      to fail-open
- [ ] The same filtering applied to the clinical and transactional lists
      — prescriptions, invoices, dispenses, sales, diagnostic orders.
      These still return the whole organization to anyone allowed to read
      them at all, which is the finding of 4 September. See §129 for the
      decision it is waiting on
- [ ] **`assign_role` refuses a facility-scoped assignment with no
      facility named.** It currently accepts one. Now that
      `apply_scope_filter` denies on an empty facility set this is
      fail-closed again — the user appears to hold a role and can see
      nothing — but the assignment should never have been storable.
      Queued rather than done because it would invalidate assignments
      that already exist
- [x] Clinical records carry the department they happened in. The field
      existed and every caller passed `None` — 123 of 123 encounters recorded
      none. Resolved by code then kind, so renaming a department does not
      break it; 187 rows backfilled
- [x] `Scope.DEPARTMENT` narrows to the department, not the parent facility.
      Written, reverted and restored the same day — the revert was right while
      the attribution was missing, and the order is the lesson. Measured: 61
      at facility scope, 28 inpatient, 33 emergency
- [x] A row with no department is **included**, not hidden — an unattributed
      encounter is not evidence it belongs to somebody else
- [ ] `Scope.UNIT` narrows to the unit. Units are recorded on almost nothing
      yet, so this needs the same attribution step first
- [x] **Clinical reads no longer demand facility scope.** `doctor`, `nurse`
      and `lab_technician` all carry `max_scope = department`, so they could
      never satisfy the `Scope.FACILITY` default — a doctor was refused seven
      of nine clinical endpoints, including the patient list. Fixed per
      endpoint, and scheduling gained the queryset narrowing it had never
      needed while the check was refusing everybody anyway
- [x] **Swept: every role against all 72 parameterless GET endpoints.** Most
      refusals are correct; three were not — the doctor's own worklist, and
      the emergency board and summary
- [x] A test fails on any 5xx from any endpoint for any role. A 403 is an
      answer; a 500 is a bug, and an endpoint only the right role can reach is
      an endpoint only the right role can crash
- [x] **Writes swept too.** A doctor could read everything their job needs and
      write none of it — no consultation, prescription, order or appointment.
      Thirty clinical write sites lowered; stock, purchase, till and theatre
      overrides keep their facility floor, being genuinely facility-wide acts
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
- [x] Export and print logging. `EXPORT`, `PRINT` and `DOWNLOAD` existed in
      the enum and had never been recorded once — wired to report CSV, every
      document download (not only a patient's), and the payslip printable
- [x] An export records **what was in it** — the report, its parameters, the
      row count — so "what was in that file?" is answerable without keeping
      the file
- [x] A printable is recorded as "produced", never as "printed". Whether
      anybody pressed print is not observable over HTTP, and an append-only
      log that overstates gets quoted back as fact
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

## Columns declared and never written

*Found by asking the source, not the database. Three passes, and the first two
were wrong in ways worth recording.*

*Asking the **database** which columns are null on every row returned 466 — it
cannot tell "no code writes this" from "the seed does not fill it in".*

*Asking the **Python** for a constructor keyword, an attribute assignment or a
name near an `update()` returned 166 — better, but it misses the least visible
way a field gets written: **a DRF serializer writes every name in its `fields`
tuple generically**, with the field never appearing on the left of an
assignment. `Supplier.drug_licence_expires_on` and `Facility.license_expires_on`
were both reported unwired and are both editable through their API.*

*Splitting those two buckets gives the real numbers: **55 fields nothing can
write at all**, and **107 that only an API can write** — empty because no
screen collects them, which is a different problem. The difference between a
list somebody acts on and a list somebody stops believing.*

*These are the ones that are a missing feature wearing a column as a disguise.*

- [x] `Invoice.due_date` — nothing could be overdue (§205)
- [x] `EmploymentContract.ends_on` — no fixed term could run out (§206)
- [x] `CriticalValueAlert.escalated_at` / `escalation_note` — **a critical
      result nobody acknowledged could never be escalated** (§207)
- [x] `Patient.date_of_death` / `cause_of_death` / `PatientStatus.DECEASED` —
      recorded by `record_death`, called from the ward and ICU paths that
      observe a death, cancelling future appointments but not past ones
      (§208)
- [ ] `AnaesthesiaRecord.difficult_airway_detail`, `intubation_attempts`,
      `lowest_spo2`, `lowest_systolic`, `adverse_events` — a difficult airway
      not recorded is a risk to the *next* anaesthetic
- [ ] `TransfusionReaction.investigation_findings` /
      `reported_to_authority_at` — reportable events that cannot be recorded
      as reported
- [x] `User.password_changed_at` — declared and never assigned, so the age of
      every password was unknown and any rotation rule unenforceable. Now
      stamped by `set_password` itself, which is the only level that makes it
      true for every caller (§209)
- [x] `Supplier.drug_licence_expires_on` — an editor on the supplier panel,
      and a reminder that watches it. The table already painted "expired" in
      red and the column was empty everywhere, so the red never appeared (§213)
- [ ] `Facility.license_expires_on` — the reminder exists and watches six
      months out; the field is still collected on no screen, and facilities are
      deliberately read-only outside the change-request flow, so this needs a
      decision about whether a licence renewal is a "facility change"
- [ ] `TenantDatabase.last_backup_at` / `backup_location` — **nothing records
      that a backup happened.** For a healthcare tenant that is the most
      serious entry on this list
- [x] `UsageEvent.idempotency_key` — supplied at both call sites, keyed on the
      subject rather than the moment, with the insert in a savepoint so a
      collision cannot abort the caller's transaction (§210)
- [ ] `User.mfa_secret` / `mfa_enabled` — MFA is declared and not implemented
- [ ] No self-service password change endpoint at all; `must_change_password`
      exists with nothing to satisfy it
- [ ] `Appointment.reminder_sent_at` — appointment reminders cannot be tracked;
      needs §93's channels
- [ ] `Subscription.current_period_start` / `current_period_end` — billing
      periods are never set on the control plane
- [ ] `Encounter.previous_encounter` — follow-up visits are not linked to what
      they follow up
- [ ] `Policy.card_number`, `sub_limits`, `exclusions`, `waiting_period_until`
      — an insurance policy records none of its terms
- [ ] `Employee.emergency_contact_*` — collected on no screen

## Write endpoints guarded only by a read permission

*A DRF `ModelViewSet` permits every verb by default, so the guard has to be
written for each one and its absence looks like nothing at all. Measured with an
empty PATCH against every patchable route as eight roles: **31 accepted a write
from somebody who should not have one**. See §211.*

- [x] `HasPermission.of(read, write=...)` — a different permission on an unsafe
      verb, in one declaration that is hard to half-write
- [x] Applied to twenty viewsets across billing, pharmacy, insurance, payroll,
      finance, HR, inpatient, diagnostics, scheduling, theatre, procurement
- [x] `HolidayViewSet` and `LeaveTypeViewSet` had **no permission at all**
      beyond being signed in, and they decide attendance and therefore pay
- [x] `SupplierViewSet.perform_update` — an auditor could change a supplier's
      bank account number
- [x] **And who can no longer do their job?** Asked a day late. An HR manager
      could not add a public holiday and a pharmacy manager could not add a
      medicine, because both had been routed to `config.update`. Maintaining a
      catalogue is not the same authority as changing the organization's
      configuration — `catalog.manage` now covers products, stock locations,
      service items and diagnostic tests; the HR calendar sits behind
      `employee.manage`; price lists and payer contracts stay tight (§215)
- [x] **DELETE measured and clean.** Run inside a test, which rolls back, so a
      sweep that would have destroyed the demo tenant as a script was harmless.
      Eight routes accept a DELETE and every one of them from a role that holds
      the write permission — the `write=` guard covers any unsafe verb, not
      only PATCH. And `BaseModel.delete()` is a soft delete, so a tax slab a
      historical payslip was computed from does not vanish from under it
- [x] **POST measured.** An *empty* body separates the answers without needing
      a valid one per endpoint: 403 is refused, 400 is past the permission and
      stopped by validation, 500 is past both and into the database. It
      reported twenty 500s, **nineteen of which were the probe's own poisoned
      transaction** — one real bug: creating a payroll profile could never
      succeed at all (§214)

## §130 Console experience

*Not in the original 132 sections, and that is the point: the specification
describes what the system must **do** and says almost nothing about what using it
is **like**. Raised on 7 September 2026 after a walk through the console, and
tracked here so it competes for attention with the rest rather than being done
when somebody happens to notice.*

*Extended on 11 September 2026 (log 273) after a second walk that concluded the
console was not pitchable. The lines below the design-system heading did not
exist before that: the theme, the type, the colour semantics and the loading
states were not tracked anywhere, so they were nobody's work.*

**Design system**
- [x] **Three-tier tokens** — `styles/tokens/{primitive,semantic,component}.css`.
      The shadcn contract is kept name-for-name, so all 44 screens and every
      existing utility class kept working and only the values moved
- [x] Warm neutrals (hue 40–60) replacing shadcn's blue-tinted slate, so the
      two themes stop being two different designs
- [x] The console's dark background moved off pure black to `#0A0A0A`. This
      *reverses* part of §267 deliberately: the OLED argument is right for a
      phone at a bedside and wrong for an LCD under strip lights, where pure
      black behind light text haloes. The patient application keeps true black
- [x] **Clinical colour semantics** — acuity 1–5, good/warning/serious/critical/
      info each as ink + tint + ink-on-tint, plus recessive chart chrome
- [x] `StatusBadge` / `StatusDot` / `AcuityBadge` / `TrendBadge` / `Freshness`,
      with every status string this product emits mapped to a tone in one
      table, and an unknown status resolving to neutral rather than to a guess
- [x] Typography: Geist and Geist Mono, self-hosted (a hospital network that
      blocks a font CDN would otherwise silently fall back), a named type
      scale, and **tabular figures by default** — 25 of 44 screens had
      remembered `tabular-nums` and 19 had not
- [x] Elevation, radius and focus as scales rather than per-component choices.
      In dark mode elevation is lightness, not shadow
- [x] A real mark, replacing the lucide `Activity` glyph that had been the
      product's identity for nine months
- [x] **325 raw Tailwind colour utilities → zero**, across 29 files, by codemod
      rather than by hand: 29 files, several over 2,000 lines, is how you
      introduce a different defect in each. The mapping keyed hue family to
      domain state, with the *step* deciding ink-on-tint from ink-on-page —
      collapsing `text-red-200` and `text-red-700` to one token makes one of
      them invisible. The 48 `dark:` variants were **deleted**, not translated:
      `text-warning` is already right in both modes, and keeping the pair
      re-introduces the split. Two decorative gradients it refused to guess at
      were done by hand. The ratchet now sits at 0 (§274)
- [x] **Five selectable palettes**, each computed and contrast-validated rather
      than chosen — 65 assertions across the five, in both modes. The verdict
      on the first one was "boring and dim", and it was: a 45%-luminance accent,
      pure grey chrome, and no second colour anywhere. The fix that mattered is
      that a fill now carries **dark ink where it can**, instead of every button
      being darkened until white text fits — which is what made the teal deep
      and lifeless. `#007865` → `#10B7A0` (§274)
- [x] Neutrals tinted with the brand hue at 5–13% — below the point at which
      anybody would name the colour, above the point at which the interface
      looks like a wireframe
- [x] `--hero` / `--hero-2` / `--hero-foreground`: a deep brand surface for the
      one banner at the top of a portal. Replaces hand-rolled literal gradients
      that ignored the palette and had no dark form
- [ ] An organization's own accent. `Organization.primary_color` has been on
      the model and in the frontend's type all along, read by nothing
- [x] `/design` renders every token, state and chart form on one scroll.
      Every dark-mode defect above existed because there was nowhere to see all
      of it at once
- [x] Every screen migrated onto the colour tokens
- [ ] The remaining screens migrated onto `DataView`, `Tabs` and `<Can>`.
      Colour is done; composition is not

**Components that existed and were used by nothing**
- [x] `@radix-ui/react-tabs` — installed since the first commit, zero imports,
      while **17 screens hand-rolled their own tab strip** with no keyboard
      support and no linkable tab. Now one `<Tabs>` with `?tab=` sync
- [x] `SegmentedControl` — written, exported, zero usages. It is the view
      switch in `DataView`
- [ ] `Timeline` — written, exported, still zero usages. It is what
      `/patients/:uuid` needs, and that screen does not exist yet
- [x] `landing` preference — declared in `preferences.py`, offered on My
      account, saved, **and read by nothing**. `resolveHome` reads it now
- [x] `Organization.primary_color` — on the model and in the frontend's type
      all along, rendered by nothing. The shell shows the customer's identity
- [ ] `@radix-ui/react-dialog`, `-select`, `-progress`, `-label` — installed,
      still reimplemented by hand in `primitives.tsx`

**Loading, empty and failed**
- [x] Five distinct waits, five treatments: nothing under 250ms (`Delayed`),
      a skeleton on first load, `RouteProgress` for a chunk, `Refreshing` for a
      refetch, an in-button spinner for an action
- [x] **Once a screen has data it never goes back to a skeleton.** Somebody
      reading row forty should still be looking at row forty
- [x] A failed chart says so rather than rendering an empty axis. "0% occupancy
      because the service failed" and "0% because the ward is empty" must not
      look the same — this is the most dangerous defect a dashboard can have

**Navigation**
- [x] **The rail is its own surface.** Header, rail and content were all
      `--background`, so the application had no frame and the links appeared to
      float on the page — most of why the navigation "looked like a list of
      things" despite being correctly grouped
- [x] Collapsible groups, remembered per browser; pinned screens above the
      groups; approval and unread counts on the rail
- [x] A folded group still reports what is waiting inside it, because folding a
      group must not hide an approval queue
- [x] **Command palette (⌘K, Ctrl-K, `/`)** over records, screens and actions,
      reusing the omnibox's stale-response guard
- [x] The navigation moved to `components/shell/nav.ts` — three things consume
      it now (rail, narrow strip, palette) and a second copy would be a rail
      and a palette that disagree about what the product contains
- [x] **The rail is the work; the avatar is the system** (§274). Everything
      lived in the rail, so it carried forty entries including six things
      somebody opens twice a year — Configuration, Change requests, Import
      records, Plan and usage, Staff access, Roles — at the same weight as the
      queue somebody opens forty times a day. Every mature product of this
      shape splits the two the same way. The rail went 36 → 30
- [x] A `/settings` hub, and the six behind the avatar menu
- [x] They stay in the *model* rather than being deleted from it:
      `SYSTEM_ITEMS` sits beside `NAV_GROUPS`, the rail renders one and the
      command palette renders both. Deleting them would make "Configuration" a
      screen you can only reach by remembering it is under an avatar
- [ ] A facility switcher in the shell. The header switches *organizations*; a
      three-hospital customer has no visible sense of which building they are
      in. The dashboard has a per-board facility selector; the shell does not
- [x] A screen nobody in this role can open is not in their sidebar. Each
      item's permission **and scope** are derived from the endpoints its screen
      calls, not guessed; a doctor went from sixteen items with eleven dead to
      six that all open (§219)
- [x] Regrouped by the job: ten groups of two to five, replacing a "Clinical"
      group of eleven spanning outpatients, inpatients, theatre and the lab
- [x] Self service moved to Mine
- [ ] **A doctor can reach six of twenty-five screens.** Honest, and thin. ICU,
      blood bank, referrals and the nurse workspace ask for `encounter.read` at
      *facility* while a doctor holds *department* — the same defect fixed for
      other clinical reads earlier. Whether a doctor should reach those is a
      clinical access decision, not a refactor

**Responsiveness**
- [x] The patient application widens by breakpoint instead of being capped at
      phone width at every size. It contained **no responsive class at all**
      — the sign-in form still stays narrow on purpose, because a form
      stretched across a monitor is harder to use (§220)
- [ ] The rest of the patient application's detail screens, checked at width —
      the shell adapts now, each section's own content has not been looked at
- [ ] Every console screen at tablet width. The sidebar already collapses to a
      strip; the screens behind it assume a desk

**Depth: view-only screens with nowhere to go**
- [x] `DetailPanel` and `DetailRow`: one component so a row opens the same way
      everywhere, a slide-over on a wide screen and a full sheet on a narrow
      one. A missing value renders as an em dash, because blank reads as
      "failed to load" (§221)
- [x] `MasterData`: a whole configure-this-list screen from a description —
      columns, fields, required marks, search, empty state, detail and edit.
      Each new list is about twenty lines (§225)
- [x] Facilities, which had the least and gains the most: address, contact,
      operating hours, licence with an expiry that turns red once past, and
      every department — all of it already returned by an endpoint no screen
      had ever called
- [ ] The other twenty-seven screens. Measured flattest first: Queue, change
      requests and Pharmacy (seventeen rows, no detail at all), then Platform
      and Time
- [ ] Edit as well as view, where editing is legitimate. Facilities is
      deliberately not — they change only through an approved request
- [~] Empty states that say what to do next rather than showing an empty
      table. The catalogue has one; the rest do not

## The console does not know what it may do

*`useSession` has exposed `can(permission)` since it was written and **no screen
used it**, so every action is offered to everybody and left to the API to refuse
(§216).*

*Checked rather than assumed: of the twenty-six endpoints that gained a write
guard in §211, exactly one is written to by the console. **The other
twenty-five have no screen at all** — no form creates a product, a price list, a
holiday, a ward or a tax slab, which is why they sat unguarded so long.*

- [x] The supplier licence editor asks before offering the form
- [ ] The other twenty-seven screens. A deliberate pass, not something to do
      while passing — hiding a control somebody is actually permitted is worse
      than the honest 403 they get today
- [x] **Five of them could not be created at all**, by anybody, through any
      client: a ward, a bed, a theatre, a stock location and a provider
      schedule each declared their required foreign key read-only, so the
      insert violated a not-null constraint. A hospital could be operated
      through this system but not set up in it (§218)
- [x] **Products**, at Pharmacy → Catalogue: list, search, view, add and edit,
      with the form hidden from anybody without `catalog.manage` (§222)
- [x] **Wards and beds**, at Wards → Wards & beds: list, view a ward with its
      beds, create a ward, and add beds in a numbered run rather than one at a
      time (§223)
- [x] **Services and prices**, at Money → Services & prices: list, filter by
      category, search, view, add and edit, with the price lists that override
      the default shown beside them (§224)
- [x] **Holidays, shift patterns, leave types and positions**, at Time →
      Setup — written as configuration against a shared `MasterData` screen
      rather than a fourth hand-built copy (§225)
- [x] **Payroll setup** (pay components, salary structures, tax slabs,
      contribution schemes) as a tab on Payroll, and **Configuration**
      (payers, scheme packages, stock locations, theatres, diagnostic tests,
      referral providers) as one screen behind one sidebar entry (§226)
- [x] `MasterData` gained **reference fields**, so a list that belongs to
      something else — a stock location to a facility, a package to a payer —
      offers a chooser rather than asking for a pasted UUID
- [ ] Price *list* editing: the lists are shown beside the services, and the
      per-service overrides inside them are not yet editable
- [x] **Departments** — which had no endpoint at all, not merely no screen.
      `department.read` and `department.manage` were in the catalogue and
      granted to roles all along, with nothing to spend them on (§227)
- [ ] Units, the level below a department. Same shape: nested in the
      department serializer, no endpoint of their own
- [x] A shared `<Can>` / `useCan` / `<RequirePermission>`, so the check reads
      the same everywhere and a screen that forgets it is visible in review.
      `mode="disable"` exists for the cases where a control's absence would
      itself read as a missing feature — because hiding a control from somebody
      who *is* permitted is worse than the honest 403 (§273)
- [ ] The other 38 screens actually using it. The wrapper is not the work; the
      deliberate pass over each screen's actions is

## §133 Visualisation and dashboards `[~]`

*A new section, added 11 September 2026 (log 273). Before it, the word
"dashboard" appeared **once** in 3,300 lines of this file — as the platform
executive dashboard — and "chart" only ever meant a patient's. So a product
whose buyers are hospital directors had no line anywhere saying it should be
able to show them anything.*

**The chart layer**
- [x] `components/charts/*` bound to the tokens, so no screen ever names a
      colour and every chart re-themes without re-rendering
- [x] Eight categorical hues **validated rather than chosen** — worst adjacent
      CVD ΔE 10.1 light / 11.2 dark against a target of 8; normal-vision 21.8 /
      19.2 against a floor of 15. Gold sits at slot 4 because red↔gold measured
      6.0 under deuteranopia
- [x] Assigned in fixed order and never cycled; a ninth series folds into
      "Other" rather than generating a hue no CVD reader can separate
- [x] Scatter, bubble and choropleth capped at three series — every pair is on
      screen at once there, and only the first three clear the gates. Enforced
      in the component rather than documented
- [x] Sequential ramp for magnitude, diverging for polarity, status hues
      reserved and never reused as a series
- [x] Four states per chart: loading, empty, **failed**, data. A failed chart
      that renders an empty axis is a claim that nothing happened
- [x] A table view behind every chart, a hover layer by default, a legend for
      two or more series and none for one, and an as-of time

**The forms**
- [x] Line, area, stacked area, bar, grouped, stacked, horizontal, emphasis
- [x] Diverging bar, combo (one shared scale — **no dual axis anywhere**),
      scatter and bubble
- [x] Donut with the total in the hole, funnel with the drop between stages
      labelled, treemap, stacked progress
- [x] **Heatmap** — arrivals by day and hour, which answers "when to roster"
      and no line chart can
- [x] **Occupancy grid** — the ward drawn as beds. The most-requested view in
      any hospital system and the one this product did not have
- [x] **Gantt** — the theatre day: the gap where a case fits and the list that
      is overrunning, both invisible in a table sorted by start time
- [x] Calendar heatmap for seasonality; waterfall for how a balance moved;
      dumbbell for before-and-after per item; population pyramid for case mix
- [x] **Levey–Jennings** for laboratory QC — §34 has asked for this since the
      beginning. Violations change shape as well as colour
- [x] Sparkline, bullet, meter, stat tile and hero figure
- [ ] Org chart visualisation (§60 lists it twice and it is built neither time)
- [ ] Floor plan by room rather than by bay

**The dashboards**
- [x] `/dashboard` exists at all, and `/` resolves to it by preference, then by
      role, then by permission. All seventeen roles previously landed on
      `/patients`
- [x] Every panel declares its permission, loads and fails on its own, and
      **never renders a zero** when its source failed
- [x] Facility overview: emergency load and acuity mix, inpatients and risk
      mix, counter takings and margin, procurement pipeline, headcount and
      expiring credentials — wired to `/ed/summary/`,
      `/inpatient/nurse-workspace/summary/`, `/pos/summary/`,
      `/procurement/dashboard/` and `/hr/dashboard/`, **all of which already
      existed and were called by no screen**
- [x] **Personas replaced the one-screen-with-gates design** (§274). The
      dashboard above was a single screen whose panels disappeared by
      permission, so a pharmacist and a medical director saw the same product
      minus different pieces — subtraction, not personalisation, and a fair
      reading of "the system itself is confused whom to show what"
- [x] A persona is inferred from **capability, not role code**. Roles are
      customer-editable now, so keying the interface to `nurse` would break
      the moment somebody renamed it. Somebody who can chart observations and
      administer medication *is* working as a nurse
- [x] **Ward**, for a nurse: patients in **deterioration order, not bed
      order** — a ward list sorted by bed number is a filing system, one
      sorted by NEWS2 is a handover
- [x] **Front desk**: the queue by longest wait, coloured past 45 and 90
      minutes. The receptionist's whole job on a busy morning is noticing the
      person who has been there ninety minutes before they come and say so
- [x] **Clinic**, for a doctor: the list, straight into the consultation, with
      the emergency acuity mix beside it
- [x] **Dispensing** and **People**, on the same frame
- [x] Distinct without being five products: the frame, palette, status colours
      and rail stay constant; a persona shifts the hero, the accent (a
      validated series slot, never a new hue) and the composition
- [x] The inference is a default and not a law — overridable, remembered per
      browser, because which board somebody wants this week is closer to a rail
      fold than to a theme
- [ ] Cash position, for a controller: receivables ageing, collections,
      payables due, till status. The leadership board covers takings; the
      ledger view is not built
- [ ] Revenue cycle: claims by status, denial reasons, days in AR
- [ ] Trend lines on the platform executive dashboard (§3) — MRR movement,
      retention, cohorts. The waterfall exists; the data behind it does not
- [ ] Widgets a person can add, remove and reorder, stored beside the other
      preferences

## §134 Roles and permissions, seen `[~]`

*Also new, and the omission it records is the starker one: **§16 tracks the
RBAC engine in forty lines and never once says a customer should be able to
look at it.** The engine is one of this product's real differentiators and it
was invisible in every client.*

- [x] `/access` — roles with holder counts, what each carries grouped by
      module, the scope ladder drawn, and the capabilities the engine has that
      no screen yet exposes, stated rather than hidden
- [x] **The permission matrix** — roles across, permissions down, read and
      write distinguished by mark. The view a procurement security review asks
      for; reading fifteen role definitions one at a time is not a review
- [x] `beyond_your_authority` rendered. `RoleSerializer` has computed it since
      it was written and nothing displayed it: "you cannot grant this" is a
      dead end, "you cannot grant this because it carries `payroll.approve`"
      tells somebody what to ask for
- [x] **`role.read`, not `user.read`.** The first version of the nav entry
      guessed the permission from what the screen *shows* — it lists people,
      so `user.read` — rather than deriving it from the endpoint it *calls*.
      `tests/test_nav.py` caught it on the first run: an operations manager
      holds `user.read`, was shown the link, and got a 403 from
      `/admin/roles/`. That guard was written for exactly this class of
      mistake and it has now made it twice, which is the argument for the
      guard rather than against the author
- [x] **Role create, edit and retire.** `role.manage` — "Create and edit
      roles" — had been in the catalogue and granted to seeded roles from the
      beginning with **nothing to spend it on**; every role in every Nirova
      database came from a seed (§274)
- [x] An unknown permission code **fails closed and names the typo**. A
      `JSONField` stores `patient.raed` happily, it resolves to nothing at
      check time, and the role looks powerful in the editor and does nothing on
      the ward
- [x] Segregation of duties refused on save, and named **as it is ticked** —
      a refusal after two minutes of work is a form people fight.
      `check_segregation_of_duties` had been correct since it was written and
      never once called from an API, because no API ever saved a role
- [x] **A role cannot carry permissions its author does not hold.** Without it
      `role.manage` is a privilege-escalation primitive. Tested as a user
      holding only `role.read`, `role.manage` and `patient.read` — not as the
      owner, who bypasses every check and would pass for the wrong reason
- [x] A system role cannot be retired, and neither can one somebody holds. The
      message says how many, because "revoke it from four people first" is
      actionable and "could not delete" is not. Deactivated, never deleted
- [x] `PATCH` merges before validating rather than `partial=True`, which
      would let `{"name": "x"}` through with `permissions` defaulting to `[]`
      and silently strip the role
- [x] **A permission catalogue endpoint.** `grouped_permissions()` has
      carried the docstring "for rendering the role editor" since the catalogue
      was written and had no route, so the console grouped by parsing the
      code's prefix — which gets `patient.clinical.read` into "Patients" by
      luck and would get a new module wrong. The prefix parser survives as the
      *fallback* for a failed request, because a broken catalogue should
      degrade the grouping rather than empty the screen
- [ ] `PermissionOverride` grants and denials, which are modelled, enforced,
      and have no screen
- [ ] Segregation-of-duty conflicts surfaced at edit time rather than on submit
- [ ] Per-person activity trail. `apps/audit` records every read and no screen
      shows one person's

## §135 Profiles and records `[~]`

*The third thing with no line anywhere. The first draft of this section claimed
there was no profile for anybody; **that was wrong and is corrected here.**
`People.tsx` does contain an employee profile — record, credentials, history and
pay, with practice status — reached by clicking a row in the directory. What it
is not is a **route**: it lives in component state, so it cannot be linked,
bookmarked, opened in a second tab or returned to with the back button, and
nothing outside that one screen can point at a person.*

*The patient half of the claim stands: there is no patient record page at all.*

- [x] An employee profile exists — record, credentials, history, pay, and
      whether they may practise, from `/hr/employees/<code>/` and
      `/practice-status/`. Rich, and reachable from exactly one place
- [x] **A colleague can be linked to.** `?employee=CODE` rather than
      component state, so the profile survives a back button, a bookmark, a
      second tab and a link pasted into a message. A search parameter rather
      than a `/people/:code` route on purpose: the profile needs the
      directory's facility filter and tab around it to return to, and a
      separate route would have to rebuild that context or drop somebody
      somewhere generic on "back"
- [ ] Roles held and at what scope, on that profile. `/admin/staff/<uuid>/`
      returns them and the HR profile does not show them — so "what may this
      person do" and "who is this person" are two screens
- [ ] The same shape for a patient
- [ ] `/patients/:uuid` as a record page with a `Timeline` — the component that
      exists and is used nowhere
- [ ] A shared `RecordPage` shell: header, identity block, tabs, right rail
- [ ] Avatar upload (§59 has "photograph upload and storage" open)
- [ ] Session listing and forced logout (§15), and login history per person

## §136 Getting data out `[~]`

*New on 11 September 2026 (§274). "Reports, excels, pdfs, billings, slips need
to be worked upon" — and the honest position before this was that **every list
in the product was a dead end**. A ward sister who needed the bed state for a
handover, an accountant reconciling against a bank statement, an auditor asked
for last quarter's dispensing: all had one option, which was to read the screen
and retype it. A system you cannot get data out of is one people keep a
spreadsheet beside, until the spreadsheet becomes the record.*

- [x] **CSV and Excel from any list**, attached to `DataView` so a screen gains
      it by adopting the component rather than by growing its own button.
      Exports the **sorted, filtered** rows, not the whole set — an export that
      silently returns everything while the screen shows a subset is the sort of
      file somebody reconciles a bank statement against and cannot work out why
      the totals differ
- [x] **CSV injection closed.** A cell beginning `=`, `+`, `-` or `@` is
      executed as a formula by Excel and Sheets, so a patient whose name was
      entered as `=cmd|…` becomes remote code execution on the machine of
      whoever opens the export. One apostrophe, stripped again on display
- [x] **A byte-order mark on the Excel export.** Without it Excel reads the file
      as the system codepage and every Devanagari name, every accented character
      and the rupee sign arrive as mojibake — and users conclude the *system*
      stored the name wrong
- [x] Only columns with a `value` accessor are exported. A cell that renders an
      avatar and a badge has no sensible CSV form, and stringifying the React
      element puts "[object Object]" in a file somebody sends to an insurer
- [x] **A print stylesheet**, which the product had none of — so every
      prescription, invoice and payslip came out as a screenshot of the
      application, navigation rail included, on a dark background
- [x] Printing forces the light palette, keeps background fills — Chrome drops
      them, which turns every status chip into invisible text — avoids splitting
      a table row across a page break, and repeats table headers
- [x] `printElement` prints **one element**, by stamping the document rather
      than by opening a new window and re-styling it. The printed layout is the
      same layout because it is the same element
- [x] **No PDF library.** jsPDF and friends are 300–800 kB, cannot lay out a
      table without being told every coordinate, and produce documents that look
      nothing like the screen. The browser already has a typesetting engine that
      writes PDF, so Print opens it and the operator chooses "Save as PDF" —
      which is what every hospital system that prints anything actually does
- [x] `PrintableDocument`: the frame every slip shares — issuer, reference,
      identity block, signature lines, and **who printed it and when**. A
      document with no provenance cannot be verified or challenged later, and in
      a dispute that is the only question anybody asks
- [x] The Nepali tax invoice on that frame — PAN, fiscal year beside the
      number, per-line discount and VAT, payments, balance, credit-note label,
      a draft warning — and it never computes a total the server did not (log 275)
- [x] **The laboratory report**, printable **only once verified** — a report
      printed between entry and verification is the document verification
      exists to stop. Names who entered and who released; abnormal values
      flagged H / L / CRITICAL in words, because monochrome printers drop
      colour; critical values state who was told and how (log 275)
- [x] **The prescription**, printed for the patient straight from signing —
      in Nepal it is very often filled at an outside pharmacy, and signing had
      ended with a notice on the doctor's screen and nothing in the patient's
      hand. NMC registration, generic first, quantity to supply, substitution
      per line, validity, and any overridden warning with its reason (log 276)
- [x] **The counter receipt** at the roll's width, printed alone — it had
      printed the whole screen. Seller's PAN and licence, batch and expiry per
      line (how a recall reaches a customer), every tender with its wallet
      reference, change, and the return terms (log 276)
- [x] **The discharge summary**, after discharge only: diagnosis on admission
      and final, the course and the wards it passed through, investigations
      released during the stay, medicines to continue, advice, follow-up and
      signatures. Sections the printer may not see say so rather than vanish
      (log 276)
- [ ] Scheduled and emailed reports
- [ ] A real `.xlsx` with formatting and several sheets, for the finance
      exports where a flat CSV genuinely is not enough

## §137 A demonstration that is alive `[x]`

*New on 11 September 2026 (log 275). Every dashboard read zero, and it was not
the dashboards: the narrative seeds each told one story once, on the day they
ran. A buyer shown "0 in department · NPR 0" concludes the product is empty.*

- [x] **`seed_demo_population`** — a register of 160 people (children, the
      elderly, stated ages, no phone), a 29-line formulary in batches through
      the stock ledger (low stock, near expiry, cold chain, 13%-VAT lines), and
      a fifty-bed inpatient estate in gendered bays with some beds out of
      service for a stated reason. Topped up to a floor, never added to
- [x] **`seed_demo_day`** — today, at the facilities where each thing happens:
      emergency arrivals through the night and day, the outpatient queue, the
      pharmacy counter, the wards (admissions, discharges through all five
      clearances, housekeeping, a nursing round every four hours), and the
      laboratory (orders through collection, receipt, results, verification)
- [x] **It tops the day up rather than generating it.** Each run adds the
      shortfall for a day this far along and moves every open case along its
      own clock; twice in a row adds nothing. Every patient's story is seeded
      from their own reference, so nine o'clock and eleven o'clock agree
- [x] **Through the service layer only**, and it will not invent what the
      product guards against: no "admitted" disposition without an admission,
      nothing prescription-only across the counter
- [x] **Kept current by Celery beat**, half-hourly — the project's first task —
      and only when `NIROVA_DEMO_DAY_SLUG` is set, which only the demonstration
      stack sets
- [x] Both run in the seed order, and therefore twice in `test_seeds.py` — which
      on its first run found a real defect: a return from a VAT-rated sale was
      refused, because the credit note carried the shelf price without its VAT
- [x] The demo nurse and doctor also hold roles at the hospital, through
      `assign_role` — they had been rostered at the clinic alone, nowhere near
      the wards and emergency department that are their day

## §138 Signing in, signing up, and getting a first password `[~]`

*New on 11 September 2026 (log 275). "The login and signup pages are still not
satisfactory" — and there was no signup at all.*

- [x] Sign-in answers every question asked on it: forgotten password (answered
      honestly — the administrator issues one), "is it me or is it down?" (live
      service status), "how do we start?" (register your hospital), "who sees
      what I open?" (every access logged)
- [x] The right-hand panel is the product at a legible size — the bed board, a
      deteriorating patient, today's figures — using the real NEWS2 component,
      and labelled illustrative
- [x] **Registration** at `/signup`: three steps, organization type as cards,
      suggested modules per type, and a page that says what happens next.
      `POST /api/auth/register/` records a request and **never provisions** —
      a database per anonymous form is a database per bot
- [x] Rate-limited by address and by email, with a honeypot that tells a bot
      it succeeded and stores nothing
- [x] The platform team's queue under Platform → Registrations: contacted,
      declined with a reason, or **onboarded** — the request's own answers
      handed to `onboard_organization`, nobody retyping a hospital's name
- [x] **An administrator can issue a temporary password.** Until now an
      invited or onboarded person had an unusable password and no route to a
      usable one — an organization could be onboarded and its owner could
      never sign in. Behind `user.deactivate`; refused for yourself, for
      platform staff, and for anybody who also belongs to another
      organization, whose account this organization must not hold the keys to
- [x] The temporary password is never written to the audit trail, and nothing
      opens until the holder replaces it with one only they know
- [x] **The API refuses everything but the way out** while
      `must_change_password` is set — reading who you are, changing the
      password, signing out. In the authenticator, because nearly every view
      names its own permission classes and a default permission would have
      reached almost nothing. Measured before: the patient list answered 200
      (log 276)
- [ ] Self-service password reset by email, for organizations that turn it on
- [x] **Two-step sign-in** (log 277): standard TOTP tested against the RFC's
      vectors, the secret encrypted at rest, codes single-use, ten hashed
      recovery codes, a signed five-minute challenge between the steps, wrong
      codes counted toward the same lockout, turning it off needs the password
      and a code, and an administrator's audited reset for a lost phone
- [x] **An organization-wide rule making it mandatory** (`security.require_mfa`,
      log 278), enforced in the API — unenrolled members reach only enrolment —
      refused to an administrator who has not enrolled, and shown in the
      console as a setup screen rather than a wall of refusals

## §139 The ward, rebuilt `[x]`

*New on 11 September 2026 (log 275). "I don't even like the nurse workspace and
the ward, so AI-generated looking."*

- [x] `GET /api/ipd/board/` — the whole facility's bed board in one request,
      with age, sex, night of stay, due-home, consultant, diagnosis and NEWS2
- [x] **The access tiers hold on it**: diagnosis and NEWS2 only for
      `patient.clinical.read`, and only for patients with a care relationship
      where the organization requires one; a withheld value says it was
      withheld. Tested, and the test proved by removing the gate
- [x] The board: a strip of figures that are also filters, occupancy bars that
      separate full from broken, tiles that answer "who do I see first" and
      "whose bed frees up today", free beds that say what they can take,
      out-of-service beds hatched with their reason
- [x] The nurse's patient card, rebuilt: no monospace, no bracketed capitals,
      no gradients or pulsing; NEWS2 with the response it obliges, the scoring
      observation coloured in place, and **when the next observations are
      due** from the RCP minimum frequency — the question a nurse carrying six
      patients asks most, which was not on the screen
- [x] Every age on the nurse workspace had read "Adult" — the server called a
      method that did not exist, including for the children on the paediatric
      ward
- [x] "My patients" with nothing assigned falls back to the whole ward **and
      says so**, instead of labelling forty-one patients "assigned to you"
- [x] Opening a till: facilities offered only where a till can sell, the tills
      already open shown, a free till name suggested, the drawer counted by
      note. The dropdown had been empty because the first facility was the
      clinic, which has no dispensary

## §140 The patient's own app `[~]`

*New on 12 September 2026 (log 276). "The patients portal needs to be
distinct" — and, probed before redesigning, it had been showing patients blank
results.*

- [x] Released results reach the patient **with their values and ranges** —
      the portal read fields the result model does not have, so every value
      was blank and the downloadable copy printed "Normal" for every range
- [x] Amended results shown once, as corrected; the clinician-first hold
      counts current rows only
- [x] A portal token with no hospital is asked to sign in again, not a 500
- [x] A home that opens on the person: health card, what is next, what is
      waiting, current medicines, an emergency button that dials
- [x] Its own palette and forms, measured for contrast; a tab bar on phones
- [x] Medicines in plain words ("three times daily"), never the chart's Latin
- [x] Written reports as paragraphs; flags as Low / High in a warm tone
- [x] **Booking a visit from the portal** (log 277): a fortnight of days, each
      doctor's slots and fee, one confirmation that states the fee; only slots
      really on offer online (the walk-in reserve untouchable), at most three
      online bookings per account, cancellation with two hours' notice
- [x] A cancelled visit no longer shows as upcoming; a proxy's actions reach the
      record they chose, not their own
- [x] **Nepali, with Bikram Sambat dates** (log 279): sign-in, home, tabs,
      booking, appointments, results and medicines in Nepali; dates in BS from
      a maintained library checked against known new-year dates, never a
      hand-typed table; medicines phrased from structured fields ("दिनको तीन
      पटक"); counts in Devanagari, hospital numbers and money left 0–9
- [ ] Nepali on the remaining screens — bills, referrals, messages, sessions,
      profile corrections, the access log
- [ ] Bikram Sambat dates in the staff console (the login page now claims only
      what is true: BS fiscal years and payroll months)
- [x] **Paying a bill in the app** (log 280): eSewa and Khalti, with the
      confirmation asked of the provider server to server rather than read off
      the redirect back

## §141 Stock traced, sales read, bills paid, passwords recovered `[~]`

*New on 12 September 2026 (log 280). "Work on stock tracing, excels, sales,
self service etc… we will go with Khalti and eSewa", and: the words, the
headings and the navigation were not up to an international standard.*

### Tracing a batch
- [x] A batch traced from the supplier's receipt to every person who received
      it — **dispensed patients and counter customers**, net of returns and
      voids. The recall list counted dispensing only, so a recalled batch sold
      over the counter reached people the recall could not see
- [x] The trace reconciles: received = to people + returned + written off +
      held, with any discrepancy stated rather than smoothed over
- [x] Names and phone numbers only for somebody who may read patients; the
      same flow otherwise, with a sentence saying what is withheld
- [x] `recall_exposure` is built from the trace, so the two cannot disagree
- [x] A printable recall list, and a four-sheet workbook

### Sales over a period
- [x] A one-day report equals the till's own daily summary to the paisa —
      asserted by a test, because two numbers for one day means neither is
      trusted
- [x] Revenue, margin, returns and average sale against the previous period of
      the same length; by day, by hour, by product, by tender, by cashier
- [x] **Both `sale.read` and `report.read`** — every doctor holds the latter
      for laboratory turnaround, and costs and margins are not theirs
- [x] "All facilities" means all of *yours*: the filter is intersected with
      what the caller's grants reach
- [ ] A dunning reminder for invoices that fall overdue

### Excel that arrives usable
- [x] Real `.xlsx`, not a CSV with a byte-order mark: title and period, who
      generated it and when, a bold frozen header, numbers as numbers in the
      formats an accountant expects, columns sized to content, a totals row,
      and one sheet per part of the report
- [x] The writer is loaded only when somebody exports

### eSewa and Khalti
- [x] **Nothing that arrives through the payer's browser is trusted.** An
      attempt is settled only by a server-to-server check against the
      identifiers we stored, and only a confirmed "completed" for the exact
      amount becomes a `Payment`
- [x] The eSewa signature verified against eSewa's own sandbox before it was
      trusted — accepted signed, refused tampered (`ES104`)
- [x] Confirming twice records one receipt; the attempt is locked while it is
      confirmed
- [x] A payer who closes the tab is reconciled by a scheduled task; an
      attempt unfinished after two hours is given up
- [x] Money taken for a bill settled meanwhile is **flagged for refund**, in
      red on the billing screen — never silently dropped
- [x] Merchant keys sealed at rest, never returned to a browser, never written
      to the audit log; test mode uses eSewa's public sandbox merchant so the
      demonstration needs no configuration
- [x] No patient name or phone is sent to either wallet
- [ ] IME Pay and Fonepay

### Getting back in
- [x] **A reset link by email**, following the OWASP guidance: one answer for
      registered and unknown addresses, sent off the request path so the
      timing does not tell either; a signed single-use token a password change
      spends; thirty minutes; silent rate limits; a confirmation email to the
      owner; the second factor still required afterwards
- [x] **A password change ends every session that predates it** — it used to
      document the opposite, so somebody changing a stolen password changed
      nothing for the thief. The device that made the change keeps working on
      fresh tokens
- [x] The console renews its access token silently, once, single-flight —
      until now nothing renewed it and every screen began failing half an hour
      into a shift
- [x] Mail goes to a Mailpit container in the Docker stack; a demonstration
      never emails a real person

### The words, and where things live
- [x] No sidebar label longer than two words, with the old wording kept as
      search keywords
- [x] Notifications are an icon in the navbar — a count, a popover of the
      latest, mark all read, and "View all" for the full page
- [x] "What needs you" is **My workspace**, in the rail and on the page
- [x] Page descriptions say what the screen is for in one line
- [ ] The same pass over badges, buttons and empty states

## Standing guards

*Not a specification section. The general checks that have each caught something
nothing else would have, kept here so they are not quietly dropped.*

- [x] **A test run is only a pass if pytest says it finished** — every run
      writes a record at start that says incomplete and overwrites it only at
      its own finish; `scripts/run_tests.py` reports a killed run as
      INCOMPLETE, never as green, and refuses to start a second run over a
      live one (log 278)
- [x] Every seed runs twice — six seeds only ever worked once
- [x] Every registered report runs — four named functions that did not exist
- [x] Every search source formats a real row — `scheduled_start` does not exist
- [x] Every GET route returns no 5xx, as two roles, detail routes called with
      real identifiers — and the guard itself proved by reintroducing the
      defect that prompted it, because a guard that has never been shown to
      fail is not a guard
- [x] Every clinical search hit belongs to a patient the searcher relates to
- [x] Every model field is assigned by some line of code, or is listed above
      as a known gap — twice a column was declared and never written, and
      both were found by accident before this existed
- [x] Master data refuses writes from roles that may only read it — and the
      test asserts how many pairs it actually exercised, because the first
      version skipped every pair and passed having checked nothing
- [x] Every console route has a way in, and every menu item has a route —
      `/privacy` and `/notifications` were both routed and unreachable
- [x] Every workspace source formats a real row, and a broken one is named
- [x] No create endpoint crashes on a malformed body — all 77 answer an empty
      POST with a 400, run as the owner so the serializer is actually reached
- [x] The guard's own savepoint is on the **tenant** connection, not the
      control plane. Proving it caught that: with the savepoint on the wrong
      database it reported four crashed routes where there was one (§217)
- [ ] The same sweep for POST and PATCH. Harder: a write needs a valid body,
      and a sweep that posts nonsense tests the serializer rather than the view
- [x] **The console's colour comes from the token system.** A ratchet, not a
      pass/fail on zero: 325 raw Tailwind utilities may fall and may not rise.
      It also fails when the count drops far *below* budget, because a budget
      well above the real number is headroom rather than a guard (§273)
- [x] **The token layer is wired**, primitive → semantic → component, all three
      before `@tailwind base`. Cheap check, expensive failure: if `index.css`
      stops importing the primitives every semantic token resolves to nothing
      and the console renders in browser defaults — obvious in a browser and
      invisible in a diff
- [x] **No component names a primitive token directly.** One that does pins
      itself to a value and will not follow a customer's re-theme

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

> **Provider schedules could be defined by nobody until log 272.** The write
> gate named `facility.manage`, which is not a permission — the catalogue has
> `facility.read`, `facility.request_change` and `facility.approve_change`.
> Now `department.manage`, held by the organization administrator and the
> facility manager: defining a consultant's weekly clinic is service
> administration, deliberately narrower than `visit.schedule`, because a
> receptionist books *into* a clinic template rather than redrawing it.

*The diary screen was built after this section was written. Every item below was
ticked and **none of it was reachable** — there was no appointment screen at all,
so a receptionist could not book. Worse, they could not have: booking required
`encounter.create`, which the `receptionist` role does not hold, and the demo
tenant had no receptionist to notice with. `visit.schedule` is the permission it
should always have had (log 261).*

- [x] **The diary itself**, at `/appointments`: a day's sessions with their
      remaining room, booking into a free slot, cancelling with a reason and
      recording a no-show
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
- [x] **`visit.schedule`**, a permission for the front-desk act rather than a
      borrowed clinical one. Held by the receptionist, doctor, nurse and
      facility manager. Granting `encounter.create` instead was not an option:
      a permission's scope comes from the assignment, so a facility-scoped
      receptionist would also have been able to run emergency triage and record
      a blood transfusion, both of which check that code at facility scope
- [x] A demo receptionist. The busiest role in a clinic had no demo user —
      `counter@` is the pharmacy till — so nothing exercised registration,
      booking or queue tokens as the person who does them
- [ ] Rescheduling flow (field exists)
- [ ] Recurring appointments
- [ ] Waitlist
- [ ] Online and patient-portal booking
- [ ] Room assignment
- [ ] Appointment reminders

## §21 Queue management `[x]`

> **Anybody who could see the queue could move it, until log 272.** `call-next`,
> `recall`, `start` and `complete` inherited the viewset's `encounter.read`,
> so a lab technician could complete somebody's consultation and so could a
> read-only auditor. Moving the queue now takes `visit.schedule` — the same
> authority issuing a token already asserted.

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

## §24 Referral management 🔷

> **The provider directory could be edited by the front desk until log 272.**
> `perform_create` asserted `department.manage`, but a `ModelViewSet` answers
> PUT, PATCH and DELETE as well and neither `perform_update` nor
> `perform_destroy` was overridden — so *adding* a provider took a manager and
> *changing the address a referral is sent to* took `encounter.read`. The
> authority is now declared on the class, which covers verbs added later.

**Shapes**
- [x] Internal, outbound and inbound as three genuinely different workflows
      rather than one with optional fields
- [x] Doctor → doctor, clinic → hospital, hospital → specialist
- [x] Internal department referral, with the destination department named
- [x] A directory of external providers, so "how many did we send there, and
      how many came back with an answer" is a question with an answer
- [x] A provider records how it can actually be reached; a referral marked
      emailed to somebody with no email never left the building
- [ ] Referral networks and agreed pathways between organizations

**Raising one**
- [x] Referrer, destination, reason and urgency
- [x] A *question* separate from the reason — a referral that asks nothing
      gets an answer that says nothing
- [x] Sending is refused without one
- [x] A second open referral for the same patient and specialty is refused
- [x] An outbound referral with no destination is refused
- [x] Urgency carries a target date, held as data
- [ ] Referral templates per specialty with required investigations

**The letter**
- [x] Assembled from the record — allergies, conditions, medications — rather
      than typed
- [x] Frozen at the moment of sending; a letter regenerated later from live
      data is a different letter with the same date
- [x] A draft shows a preview, clearly labelled as not yet a record
- [ ] PDF rendering and print layout
- [ ] Attaching results and images

**Status tracking**
- [x] Sent, acknowledged, accepted, booked, seen and answered as separate
      states — each pair is a place where referrals silently stop
- [x] Declined, with a reason from a countable list
- [x] Did not attend as an outcome rather than an absence
- [x] Lapsed: written by a sweep, so referrals that quietly stopped mattering
      are a number rather than an impression
- [x] Every state change appends an event; the history is the referral
- [x] A referral cannot be seen before it was sent, or answered before it was
      seen — both enforced by constraint, because either reversal makes the
      waiting-time statistics negative
- [ ] Appointment-module linkage on booking

**The feedback loop**
- [x] A response is its own record with its own author and date
- [x] More than one is possible — an interim opinion, then a definitive one
- [x] The answer is kept apart from the findings, and checked against the
      question
- [x] Care handed back or kept, stated explicitly rather than left to be
      inferred
- [x] Advice to the referrer, which is the half that makes a reply actionable
- [x] "Seen but the referrer has been told nothing" as its own report
- [ ] Notifying the referrer when an answer arrives

**Analytics**
- [x] Worklist ordered by breach then target, not by arrival
- [x] Breach rate, decline reasons, median days to be seen and to answer
- [x] Answered percentage and the unanswered count
- [x] Per specialty
- [x] A patient's referral history, leading with what came back
- [ ] Per-referrer and per-provider league tables

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

> **Collection, result entry and verification took only `encounter.read` until
> log 272** — the permission the front desk holds for the appointment diary.
> Now `diagnostic.process` (collect, receive, reject, enter) and
> `diagnostic.verify` (release to the chart, notify a critical value), kept
> apart because that is the maker-checker pair a laboratory is built around.
> The service layer already refused the *individual* who entered the values;
> it said nothing about whether the second individual is qualified to release
> anything.

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

## §36 Blood bank 🔷

> **Every tick below was true of the domain logic and false of the product,
> until log 272.** Every write in this module called
> `require("pharmacy.dispense")` — a permission code that has never existed.
> `require()` does not validate that a code is real, so the guard refused
> *everybody, forever*: donor registration, collection, grouping, screening,
> separation, release, issue and discard were all unreachable from outside.
> The module's own tests passed throughout, because they run as the
> organization owner, who is exempt from every permission check.
>
> Writing now takes `blood.process` (the bank's own work, up to release) or
> `blood.issue` (the ward's use of what was released), split so the technician
> who screened a unit is not the person who hangs it.

**Donors**
- [x] A donor is not a patient — different record, different consent,
      different privacy, and not in the patient index
- [x] A phone number is required: a donor who cannot be reached cannot be told
      about a reactive result
- [x] Voluntary, replacement, directed and autologous kept distinct
- [x] Eligibility answered as sentences, not a boolean — a permanent deferral
      and "you gave five weeks ago" are different conversations
- [x] The donation interval enforced from the last donation, ninety days for
      men and a hundred and twenty for women
- [x] Deferral with a reason and an end date; permanent deferral has neither
- [x] Donation count as a cache over the donations, rebuilt not incremented
- [x] Call list by group, ordered by when each becomes eligible
- [ ] Donor cards, appointment reminders and campaign tracking

**Collection**
- [x] Haemoglobin below 12.5 g/dL refuses the donation — it harms the donor
- [x] Weight below 45 kg refuses a 450 ml collection
- [x] Mobile drives flagged, because that is where labelling errors
      concentrate
- [x] Adverse events during collection recorded, because they decide whether
      the donor is called again
- [ ] Bag lot tracking and collection-set traceability

**Grouping**
- [x] Two determinations by two different people before anything is labelled
- [x] The same person cannot provide the second, enforced by constraint
- [x] Forward and reverse results stored separately
- [x] Weak D recorded, because a weak-D donor is positive and a weak-D
      recipient is negative
- [x] A disagreement stops the donation; it is a finding, not a vote
- [ ] Automated analyser interface

**Screening**
- [x] Results per infection, not one pass/fail
- [x] Untested is not negative, and is reported separately from reactive
- [x] Verification by a second person, who cannot be the one who ran it
- [x] The panel is data — adding malaria screening is a row, not a column
- [x] A reactive result on HIV, hepatitis B or C discards the donation *and*
      defers the donor permanently, in one step
- [ ] NAT testing and confirmatory-result workflow

**Components**
- [x] A donation and a component are different objects
- [x] Shelf life and storage range per component, copied onto the unit so it
      records the rule that applied when it was made
- [x] Platelets five days, red cells thirty-five, plasma a year
- [x] Units are created quarantined and released only through one gate
- [x] Release refuses on any blocker and lists them all at once
- [ ] Irradiation, leucodepletion and washed-cell products

**Inventory**
- [x] Stock by group and component, not one total
- [x] Expiring within seven days surfaced per cell
- [x] Expiry sweep selects on the date, so running it twice is a no-operation
- [x] Wastage by reason: expiry is a stock problem, a broken cold chain is a
      process problem, and a reactive screen is the system working
- [ ] Fridge temperature logging and alarm integration
- [ ] Inter-facility transfer of units

**Requests, reservation and cross-matching**
- [x] A request states the indication, because over-transfusion is the
      commonest quality finding and is invisible without one
- [x] Reservation and cross-match are different states
- [x] A cross-match is between one unit and one patient, and expires after 72
      hours
- [x] Separate compatibility tables for red cells and plasma — they run in
      opposite directions
- [x] An ABO-incompatible pairing is refused outright, not filed as a result
- [x] Compatible units listed oldest-first
- [ ] Antibody-identification panels and phenotype matching
- [ ] Platelet-specific compatibility (currently uses the red-cell table)

**Issue**
- [x] `issue_unit` has no override parameter and no endpoint flag
- [x] Blockers listed before the button, not after the click
- [x] The emergency path is a separate function and a separate endpoint,
      demanding a named authoriser and a reason
- [x] Emergency issue still refuses an expired unit and a non-universal group
- [x] Return only within the thirty-minute cold-chain window; beyond it the
      unit is discarded and that discard survives the refusal
- [ ] Blood-fridge issue via a card reader

**Transfusion**
- [x] Bedside check by two named people, and the database refuses the two
      names being the same
- [x] Observations appended to the transfusion chart, never edited
- [x] Outcome distinguishes completed from stopped, with the volume actually
      given
- [x] The unit-to-patient link is permanent, which is what makes a look-back
      possible
- [ ] Timed observation prompts during the transfusion

**Reactions**
- [x] A fixed list of reportable categories, served by the API
- [x] Severity from mild to fatal
- [x] Minutes into the transfusion — the most diagnostic fact on the form
- [x] The investigation recorded: repeat grouping, repeat cross-match,
      culture, unit returned
- [x] Clerical errors counted separately, because they are the preventable
      category
- [x] Haemovigilance return with rate, type, severity and what has not been
      reported to the authority
- [ ] Direct submission to the national haemovigilance system

**Traceability**
- [x] Look-back from a donor to every recipient, with phone numbers
- [x] Trace from a patient back to every donor
- [ ] Barcode and ISBT 128 labelling

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

> **Finding, 5 September 2026, now addressed.** Creating an employee and
> creating their login were two separate acts and nothing insisted on the
> second. Measured in the demo tenant: five active employees, two linked to a
> login. Everything built on `Employee.user_id` — self-service (§95), every
> employee-addressed notification, `Scope.OWN` filtering — was inert for the
> rest. The features were not wrong; they reached nobody, and nothing said so.

- [x] `give_login()` creates or attaches the account, adds the membership and
      the base `staff` role, and refuses a second login for the same person
- [x] No password is set: the account is unusable until one is set through the
      ordinary route, because generating one here means delivering it somehow
      and every way of delivering it is worse
- [x] An existing account for that email is reused, never duplicated — people
      are rehired and move between facilities in one group
- [x] Gated on `employee.hire`, not `employee.manage`. Creating an account that
      can reach a medical record is closer to hiring than to correcting a phone
      number
- [x] `GET /api/hr/logins/` counts it: active staff, how many can sign in, who
      cannot. An absence that can be counted gets chased
- [ ] Offered at the point of hiring, rather than only afterwards
- [ ] Invitation email, so the account can be used without an administrator
      setting the password

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

> **Nursing writes took only `patient.clinical.read` until log 272** — allocating
> a nurse to a bed, writing an SBAR handover and closing a bedside task were
> open to everybody who can *read* clinical data, which includes the medical
> director and the read-only auditor. All three now take `encounter.create`,
> the permission that already means "record clinical data" and that the doctor
> and the nurse hold. A ward round recorded through `AdmissionViewSet.rounds`
> had the same hole for a subtler reason: the action answers GET *and* POST
> through one handler, so reading the rounds and charting one shared a guard.
>
> The demo tenant had no `nurse@` account until log 272, so every probe of
> these four screens had run as a doctor or the owner.

- [x] Ward census
- [x] Nurse assignment
- [x] Nursing rounds
- [x] Vitals capture (reuses §22) 🔷
- [ ] Care plans
- [ ] Nursing notes
- [ ] Intake and output
- [x] Medication administration record
- [x] Administration schedule and verification
- [ ] Patient observations
- [ ] Risk assessment: falls, pressure ulcers
- [x] Nursing tasks
- [x] Shift handover
- [x] Escalation to a doctor

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

> **The unit summary was reachable by nobody until log 272.** It asked for
> `report.view`; the catalogue's code is `report.read`. A one-word slip that
> no test could see, because a permission code is a string and nothing checked
> it against the catalogue. Charting itself was correctly guarded throughout —
> `encounter.create`, asserted in a `_writable()` helper.

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

**Visibility between facilities of one tenant** — *decided 5 September 2026.
The design and its reasoning are in [ACCESS_DESIGN.md](ACCESS_DESIGN.md);
the short version is that facility is the wrong unit of access control, and
the model is relationship-based with an emergency override. Probed 4
September; findings measured, not assumed.*
- [x] The patient record is deliberately organization-wide. `Patient` has no
      facility restriction and `registered_at_facility` is documented as
      provenance, not a restriction — the alternative is one person holding
      four MRNs and four allergy lists inside one hospital group
- [x] Clinical detail is already out of reach of a counter: encounters,
      diagnostic orders and the ward census all refuse without
      `encounter.read`
**Phase 1 — the tiers and the safety net** — *shipped; full record in
[PHASE1.md](PHASE1.md)*
- [x] `patient.read` split into three: identity (`patient.read`), safety
      (`patient.safety.read`), clinical (`patient.clinical.read`). Granted to
      every role holding `encounter.read` today, so this step changes no
      behaviour — the vocabulary comes before the enforcement
- [x] **Dispensing runs the allergy, interaction and duplicate checks the
      prescriber has always faced.** It had none. The demo data itself
      contained a seed handing amoxicillin to a patient with a severe
      penicillin allergy, on every run, since it was written
- [x] It refuses rather than forbids: a typed reason overrides, because a
      control that cannot be overridden gets worked around outside the system
- [x] `pharmacist` and `pharmacy_counter` hold `patient.safety.read`, which is
      what makes restricting the rest safe
- [x] `assign_role` refuses a narrow scope naming no facility or department
- [x] Facility-filter the **business** lists — invoices, sales, dispensings,
      till sessions. No clinical safety argument applies to these, and
      organization-scoped roles keep the whole view
- [x] Prescriptions deliberately **not** filtered this way, with a test
      asserting it, so nobody tidies it later. A prescription may be presented
      at any pharmacy; Phase 2 narrows it by relationship instead
- [x] Prescription and invoice reads logged through `record_patient_access`

**Phase 2 — relationship and break-glass** — *build plan in
[PHASE2_PLAN.md](PHASE2_PLAN.md)*
- [x] `has_care_relationship(user, patient)` computed from admissions,
      appointments, orders and prescriptions — and returning *why*, since a
      boolean cannot be written onto an access log
- [x] `patient.clinical.read` enforced against it on encounters, behind
      `privacy.require_care_relationship`, off by default
- [x] The refusal names the way out rather than returning a bare 403
- [x] `BreakGlassGrant`: immediate, four hours, a sentence not a category,
      ends by time, cannot be self-reviewed, revocable by a reviewer
- [x] `privacy.review` queue, screen at `/privacy`, `CRITICAL` notification on
      every override, and no bulk sign-off anywhere
- [x] Switchable per organization through the configuration hierarchy
- [x] Enforcement extended to diagnostic orders, patient results, ICU stays
      and admissions
- [x] `PatientResultsView` calls `check_object_permissions` explicitly — a
      plain `APIView` never calls `get_object()`, so the class was listed and
      never ran
- [ ] The check on admissions cannot refuse anybody: for inpatients, facility
      scope *is* the relationship. Harmless and honest to leave, and it starts
      mattering the day `_admission` narrows to a ward or a team
- [x] Lists narrow to the relationship; **lookup by reference stays open** to
      the dispensing role — the patient handing over the reference is the care
      relationship and is the consent. Measured: a counter assistant
      enumerates 0 prescriptions and still opens the one presented
- [x] A *presented at this facility* relationship source. `Prescription.facility`
      is where it was **written**, so this is an event — `PrescriptionPresentation`,
      written when a dispenser opens one by reference, closed on dispensing,
      and bounded to the branch it was presented at
- [x] `GET /api/clinical/prescriptions/awaiting/` — what is waiting to be
      dispensed at this counter, the question that had no answer

**Phase 3 — making it visible**
- [x] "Who looked at my record" at `/api/me/?section=access`, unaggregated and
      naming staff. A proxy cannot see it
- [x] Reads with no care relationship, hedged in its own text because the
      relationship is recomputed now — a report that overstates its case is
      dismissed wholesale after the first false positive
- [x] Read volume against the median for the *same role*, with a floor so that
      five reads against a median of one is not an "outlier"
- [x] `actor_role` is recorded, which it never was — the report compared
      everybody to everybody until 6 September 2026
- [x] The access-pattern reports on the `/privacy` screen, showing the
      server's hedge above each list and offering no way to clear either —
      they are prompts to go and ask somebody, not a queue to be emptied
- [x] "Who saw my record" in the patient application, staff named, with the
      explanation above the list rather than under it
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

## §94 Patient portal 🔷

**Identity**
- [x] A patient account is its own table with its own credential, not a flag
      on a staff user — the separation is structural rather than conditional
- [x] Its own authentication scheme (`Authorization: Portal <token>`) and its
      own tenant binding, because a patient has no membership
- [x] `request.user` on a portal request is a principal that answers
      `is_authenticated` and nothing else, so code that treats a patient as
      staff raises rather than granting
- [x] Registration only against an invitation issued by somebody at the desk
- [x] Identified by the number on the patient's card plus that code, and
      neither alone is enough
- [x] Five wrong codes kills the invitation; the counter survives the
      refusal that raises it
- [x] The code is checked before the identifier collision, so a stranger
      cannot learn which phone numbers have accounts
- [x] The invitation code is returned once and stored hashed
- [x] Any earlier unused invitation is revoked, so nobody holds two live codes
- [x] How the code was delivered, and to what, is recorded
- [x] Authentication answers identically whether or not the account exists
- [x] Lockout after repeated failures, expiring on its own
- [ ] Password reset by SMS one-time code
- [ ] Two-factor authentication

**Sessions**
- [x] Sessions are rows, so signing out actually invalidates
- [x] A patient can see where they are signed in and end one
- [x] Sign out everywhere
- [ ] Device fingerprinting and unfamiliar-device notification

**What may be seen**
- [x] Only results the laboratory has released
- [x] Critical results held for a day, abnormal ones briefly, so a clinician
      can ring first
- [x] Held is announced, not hidden: the patient is told a result is ready
      and that somebody will be in touch
- [x] The hold expires — an indefinite one is a result they never learn about
- [x] Appointments, prescriptions, referrals and issued invoices
- [x] Draft invoices are never shown
- [x] Which record is being read comes from the session and the live grants,
      never from the request
- [ ] Documents, images and discharge summaries
- [ ] Online payment from the portal
- [ ] Queue position in real time
- [ ] Telemedicine

**What the patient may change or take away**
- [x] Correcting their own details: address, telephone, next of kin —
      proposing a correction for desk staff verification, preventing
      uncontrolled writes to canonical MRNs while providing a clear patient route
- [x] Taking a copy: a result as a document, a printable invoice receipt, or
      an outpatient prescription formatted with facility branding and print styles
- [ ] Uploading anything — an outside report, a photograph, a scanned
      insurance card
- [ ] Booking, rescheduling or cancelling an appointment themselves

**The patient's application**
- [x] A separate build (`patient/`), not a section of the staff console —
      its own bundle, its own origin, its own auth store
- [x] 63 kB gzipped, because it is downloaded over a phone connection
- [x] The token lives in `sessionStorage`, which dies with the tab —
      the behaviour somebody in an internet café wants and would not
      think to ask for
- [x] Sign in, register with card number and code, home, results,
      appointments, bills, medicines, referrals, messages, sessions
- [x] A held result is shown as a card saying a doctor will call, never
      omitted
- [x] Reading somebody else's record is stated at the top of the screen
- [x] "Not for urgent problems" beside the message box, not in terms of use
- [~] Nepali translation — the main paths and Bikram Sambat dates are done
      (§140, log 279); bills, referrals, messages, sessions, profile and the
      access log are still English
- [ ] Offline reading of already-fetched pages
- [ ] Installable as a progressive web app

**Family and proxy accounts**
- [x] Proxy access is an interval with a relationship, evidence of consent,
      an expiry and a revocation
- [x] Narrower than the patient's own view by default — a carer arranging
      appointments does not need the notes
- [x] One live grant per account and patient, enforced by constraint
- [x] Checked at query time, so withdrawal takes effect immediately
- [x] A proxy's reads are logged; a patient's own reads are not
- [x] A review list of grants nobody has revisited
- [ ] A patient granting and withdrawing access themselves
- [ ] Automatic expiry when a child reaches majority

**Messages**
- [x] Patient to practice, and staff replies
- [x] Answered is distinct from read
- [x] An unanswered queue, because a message somebody glanced at is not
      answered
- [x] Stated as not a clinical channel, in the model and on the screen
- [ ] Attachments and photographs

**Oversight**
- [x] Take-up: invitations issued against accounts registered, and coverage
      against the patient list
- [x] Invitations that expired unused
- [x] Accounts locked right now
- [x] Live proxy grants, and the ones that see results marked
- [ ] Per-facility breakdown

## §95 Employee self-service 🔷

*Built and running. The data all exists in `apps/hr` and `apps/payroll`, accessed
through the staff console behind `Scope.OWN` query filtering and dedicated `/api/hr/me/summary/`
and manager queue endpoints. Direct self-approval is prevented by maker-checker validation,
peer shift swaps exchange roster entries atomically, and payslips export cleanly.*

**The scope question, which everything below depends on**
- [x] `own` scope actually filters, rather than being declared and ignored.
      This was the same defect §16 recorded for facility scope: an employee reading
      their own payslip or profile through `apply_scope_filter` sees only their own
      records and zero peer records
- [x] Whichever surface is chosen, an employee reading their own record needs
      no HR permission — the permission model expresses "mine" through `Scope.OWN`
      and dedicated self-service summary endpoints without granting tenant-wide `employee.read`

      **This was ticked and was not true, and the way it was untrue is worth
      keeping.** `Scope.OWN` filtering only helps somebody who *holds* the
      permission at own scope. The demo doctor, counter assistant and
      pharmacist hold no `attendance.read`, `employee.read` or `salary.read`
      at any scope, so six of the self-service screen's fourteen endpoints
      returned 403 to them — measured with `manage.py audit_screens`, not
      noticed by reading. The design had assumed every employee also holds
      the `staff` role. `scope_or_own()` closed it: no grant means your own
      rows rather than no rows (log 255). Ticked again, and this time with
      `tests/test_self_service.py` behind it.

**My profile**
- [x] Read: position, department, employment type, joining date, reporting
      line, contract
- [x] Propose a correction to address, telephone or next of kin — a request
      HR approves, not a direct write, because these feed payroll and
      statutory returns
- [x] Upload and replace their own documents; see which are expiring
- [x] Their own professional credentials with expiry, and a warning before it
      lapses rather than after

**My time**
- [x] Attendance for the month, with late and early-leaving flags shown as
      the system recorded them
- [x] Raise a regularisation when the clock was missed, with a reason, routed
      to their manager
- [x] Their roster, forward as far as it is published
- [x] Shift-swap request between two named people, needing both to accept and
      the manager to approve

**My leave**
- [x] Balance per leave type, and the ledger it was summed from — a balance
      that cannot be explained line by line will be disputed
- [x] Apply, with the working days computed against the holiday calendar
      rather than typed
- [x] Refused if the balance is short, or if it collides with a roster the
      employee is already on
- [x] Cancel or amend a request that has not yet been approved
- [x] Approval status, and who it is sitting with
- [x] The team calendar their manager sees, so a request is not made blind

**My pay**
- [x] Payslips for approved runs only — a draft run is not a payslip
- [x] Line-by-line earnings, deductions and employer contributions
- [x] Year-to-date, and the tax computation that produced the deduction
- [x] Statutory statements: PF, CIT, SSF
- [x] A payslip as a document to keep. This is the first genuine export in
      the system and settles the pattern for §129's export authorisation
- [x] Bank account on file, changed by request rather than directly

**My manager's side**
- [x] One queue holding every request from the team — leave, regularisation,
      swap, correction — rather than four screens
- [x] Approve or refuse with a reason the requester sees
- [x] Who is away when, before deciding

**Deferred, and named so they are not forgotten**
- [ ] Loans and advances against salary
- [ ] Expense claims and reimbursement (§70)
- [ ] Performance reviews (§118)
- [ ] Training records (§119)
- [ ] Announcements and acknowledgements
- [ ] Grievances and disciplinary records, which need a confidentiality model
      of their own before they go anywhere near self-service

## §96 My workspace `[~]`
- [x] Doctor worklist — open encounters, triage-ordered
- [x] Laboratory worklist — STAT-first
- [x] **My approvals**, at `/workspace` — eight sources across procurement,
      payroll, HR, point of sale, privacy and facility changes, gathered from
      the modules that own them rather than recomputed
- [x] Only what you can **act on** appears — absent, not greyed. A queue of
      things you can only look at teaches people it is not their queue
- [x] A source that fails is named as broken and `is_complete` goes false. An
      empty approval queue is a positive claim that there is nothing to
      approve, and a swallowed error makes that claim falsely
- [x] Ordered by what it costs to leave it sitting, not alphabetically
- [x] Unread notification count, read through the notification centre so the
      screen cannot disagree with the bell
- [ ] Tasks — needs §100, which has no model yet
- [ ] Reminders and the day's schedule on the same screen
- [x] Nurse workspace: assigned patients, vitals, medication, handover
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

## §99 Universal reminder engine `[~]`

*`apps/notifications/reminders.py`, run by `manage.py run_sweeps`.*

- [x] The engine: per-subject escalation bands, dedupe by subject **and** band
      so an hourly cron raises one notification rather than twenty-four, and
      resolution when the situation stops being true rather than when somebody
      swipes it away
- [x] **A reminder that reaches nobody is counted and reported**, not shrugged
      at. A sweep that finds forty expiring batches, tells nobody and reports
      success looks exactly like a system that is watching
- [x] Licence · probation · contract · batch expiry · blood unit expiry ·
      supplier invoice due · pre-authorisation expiry · supplier drug licence ·
      facility operating licence
- [x] `Invoice.due_date` is now written at issue, from credit terms held per
      patient category in the configuration hierarchy. The default is **due on
      issue** — the cash counter's status quo written down, not a credit
      policy invented on somebody's behalf
- [x] Receivables ageing reports days *past due* alongside days since issue,
      and counts the invoices it cannot answer for rather than calling them
      punctual. Nothing was back-filled
- [x] `EmploymentContract.ends_on` is enforced: a locum, intern, trainee or
      fixed-term contract is refused without one, while daily-wage, part-time
      and visiting engagements stay open-ended because those describe how
      somebody is paid rather than how long they are engaged
- [ ] Appointment reminders and clinical follow-up — these go to *patients*,
      so they need §93's channels first
- [ ] Stock count due · low stock · maintenance · calibration · accreditation
      · subscription · tax filing: no model carries these dates yet

## §100 Task management `[ ]`
- [ ] Owner · department · facility · priority · deadline · SLA · status
- [ ] Checklist · attachments · comments · escalation · audit

## §101 Notification centre 🔷

*Built and running. `apps/notifications`, one screen at `/notifications`, and
the first producer wired in diagnostics. Built ahead of the analytics work
because three modules were already working around its absence.*

**The shape**
- [x] One event, many recipients: a `Notification` is what happened, a
      `NotificationReceipt` is one person's copy and read state. Five
      clinicians told about one result is one row and five receipts, so
      "how many were told" and "how many read it" stay different questions
- [x] Six categories: critical, warning, approval, task, reminder,
      information
- [x] The text is frozen at the moment of raising, like the referral letter —
      a notification states what was true then, not what is true now
- [x] Subject recorded as a type name and a UUID rather than a foreign key,
      so a notification outlives the row it refers to and no cascade can
      delete the evidence that somebody was told
- [x] Channel recorded although only in-app is delivered, so §93 adds a row
      rather than restructuring the table everything reads

**Read state**
- [x] Read and dismissed are separate acts: seen, versus dealt with
- [x] A critical notification refuses to be dismissed without a note saying
      what was done, and the note is audited
- [x] Dismissing is one person's act — it does not clear anybody else's copy,
      and does not resolve the underlying situation
- [x] "Mark all read" clears the badge and dismisses nothing. Said out loud on
      the screen, because it is the control people misread
- [x] Constraint: dismissed implies read, so the unread count cannot go
      negative

**Counting**
- [x] The badge is summed from receipts on every request. No stored counter —
      one is wrong the first time two requests race and nobody notices
- [x] "Outstanding" is not "unread": a thing can be read three times and still
      be waiting. Outstanding is the default view

**Repetition**
- [x] A `dedupe_key` unique among *open* notifications, so an hourly sweep
      produces one row and not twenty-four
- [x] The key is released when the situation resolves, so "this fired every
      morning for a week" stays countable
- [x] `resolve_by_key` for a sweep whose condition has cleared
- [x] Information and reminders age out; approvals and tasks never do — one
      nobody has touched in ninety days is the most interesting row in the
      system, not a stale one

**Preferences**
- [x] Per person, per category
- [x] Critical cannot be switched off, and `set_preference` refuses rather
      than storing a value it would then ignore
- [x] Shown on the screen as locked with the reason, not hidden from the list
- [x] Applied when the notification is raised, not when it is read

**Raising**
- [x] `notify()` never raises into its caller — the event has already
      happened and failing to mention it must not undo it
- [x] Its writes sit in a savepoint, so a swallowed database error cannot
      abort the caller's transaction (log 162)
- [x] Recipients resolved and frozen at raise time, each with the reason they
      were chosen, so "why was I told?" survives a roster change
- [x] No endpoint lets a client post an arbitrary notification to arbitrary
      people. The single exception is an announcement, gated on
      `notification.broadcast`, carrying the sender's name, and unable to be
      critical
- [x] Reading an inbox needs no permission and takes no recipient parameter:
      the queryset narrows to `request.user` first, so nothing later can
      widen it

**Producers**
- [x] Diagnostics: a critical value notifies the clinician who ordered the
      test, alongside the log line. Deliberately not everyone at the facility
- [x] `holders_of(code, facility, exclude_user_id)` in `apps/rbac` — "who can
      approve this", answered from the permission outwards. Cross-checked
      against `resolve_authorization` in both directions
- [x] Leave: an application notifies whoever holds `leave.approve` at that
      facility, excluding the applicant; the decision resolves it and tells
      the applicant back
- [x] Expiry sweeps (`manage.py run_sweeps`): professional registrations in
      three bands, ninety days / thirty days / expired, with the band in the
      dedupe key so crossing a threshold raises a fresh notification rather
      than rewriting one already read
- [x] A sweep resolves as well as raises — renewing the licence clears the
      reminder because the situation ended, not because somebody swiped it
- [x] The sweep report distinguishes newly raised from already standing, and
      prints per tenant rather than summed
- [ ] Backfill for alerts already open when the wiring is deployed
- [x] Approvals: purchase requisitions and payroll runs, each telling whoever
      holds the approving permission and resolving on the decision. Payroll is
      the one that mattered — the highest-value approval in the system, and
      until now the second person had no way of knowing the first had finished
- [ ] Facility change requests, the one approval still without a notification
- [ ] Expiry sweeps for contracts, supplier agreements and stock
- [ ] Digest and quiet hours
- [ ] Delivery beyond in-app (§93). **Note:** patient invitation codes cannot
      be moved off the desk by this module — the recipient has no account yet,
      so an in-app notification reaches nobody. That one waits on §93, not
      §101

## §122 Document management 🔷

> **Uploading and archiving took only `patient.read` until log 272.** Attaching
> a document to a patient's record is an edit to that record and now takes
> `patient.update`; reading stays at `patient.read`, because the pharmacist and
> the counter both need to open a scanned prescription without being able to
> add to it.

*Built. `apps/documents`, mounted at `/api/documents/`.*

- [x] Upload, with an allow-list of content types and a 50 MB limit
- [x] Stored by **checksum, never by filename** — a filename is
      attacker-controlled, it collides, and a file called
      `ram-bahadur-hiv-result.pdf` on disk is a disclosure to anybody who can
      list a directory
- [x] The same bytes against the same subject is one document; the second
      upload returns the first rather than refusing
- [x] **Access inherited from the subject** — a document about a patient is
      governed by the same care relationship as their record, not by a second
      permission model that would drift out of step
- [x] Versions supersede rather than overwrite
- [x] Archived with a required reason, never deleted
- [x] Downloads logged; listings not — opening a scan is the sensitive act
- [ ] **Malware scanning.** Nothing scans anything. This is the blocker for
      letting *patients* upload, specifically
- [ ] Retention rules and legal hold
- [ ] Full-text search across documents
- [ ] A screen: the API exists, neither application shows it yet

## §123 Template management `[ ]`
- [ ] Invoice · prescription · lab report · discharge · referral
- [ ] Salary slip · purchase order · receipt · consent · email · SMS · WhatsApp
- [ ] Tenant-specific branding

---

# Phase 10 — Intelligence `[ ]`

## §104 Global search `[~]`

*`apps/search`, mounted at `/api/search/`. Eleven sources.*

- [x] Patients, staff, medicines, suppliers, invoices, documents,
      appointments, prescriptions, admissions, laboratory, imaging
- [x] Permission filtering applied **before** the query is issued, not after
      the rows come back. Filtering after fetching leaks a count, logs a read
      that should not have happened, and leaves a timing difference
- [x] The count is the count of what the caller may see. No "42 results, 3
      shown" — that reports the other 39 into existence
- [x] Clinical sources narrow to the care relationship; patient identity stays
      browsable, because the registration desk cannot have a relationship with
      somebody not yet registered
- [x] An **exact** reference searches unnarrowed while partial and name matches
      stay narrowed — naming a record is a lookup, typing part of a name is a
      browse. Flagged `by_reference` and counted separately in the audit event
- [x] Sources the caller cannot use are named with the permission they need,
      never silently dropped
- [x] One audit event per search recording the term, not one per hit
- [ ] Doctors as a source in their own right — today they are found through
      `employee`, which is right for staff lookup and wrong for "who can I
      refer this patient to?"
- [x] A screen: the omnibox in the header, Ctrl-K, with stale responses
      dropped and hits found by reference labelled as such
- [ ] Ranking across sources. Each source ranks exact before partial; the
      groups themselves are returned in a fixed order rather than by relevance
- [ ] Trigram or full-text indexes. `icontains` across eleven sources is 27
      queries and 94ms on demo data — fine now, measured, and not a plan

## §105 Reporting engine `[~]`

*`apps/reporting`, mounted at `/api/reports/`.*

- [x] Standard report library: thirteen reports that already existed beside the
      modules that understand them, made discoverable and uniform. Each declares
      the **question it answers**, not only its name — "Trial balance" means
      nothing to somebody who needs to know whether the books balance
- [x] Each report names the permission it needs and the registry enforces it. A
      reporting layer is exactly where somebody would look for a way around the
      access controls
- [x] Reports the caller cannot run are **listed and marked, not hidden**
- [x] CSV export, at `?export=csv` — `format` is DRF's reserved parameter and
      collides. Reports that are not tables say so rather than inventing a shape
      whose columns mean different things down the page
- [ ] **No custom builder, deliberately.** A builder is at best a worse SQL with
      a mouse and at worst a way to produce a number nobody can reproduce and
      everybody quotes. Revisit only if a real need appears that a curated
      report cannot meet
- [x] A screen at `/reports`, listing each report by the question it answers
      with the name as the small print, and per-section CSV
- [x] A result holding more than one table **refuses to export** under the
      report's name and says which sections exist. A CSV called
      `finance.balance_sheet` holding only the assets looks complete and is not
- [ ] PDF and Excel export
- [ ] Scheduled reports — delivery to an inbox on a calendar

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

## §124 Data import and migration `[~]`

*The pipeline is built and running: `apps/dataimport`, `/api/import/...`, and the
`/import` screen. What remains is more kinds, not more pipeline — adding one is
an `Importer` in `kinds.py` declaring its columns, its duplicate rule and which
service creates the record.*

- [x] CSV, TSV and Excel import. Encoding sniffed (a UTF-8 BOM from Excel on
      Windows silently unmatched the first column), delimiter sniffed (a
      semicolon file read as CSV parses as one enormous column with no error),
      `data_only=True` so a `=CONCATENATE()` cell imports its value rather than
      its formula, and duplicate Excel headers de-duplicated rather than
      overwriting each other in a dict
- [x] **Upload → mapping → validation → duplicate detection → preview → import
      → error report → audit**, each a step somebody agrees to. Nothing before
      commit touches a patient or a product, which is what makes the preview
      trustworthy
- [x] Mapping suggested from header aliases, then editable — and *stored*, so a
      reviewer's correction is not silently re-suggested away. Three sample
      values shown per column, because a column called "Date 2" cannot be
      identified from its name
- [x] Duplicate detection against existing records **and within the file
      itself**. The second is the one every naive importer misses: at
      validation time neither row exists, so no database lookup can find it,
      and a spreadsheet kept for a decade has the same person in it several
      times
- [x] Every duplicate needs an explicit import-or-skip decision. No default:
      skipping silently loses somebody who is genuinely new, importing silently
      creates the split record the whole feature exists to prevent
- [x] Commit goes through the real creation services, never the models — so an
      imported patient gets an MRN from the same sequence as one registered at
      the counter, and is metered and audited identically
- [x] One savepoint per row, so row 4,312 failing does not roll back the 4,311
      before it; idempotent at batch level (a second commit is refused) and at
      row level (a row already created is skipped), because a slow request and
      a second click is the likeliest way a migration duplicates a file
- [x] Entitlement quota checked once for the whole batch before anything is
      created — a per-row check stops halfway with the customer over their plan
      *and* their migration half done
- [x] Error report as a CSV shaped to be corrected and re-uploaded: the original
      columns first with the file's own headers, then the row number and the
      problem
- [x] `data.import`, its own sensitive permission. Registering one patient at
      the counter is a clerk's job; creating eight thousand from a spreadsheet
      is a migration
- [x] Patients and medicines
- [ ] Employees, suppliers, services and prices — importers, not pipeline
- [ ] Opening stock and opening balances. Deliberately last: these are not
      record creation, they are a stock ledger and a journal entry, and they
      have to go through those services with a date and a counterpart account
      rather than being written as rows
- [ ] Historical clinical data (past encounters, prescriptions, results), which
      needs a decision about what an imported encounter means for audit and for
      the clinical record before any of it is built
- [ ] API import

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
- [x] **`manage.py audit_screens`** — reads the frontend source for every API
      path each page calls and probes all of them as each demo account,
      printing a status matrix. Reports rather than asserts: a 403 is often
      correct, so it is rendered amber and the judgement stays with a person.
      Paths it cannot honestly probe — interpolated detail routes truncated to
      a collection prefix, and anything answering 405 because the screen uses
      a verb other than GET — are marked `~` and excluded from the count.
      First run 117 failing endpoint/user pairs; 54 after the artifacts were
      classified and self-service was fixed (logs 253, 255)
- [ ] API, database and queue health
- [ ] Background job monitoring
- [ ] Error log aggregation
- [ ] Infrastructure, storage, backup, integration, notification, search and sync monitoring

## §132 Customer support `[ ]`
- [ ] Tickets · priority · SLA · category · agent · escalation
- [ ] Internal notes · customer response · attachments · resolution
- [ ] Knowledge base · training

---

# Permissions that answered two questions `[~]`

*Prompted by one question: "why was a doctor given access to Capacity, Finance,
Nurse workspace — is it an access thing?" It was, and the audits could not see
it: they check that the sidebar and the API **agree**, and both agreed on
permissions that were too coarse (log 271).*

- [x] **`finance.read`** — `report.read` gated both laboratory turnaround (which
      a doctor needs) and the chart of accounts, bank statements, VAT return and
      general ledger (which they do not). Seven endpoints moved; held by
      accountant, auditor, facility manager and financial controller
- [x] **Capacity is `subscription.read`** — it shows what the *plan* allows and
      how much is spent, and inherited `facility.read`, which every clinician
      holds in order to know which facilities exist
- [x] **The four clinical boards moved to `patient.clinical.read`** — ICU,
      theatre, blood bank and the nurse's bedside console. `encounter.read` is
      held by the receptionist, correctly, for the outpatient queue and the
      appointment diary, and it was putting the critical-care record and the
      transfusion history in the front desk's sidebar. The tier already existed
      in `ACCESS_DESIGN.md` phase 1; the screens had never moved onto it
- [x] **`manage.py audit_access`** — the screen-by-role matrix, so this is read
      once rather than discovered one cell at a time
- [ ] Emergency and Wards stay on `encounter.read` deliberately: registering an
      arrival and knowing which bed somebody is in are front-desk work. Revisit
      if a customer disagrees
- [ ] Phase 2 of `ACCESS_DESIGN.md`: `patient.clinical.read` enforced against a
      *care relationship* rather than a facility, with break-glass as the
      escape. The machinery exists (`apps/rbac/relationships.py`, break-glass,
      the privacy queue) and is off by default

# A read permission that was a licence to write `[x]`

*Found by chasing the one cell log 271 left unexplained — the receptionist's 403
on `/api/clinical/encounters/` — which turned out to be **correct**. The Queue
screen reads `/clinical/queue/` and `/clinical/availability/`, both of which the
front desk can open; it touches `/clinical/encounters/` only when a clinician
opens a chart. Four other things were wrong (log 272).*

## The defect class

- [x] **`HasPermission.of(..., write=...)` on every route that changes
      something.** DRF's `@action(methods=["post"])` inherits the viewset's
      `permission_classes`, so a class declaring only a read permission guarded
      its writes with it. `QueueViewSet` was the example: `call-next`, `recall`,
      `start` and `complete` — the four verbs that move a waiting room — behind
      `encounter.read`. A lab technician could complete somebody's
      consultation, and so could an **auditor**, whose role description is
      "read-only oversight across the organization"
- [x] **`manage.py audit_writes`** — the same question asked repeatably rather
      than by a one-off script. Walks the URLconf, resolves each route's guard
      *the way DRF does* (instantiating the view and setting `self.action`, so a
      per-action `get_permissions()` is read rather than guessed), follows
      guards factored into a `self._writable()` helper, and respects
      `http_method_names`. Reports **0**
- [x] **Two exemption tables, each entry carrying a written reason.**
      `OPEN_BY_DESIGN` (signing in, your own inbox, break-glass) and
      `READ_SHAPED_POST` (a duplicate check, a price preview, a till quotation,
      a change preview — questions that arrive as POSTs because they do not fit
      in a query string). Named individually, never pattern-matched on
      "preview", because a pattern is a loophole waiting for somebody to call an
      endpoint `preview_and_apply`
- [x] Where the 81 went: the queue → `visit.schedule`; laboratory collection and
      result entry → `diagnostic.process`; verification and critical-value
      notification → `diagnostic.verify`; nursing assignments, SBAR handover and
      bedside tasks → `encounter.create`; a ward round recorded through a
      dual-verb action → `encounter.create`; the referral provider directory →
      `department.manage`; documents on a patient → `patient.update`; a
      requisition sent for approval → `purchase.create`; a donor's record after
      deferral → `blood.process`

## Permission codes that had never existed

- [x] **`tests/test_permission_codes.py`** — `require(code, scope)` takes a
      string and never checked it against the catalogue, so a typo refused
      **everybody, forever**: the worst failure mode a permission check has,
      because it looks exactly like security working. Three codes, eight call
      sites, all of them dead:
      - `pharmacy.dispense` (six sites) — every write in the blood bank. Donor
        registration, collection, grouping, screening, separation, release,
        issue, discard. The whole module, unusable by anybody
      - `facility.manage` — provider schedules, so nobody could define a
        consultant's clinic
      - `report.view` — the ICU unit summary
- [x] Every affected module's own tests passed throughout, because they run as
      the organization owner, who is exempt from every permission check by
      design. **A suite that only ever acts as the owner cannot see an
      authorization defect at all**
- [x] Found by probing the running stack as the auditor and noticing the
      refusals were *too uniform to be real*. A 403 where a 403 belongs proves
      nothing on its own
- [x] Second test in the same file: permissions **no seeded role grants**, with
      an exemption table. A permission held by nobody is the same outage
      arriving by a different road

## Two permissions where there had been one

- [x] **`blood.process` / `blood.issue`** — the bank's own work up to release,
      and the ward's use of what was released. The technician who screened a
      unit is not the person who hangs it
- [x] **`diagnostic.process` / `diagnostic.verify`** — entering a result and
      releasing it to a chart. The service layer already refused the person who
      entered the values, which is a check between two *individuals*; it said
      nothing about whether the second person is qualified to release anything,
      so "a second pair of eyes" meant any second pair of eyes in the building
- [ ] A small lab that wants one senior technician doing both grants it in a
      role of its own. Deliberately a customer's decision, and visible because
      it is two permissions rather than one

## The tenant was on two plans at once

- [x] **`Subscription`: one live subscription per organization**, as a partial
      unique constraint over the entitled statuses, excluding soft-deleted rows.
      A customer's history is a stack of cancelled subscriptions and it must stay
- [x] `seed_demo` keys its subscription lookup on the **customer**, not on the
      customer *and the plan*. Keyed on both, it did not find the `enterprise`
      subscription the tenant had been upgraded to, and made a second live one
      on `professional`. Entitlement resolution picked the narrower of the two
      and the demo hospital silently lost the `hospital` module — six seed tests
      failing with "module not entitled" against a subscription screen showing a
      healthy active plan
- [x] **A seed must be safe to re-run against a tenant somebody has changed
      since.** Re-running is the whole point of a seed; an untouched tenant is
      the easy case
- [x] The duplicate was cancelled with a reason and a subscription event, not
      deleted. It is a billing record

## Demo accounts that should have existed from the start

- [x] **`auditor@`** — the account that makes "read-only" provable. A role whose
      whole value is what it *cannot* do needs an account, or the claim is
      decoration
- [x] **`nurse@`** — four screens exist whose only intended user is a nurse
      (workspace, eMAR, handover, bedside rounds) and every probe of them had
      run as a doctor or the owner
- [x] **`lab@`** — `lab_technician`'s ceiling moved from department to facility.
      Departments are created by the module seeds, which run *after* roles are
      bound, so a department-scoped assignment had nothing to name and was
      refused outright. A role nobody can be given describes an organisation
      chart rather than a job
- [x] **`tests/test_write_authority.py`** is written as the auditor, and
      deliberately: for every route in it, the missing write check is the *only*
      obstacle. The same test written as a receptionist would pass several of
      them for the wrong reason — refused for lack of the read permission,
      never reaching the write check
- [x] It resolves each path before probing it. The first draft aimed at
      `/api/lab/orders/.../verify/`; the route is under `/api/diagnostics/`, so
      it 404ed. The assertion is "403 and only 403", so the typo failed loudly —
      but under a looser "not 2xx" it would have been green forever against a
      URL that does not exist

## Verified against the running stack, not only the source

- [x] The auditor is refused all eight probed writes (`403` on every one; two
      answered `400`/`404` before, meaning they had got past the gate)
- [x] And the other half, which matters more: the receptionist can call the next
      patient, the nurse can open the workspace and reserve a blood unit, the
      technician can collect a sample and defer a donor, the doctor can verify a
      result — while the technician is **refused** verification
- [x] `NIROVA_TENANT_DB_HOST` is in `backend/.env` *and* set explicitly in
      `infra/docker-compose.yml`. The override existed and nobody remembered to
      export it, which is the same as not existing

# Returns at the counter, reachable at last `[x]`

*Four endpoints with no screen (log 266). A pharmacy could sell and could not
take anything back — which in practice means it happens in cash out of the
drawer and the stock ledger never hears about it.*

- [x] Raise a return against a sale, line by line, with the condition each item
      came back in
- [x] `returnable_quantity` comes from the server, never computed in the
      browser: a line already partly returned can only give back the remainder,
      and a browser-side subtraction would disagree with the service at the
      moment the goods are already over the counter
- [x] Decide it: approve with a refund method, or refuse with a reason
- [x] Raising and approving are different permissions — `sale.return` at the
      counter, `sale.return_approve` for the manager — **and no role holds
      both**
- [x] Approving is refused to whoever raised it, which is the only control that
      binds the organization owner (who bypasses every permission check)
- [x] Restocking is a separate question from refunding. Money can go back
      without the goods going back on the shelf: a cold-chain vial that sat on
      a counter is refundable and not sellable

# Payables, reachable at last `[x]`

*Added after `audit_reach` found six finance endpoints with no screen (log 264).
Building it turned up a complete deadlock behind them.*

- [x] Claim an expense, and approve one — approval posts it to the ledger in the
      same step, and is refused to whoever claimed it
- [x] Record a supplier invoice and approve it, with the supplier **chosen**
      rather than typed (the model makes supplier and invoice number unique
      together, which is what stops one bill arriving twice under two spellings)
- [x] **`financial_controller`** — no seeded role held `finance.post`, so posting
      a journal entry and approving an expense were the organization owner's
      personal jobs. Deliberately without `invoice.create`: raising invoices and
      keeping the ledger are separate on purpose
- [x] Claiming an expense no longer requires the permission to post it. It did,
      which meant the only account that could raise a claim was the only account
      forbidden from approving it — nobody could complete the flow at all
- [x] Recording and approving a supplier invoice are different permissions
      again. The class gate covers create, update and delete; the `approve`
      action carries its own
- [x] **References are allocated from the highest already issued**, not from
      `objects.count() + 1`. Soft-deletion drops the count while the unique
      constraint still sees the deleted row, so any tenant that had ever
      deleted one of these could never create another
- [ ] Paying a supplier invoice, and the payment run behind it

# The stockroom, reachable at last `[x]`

*Added after `manage.py audit_reach` found thirteen pharmacy endpoints that no
screen called (log 263). A pharmacy could dispense from stock it had no way of
putting there.*

- [x] Receive a delivery — the only door through which a batch is created, and
      the same batch number, product and expiry adds to the existing batch
      rather than splitting it (which would leave a recall finding half of it)
- [x] Adjust a batch, with a reason the API insists is long enough to mean
      something to whoever reads the ledger next year
- [x] The movement ledger, with the running balance rather than deltas alone
- [x] Valuation: at cost, at retail, the margin held in the stock, and the
      figure worth acting on — what has expired and is still being counted as
      if it were sellable
- [x] Stock counts: open, count blind, submit for review, approve. **Approving
      is refused to whoever did the counting** — a stock adjustment is the
      classic route for concealing theft
- [x] A blind count is blind at the API, not merely on the screen: the expected
      quantity is nulled in the serializer, so it never reaches the browser
- [x] A `store_keeper` demo user. `pharmacy_manager` holds `stock.count` and
      `stock.approve_adjustment` and deliberately **not** `stock.adjust`, so no
      demo account could receive a delivery and the maker half of the pair was
      untestable from outside
- [ ] Batch quarantine and recall exposure, reconciliation — endpoints exist,
      still no screen

# Locale and self-service configuration `[~]`

*Added 8 September 2026 (logs 241-244), on the instruction to judge this
against real practices from a single clinic to a multinational group.*

- [x] `TIME_ZONE` was one global constant, so every timestamp rendered in
      Kathmandu time. Storage was always UTC, so the data was right and the
      display was wrong — the more dangerous of the two, because nothing looks
      broken. Now activated per request from the facility's own zone
- [x] Four fiscal calendars (Nepal, calendar year, 1 April, 1 July), named by
      what they are rather than by country. Invoice numbering is gapless per
      fiscal year, so a January–December branch numbering against Nepal's July
      boundary reset its sequence mid-year
- [x] The standard tax rate follows the tenant. A Gulf branch was charging
      Nepal's 13% and the invoice was arithmetically consistent and wrong
- [x] Defaults are Nepal throughout — a single clinic configures nothing
- [x] Built on `ConfigSetting`, so a facility may hold its own value and the
      group may **lock** one so no branch differs. No migration to every tenant
      database in the fleet
- [x] Resolution memoised per request in a `ContextVar` and invalidated on
      write, because `effective_tax_rate` is a property evaluated once per row
- [x] `GET/PUT/DELETE /api/org/settings/` — the first endpoint `ConfigSetting`
      has ever had. The privacy switch was previously unturnable except from a
      Django shell
- [x] A declared registry, not a key/value endpoint: an API accepting any
      namespace and key is permission to write arbitrary configuration rows
- [x] Validation at the boundary — a misspelled timezone throws nowhere and
      silently leaves every timestamp in the default zone
- [x] `SystemSettings` screen, rendered from the server's registry so there is
      no second copy of the calendars in the frontend
- [ ] `province`/`district` as the shape of every address. A Gulf facility has
      an emirate; a UK one has a county
- [ ] `name_nepali` on `ServiceItem` as *the* second language
- [ ] NMC registration as *the* clinical credential. Dubai issues a DHA
      licence, the UK a GMC number
- [ ] Currency conversion. The setting relabels prices; it converts nothing,
      and says so before you change it
- [ ] Per-country invoice layout and statutory fields

---

# Staff administration `[~]`

*Added 8 September 2026 (logs 235, 236). Seven catalogue permissions were
granted by four roles and checked by no endpoint: the product could not onboard
a second member of staff.*

- [x] `GET/POST /api/admin/staff/` — list with roles, invite, optionally
      granting a role in the same act
- [x] `GET/PATCH /api/admin/staff/<uuid>/`, and `deactivate/` with `?undo=1`
- [x] `GET /api/admin/roles/` — annotated with whether *you* may grant each,
      and what puts the others out of reach
- [x] `POST/DELETE /api/admin/staff/<uuid>/roles/…` — grant and revoke
- [x] `revoke_role`, which did not exist — nothing could take a role away,
      which is why `RoleAssignment.revoked_at` had never been written to
- [x] Revoked, never deleted: "who could approve this in March?" stays
      answerable
- [x] Deactivating revokes every role; reactivating restores **none** of them,
      because authority held a year ago is not authority reviewed today
- [x] The escalation guard is live — every grant passes
      `assigner_authorization`, which nothing had done since it was written
- [x] Delegation is stated, not inferred (`Role.grantable_roles`). The strict
      "you may not grant what you do not hold" rule let a facility manager
      grant exactly one role: their own
- [x] **You may not grant a role to yourself**, owner included — without it,
      delegation is escalation with an extra step
- [x] `src/pages/Staff.tsx`, with the three acts kept apart because their
      permissions are held by different people
- [x] 18 tests, both security guards proved by reintroducing their defects
- [ ] Transferring organization ownership (the owner cannot be deactivated and
      there is no way to hand the role over)
- [ ] Sending the invitation. The account is created and cannot sign in until a
      password is set; nothing emails the person yet
- [ ] `role.manage` — creating and editing custom roles. Assignment works;
      authoring a role does not
- [ ] Per-user permission overrides (`PermissionOverride` exists, no endpoint)

---

# Packaging and local operation `[x]`

*Added 8 September 2026, on the ask: "we need frontend, backend everything, so
that one click can make system up" and "app build should not make me wait"
(log 230).*

- [x] `docker compose -f infra/docker-compose.yml up` brings up all seven
      services — Postgres, Redis, API, Celery worker, Celery scheduler, and
      both React applications behind nginx. Measured cold, no images, no
      volumes: 3m26s to all seven healthy
- [x] First run also migrates, seeds the catalogue, provisions a demo tenant
      and fills it — nothing else is typed
- [x] Backend image is multi-stage, non-root, with the dependency layer keyed
      only on `requirements.txt` and pip's cache in a BuildKit mount
- [x] **One** web image for both React applications (`ARG APP`) and **one**
      nginx template for both, expanded by `envsubst`. Two files 95% the same
      drift, and the half that drifts is whichever nobody rebuilt
- [x] `/api` is proxied, not called cross-origin, so the container stack sees
      one origin exactly as the Vite dev proxy does — CORS behaviour is then
      the same in both rather than production being a special case
- [x] Hashed assets `immutable` for a year; `index.html` `no-cache`. Correct
      rather than aggressive, because Vite fingerprints every filename
- [x] Every dependant waits on `condition: service_healthy`, never a bare
      `depends_on` — the gap between "container started" and "Postgres accepts
      connections" is the commonest reason a stack works on the second try
- [x] `manage.py bootstrap` decides "already done" by asking the database, not
      by leaving a marker file a volume can outlive
- [x] Production settings' TLS assumptions behind one flag defaulting to
      secure. `SECURE_SSL_REDIRECT` alone would answer every URL in a local
      stack with a 301 to a port nothing listens on
- [x] `.gitattributes` forces LF on shell scripts, Dockerfiles and templates —
      a CRLF entrypoint fails as `exec format error`, invisible in a diff
- [x] Hot-reload override (`infra/docker-compose.dev.yml`): Vite dev server and
      `runserver` on bind mounts, so in that mode there is no build at all
- [x] Frontend first load 984 kB → **314 kB** raw, 237 kB → **90 kB** gzipped,
      via route-level `lazy()` and vendor chunks split by how often each
      changes. `vite build` 15s → 8.5s (log 229)
- [x] `@tanstack/react-query` removed — its chunk built to 1 kB because nothing
      had ever imported it (log 229)
- [ ] A published image and a deploy target. This is local operation only
- [ ] TLS in front, and a compose profile that terminates it
- [ ] Resource limits and a restart policy tuned for anything but a laptop

---

# Testing and CI `[~]`

*Added 5 September 2026. There were no tests at all until then — the seeds
were the whole verification mechanism, which worked only because somebody
remembered to run them twice by hand.*

- [x] `pytest` + `pytest-django`, 288 tests (279 pass, 9 skip)
- [x] Every seed run twice, in dependency order, as separate parametrised
      tests — so a failure says whether it never worked or only worked once
- [x] One invariant test per numbered development-log entry. That is the
      selection rule: a record of what has actually broken, not an attempt at
      coverage
- [x] `makemigrations --check`, which would have caught log 156 on the day
- [x] Deliberately not hermetic: the suite drives the real router, the real
      migrations and the real constraints, because every defect it exists to
      catch is a disagreement between two layers that a mock removes
- [x] GitHub Actions: the same sequence a developer runs, plus a type check
      and a real build of both frontends
- [x] `patient/` lockfile generated — `npm ci` would have failed there and its
      builds were never reproducible
- [x] The seed registry is read from the filesystem, not maintained by hand.
      `seed_hr_demo` existed, was committed, was in the README, and was in no
      list — so nothing ran it for months and it raised `NameError` the first
      time anything did (log 231)
- [x] The demo estate is built from **empty** by `manage.py bootstrap`, in an
      order that was measured rather than reasoned about. Until a container
      did this, every run in the project's life had used a database somebody
      had already built (log 231)
- [ ] The suite itself run against a fresh tenant in CI, not only against
      whatever the runner happens to have. Four tests were passing vacuously
      because the demo doctor held no role and a user who sees nothing
      satisfies every assertion about not seeing too much (log 231)
- [x] **73 of 83** catalogue permissions are checked somewhere in `apps/`, up
      from 65 of 76. `subscription.read` joined them with Capacity (log 271);
      `blood.process`, `blood.issue`, `diagnostic.process` and
      `diagnostic.verify` are new and enforced from the start (log 272).
      **10 remain unreachable**: `analytics.read`, `audit.export`,
      `organization.read/update`, `patient.safety.read`,
      `prescription.approve`, `refund.create`, `report.build`, `role.manage`,
      `stock.transfer`
- [x] **Every code a guard names is declared** — `tests/test_permission_codes.py`.
      Three were not, and each refused everybody rather than failing loudly
      (log 272)
- [x] **No write route takes only a read permission** —
      `tests/test_write_authority.py` plus `manage.py audit_writes`, asserted at
      zero. Written as the auditor, because that is the actor for whom the
      missing check is the *only* obstacle (log 272)
- [ ] A test that acts as somebody other than the organization owner for every
      module. The owner bypasses every permission check by design, so a suite
      that only ever acts as the owner cannot see an authorization defect at
      all — which is why three dead permission codes survived for months with
      green tests (log 272)
- [ ] Coverage measurement
- [ ] A hermetic unit layer for the pure calculations (NEWS2, tax slabs,
      ageing buckets) that needs no database
- [ ] Frontend tests beyond the type check
- [ ] Load and concurrency tests on the tenant router

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
- [ ] **A viewset that answers an unsafe verb declares `write=`.** A DRF
      `@action(methods=["post"])` inherits `permission_classes`, so a class
      declaring only a read permission guards its writes with it — and the
      missing line looks like nothing at all. `manage.py audit_writes` is the
      check; an exception goes in its exemption tables with a reason (log 272).
- [ ] **A permission code is checked against the catalogue, not trusted.**
      `require()` takes a string and never validated it, so a typo refused
      everybody forever — which looks exactly like security working, and hid
      three dead modules behind green tests (log 272).
- [ ] **An authorization test names an actor for whom the missing check is the
      only obstacle.** A test as the owner proves nothing (they are exempt);
      a test as somebody lacking the *read* permission never reaches the write
      check and passes for the wrong reason (log 272).
- [ ] **A maker-checker split is two permissions as well as two people.**
      Refusing the individual who entered a value says nothing about whether
      the second individual is qualified to release it (log 272).
- [ ] **A seed is safe to re-run against a tenant somebody has changed since.**
      Keyed on the wrong tuple, `seed_demo` gave one customer two live
      subscriptions and silently removed a module (log 272).
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
