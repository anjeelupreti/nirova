/**
 * Who may do what — the screen for one of this product's real differentiators.
 *
 * **The backend here is genuinely deep and completely invisible.** `Role`
 * carries a permission array, inheritance, a maximum scope, a delegable set and
 * an approval requirement; `RoleAssignment` is time-bounded and scoped down a
 * seven-level ladder; `PermissionOverride` grants and *denies* per user;
 * segregation-of-duties conflicts are declared on permissions and enforced at
 * design time and at approval time. None of it could be seen anywhere.
 *
 * A hospital's procurement process asks two questions about access — "can we
 * see who can do what" and "can we prove it afterwards" — and the honest answer
 * was that the engine could and the product could not show you.
 *
 * **Roles are now writable here**, which is the half that turns a described
 * capability into a real one. `POST`/`PATCH`/`DELETE /admin/roles/` and
 * `GET /admin/permissions/` were written for this screen; before them every
 * role in every Nirova database came from a seed, and "roles should be
 * configurable" was true of us and of nobody else.
 *
 * Three rules the API enforces and this screen surfaces *before* submit,
 * because each of them is a refusal somebody would otherwise discover after
 * two minutes of work:
 *
 *  - **Segregation of duties.** A conflicting pair is named as it is ticked.
 *  - **You cannot create authority you do not hold.** Otherwise `role.manage`
 *    is a privilege-escalation primitive; the permissions outside your own are
 *    disabled with the reason rather than hidden.
 *  - **A system role cannot be retired, and neither can one somebody holds.**
 *    The message says how many hold it, because "revoke it from four people
 *    first" is actionable and "could not delete" is not.
 */

import * as React from "react";
import { Link } from "react-router-dom";

import api, { ApiError } from "@/lib/api";
import { cn } from "@/lib/utils";
import { useCan } from "@/components/ui/can";
import { useSession } from "@/hooks/useSession";
import { Icon } from "@/components/ui/icon";
import { Page, PageHeader, Section, StatGrid } from "@/components/ui/layout";
import { TabbedSection } from "@/components/ui/tabs";
import { Button, Card, CardContent, Input } from "@/components/ui/primitives";
import { DataView, type Column } from "@/components/ui/dataview";
import { EmptyState, ErrorState, TableSkeleton } from "@/components/ui/feedback";
import { StatusBadge } from "@/components/ui/status";
import { Chart } from "@/components/charts";
import {
  RoleEditor,
  type PermissionCatalogue,
  type Role,
} from "@/components/access/RoleEditor";

/* -------------------------------------------------------------------------- */
/* Types                                                                       */
/* -------------------------------------------------------------------------- */

interface AssignedRole {
  uuid: string;
  role_code: string;
  role_name: string;
  scope: string;
  scope_label: string;
  facility_name: string;
  department_name: string;
  status: string;
  valid_until: string | null;
}

interface StaffMember {
  uuid: string;
  email: string;
  full_name: string;
  status: string;
  is_organization_owner: boolean;
  roles: AssignedRole[];
}

/**
 * The seven-level scope ladder, narrowest first.
 *
 * Shown as a ladder rather than as a word because "department" means nothing
 * on its own — what a reader needs is where it sits relative to "facility",
 * and that is a position, not a label.
 */
const SCOPES = [
  "own",
  "own_patients",
  "unit",
  "department",
  "facility",
  "multi_facility",
  "organization",
] as const;

const SCOPE_LABEL: Record<string, string> = {
  own: "Own records",
  own_patients: "Own patients",
  unit: "Unit",
  department: "Department",
  facility: "Facility",
  multi_facility: "Several facilities",
  organization: "Whole organization",
};

/**
 * Which module a permission belongs to.
 *
 * **The fallback, not the source of truth.** `GET /admin/permissions/` now
 * serves the group each permission was *declared* in, and that is what the
 * screen uses. This remains for the case where that request failed: a broken
 * catalogue should degrade the grouping, not empty the screen. Parsing a
 * prefix gets `patient.clinical.read` into "Patients" by luck and would get a
 * new module wrong, which is exactly why it is second choice.
 */
