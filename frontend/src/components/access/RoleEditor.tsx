/**
 * Write a role.
 *
 * **The screen that turns a described capability into a real one.** Nirova's
 * RBAC engine has always been one of its genuine differentiators — permissions
 * with declared conflicts, seven scope levels, inheritance, per-user overrides
 * — and a customer could not create a single role. Every role in every
 * database came from a seed. "Different roles should have different works and
 * permissions, and those should be configurable" was the brief, and the honest
 * answer until now was that they were configurable by us and by nobody else.
 *
 * Four things this form does that a generic CRUD form would not, each because
 * the engine behind it has a rule that would otherwise be discovered on submit:
 *
 *  1. **Segregation of duties is checked as you tick.** `purchase.create` and
 *     `purchase.approve` in one role is refused by the service, and a form
 *     that only says so after you have spent two minutes building the role is
 *     a form people fight. The conflicting pair is named the moment it exists.
 *
 *  2. **Permissions you do not hold are disabled, with the reason.** You may
 *     not create authority you do not have — otherwise `role.manage` is a
 *     privilege-escalation primitive. Showing those greyed rather than hiding
 *     them tells an administrator what to ask *their* administrator for.
 *
 *  3. **Sensitive permissions are marked.** Anything touching patient-
 *     identifiable data is written to the audit log on every use. Somebody
 *     assembling a role should know which ticks carry that weight.
 *
 *  4. **The scope ceiling is part of the role, not an afterthought.** A ward
 *     nurse role capped at `department` cannot later be granted
 *     organization-wide by an over-eager administrator. That is the single
 *     most useful field on this form and the one nobody would think to add.
 */

import * as React from "react";

import api, { ApiError } from "@/lib/api";
import { cn } from "@/lib/utils";
import { Icon } from "@/components/ui/icon";
import { Spinner } from "@/components/ui/loader";
import { StatusBadge } from "@/components/ui/status";
import {
  Alert,
  AlertDescription,
  AlertTitle,
  Button,
  Input,
  Label,
  Textarea,
} from "@/components/ui/primitives";

/* -------------------------------------------------------------------------- */
/* Types                                                                       */
/* -------------------------------------------------------------------------- */

export interface Role {
  uuid: string;
  code: string;
  name: string;
  description: string;
  max_scope: string;
  permissions: string[];
  permission_count: number;
  requires_approval_to_assign: boolean;
  grantable: boolean;
  beyond_your_authority: string[];
  is_system: boolean;
  is_superuser_role: boolean;
  grantable_roles: string[];
  display_order: number;
  editable: boolean;
  deletable: boolean;
  holders: number;
}

export interface PermissionDef {
  code: string;
  label: string;
  description: string;
  is_sensitive: boolean;
  conflicts_with: string[];
}

export interface PermissionCatalogue {
  groups: { group: string; permissions: PermissionDef[] }[];
  count: number;
}

const SCOPES = [
  ["own", "Own records only"],
  ["own_patients", "Their own patients"],
  ["unit", "Their unit"],
  ["department", "Their department"],
  ["facility", "Their whole facility"],
  ["multi_facility", "Several named facilities"],
  ["organization", "The whole organization"],
] as const;

/* -------------------------------------------------------------------------- */
/* Editor                                                                      */
/* -------------------------------------------------------------------------- */

