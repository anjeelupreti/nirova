# Experience Plan — theme, consistency, personalization, enrichment

*Written 11 September 2026, after a full pass over the console, the patient
application and the checklist. The complaint that prompted it was that the
product is not pitchable: the theme reads as a default, nothing is grouped or
personal, there is no dashboard, no visualisation, no user management, no card
views, no profiles. Most of that is correct. This document says exactly how
much is correct, why it happened, and what to build.*

**The one-line diagnosis.** Nirova has been built API-first for nine months and
it shows: the backend is a real hospital platform, and the frontend is a set of
44 admin screens that read the same API back. Nothing on screen is *composed* —
there is no view that answers a question, only views that list a table. A buyer
in a demo does not evaluate endpoint coverage. They evaluate the first screen,
whether it feels like theirs, and whether it tells them something they did not
already know. We currently lose on all three.

---

## Status — Waves 1 to 3 are built

*Updated 11 September 2026. Log 273 has the full account; this is the index.
Everything below in Parts 1–4 that is now **done** is marked ✅ where it is
described. What follows is what a reader wants first: what changed and what
did not.*

**Built**

| | Where |
|---|---|
| Three-tier tokens, warm neutrals, clinical colour semantics | `frontend/src/styles/tokens/` |
| Geist + Geist Mono self-hosted, named type scale, tabular figures by default | `index.css`, `main.tsx` |
| Elevation, radius, focus as scales; motion adopted | `tailwind.config.js` |
| A real mark, and a slot for the customer's | `components/ui/brand.tsx` |
| Icon vocabulary — one glyph per concept, stroke scaling with size | `components/ui/icon.tsx` |
| Five distinct loading treatments, including *not* showing one under 250ms | `components/ui/loader.tsx` |
| `StatusBadge` / `AcuityBadge` / `TrendBadge` / `Freshness` | `components/ui/status.tsx` |
| `Tabs` on Radix with `?tab=` sync, replacing 17 hand-rolled strips | `components/ui/tabs.tsx` |
| `DataView` — table / cards / board, remembered per person per screen | `components/ui/dataview.tsx` |
| `Can` / `useCan` / `RequirePermission` | `components/ui/can.tsx` |
| 22 chart forms on a validated palette, with a table view and four states each | `components/charts/` |
| The shell: rail as its own surface, collapsible groups, pins, counts, org identity | `components/shell/` |
| Command palette (⌘K) over records, screens and actions | `components/shell/CommandPalette.tsx` |
| `/dashboard`, wired to five summary endpoints that existed and were called by nothing | `pages/Dashboard.tsx` |
| `/access` — roles, the permission matrix, the scope ladder | `pages/Access.tsx` |
| `/design` — every token, state and chart on one scroll | `pages/Kitchen.tsx` |
| Redesigned sign-in | `pages/Login.tsx` |
| `landing` preference finally read; role- and permission-based home | `components/shell/nav.ts` |
| Three guards: colour ratchet, token wiring, no primitive leakage | `backend/tests/test_design_tokens.py` |

**Not built at the end of round one** — *and four of these were done in round
two; see the table below, kept here so the sequence is legible rather than
tidied away.*

- ~~**Role editing.**~~ Built. `POST`/`PATCH`/`DELETE /admin/roles/`.
- ~~**A permission catalogue endpoint.**~~ Built. The prefix parser survives as
  the fallback for a failed request.
- ~~**Raw colours on the other 42 screens.**~~ Cleared, by codemod, to zero —
  and the guard now covers the whole of `frontend/src` rather than only the
  screens, after a `bg-emerald-500` was found surviving in the timeline marker.
- ~~**The theme still reading as generated.**~~ Five computed palettes.
- **`/patients/:uuid` as a record page** with a timeline. Still not built;
  `Timeline` is still used by nothing. The employee profile became linkable
  (`?employee=`) but still shows nothing about what the person may *do*.
- **The individual printed slips.** The frame and the stylesheet exist; the
  invoice, prescription and discharge summary do not yet sit on them.