function moduleOf(permission: string): string {
  const [head] = permission.split(".");
  const NAMES: Record<string, string> = {
    patient: "Patients",
    encounter: "Encounters",
    prescription: "Prescriptions",
    diagnostic: "Diagnostics",
    lab: "Laboratory",
    blood: "Blood bank",
    referral: "Referrals",
    stock: "Stock",
    catalog: "Catalogue",
    purchase: "Procurement",
    sale: "Counter",
    invoice: "Billing",
    finance: "Finance",
    salary: "Payroll",
    employee: "People",
    attendance: "Attendance",
    leave: "Leave",
    user: "Access",
    role: "Access",
    config: "Configuration",
    facility: "Facilities",
    department: "Facilities",
    subscription: "Subscription",
    report: "Reporting",
    privacy: "Privacy",
    document: "Documents",
    data: "Data",
    theatre: "Theatre",
    icu: "Critical care",
    ward: "Wards",
    notification: "Notifications",
  };
  return NAMES[head] ?? (head ? head[0].toUpperCase() + head.slice(1) : "Other");
}

/* -------------------------------------------------------------------------- */
/* Page                                                                        */
/* -------------------------------------------------------------------------- */

export default function AccessPage() {
  const can = useCan();
  const { session } = useSession();
  const [roles, setRoles] = React.useState<Role[] | null>(null);
  const [catalogue, setCatalogue] = React.useState<PermissionCatalogue | null>(null);
  const [staff, setStaff] = React.useState<StaffMember[] | null>(null);
  const [error, setError] = React.useState<string | null>(null);
  const [loading, setLoading] = React.useState(true);

  /*
    `role.read`, which is what `RoleListView` asks for.

    The first version of this line was `can("role.assign") || can("user.read")`
    — reasoned about rather than derived, and wrong in both directions: it let
    in anybody with `user.read` (who is then refused by the API) and it would
    have kept out somebody holding `role.read` alone. The staff list is
    secondary here and is allowed to fail on its own; see `load`.
  */
  const mayReadRoles = can("role.read", "own");
  const mayManageRoles = can("role.manage", "own");

  /*
    What the caller holds, as a set.

    `authorization.permissions` is a map of code to grant; the editor only
    needs membership, and building the set once here keeps the per-checkbox
    lookup O(1) across a catalogue of a couple of hundred.
  */
  const yourPermissions = React.useMemo(
    () => new Set(Object.keys(session?.authorization?.permissions ?? {})),
    [session],
  );
  const isOwner = Boolean(session?.authorization?.is_organization_owner);

  const load = React.useCallback(async () => {
    setLoading(true);
    try {
      const [roleList, staffList, catalogueResponse] = await Promise.all([
        api.get<Role[]>("/admin/roles/"),
        api
          .get<{ results?: StaffMember[] } | StaffMember[]>("/admin/staff/")
          .catch(() => [] as StaffMember[]),
        // The permission catalogue. `grouped_permissions()` has existed in
        // Python since the catalogue was written, with the docstring "for
        // rendering the role editor", and had no endpoint until now — so this
        // screen grouped permissions by parsing the code prefix, which is a
        // stand-in that gets a new module wrong.
        api
          .get<PermissionCatalogue>("/admin/permissions/")
          .catch(() => null),
      ]);
      setRoles(roleList);
      setCatalogue(catalogueResponse);
      setStaff(Array.isArray(staffList) ? staffList : (staffList.results ?? []));
      setError(null);
    } catch (problem) {
      setError(
        problem instanceof ApiError
          ? problem.message
          : "Roles could not be read.",
      );
    } finally {
      setLoading(false);
    }
  }, []);

  React.useEffect(() => {
    if (mayReadRoles) void load();
    else setLoading(false);
  }, [load, mayReadRoles]);

  /*
    How many people hold each role, tallied from the staff list.

    Above the permission check rather than below it: a hook after an early
    return is a hook that runs on some renders and not others, and React's
    order-based hook identity does not survive that. The permission gate lives
    underneath.
  */
  const holders = React.useMemo(() => {
    const tally = new Map<string, number>();
    for (const member of staff ?? []) {
      for (const role of member.roles) {
        if (role.status !== "active") continue;
        tally.set(role.role_code, (tally.get(role.role_code) ?? 0) + 1);
      }
    }
    return tally;
  }, [staff]);

  if (!mayReadRoles) {
    return (
      <Page>
        <PageHeader title="Access" />
        <EmptyState
          title="This screen is not part of your role"
          description="Administering who may do what needs user.read or role.assign. Nothing is broken — ask an administrator if you need it."
        />
      </Page>
    );
  }

  return (
    <Page>
      <PageHeader
        title="Access"
        description="Roles, what each one carries, and who holds them. Every permission here is enforced by the API — this screen shows what it will decide, it does not decide it."
        breadcrumbs={[{ label: "Organization" }, { label: "Access" }]}
        actions={
          <Button variant="outline" size="sm" onClick={() => void load()}>
            <Icon name="refresh" size="sm" className="mr-1.5" />
            Refresh
          </Button>
        }
      />

      {error ? (
        <ErrorState
          title="Roles could not be read"
          description={error}
          onRetry={() => void load()}
        />
      ) : (
        <TabbedSection
          tabs={[
            { id: "roles", label: "Roles", icon: "role", count: roles?.length ?? null },
            { id: "matrix", label: "Permission matrix", icon: "permission" },
            { id: "people", label: "People", icon: "staff", count: staff?.length ?? null },
            { id: "scopes", label: "Scopes", icon: "capacity" },
          ]}
        >
          {{
            roles: (
              <RolesTab
                roles={roles}
                holders={holders}
                loading={loading}
                catalogue={catalogue}
                yourPermissions={yourPermissions}
                isOwner={isOwner}
                mayManage={mayManageRoles}
                onChanged={() => void load()}
              />
            ),
            matrix: (
              <MatrixTab roles={roles} loading={loading} catalogue={catalogue} />
            ),
            people: <PeopleTab staff={staff} loading={loading} />,
            scopes: <ScopesTab roles={roles} />,
          }}
        </TabbedSection>
      )}
    </Page>
  );
}

