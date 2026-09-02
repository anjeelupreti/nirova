# ADR 0002 — Identity lives in the control plane

**Status.** Accepted · 2026-09-02
**Related.** [ADR 0001 — One database per tenant](0001-database-per-tenant.md)

## Context

ADR 0001 puts each customer's data in its own database. That raises an
immediate question with no comfortable answer: **where do user accounts go?**

The tension is real in both directions.

- Putting users in tenant databases is the pure reading of ADR 0001 — a user
  is a customer's data, so it belongs in the customer's database.
- But authentication happens *before* any tenant is known. A person types an
  email and a password. To look them up in their organization's database, you
  must first know their organization — which you learn by looking them up.

That circularity has to be broken somewhere.

## Options considered

### A. Users in tenant databases, with a control-plane routing index

A small control-plane table maps `email → organization`, used only at login to
choose which tenant database to authenticate against.

- **For:** full user records stay in the tenant database.
- **Against:** the routing index *already contains every user's email address*
  in a shared table — which is the main thing this option was trying to avoid.
  It buys very little privacy while making every login two hops, and it makes
  a person who works for two organizations in a group into two accounts with
  two passwords.

### B. Users in the control plane  ← chosen

One `User` table in the control plane. A `Membership` links a user to each
organization they may act within. Roles and role assignments stay in the
tenant database.

- **For:**
  - Login resolves in one place, with no bootstrap problem.
  - One person, one account, several organizations — which is how healthcare
    groups actually work: a consultant covering two hospitals in the same
    group, a shared finance team, a locum.
  - SSO, MFA, device management, password policy and lockout are genuinely
    platform-level concerns. Implementing them once beats implementing them per
    tenant.
- **Against:** names and email addresses of every customer's staff sit in a
  shared database. That is a real reduction in isolation and is stated plainly
  rather than glossed over.

### C. An external identity provider

Delegate to Keycloak, Auth0 or similar.

- **For:** proper SSO, someone else's problem to secure.
- **Against:** an additional service to run and pay for, in a market where many
  customers are cost-sensitive and some sites have unreliable connectivity.
  Not ruled out later — option B does not preclude it, since `User` can become
  a shadow of an external subject.

## Decision

**Identity in the control plane; authorization in the tenant database.**

| Concept | Database | Why |
|---|---|---|
| `User` | control plane | Login must resolve before a tenant is known |
| `Membership` | control plane | Links a user to each organization; what a seat licence counts |
| `LoginAttempt`, `UserDevice` | control plane | Security signals that span organizations |
| `Role`, `RoleAssignment` | tenant | Roles are per-customer data, scoped to that customer's facilities |
| `PermissionOverride` | tenant | Same |
| `AuditEvent` | tenant | Records who read which patient's file — itself identifiable |

The seam is `RoleAssignment.user_id`: a bare `UUIDField`, because Django cannot
enforce a foreign key across databases. `user_email` is denormalised beside it
so listing assignments needs no cross-database lookup.

## The boundary, stated precisely

What leaves the tenant database: **a person's name, email, phone and login
history.**

What never leaves it: **patients, encounters, prescriptions, diagnoses,
clinical notes, stock, invoices, payroll, and the audit log recording who
looked at any of it.**

That line is the whole argument. If a future change proposes moving anything
from the second list into the control plane, it invalidates this ADR and
requires a new one.

## Consequences

- `resolve_authorization()` must run with the tenant context bound, since roles
  live in the tenant database. Calling it without a bound tenant raises rather
  than returning an empty result — an empty permission set is
  indistinguishable from "denied", and would look like a permissions bug.
- Platform staff can technically reach any tenant. That is constrained rather
  than assumed away: `support_access_enabled` is off by default, time-boxed via
  `support_access_expires_at`, and every action taken under it is written to
  the tenant's own audit log with `is_platform_actor = True`. A customer can
  see exactly when the platform entered their data and what it did.
- Deleting a customer does not delete their users' accounts, because those
  accounts may belong to other organizations. Membership revocation is the
  operation that ends access; account deletion is separate and only applies
  when the last membership goes.