- **The facility switcher in the shell**, org logo upload, saved views, the
  onboarding wizard, an organization's own accent colour.

**The honest read on pitchability.** Sign-in, the shell, the persona boards,
the access story and the design page are demo-grade. The deep screens now share
the palette and the status colours — so they no longer look like a different
product — but their *composition* is still the old console: raw tables, no card
or board views, hand-rolled tab strips. That is the remaining work, and it is
the largest item in this document.

---

## Round two — what the second review changed

*Updated 11 September 2026. The verdict on the first pass was blunt and mostly
right: the theme still read as generated, everything started from the sidebar,
roles were not configurable, the login was dull, and — the sharpest line —
**the system itself is confused whom to show what**. Log 274 has the full
account; this is the index.*

| Complaint | What it actually was | Now |
|---|---|---|
| "The colour combination is boring and dim" | A 45%-luminance accent, pure grey chrome, and no second colour anywhere | **Five computed palettes**, switchable from Settings. 65 contrast assertions across both modes. A fill carries dark ink where it can, so the teal went `#007865` → `#10B7A0` |
| "Nurse workspace and ward look AI-generated" | 95 raw colour utilities between them, most with no dark form at all | Zero raw colours anywhere under `frontend/src`, cleared by codemod. The ratchet is absolute now |
| "Everything starts from sidebar menus" | Forty entries, six of them things somebody opens twice a year | The rail is **the work**, the avatar is **the system**, plus a `/settings` hub. Rail 36 → 30 |
| "Roles should be configurable" | `role.manage` had been in the catalogue since day one with nothing to spend it on | A full role editor, with four refusals surfaced *before* submit rather than on it |
| "The system is confused whom to show what" | One dashboard whose panels disappeared by permission — subtraction, not personalisation | **Personas**, inferred from capability rather than role code, each with a board composed for the job |
| "Login and signup are dull" | A marketing panel with three bullet points | The right-hand panel is **the product working** — ward board, theatre day, triage board, cycling |
| "Reports, excels, pdfs, slips need work" | Every list in the product was a dead end | CSV and Excel on every `DataView`, a real print stylesheet, and `PrintableDocument` |

**Three things went wrong on the way, and are worth keeping.** The first
palette generator walked a fixed lightness ladder and failed eleven contrast
checks, because HSL lightness is not perceived luminance. The fix for that — a
hard lightness cap — repaired cyan and broke indigo, violet and green. And the
colour ratchet, once at zero, started failing on comments that *described* the
classes they had removed. All three were caught by a script rather than by my
eye, which is the argument for having the scripts.

**Still open, and honestly so:** the individual slips on the printable frame
(invoice, prescription, discharge summary); the patient record page with a
timeline; logistics and stock-tracing depth; the patient portal as its own
distinct surface; an organization's own accent colour. Part 5 sequences them.

---

## Part 0 — What is actually there

Being precise matters, because the fix is different for "missing" than for
"built and never used".

### Genuinely missing

| | Evidence |
|---|---|
| **Any dashboard** | No `/dashboard` route. `/workspace` is an approval inbox, not a dashboard. `home` in `App.tsx` is hardcoded to `/patients`. |
| **Any data visualisation** | Zero charting dependencies in `frontend/package.json`. Zero `<svg>` charts. 13 registered reports in `apps/reporting/registry.py` render as tables only. |
| **Role & permission management UI** | Backend has `Role` with inheritance, `permissions` JSON, `max_scope`, `grantable_roles`, `PermissionOverride`, segregation-of-duties conflicts, break-glass. The API exposes exactly one read: `RoleListView` (GET). **No role can be created or edited through any client.** |
| **A linkable profile** | Corrected after a closer read: `People.tsx` *does* have an employee profile — record, credentials, history, pay, practice status. It is component state, not a route, so it cannot be linked, bookmarked or reached from anywhere else, and it shows nothing about what the person may *do*. A patient record page does not exist at all. |
| **Card / board / calendar views** | Every list in the product is a `<Table>`. 34 of 44 pages render one directly. |
| **Org identity in the shell** | The header is a lucide `Activity` icon and the word "Nirova". A customer never sees their own name or mark anywhere except a text label. |
| **Onboarding / first-run** | §6 has the wizard unbuilt. A new tenant lands on an empty patient list with no next step. |