/* -------------------------------------------------------------------------- */
/* Roles                                                                       */
/* -------------------------------------------------------------------------- */

function RolesTab({
  roles,
  holders,
  loading,
  catalogue,
  yourPermissions,
  isOwner,
  mayManage,
  onChanged,
}: {
  roles: Role[] | null;
  holders: Map<string, number>;
  loading: boolean;
  catalogue: PermissionCatalogue | null;
  yourPermissions: Set<string>;
  isOwner: boolean;
  mayManage: boolean;
  onChanged: () => void;
}) {
  const [selected, setSelected] = React.useState<Role | null>(null);
  /** `null` = closed, `"new"` = creating, a Role = editing that one. */
  const [editing, setEditing] = React.useState<Role | "new" | null>(null);

  const columns: Column<Role>[] = [
    {
      key: "name",
      header: "Role",
      value: (role) => role.name,
      cell: (role) => (
        <div className="min-w-0">
          <p className="truncate font-medium">{role.name}</p>
          <p className="truncate type-code text-xs text-muted-foreground">{role.code}</p>
        </div>
      ),
    },
    {
      key: "permissions",
      header: "Permissions",
      numeric: true,
      value: (role) => role.permission_count,
      cell: (role) => role.permission_count,
    },
    {
      key: "holders",
      header: "Held by",
      numeric: true,
      value: (role) => holders.get(role.code) ?? 0,
      cell: (role) => {
        const count = holders.get(role.code) ?? 0;
        return (
          <span className={cn(count === 0 && "text-muted-foreground")}>{count}</span>
        );
      },
    },
    {
      key: "scope",
      header: "Ceiling",
      secondary: true,
      value: (role) => SCOPES.indexOf(role.max_scope as (typeof SCOPES)[number]),
      cell: (role) => (
        <span className="type-caption">
          {SCOPE_LABEL[role.max_scope] ?? role.max_scope}
        </span>
      ),
    },
    {
      key: "grantable",
      header: "You may grant",
      align: "right",
      value: (role) => (role.grantable ? "yes" : "no"),
      cell: (role) =>
        role.grantable ? (
          <StatusBadge status="approved" label="Yes" />
        ) : (
          <StatusBadge status="on hold" label="Beyond you" icon="permission" />
        ),
    },
  ];

  if (editing && catalogue) {
    return (
      <RoleEditor
        role={editing === "new" ? null : editing}
        catalogue={catalogue}
        yourPermissions={yourPermissions}
        isOwner={isOwner}
        onSaved={() => {
          setEditing(null);
          setSelected(null);
          onChanged();
        }}
        onCancel={() => setEditing(null)}
      />
    );
  }

  return (
    <div className="space-y-5">
      {mayManage ? (
        <div className="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-dashed bg-muted/30 px-4 py-3">
          <p className="type-caption">
            {catalogue
              ? "Roles are yours to write. A role cannot carry a permission you do not hold yourself, and conflicting pairs are refused as you tick them."
              : "The permission catalogue could not be read, so roles cannot be edited right now."}
          </p>
          <Button size="sm" disabled={!catalogue} onClick={() => setEditing("new")}>
            <Icon name="add" size="sm" className="mr-1.5" />
            New role
          </Button>
        </div>
      ) : null}

      <StatGrid>
        <Chart.Stat
          label="Roles defined"
          value={roles?.length ?? null}
          icon="role"
          goodDirection="neither"
        />
        <Chart.Stat
          label="You may grant"
          value={roles?.filter((role) => role.grantable).length ?? null}
          icon="confirm"
          goodDirection="neither"
          footnote="the rest carry permissions you do not hold"
        />
        <Chart.Stat
          label="Need approval to assign"
          value={roles?.filter((role) => role.requires_approval_to_assign).length ?? null}
          icon="permission"
          goodDirection="neither"
        />
        <Chart.Stat
          label="Held by nobody"
          value={
            roles?.filter((role) => (holders.get(role.code) ?? 0) === 0).length ?? null
          }
          icon="warning"
          goodDirection="down"
          tone="warning"
          footnote="a role granted to nobody describes an org chart, not a job"
        />
      </StatGrid>

      <DataView
        rows={roles ?? []}
        columns={columns}
        rowKey={(role) => role.uuid}
        storageKey="access.roles"
        loading={loading}
        onOpen={setSelected}
        search={{ placeholder: "Search roles" }}
        empty={{ title: "No roles defined" }}
        card={{
          title: (role) => role.name,
          subtitle: (role) => role.code,
          badge: (role) =>
            role.grantable ? (
              <StatusBadge status="approved" label="Grantable" />
            ) : (
              <StatusBadge status="on hold" label="Beyond you" />
            ),
          facts: (role) => [
            { label: "Permissions", value: role.permission_count },
            { label: "Held by", value: holders.get(role.code) ?? 0 },
            { label: "Ceiling", value: SCOPE_LABEL[role.max_scope] ?? role.max_scope },
            {
              label: "Approval",
              value: role.requires_approval_to_assign ? "Required" : "Not needed",
            },
          ],
        }}
      />

      {selected ? (
        <RoleDetail
          role={selected}
          mayManage={mayManage}
          onEdit={() => setEditing(selected)}
          onDeleted={() => {
            setSelected(null);
            onChanged();
          }}
          onClose={() => setSelected(null)}
        />
      ) : null}
    </div>
  );
}