export function RoleEditor({
  role,
  catalogue,
  /** Permissions the *caller* holds. Anything outside this cannot be granted. */
  yourPermissions,
  isOwner,
  onSaved,
  onCancel,
}: {
  /** `null` creates. */
  role: Role | null;
  catalogue: PermissionCatalogue;
  yourPermissions: Set<string>;
  isOwner: boolean;
  onSaved: (role: Role) => void;
  onCancel: () => void;
}) {
  const [name, setName] = React.useState(role?.name ?? "");
  const [description, setDescription] = React.useState(role?.description ?? "");
  const [maxScope, setMaxScope] = React.useState(role?.max_scope ?? "facility");
  const [needsApproval, setNeedsApproval] = React.useState(
    role?.requires_approval_to_assign ?? false,
  );
  const [selected, setSelected] = React.useState<Set<string>>(
    () => new Set(role?.permissions ?? []),
  );
  const [filter, setFilter] = React.useState("");
  const [saving, setSaving] = React.useState(false);
  const [problem, setProblem] = React.useState<string | null>(null);
  const [detail, setDetail] = React.useState<string[] | null>(null);

  /** Every permission, flattened, for conflict and authority lookups. */
  const byCode = React.useMemo(() => {
    const map = new Map<string, PermissionDef>();
    for (const group of catalogue.groups) {
      for (const permission of group.permissions) map.set(permission.code, permission);
    }
    return map;
  }, [catalogue]);

  /*
    The live segregation-of-duties check.

    The same rule the service applies on save, run on every tick so the
    conflict is caught while somebody is looking at the two things that
    conflict — which is the only moment the message is actionable.
  */
  const conflicts = React.useMemo(() => {
    const pairs: [string, string][] = [];
    for (const code of selected) {
      const definition = byCode.get(code);
      if (!definition) continue;
      for (const other of definition.conflicts_with) {
        if (!selected.has(other)) continue;
        const pair = [code, other].sort() as [string, string];
        if (!pairs.some(([a, b]) => a === pair[0] && b === pair[1])) pairs.push(pair);
      }
    }
    return pairs;
  }, [selected, byCode]);

  const beyondYou = React.useMemo(
    () =>
      isOwner
        ? []
        : [...selected].filter((code) => !yourPermissions.has(code)).sort(),
    [selected, yourPermissions, isOwner],
  );

  const sensitiveCount = React.useMemo(
    () => [...selected].filter((code) => byCode.get(code)?.is_sensitive).length,
    [selected, byCode],
  );

  const groups = React.useMemo(() => {
    if (!filter.trim()) return catalogue.groups;
    const needle = filter.trim().toLowerCase();
    return catalogue.groups
      .map((group) => ({
        ...group,
        permissions: group.permissions.filter(
          (permission) =>
            permission.code.toLowerCase().includes(needle) ||
            permission.label.toLowerCase().includes(needle),
        ),
      }))
      .filter((group) => group.permissions.length > 0);
  }, [catalogue, filter]);

  function toggle(code: string) {
    setSelected((current) => {
      const next = new Set(current);
      if (next.has(code)) next.delete(code);
      else next.add(code);
      return next;
    });
  }

  function toggleGroup(permissions: PermissionDef[], on: boolean) {
    setSelected((current) => {
      const next = new Set(current);
      for (const permission of permissions) {
        if (!isOwner && !yourPermissions.has(permission.code)) continue;
        if (on) next.add(permission.code);
        else next.delete(permission.code);
      }
      return next;
    });
  }

  const blocked = conflicts.length > 0 || beyondYou.length > 0 || !name.trim();

  async function save() {
    setSaving(true);
    setProblem(null);
    setDetail(null);
    const body = {
      name: name.trim(),
      description: description.trim(),
      permissions: [...selected].sort(),
      max_scope: maxScope,
      requires_approval_to_assign: needsApproval,
    };
    try {
      const saved = role
        ? await api.patch<Role>(`/admin/roles/${role.uuid}/`, body)
        : await api.post<Role>("/admin/roles/", body);
      onSaved(saved);
    } catch (error) {
      if (error instanceof ApiError) {
        setProblem(error.message);
        // The API returns *which* permissions were the problem. Rendering the
        // list is the difference between "that was refused" and "remove these
        // three".
        const named =
          (error.detail?.beyond_your_authority as string[] | undefined) ??
          (error.detail?.unknown_permissions as string[] | undefined) ??
          (error.detail?.conflicts as string[][] | undefined)?.map((pair) =>
            pair.join(" + "),
          );
        setDetail(named ?? null);
      } else {
        setProblem("The role could not be saved.");
      }
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="type-title">{role ? `Edit ${role.name}` : "New role"}</p>
          <p className="mt-0.5 type-caption">
            {role?.is_system
              ? "A role that ships with the product. Its permissions are yours to change; the role itself cannot be removed."
              : "A role is a named set of permissions plus a ceiling on how far it may reach."}
          </p>
        </div>
        <div className="flex shrink-0 items-center gap-2">
          <Button variant="ghost" size="sm" onClick={onCancel} disabled={saving}>
            Cancel
          </Button>
          <Button size="sm" onClick={() => void save()} disabled={blocked || saving}>
            {saving ? <Spinner size="sm" className="mr-2" /> : null}
            {role ? "Save changes" : "Create role"}
          </Button>
        </div>
      </div>

      {problem ? (
        <Alert variant="destructive">
          <Icon name="warning" size="md" />
          <AlertTitle>That was refused</AlertTitle>
          <AlertDescription>
            {problem}
            {detail?.length ? (
              <span className="mt-1.5 flex flex-wrap gap-1">
                {detail.map((entry) => (
                  <code
                    key={entry}
                    className="rounded bg-card px-1.5 py-0.5 type-code text-xs"
                  >
                    {entry}
                  </code>
                ))}
              </span>
            ) : null}
          </AlertDescription>
        </Alert>
      ) : null}

      {/* -- Identity ------------------------------------------------------ */}
      <div className="grid gap-4 rounded-lg border bg-card p-4 sm:grid-cols-2">
        <div className="space-y-1.5">
          <Label htmlFor="role-name">Name</Label>
          <Input
            id="role-name"
            value={name}
            onChange={(event) => setName(event.target.value)}
            placeholder="Ward sister"
          />
          {role ? (
            <p className="type-caption">
              Code <code className="type-code">{role.code}</code> — fixed, because
              seeds and delegation rules reference it.
            </p>
          ) : (
            <p className="type-caption">
              The code is derived from the name and cannot be changed afterwards.
            </p>
          )}
        </div>

        <div className="space-y-1.5">
          <Label htmlFor="role-scope">Widest scope it may be granted at</Label>
          <select
            id="role-scope"
            value={maxScope}
            onChange={(event) => setMaxScope(event.target.value)}
            className="h-9 w-full rounded-md border border-input bg-card px-2.5 text-sm"
          >
            {SCOPES.map(([value, label]) => (
              <option key={value} value={value}>
                {label}
              </option>
            ))}
          </select>
          <p className="type-caption">
            A ceiling, not a default. A role capped at department cannot be
            granted organization-wide however it is assigned.
          </p>
        </div>

        <div className="space-y-1.5 sm:col-span-2">
          <Label htmlFor="role-description">What this role is for</Label>
          <Textarea
            id="role-description"
            rows={2}
            value={description}
            onChange={(event) => setDescription(event.target.value)}
            placeholder="Runs a ward: assigns beds, records observations, administers medication. Does not order investigations."
          />
        </div>

        <label className="flex cursor-pointer items-start gap-2 sm:col-span-2">
          <input
            type="checkbox"
            checked={needsApproval}
            onChange={(event) => setNeedsApproval(event.target.checked)}
            className="mt-0.5 h-4 w-4 accent-[hsl(var(--primary))]"
          />
          <span>
            <span className="text-sm font-medium">Assigning this needs approval</span>
            <span className="block type-caption">
              For roles that can move money or change clinical records. The grant
              waits as pending rather than taking effect immediately.
            </span>
          </span>
        </label>
      </div>

      {/* -- Refusals ------------------------------------------------------ */}
      {conflicts.length > 0 ? (
        <Alert variant="destructive">
          <Icon name="audit" size="md" />
          <AlertTitle>Segregation of duties</AlertTitle>
          <AlertDescription>
            One person may not hold both halves of these pairs — it is the
            maker-checker rule, and the service refuses it on save:
            <span className="mt-1.5 flex flex-col gap-1">
              {conflicts.map(([a, b]) => (
                <span key={`${a}|${b}`} className="flex items-center gap-1.5">
                  <code className="rounded bg-card px-1.5 py-0.5 type-code text-xs">{a}</code>
                  <span className="type-caption">and</span>
                  <code className="rounded bg-card px-1.5 py-0.5 type-code text-xs">{b}</code>
                </span>
              ))}
            </span>
          </AlertDescription>
        </Alert>
      ) : null}

      {beyondYou.length > 0 ? (
        <Alert variant="warning">
          <Icon name="permission" size="md" />
          <AlertTitle>Beyond your own authority</AlertTitle>
          <AlertDescription>
            A role cannot carry permissions you do not hold yourself — otherwise
            editing roles would be a way to grant yourself anything. Ask an
            administrator who holds these, or remove them:
            <span className="mt-1.5 flex flex-wrap gap-1">
              {beyondYou.map((code) => (
                <code key={code} className="rounded bg-card px-1.5 py-0.5 type-code text-xs">
                  {code}
                </code>
              ))}
            </span>
          </AlertDescription>
        </Alert>
      ) : null}

      {/* -- Permissions --------------------------------------------------- */}
      <div className="rounded-lg border bg-card">
        <div className="flex flex-wrap items-center justify-between gap-3 border-b px-4 py-3">
          <div className="min-w-0">
            <p className="type-heading">Permissions</p>
            <p className="type-caption">
              {selected.size} of {catalogue.count} selected
              {sensitiveCount > 0 ? (
                <>
                  {" · "}
                  <span className="text-serious">
                    {sensitiveCount} touch patient data and are audited on every use
                  </span>
                </>
              ) : null}
            </p>
          </div>
          <div className="relative w-full sm:w-64">
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
        </div>

        <div className="max-h-[26rem] divide-y overflow-y-auto">
          {groups.map((group) => {
            const grantable = group.permissions.filter(
              (permission) => isOwner || yourPermissions.has(permission.code),
            );
            const allOn =
              grantable.length > 0 &&
              grantable.every((permission) => selected.has(permission.code));

            return (
              <div key={group.group} className="px-4 py-3">
                <div className="mb-2 flex items-center justify-between gap-3">
                  <p className="type-eyebrow text-muted-foreground">{group.group}</p>
                  {grantable.length > 0 ? (
                    <button
                      type="button"
                      onClick={() => toggleGroup(grantable, !allOn)}
                      className="text-xs font-medium text-primary-ink hover:underline"
                    >
                      {allOn ? "Clear all" : "Select all"}
                    </button>
                  ) : null}
                </div>

                <div className="grid gap-1.5 sm:grid-cols-2">
                  {group.permissions.map((permission) => {
                    const held = selected.has(permission.code);
                    const allowed = isOwner || yourPermissions.has(permission.code);
                    const conflicting = conflicts.some((pair) =>
                      pair.includes(permission.code),
                    );
                    return (
                      <label
                        key={permission.code}
                        title={
                          allowed
                            ? permission.description || permission.label
                            : `You do not hold ${permission.code}, so you cannot put it in a role.`
                        }
                        className={cn(
                          "flex items-start gap-2 rounded-md px-2 py-1.5 transition-colors duration-quick",
                          allowed
                            ? "cursor-pointer hover:bg-accent/50"
                            : "cursor-not-allowed opacity-45",
                          conflicting && "bg-critical-subtle",
                        )}
                      >
                        <input
                          type="checkbox"
                          checked={held}
                          disabled={!allowed}
                          onChange={() => toggle(permission.code)}
                          className="mt-0.5 h-4 w-4 shrink-0 accent-[hsl(var(--primary))]"
                        />
                        <span className="min-w-0">
                          <span className="flex flex-wrap items-center gap-1.5">
                            <span className="text-sm">{permission.label}</span>
                            {permission.is_sensitive ? (
                              <StatusBadge
                                status="sensitive"
                                tone="serious"
                                label="audited"
                                icon="privacy"
                              />
                            ) : null}
                            {!allowed ? (
                              <StatusBadge
                                status="locked"
                                tone="neutral"
                                label="beyond you"
                                icon="permission"
                              />
                            ) : null}
                          </span>
                          <code className="block truncate type-code text-[0.6875rem] text-muted-foreground">
                            {permission.code}
                          </code>
                        </span>
                      </label>
                    );
                  })}
                </div>
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}