### Built and used by nothing — the more embarrassing category

| | Evidence |
|---|---|
| `SegmentedControl` | `components/ui/data.tsx:256`. **Zero usages.** The exact component a table/card view switch needs. |
| `Timeline` / `TimelineItem` | `data.tsx:324`. **Zero usages.** The exact component a patient record needs. |
| `@radix-ui/react-tabs` | Installed. **Zero imports.** Meanwhile **17 pages hand-roll their own tab strip**, each with its own `type Tab` and `const TABS`. |
| `@radix-ui/react-dialog`, `-select`, `-progress`, `-label` | Installed, unused. Four accessible primitives paid for and reimplemented by hand. |
| `landing` preference | Declared in `apps/identity/preferences.py:59`, offered as a control on My account (which renders the server's catalogue), saved to the user row — and **read by nothing**. `App.tsx` computed its home as `isPlatformOnly ? "/platform" : "/patients"` and never consulted it, so anybody who set it watched their choice be stored and ignored. Worse than the preference not existing. |
| `can()` | Exposed by `useSession` since it was written. **6 of 44 pages call it.** Every other screen offers every action to everybody and lets the API refuse. |

### Consistency, measured

- `PageHeader`: **34 of 44** pages. Nine still hand-roll an `<h1>`.
- `EmptyState`: **7 of 44**. The other 37 show an empty table, which reads as a failure.
- Skeletons: **7 of 44**. The rest show `Loader2` spinners or nothing.
- `tabular-nums`: **25 of 44**. Money and counts jitter on the other 19.
- **325 hardcoded colour utilities** across 29 files (`text-amber-600`, `bg-red-50`, `border-emerald-500/40`, …) bypassing the token system. **Only 48 of them carry a `dark:` counterpart**, so 277 are light-mode-only: most of the product's semantic colour is invisible or wrong in dark mode, and dark mode was only wired up recently, so nobody has looked.

### The theme

`index.css` is the shadcn/ui starter palette with `--primary` swapped to teal
(`175 84% 24%`) and a considered dark ramp. The dark theme's reasoning is
genuinely good and documented. But:

- One accent colour, and it means "this is a button". Colour carries **no
  clinical meaning** anywhere in the system.
- Neutrals are shadcn's blue-tinted slate in light mode and pure neutral grey
  in dark. The two themes are not the same design.
- No type scale, no elevation scale, no spacing scale beyond Tailwind's
  defaults. `--radius: 0.6rem` is the only shape decision in the product.
- No typeface. The system font stack, at every size, everywhere.

**This is the specific reason it "looks AI generated": it is the unmodified
default of the most common component library, and defaults are what a generator
produces.** The fix is not decoration. It is having opinions and applying them
to 44 screens.

---

## Part 1 — Theme: a design language, not a palette swap

### 1.1 Three-tier tokens

Today `index.css` declares 20 semantic variables directly. There is no
primitive layer, so "make the teal slightly warmer" is 20 edits and a guess.
Replace with:

```
tokens/primitive.css   – ramps only. brand-50..950, neutral-0..1000,
                         and clinical ramps (see 1.3). No component knows these.
tokens/semantic.css    – the shadcn contract (--background, --primary, …)
                         plus new ones, defined *in terms of* primitives.
                         Light and dark are two mappings of one ramp set.
tokens/component.css   – where a component needs its own knob:
                         --sidebar-bg, --header-height, --row-padding-y.
```

Everything downstream keeps working — the semantic names are unchanged, so
Tailwind config and every existing class survive. This is a refactor with a
zero-diff first commit, then the values change.

### 1.2 Neutrals with a temperature

Move light-mode surfaces off blue-slate onto a **very slightly warm neutral**
(hue ~40, saturation 4–6%). Two reasons, one aesthetic and one practical: warm
greys are what considered products use and cool greys are what defaults use;
and a warm ground makes the teal read as deliberate rather than as the one
colour that survived. Keep dark mode's zero-saturation ramp — the reasoning in
`index.css` is right and OLED-correct — but lift `--background` from `0%` to
`0 0% 4%` for the desktop console while keeping true black for the patient app
and any bedside/mobile surface. Pure black on a monitor at a nurses' station
under fluorescent light produces halation on every border.

### 1.3 Colour that means something clinically

This is the single highest-leverage visual change, and it is the thing that
makes the product look like it was built by people who have been in a hospital.

Define **semantic ramps that map to states the domain actually has**, and then
forbid raw Tailwind colours in `src/pages/`:

| Token family | Means | Where it earns its place |
|---|---|---|
| `--acuity-1 … --acuity-5` | Triage category | Emergency board, ICU, queue. Not "red/amber/green" — the five-step ladder the ED already models. |
| `--vital-normal / -abnormal / -critical` | Observation against reference range | ICU flowsheet, nurse workspace, diagnostics. |
| `--stock-ok / -low / -expiring / -expired` | Batch state | Pharmacy, stockroom, procurement. Expiring and expired must be *different*, which `text-amber-600` for both cannot express. |
| `--money-in / -out / -owed / -overdue` | Ledger direction and ageing | Finance, billing, claims, payables. |
| `--status-draft / -pending / -approved / -rejected / -void` | Workflow state | Everywhere. This alone replaces most of the 325 hardcoded utilities. |

Each defined in both themes, each contrast-checked against its own surface.
The pass that introduces these is also the pass that **fixes dark mode across
277 light-mode-only sites**, so it pays for itself twice.

### 1.4 Type

Add two faces, self-hosted, subset:

- **UI / headings** — a geometric-humanist sans with real character at small
  sizes and a proper tabular figure set. Recommendation: *Inter* is the safe
  choice and also the "AI default" choice; prefer **Geist**, **Public Sans**,
  or **Söhne** if budget allows. The distinguishing requirement is that the
  digits be tabular by default, because this product is 60% numbers.
- **Data / code** — a monospace for identifiers: MRN, batch number, invoice
  number, UUID. Anywhere a human reads a code back to another human, it should
  be monospace. That single rule makes a screen look like a hospital system
  rather than a website.

Then a named type scale (`display / title / heading / body / label / caption /
mono`) as component classes, not ad-hoc `text-2xl` per page.

### 1.5 Shape, elevation, motion

- One radius scale, with **cards larger than controls** (currently everything
  is `0.6rem`). Cards 10px, controls 6px, chips full.
- Elevation as tokens, not `shadow-sm` sprinkled: `--elevation-flat` (border
  only), `-raised` (card), `-floating` (popover), `-modal`. In dark mode
  elevation is lightness, not shadow — the token indirection is what lets that
  be true without every component knowing.
- Motion is already well-specified in `tailwind.config.js` and used almost
  nowhere. Adopt it: row hover, panel slide, tab underline, number ticks.

### 1.6 A mark

`Activity` from lucide is a placeholder that has been shipping for nine months.
Nirova needs an actual wordmark and glyph, and — critically — a **slot for the
customer's**. See 3.2.

---

## Part 2 — Consistency: make the system unavoidable

The design system exists and is bypassed. Components alone will not fix that;
the bypass has to become harder than the compliance.

### 2.1 Missing primitives to build

| Component | Replaces |
|---|---|
| `<Tabs>` on `@radix-ui/react-tabs` | 17 hand-rolled tab strips, with URL sync (`?tab=`) so a tab is linkable — today they are not. |
| `<DataView>` | The core one. Takes columns + rows and renders **table, card grid, or board** with `SegmentedControl` switching between them, remembering the choice per user per screen. This is "no card view", solved once instead of 34 times. |
| `<FilterBar>` | Search + facets + date range + saved views, in `Toolbar`'s left slot. |
| `<RecordPage>` | Header + identity block + tab set + right rail. The shape every `:uuid` route needs and none has. |
| `<Chart.*>` | See Part 4.1. |
| `<Can>` / `useCan` | Wraps an action in its permission. Named in §130 as outstanding; blocks the 38-page pass. |
| `<StatusBadge>` | Takes a domain status, emits the right semantic token. The thing that makes 1.3 actually get used. |

### 2.2 Enforcement

- **ESLint rule** banning raw colour utilities in `src/pages/**` (allow in
  `src/components/ui/**`). Turns 325 violations into a burn-down list.
- **A page-shape test** in the existing sweep style: every route renders
  `Page` + `PageHeader`, every list renders an `EmptyState` when empty and a
  `Skeleton` when loading. This codebase's culture is guard-tests; this is one.
- **Storybook** (or a `/kitchen-sink` route behind a platform flag) so the
  system can be reviewed in both themes at three widths without clicking
  through 44 screens. Every dark-mode defect above exists because there is
  nowhere to see them all at once.

### 2.3 The migration pass

44 screens, done in the order §130 already names — flattest first. Each screen
gets: `Page`/`PageHeader`, `DataView` where it lists, `EmptyState`,
`Skeleton`, `Tabs` if tabbed, `<Can>` on every action, tokens for every
colour. Budget ~2 hours per simple screen, ~1 day for the six 1,500+ line
monsters (`Icu`, `NurseWorkspace`, `Emergency`, `Counter`, `People`, `Wards`).

---

## Part 3 — Personalization: the ownership feeling

"No portal ownership feeling" is the sharpest thing in the brief and the least
addressed by the checklist. Ownership comes from four things.

### 3.1 A home that is shaped like your job

Seventeen roles exist (`apps/rbac/services.py`). Every one of them lands on
`/patients`. Build `/` as a **role home**, resolved in this order:

1. The user's `landing` preference, if set — **connecting the preference that
   already exists and does nothing.**
2. Otherwise a role-derived default: doctor → clinic day; nurse → her ward;
   pharmacist → dispensing + expiry; receptionist → queue + arrivals;
   accountant → cash position; medical director → facility overview; platform
   staff → console (already correct).

The home is composed of **widgets**, each declaring its permission, so a home
is assembled from what you may see rather than being a fixed page per role.
Users can add, remove and reorder them; the layout is stored beside the other
preferences.

### 3.2 The customer's identity, not ours

- Organization logo upload; shown in the header, on invoices, on portal, on
  printed documents.
- An accent colour per organization, constrained to a set that passes contrast
  against both themes — a picker that lets a hospital choose an unreadable
  brand pink is a support ticket generator.
- Facility name and the **current facility switcher** in the shell. Today the
  header switches *organizations*; a three-hospital customer has no visible
  sense of which building they are in.
- Configurable product name for resellers. §2 already scopes white-label
  commercially; this is the surface of it.

### 3.3 The person, visible

- Real avatars with upload (§59 has "Photograph upload and storage" open) with
  initials fallback — `Avatar` already handles this and is used on two screens.
- `/people/:uuid` — a colleague's profile: identity, position, department,
  facility, credentials with expiry, roles held and at what scope, current
  shift, contact. Assembled almost entirely from data the API already returns.
- `/patients/:uuid` as a real `RecordPage` with a `Timeline` — the component
  that exists and is used nowhere.

### 3.4 Trails through your own work

- **Command palette** (⌘K) over the existing global search plus navigation and
  actions. Highest ratio of "feels like a serious product" to effort in this
  entire document.
- **Pinned screens** in the sidebar above the groups.
- **Recently viewed** patients/records, per user.
- **Saved views** — a filtered list, named and kept. Turns a generic table into
  "my Tuesday clinic".

### 3.5 Sidebar

The grouping complaint is half-right: `NAV_GROUPS` *is* grouped into ten
labelled groups, and the reasoning in `App.tsx` is sound. What is missing is
that it **looks** like an undifferentiated list — no icons for groups, no
collapse, no pins, no counts, uniform weight throughout, and ten groups is
still a lot of scrolling at 44 items. Fix visually and behaviourally:
collapsible groups, persisted per user; badge counts on Workspace and
Notifications; pinned section on top; a visible facility/org block at the head
of the rail rather than in the far header.

---

## Part 4 — Feature enrichment

### 4.1 Dashboards and visualisation

Pick **Recharts** (or visx if we want full control; not Chart.js — canvas
fights theming). Wrap it in a `Chart.*` layer bound to the tokens so no page
ever names a colour. Series colours come from a categorical ramp validated for
both themes and for the two commonest colour-vision deficiencies — in a
clinical product, colour-only encoding of a critical value is a safety issue,
so every chart pairs colour with shape, position or a label.

**Seven dashboards, in this order:**

1. **Facility overview** (medical director, operations manager) — census,
   occupancy by ward, ED load, theatre utilisation, revenue today vs. average,
   staff on duty. Most of this is `apps/*/summary/` endpoints that already
   exist and no screen calls.
2. **Clinic day** (doctor) — today's list, waiting, results to acknowledge,
   prescriptions to sign.
3. **Ward** (nurse) — beds, due medications, observations overdue, handover.
   `NurseWorkspaceSummaryView` exists.
4. **Cash position** (accountant, controller) — receivables ageing, collections,
   payables due, till status. Three of the 13 registered reports.
5. **Pharmacy** — stock value, expiring in 30/60/90, out of stock, top movers.
6. **Revenue cycle** — claims by status, denial reasons, days in AR.
7. **Platform executive** — §3 is half-built as numbers; give it the trend
   lines it is missing (MRR movement, retention, cohorts).

Every dashboard tile links to the screen that can act on it, and states
staleness — a KPI without an as-of time is a guess.

**Non-dashboard visualisation that matters more than charts:**
occupancy floor plan (wards), theatre Gantt, roster calendar, ED triage board
as a real board, ICU flowsheet as a proper time grid, Levey-Jennings for lab QC
(§34, already listed), org chart (§60, listed twice and built neither time).

### 4.2 Roles and permissions studio

Backend depth here is one of the product's genuine differentiators and it is
invisible. Build `/access` with four tabs:

- **Roles** — list with holder counts; create, clone, edit. Inheritance shown
  as a tree.
- **Permission matrix** — roles × permission catalogue, grouped by module, with
  inherited vs. direct distinguished. Editable where you have authority; a
  permission you cannot grant is shown disabled with the reason
  (`beyond_your_authority` is already computed by `RoleSerializer` and never
  rendered).
- **People** — merge `Staff.tsx` here: assign, scope, time-bound, revoke.
- **Exceptions** — `PermissionOverride` grants and denials, break-glass grants
  and their review queue (`/privacy` folds in here).

Backend work required: role create/update/delete endpoints and a permission
catalogue endpoint. Both are small; the models are done. **Segregation-of-duty
conflicts must be surfaced at edit time** — the service refuses them already,
and a form that only learns this on submit is a form people fight.

### 4.3 User management

`Staff.tsx` covers invite / edit / roles / deactivate and is decent. Missing:
bulk invite, resend invitation, password reset from admin, session listing and
forced logout (§15, open), login history per user, and the activity trail —
`apps/audit` records everything and no screen shows it per person.

### 4.4 List views worth using

Delivered by `DataView` in 2.1, then per screen: card grid for patients, staff,
products, facilities; board for ED triage, theatre list, claims, procurement;
calendar for appointments, roster, theatre schedule. Plus column chooser,
sticky headers, row density honouring the existing preference, multi-select
with bulk actions, and CSV/PDF export — the reporting engine already produces
the data.

### 4.5 The first thirty seconds

- **Login**: a 384px card on grey. It is the first thing a client sees and it
  says nothing. Split layout: form left, and right a real statement of what the
  product is, the customer's own branding once the subdomain is known.
- **Onboarding wizard** (§6, open): facility setup, departments, first users,
  services, with a completion meter. A tenant that opens onto an empty patient
  list has been abandoned at the door.
- **Empty states with an action**, everywhere — §130 has this at `[~]` with one
  screen done.

---

## Part 5 — Sequencing

Five waves. Each ends somewhere demonstrable, because a plan whose first
demoable moment is in week nine is a plan that gets abandoned in week four.

### Wave 1 — Foundation *(the theme stops looking generated)*
Three-tier tokens · warm neutrals · clinical semantic ramps · type scale and
webfonts · elevation and radius · wordmark · `Tabs`, `DataView`, `FilterBar`,
`StatusBadge`, `Can` · Storybook/kitchen-sink · the ESLint colour rule.
**Ends with:** the system reviewable in both themes; nothing shipped to a user
yet.

### Wave 2 — The shell *(it starts feeling like theirs)*
New sidebar with collapse, pins, counts and a facility block · header with org
logo and facility switcher · command palette · redesigned login · avatars ·
`landing` preference connected and a control for it.
**Ends with:** a demo that opens well. This is the first pitchable moment.

### Wave 3 — Dashboards *(it tells you something)*
`Chart.*` layer · role home with widgets · facility overview, clinic day, ward,
cash position. Wire the summary endpoints that already exist.
**Ends with:** the demo that closes deals. Prioritise this wave over Wave 4 if
a pitch is imminent.

### Wave 4 — Access & identity *(it looks enterprise)*
`/access` studio with the permission matrix · role CRUD endpoints ·
`/people/:uuid` and `/patients/:uuid` as `RecordPage` · user management gaps ·
audit trail per person.
**Ends with:** the security conversation that every hospital procurement has.

### Wave 5 — The long pass *(it holds together)*
All 44 screens migrated · card/board/calendar views per screen · remaining
dashboards · saved views · export · empty states · the tablet-width pass §130
already names.
**Ends with:** consistency, which is the only one of these that cannot be
faked and is the reason the product currently reads as thirty-four small
applications.

---

## Part 6 — The brand direction, decided

This was the one genuinely open question: whether Nirova is *clinical and calm*
(deep teal, warm neutrals, restrained), *modern and sharp* (near-black chrome,
one vivid accent, dense), or *warm and human* (softer palette, illustration,
more space).

**Built as clinical-and-calm with the density of modern-and-sharp.** Deep teal
brand, warm neutral surfaces, a distinct chrome surface for the rail and
header, tight vertical rhythm, tabular figures and monospace identifiers. The
reasoning: a hospital procurement committee and a private group's medical
director are both in the room, and restraint reads as trustworthy to the first
without reading as dated to the second. Illustration and space were the wrong
trade for a product whose main screens are dense lists read across a room.

**It is one file to change.** `styles/tokens/primitive.css` holds the ramps and
nothing else; `semantic.css` maps them to roles. Swapping the brand ramp
re-themes the entire console, the charts included, without touching a
component — that indirection is the point of Part 1, and the guard in
`test_design_tokens.py` keeps it true by failing any component that names a
primitive directly.

The remaining decisions are smaller and are yours when you get to them: whether
a customer may pick their own accent (the model already has
`Organization.primary_color`), and how far the white-label goes for resellers.

---

## Part 7 — What this adds to the checklist

`docs/IMPLEMENTATION_CHECKLIST.md` should gain these as tracked lines, because
none of them exist there today and the checklist's own preamble says a
capability that is not a line is not scoped:

- **§130 Console experience** — extend with: design tokens; clinical colour
  semantics; typography; card/board/calendar views; command palette; saved
  views; pinned navigation; role home; dark-mode correctness across 325 sites.
- **A new §133 Visualisation and dashboards** — the seven dashboards, the chart
  layer, the non-chart visualisations. Currently the word "dashboard" appears
  once in 3,300 lines of checklist, and "chart" only ever means a patient's.
- **§16 RBAC** — add the administration surface. The engine is `[~]` and the UI
  is not a line at all.
- **§15 Identity** — add profiles, avatars, session management UI.
- **§2 / §13** — add white-label and organization branding as a customer-facing
  surface rather than only a commercial term.

The current count reads 33 of 132 sections done. None of the above is inside
that denominator, which is why the checklist can look reasonable while the
product does not.