/** What a role actually carries, grouped by module. */
function RoleDetail({
  role,
  mayManage,
  onEdit,
  onDeleted,
  onClose,
}: {
  role: Role;
  mayManage: boolean;
  onEdit: () => void;
  onDeleted: () => void;
  onClose: () => void;
}) {
  const [retiring, setRetiring] = React.useState(false);
  const [refusal, setRefusal] = React.useState<string | null>(null);

  async function retire() {
    setRetiring(true);
    setRefusal(null);
    try {
      await api.del("/admin/roles/" + role.uuid + "/");
      onDeleted();
    } catch (problem) {
      // The API refuses a system role and a held one, each with a message that
      // says what to do instead. Showing it verbatim is the whole value:
      // "four people hold this, revoke it from them first" is actionable and
      // "could not delete" is not.
      setRefusal(
        problem instanceof ApiError ? problem.message : "That could not be done.",
      );
    } finally {
      setRetiring(false);
    }
  }

  const grouped = React.useMemo(() => {
    const map = new Map<string, string[]>();
    for (const permission of role.permissions) {
      const module = moduleOf(permission);
      map.set(module, [...(map.get(module) ?? []), permission]);
    }
    return [...map.entries()].sort((a, b) => a[0].localeCompare(b[0]));
  }, [role.permissions]);

  return (
    <Card>
      <CardContent className="space-y-4 pt-5">
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0">
            <p className="type-title">{role.name}</p>
            <p className="type-code text-xs text-muted-foreground">{role.code}</p>
            {role.description ? (
              <p className="mt-1.5 max-w-2xl type-caption">{role.description}</p>
            ) : null}
          </div>
          <div className="flex shrink-0 items-center gap-1.5">
            {mayManage && role.editable ? (
              <Button variant="outline" size="sm" onClick={onEdit}>
                <Icon name="edit" size="sm" className="mr-1.5" />
                Edit
              </Button>
            ) : null}
            {mayManage && role.deletable ? (
              <Button
                variant="ghost"
                size="sm"
                className="text-destructive"
                disabled={retiring}
                onClick={() => void retire()}
              >
                <Icon name="remove" size="sm" className="mr-1.5" />
                Retire
              </Button>
            ) : null}
            <Button variant="ghost" size="sm" onClick={onClose}>
              <Icon name="close" size="sm" />
            </Button>
          </div>
        </div>

        {refusal ? (
          <div className="rounded-lg border border-critical/40 bg-critical-subtle/50 p-3">
            <p className="text-sm font-medium text-critical-subtle-foreground">
              Not retired
            </p>
            <p className="mt-0.5 type-caption">{refusal}</p>
          </div>
        ) : null}

        {role.is_system ? (
          <p className="rounded-lg border border-dashed bg-muted/30 p-3 type-caption">
            This role ships with the product. Its permissions are yours to
            change; the role itself cannot be removed, because seeds reference
            it by code and a customer who tidies one away breaks their own next
            migration.
          </p>
        ) : role.holders > 0 ? (
          <p className="rounded-lg border border-dashed bg-muted/30 p-3 type-caption">
            {role.holders} {role.holders === 1 ? "person holds" : "people hold"}{" "}
            this role. It cannot be retired until they no longer do — so that
            each revocation is recorded against the person it affects, rather
            than forty people losing access in one edit.
          </p>
        ) : null}

        {/*
          The reason a role is out of reach, not just the fact.
          `beyond_your_authority` is computed by `RoleSerializer` and had never
          been rendered anywhere. "You cannot grant this" is a dead end;
          "you cannot grant this because it carries payroll.approve" tells
          somebody what to ask their own administrator for.
        */}
        {!role.grantable && role.beyond_your_authority.length > 0 ? (
          <div className="rounded-lg border border-warning/40 bg-warning-subtle/50 p-3">
            <p className="text-sm font-medium text-warning-subtle-foreground">
              You cannot grant this role
            </p>
            <p className="mt-1 type-caption">
              It carries permissions you do not hold yourself:
            </p>
            <div className="mt-2 flex flex-wrap gap-1.5">
              {role.beyond_your_authority.map((permission) => (
                <code
                  key={permission}
                  className="rounded bg-card px-1.5 py-0.5 type-code text-xs"
                >
                  {permission}
                </code>
              ))}
            </div>
          </div>
        ) : null}

        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {grouped.map(([module, permissions]) => (
            <div key={module} className="rounded-lg border p-3">
              <p className="mb-2 type-eyebrow text-muted-foreground">{module}</p>
              <ul className="space-y-1">
                {permissions.sort().map((permission) => (
                  <li key={permission} className="flex items-start gap-1.5">
                    <Icon
                      name={permission.endsWith(".read") ? "view" : "edit"}
                      size="xs"
                      className={cn(
                        "mt-1",
                        permission.endsWith(".read")
                          ? "text-muted-foreground"
                          : "text-warning",
                      )}
                    />
                    <code className="min-w-0 break-all type-code text-xs">
                      {permission}
                    </code>
                  </li>
                ))}
              </ul>
            </div>
          ))}
        </div>

      </CardContent>
    </Card>
  );
}

/* -------------------------------------------------------------------------- */
/* Matrix                                                                      */
/* -------------------------------------------------------------------------- */

/**
 * Roles down, permissions across.
 *
 * **The view a procurement security review asks for and no screen provided.**
 * Reading fifteen role definitions one at a time and holding them in your head
 * is not a review; seeing that four roles carry `invoice.void` in one glance
 * is.
 *
 * Read and write are distinguished by mark, not only by presence: a filled
 * square for a write permission, a hollow one for a read. The row that matters
 * in an audit is always the write row.
 */
function MatrixTab({
  roles,
  loading,
  catalogue,
}: {
  roles: Role[] | null;
  loading: boolean;
  catalogue: PermissionCatalogue | null;
}) {
  const [filter, setFilter] = React.useState("");
  const [onlyWrites, setOnlyWrites] = React.useState(false);

  /*
    The declared group for each code, from the catalogue endpoint. Falls back
    to `moduleOf` per code, so a failed catalogue request costs the grouping
    its accuracy rather than costing the screen its rows.
  */
  const groupOf = React.useMemo(() => {
    const map = new Map<string, string>();
    for (const group of catalogue?.groups ?? []) {
      for (const permission of group.permissions) map.set(permission.code, group.group);
    }
    return (code: string) => map.get(code) ?? moduleOf(code);
  }, [catalogue]);

  const { modules, permissions } = React.useMemo(() => {
    const all = new Set<string>();
    for (const role of roles ?? []) for (const permission of role.permissions) all.add(permission);
    let list = [...all].sort();
    if (onlyWrites) list = list.filter((permission) => !permission.endsWith(".read"));
    if (filter.trim()) {
      const needle = filter.trim().toLowerCase();
      list = list.filter((permission) => permission.toLowerCase().includes(needle));
    }
    const grouped = new Map<string, string[]>();
    for (const permission of list) {
      const module = groupOf(permission);
      grouped.set(module, [...(grouped.get(module) ?? []), permission]);
    }
    return {
      modules: [...grouped.entries()].sort((a, b) => a[0].localeCompare(b[0])),
      permissions: list,
    };
  }, [roles, filter, onlyWrites, groupOf]);

  if (loading) return <TableSkeleton rows={10} columns={6} />;
  if (!roles?.length) return <EmptyState title="No roles to compare" />;

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-3">
        <div className="relative w-full sm:w-72">
          <Icon
            name="search"
            size="sm"
            className="pointer-events-none absolute left-2.5 top-1/2 -translate-y-1/2 text-muted-foreground"
          />
          <Input
            value={filter}
            onChange={(event) => setFilter(event.target.value)}
            placeholder="Filter permissions"
            className="pl-8"
          />
        </div>
        <label className="flex cursor-pointer items-center gap-2 text-sm">
          <input
            type="checkbox"
            checked={onlyWrites}
            onChange={(event) => setOnlyWrites(event.target.checked)}
            className="h-4 w-4 rounded border-input accent-[hsl(var(--primary))]"
          />
          Writes only
        </label>
        <span className="type-caption tabular-nums">
          {permissions.length} permissions × {roles.length} roles
        </span>
      </div>

      <div className="overflow-auto rounded-lg border bg-card">
        <table className="w-full border-collapse text-sm">
          <thead className="sticky top-0 z-10 bg-card">
            <tr>
              <th
                scope="col"
                className="sticky left-0 z-20 min-w-[16rem] border-b border-r border-border-strong bg-card px-3 py-2 text-left type-label text-muted-foreground"
              >
                Permission
              </th>
              {roles.map((role) => (
                <th
                  key={role.uuid}
                  scope="col"
                  className="border-b border-border-strong px-1 py-2 align-bottom"
                  title={`${role.name} — ${role.permission_count} permissions`}
                >
                  {/*
                    Vertical role names. Fifteen columns of horizontal text
                    would make the table four screens wide; rotated, the whole
                    matrix fits and stays scannable, which is the only way this
                    view is worth having.
                  */}
                  <span className="mx-auto block h-28 w-5 [writing-mode:vertical-rl] rotate-180 truncate text-left text-xs font-medium">
                    {role.name}
                  </span>
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {modules.map(([module, entries]) => (
              <React.Fragment key={module}>
                <tr>
                  <th
                    scope="colgroup"
                    colSpan={roles.length + 1}
                    className="sticky left-0 bg-muted/60 px-3 py-1 text-left type-eyebrow text-muted-foreground"
                  >
                    {module}
                  </th>
                </tr>
                {entries.map((permission) => {
                  const isWrite = !permission.endsWith(".read");
                  return (
                    <tr key={permission} className="border-b last:border-0">
                      <th
                        scope="row"
                        className="sticky left-0 z-10 border-r bg-card px-3 py-1.5 text-left font-normal"
                      >
                        <code className="type-code text-xs">{permission}</code>
                      </th>
                      {roles.map((role) => {
                        const held = role.permissions.includes(permission);
                        return (
                          <td
                            key={role.uuid}
                            className="px-1 py-1.5 text-center"
                            title={
                              held
                                ? `${role.name} holds ${permission}`
                                : `${role.name} does not hold ${permission}`
                            }
                          >
                            {held ? (
                              <span
                                aria-label="held"
                                className={cn(
                                  "mx-auto block h-2.5 w-2.5 rounded-[2px]",
                                  isWrite
                                    ? "bg-warning"
                                    : "border-[1.5px] border-primary bg-transparent",
                                )}
                              />
                            ) : (
                              <span className="sr-only">not held</span>
                            )}
                          </td>
                        );
                      })}
                    </tr>
                  );
                })}
              </React.Fragment>
            ))}
          </tbody>
        </table>
      </div>

      <div className="flex flex-wrap items-center gap-5 type-caption">
        <span className="flex items-center gap-1.5">
          <span className="h-2.5 w-2.5 rounded-[2px] border-[1.5px] border-primary" />
          read
        </span>
        <span className="flex items-center gap-1.5">
          <span className="h-2.5 w-2.5 rounded-[2px] bg-warning" />
          write — the row that matters in an audit
        </span>
        <span>Blank means the role does not carry it.</span>
      </div>
    </div>
  );
}

/* -------------------------------------------------------------------------- */
/* People                                                                      */
/* -------------------------------------------------------------------------- */

function PeopleTab({ staff, loading }: { staff: StaffMember[] | null; loading: boolean }) {
  const columns: Column<StaffMember>[] = [
    {
      key: "name",
      header: "Person",
      value: (member) => member.full_name || member.email,
      cell: (member) => (
        <div className="min-w-0">
          <p className="truncate font-medium">{member.full_name || "—"}</p>
          <p className="truncate type-caption">{member.email}</p>
        </div>
      ),
    },
    {
      key: "roles",
      header: "Roles",
      value: (member) => member.roles.map((role) => role.role_name).join(" "),
      cell: (member) =>
        member.roles.filter((role) => role.status === "active").length === 0 ? (
          <span className="type-caption">No active role</span>
        ) : (
          <div className="flex flex-wrap gap-1">
            {member.roles
              .filter((role) => role.status === "active")
              .map((role) => (
                <span
                  key={role.uuid}
                  className="rounded-full bg-muted px-1.5 py-0.5 text-[0.6875rem]"
                  title={`${role.role_name} at ${role.scope_label}`}
                >
                  {role.role_name}
                  <span className="ml-1 text-muted-foreground">
                    · {role.scope_label}
                  </span>
                </span>
              ))}
          </div>
        ),
    },
    {
      key: "expiry",
      header: "Time-bounded",
      secondary: true,
      value: (member) =>
        member.roles.find((role) => role.valid_until)?.valid_until ?? null,
      cell: (member) => {
        const bounded = member.roles.filter((role) => role.valid_until);
        return bounded.length === 0 ? (
          <span className="type-caption">—</span>
        ) : (
          <StatusBadge
            status="expiring"
            label={`${bounded.length} expiring`}
          />
        );
      },
    },
    {
      key: "status",
      header: "Status",
      align: "right",
      value: (member) => member.status,
      cell: (member) => (
        <div className="flex justify-end gap-1.5">
          {member.is_organization_owner ? (
            <StatusBadge status="active" tone="brand" label="Owner" icon={false} />
          ) : null}
          <StatusBadge status={member.status} />
        </div>
      ),
    },
  ];

  return (
    <div className="space-y-4">
      <p className="rounded-lg border border-dashed bg-muted/30 p-3 type-caption">
        Inviting somebody, changing their details and granting a role are three
        acts with three permissions held by different people — they live on{" "}
        <Link to="/staff" className="underline">
          Staff access
        </Link>
        . This is the read view: who holds what, and at what scope.
      </p>
      <DataView
        rows={staff ?? []}
        columns={columns}
        rowKey={(member) => member.uuid}
        storageKey="access.people"
        loading={loading}
        search={{ placeholder: "Search people" }}
        empty={{
          title: "Nobody has been invited yet",
          description: "Accounts are created on Staff access.",
        }}
        card={{
          title: (member) => member.full_name || member.email,
          subtitle: (member) => member.email,
          badge: (member) => <StatusBadge status={member.status} />,
          facts: (member) => [
            {
              label: "Active roles",
              value: member.roles.filter((role) => role.status === "active").length,
            },
            {
              label: "Widest scope",
              value:
                member.roles
                  .map((role) => role.scope_label)
                  .sort()
                  .at(-1) ?? "—",
            },
          ],
        }}
      />
    </div>
  );
}

/* -------------------------------------------------------------------------- */
/* Scopes                                                                      */
/* -------------------------------------------------------------------------- */

/**
 * The scope ladder, drawn.
 *
 * Scope is the half of this system that people do not expect and cannot guess:
 * holding `patient.read` says nothing about *which* patients. Seven levels are
 * hard to hold in your head as words and trivial as a ladder, so it is drawn
 * as one, with each role's ceiling marked on it.
 */
function ScopesTab({ roles }: { roles: Role[] | null }) {
  const byScope = React.useMemo(() => {
    const map = new Map<string, Role[]>();
    for (const scope of SCOPES) map.set(scope, []);
    for (const role of roles ?? []) {
      map.set(role.max_scope, [...(map.get(role.max_scope) ?? []), role]);
    }
    return map;
  }, [roles]);

  return (
    <div className="space-y-5">
      <Section
        title="The ladder"
        description="A permission answers 'may they'. A scope answers 'to which records'. Both are checked on every request, and the second is the one people forget exists."
      >
        <div className="space-y-2">
          {[...SCOPES].reverse().map((scope, index) => {
            const held = byScope.get(scope) ?? [];
            const width = ((SCOPES.length - index) / SCOPES.length) * 100;
            return (
              <div key={scope} className="flex items-center gap-3">
                <span className="w-40 shrink-0 text-sm">{SCOPE_LABEL[scope]}</span>
                <div className="relative h-9 flex-1 rounded-md bg-muted/50">
                  <div
                    className="flex h-full items-center rounded-md bg-primary/12 px-3"
                    style={{ width: `${width}%` }}
                  >
                    <span className="truncate text-xs text-muted-foreground">
                      {held.length === 0
                        ? "no role stops here"
                        : held.map((role) => role.name).join(", ")}
                    </span>
                  </div>
                </div>
                <span className="w-8 shrink-0 text-right text-xs tabular-nums text-muted-foreground">
                  {held.length}
                </span>
              </div>
            );
          })}
        </div>
      </Section>

      <Section
        title="What else the engine does"
        description="Stated rather than hidden — a capability nobody can see is a capability nobody buys. The ones without a screen say so."
      >
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {[
            {
              title: "Per-user overrides",
              detail:
                "PermissionOverride grants a permission to one person, or denies one their role gives them — with a mandatory reason and an expiry. Enforced on every request. No screen yet: it is the next thing to build here.",
              icon: "permission" as const,
            },
            {
              title: "Segregation of duties",
              detail:
                "Conflicts are declared on permissions and refused when a role is saved and again at the moment of approval. Purchase create ≠ approve; payroll process ≠ approve. The role editor now names a conflicting pair as you tick it.",
              icon: "audit" as const,
            },
            {
              title: "Break-glass",
              detail:
                "Emergency access to a record outside your care relationship, time-boxed, counted, and queued for review. Reviewable on Privacy.",
              icon: "breakGlass" as const,
            },
            {
              title: "Time-bounded assignments",
              detail:
                "A role can be granted until a date and expires on its own — for a locum, a covering manager, an auditor.",
              icon: "duration" as const,
            },
            {
              title: "Role inheritance",
              detail:
                "A role can inherit another's permissions rather than restating them, so a senior role cannot drift from the junior one it extends.",
              icon: "role" as const,
            },
            {
              title: "Entitlement, above permission",
              detail:
                "Even a permitted action is refused if the subscription does not include the module. Four-layer resolution with provenance for every value.",
              icon: "capacity" as const,
            },
          ].map((item) => (
            <div key={item.title} className="rounded-lg border bg-card p-4">
              <Icon name={item.icon} size="lg" className="mb-2 text-muted-foreground" />
              <p className="type-heading">{item.title}</p>
              <p className="mt-1 type-caption">{item.detail}</p>
            </div>
          ))}
        </div>
      </Section>
    </div>
  );
}
