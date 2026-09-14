/**
 * Staff administration: who can sign in, and what they may do.
 *
 * The screen the product has never had. Every account in every Nirova database
 * was created by a seed script, because there was no API and no page — an
 * administrator could see their colleagues nowhere and add one never.
 *
 * **Three things happen here and they are deliberately not one form.** Adding
 * a person, changing their details, and changing what they may do are separate
 * acts with separate permissions (`user.invite`, `user.update`, `role.assign`)
 * held by different people. An HR manager may invite a colleague and may not
 * grant them a role; collapsing the three into one dialogue would mean either
 * showing controls that will be refused or hiding the whole screen from
 * somebody who can use two thirds of it.
 */

import { useCallback, useEffect, useMemo, useState } from "react";
import {
  Loader2,
  Plus,
  ShieldCheck,
  ShieldAlert,
  Trash2,
  UserCheck,
  UserX,
} from "lucide-react";

import {
  Alert,
  AlertDescription,
  AlertTitle,
  Badge,
  Button,
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
  DetailPanel,
  DetailRow,
  Input,
  Label,
  Select,
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/primitives";
import { useSession } from "@/hooks/useSession";
import api, { ApiError } from "@/lib/api";
import { TemporaryPassword } from "@/components/access/TemporaryPassword";
import { ResetSecondFactor } from "@/components/access/ResetSecondFactor";
import { cn } from "@/lib/utils";
import { PageHeader } from "@/components/ui/layout";
import { formatDate } from "@/lib/dates";

/* -------------------------------------------------------------------------- */
/* Types                                                                      */
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
  valid_from: string | null;
  valid_until: string | null;
  reason: string;
}

interface StaffMember {
  uuid: string;
  email: string;
  full_name: string;
  phone: string;
  status: string;
  is_organization_owner: boolean;
  consumes_seat: boolean;
  invited_at: string | null;
  joined_at: string | null;
  last_active_at: string | null;
  /** Whether they sign in with a second factor. */
  mfa_enabled?: boolean;
  roles: AssignedRole[];
}

interface GrantableRole {
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
}

interface Paginated<T> {
  count: number;
  results: T[];
}

interface FacilityOption {
  uuid: string;
  name: string;
}

const SCOPES = [
  { value: "own", label: "Own records" },
  { value: "own_patients", label: "Own patients" },
  { value: "unit", label: "Own unit" },
  { value: "department", label: "Own department" },
  { value: "facility", label: "Own facility" },
  { value: "multi_facility", label: "Assigned facilities" },
  { value: "organization", label: "Whole organization" },
];

function when(value: string | null): string {
  if (!value) return "";
  return formatDate(value);
}

/* -------------------------------------------------------------------------- */
/* Screen                                                                     */
/* -------------------------------------------------------------------------- */

export default function StaffPage() {
  const { can } = useSession();
  const mayInvite = can("user.invite", "own");
  const mayDeactivate = can("user.deactivate", "own");
  const mayAssign = can("role.assign", "own");
  const mayReadRoles = can("role.read", "own");

  const [members, setMembers] = useState<StaffMember[] | null>(null);
  const [count, setCount] = useState(0);
  const [query, setQuery] = useState("");
  const [showLeavers, setShowLeavers] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [selected, setSelected] = useState<StaffMember | null>(null);
  const [inviting, setInviting] = useState(false);
  const [roles, setRoles] = useState<GrantableRole[] | null>(null);
  const [facilities, setFacilities] = useState<FacilityOption[]>([]);

  const load = useCallback(async () => {
    setError(null);
    try {
      const params = new URLSearchParams();
      if (query.trim()) params.set("q", query.trim());
      if (showLeavers) params.set("status", "all");
      const suffix = params.toString() ? `?${params}` : "";
      const page = await api.get<Paginated<StaffMember>>(
        `/admin/staff/${suffix}`,
      );
      setMembers(page.results);
      setCount(page.count);
    } catch (err) {
      setMembers([]);
      setError(
        err instanceof ApiError ? err.message : "Could not load staff.",
      );
    }
  }, [query, showLeavers]);

  useEffect(() => {
    // Debounced, because this runs on every keystroke in the search box and
    // an administrator typing a surname should not issue eight requests.
    const timer = setTimeout(load, 250);
    return () => clearTimeout(timer);
  }, [load]);

  useEffect(() => {
    if (!mayReadRoles) return;
    api
      .get<GrantableRole[]>("/admin/roles/")
      .then(setRoles)
      .catch(() => setRoles([]));
  }, [mayReadRoles]);

  useEffect(() => {
    // Facilities are needed to say *where* a role applies. Failure is not
    // fatal: the grant form falls back to organization scope, which is the
    // only scope that names nothing.
    api
      .get<Paginated<FacilityOption>>("/org/facilities/")
      .then((page) => setFacilities(page.results ?? []))
      .catch(() => setFacilities([]));
  }, []);

  // Kept in sync after any mutation so the panel does not show stale roles.
  const refresh = useCallback(
    async (uuid: string) => {
      await load();
      try {
        setSelected(await api.get<StaffMember>(`/admin/staff/${uuid}/`));
      } catch {
        setSelected(null);
      }
    },
    [load],
  );

  return (
    <div className="space-y-6">
      <PageHeader
        title="Staff"
        description="Who can sign in, and their roles."
        actions={
          <>
            {mayInvite && (
              <Button onClick={() => setInviting(true)}>
                <Plus className="mr-2 h-4 w-4" />
                Invite someone
              </Button>
            )}
          </>
        }
      />

      <Card>
        <CardHeader className="flex flex-col gap-4 sm:flex-row sm:items-end sm:justify-between">
          <div className="min-w-0 flex-1">
            <CardTitle>
              {count} {count === 1 ? "person" : "people"}
            </CardTitle>
            <CardDescription>
              A role says what somebody may do; its scope says where.
            </CardDescription>
          </div>
          <div className="flex flex-wrap items-center gap-3">
            <Input
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder="Search name or email"
              className="w-full sm:w-56"
            />
            <label className="flex items-center gap-2 text-sm text-muted-foreground">
              <input
                type="checkbox"
                checked={showLeavers}
                onChange={(event) => setShowLeavers(event.target.checked)}
                className="h-4 w-4"
              />
              Include leavers
            </label>
          </div>
        </CardHeader>
        <CardContent>
          {error && (
            <Alert variant="warning" className="mb-4">
              <AlertTitle>Not shown</AlertTitle>
              <AlertDescription>{error}</AlertDescription>
            </Alert>
          )}

          {members === null ? (
            <p className="py-10 text-center text-sm text-muted-foreground">
              <Loader2 className="inline h-4 w-4 animate-spin" />
            </p>
          ) : members.length === 0 ? (
            <EmptyState
              searching={Boolean(query.trim())}
              mayInvite={mayInvite}
              onInvite={() => setInviting(true)}
            />
          ) : (
            /* Horizontal scroll on the container, never the page. A staff list
               is wide and a phone is not. */
            <div className="overflow-x-auto">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Name</TableHead>
                    <TableHead>Roles</TableHead>
                    <TableHead className="hidden md:table-cell">
                      Last active
                    </TableHead>
                    <TableHead className="text-right">Status</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {members.map((member) => (
                    <TableRow
                      key={member.uuid}
                      onClick={() => setSelected(member)}
                      className="cursor-pointer"
                    >
                      <TableCell>
                        <div className="font-medium">{member.full_name}</div>
                        <div className="text-xs text-muted-foreground">
                          {member.email}
                        </div>
                      </TableCell>
                      <TableCell>
                        {member.roles.length === 0 ? (
                          <span className="text-xs text-muted-foreground">
                            No roles — can sign in and see nothing
                          </span>
                        ) : (
                          <div className="flex flex-wrap gap-1">
                            {member.roles.map((role) => (
                              <Badge key={role.uuid} variant="secondary">
                                {role.role_name}
                              </Badge>
                            ))}
                          </div>
                        )}
                      </TableCell>
                      <TableCell className="hidden md:table-cell text-sm text-muted-foreground">
                        {when(member.last_active_at) || "Never"}
                      </TableCell>
                      <TableCell className="text-right">
                        {member.is_organization_owner && (
                          <Badge className="mr-1">Owner</Badge>
                        )}
                        <Badge
                          variant={
                            member.status === "active" ? "outline" : "secondary"
                          }
                        >
                          {member.status}
                        </Badge>
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
          )}
        </CardContent>
      </Card>

      <MemberPanel
        member={selected}
        roles={roles ?? []}
        facilities={facilities}
        mayAssign={mayAssign}
        mayDeactivate={mayDeactivate}
        onClose={() => setSelected(null)}
        onChanged={refresh}
      />

      <InvitePanel
        open={inviting}
        roles={roles ?? []}
        facilities={facilities}
        mayAssign={mayAssign}
        onClose={() => setInviting(false)}
        onInvited={async () => {
          setInviting(false);
          await load();
        }}
      />
    </div>
  );
}

/* -------------------------------------------------------------------------- */
/* Empty state                                                                */
/* -------------------------------------------------------------------------- */

function EmptyState({
  searching,
  mayInvite,
  onInvite,
}: {
  searching: boolean;
  mayInvite: boolean;
  onInvite: () => void;
}) {
  // Two different emptinesses. "No results for 'gurung'" and "nobody works
  // here yet" call for different next actions, and one message for both
  // leaves the reader to work out which they are looking at.
  if (searching) {
    return (
      <p className="py-12 text-center text-sm text-muted-foreground">
        Nobody matches that. Try part of a surname, or an email address.
      </p>
    );
  }
  return (
    <div className="py-12 text-center">
      <p className="text-sm text-muted-foreground">
        Only you so far. Invite the people who will use this system and give
        each of them a role.
      </p>
      {mayInvite && (
        <Button className="mt-4" onClick={onInvite}>
          <Plus className="mr-2 h-4 w-4" />
          Invite someone
        </Button>
      )}
    </div>
  );
}

/* -------------------------------------------------------------------------- */
/* One person                                                                 */
/* -------------------------------------------------------------------------- */

function MemberPanel({
  member,
  roles,
  facilities,
  mayAssign,
  mayDeactivate,
  onClose,
  onChanged,
}: {
  member: StaffMember | null;
  roles: GrantableRole[];
  facilities: FacilityOption[];
  mayAssign: boolean;
  mayDeactivate: boolean;
  onClose: () => void;
  onChanged: (uuid: string) => Promise<void>;
}) {
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);
  const [granting, setGranting] = useState(false);

  useEffect(() => {
    setProblem(null);
    setGranting(false);
  }, [member?.uuid]);

  if (!member) return <DetailPanel open={false} title="" onClose={onClose}>{null}</DetailPanel>;

  async function act(work: () => Promise<unknown>) {
    setBusy(true);
    setProblem(null);
    try {
      await work();
      await onChanged(member!.uuid);
    } catch (err) {
      // The refusal message is the useful part. `assign_role` names which
      // permissions put a role out of reach and `deactivate` says why an
      // owner cannot be removed; replacing either with "something went wrong"
      // throws away the only thing that tells somebody what to do next.
      setProblem(
        err instanceof ApiError ? err.message : "That did not work.",
      );
    } finally {
      setBusy(false);
    }
  }

  return (
    <DetailPanel
      open
      title={member.full_name}
      subtitle={member.email}
      onClose={onClose}
      footer={
        mayDeactivate && !member.is_organization_owner ? (
          <div className="flex w-full flex-wrap items-start justify-between gap-2">
          {member.status === "active" && (
            <TemporaryPassword uuid={member.uuid} name={member.full_name} />
          )}
          {member.status === "active" && member.mfa_enabled && (
            <ResetSecondFactor
              uuid={member.uuid}
              name={member.full_name}
              onDone={() => void onChanged(member.uuid)}
            />
          )}
          <Button
            variant={member.status === "active" ? "destructive" : "default"}
            disabled={busy}
            onClick={() =>
              act(() =>
                api.post(
                  `/admin/staff/${member.uuid}/deactivate/${
                    member.status === "active" ? "" : "?undo=1"
                  }`,
                  { reason: "" },
                ),
              )
            }
          >
            {member.status === "active" ? (
              <>
                <UserX className="mr-2 h-4 w-4" />
                Deactivate
              </>
            ) : (
              <>
                <UserCheck className="mr-2 h-4 w-4" />
                Reactivate
              </>
            )}
          </Button>
          </div>
        ) : null
      }
    >
      {problem && (
        <Alert variant="warning" className="mb-4">
          <AlertTitle>Refused</AlertTitle>
          <AlertDescription>{problem}</AlertDescription>
        </Alert>
      )}

      <section className="mb-6">
        <h3 className="mb-2 text-xs font-medium uppercase tracking-wide text-muted-foreground">
          Account
        </h3>
        <DetailRow label="Email">{member.email}</DetailRow>
        <DetailRow label="Phone">{member.phone}</DetailRow>
        <DetailRow label="Status">{member.status}</DetailRow>
        <DetailRow label="Uses a licensed seat">
          {member.consumes_seat ? "Yes" : "No"}
        </DetailRow>
        <DetailRow label="Invited">{when(member.invited_at)}</DetailRow>
        <DetailRow label="Last active">
          {when(member.last_active_at)}
        </DetailRow>
      </section>

      <section>
        <div className="mb-2 flex items-center justify-between">
          <h3 className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
            Roles
          </h3>
          {mayAssign && !granting && (
            <Button size="sm" variant="outline" onClick={() => setGranting(true)}>
              <Plus className="mr-1 h-3 w-3" />
              Grant a role
            </Button>
          )}
        </div>

        {member.roles.length === 0 && !granting && (
          <p className="py-4 text-sm text-muted-foreground">
            None. They can sign in and will see an empty application until
            somebody grants them a role.
          </p>
        )}

        <div className="space-y-2">
          {member.roles.map((role) => (
            <div
              key={role.uuid}
              className="flex items-start justify-between gap-3 rounded-md border p-3"
            >
              <div className="min-w-0">
                <div className="text-sm font-medium">{role.role_name}</div>
                <div className="text-xs text-muted-foreground">
                  {role.scope_label}
                </div>
              </div>
              {mayAssign && (
                <Button
                  size="sm"
                  variant="ghost"
                  disabled={busy}
                  onClick={() =>
                    act(() =>
                      api.del(
                        `/admin/staff/${member.uuid}/roles/${role.uuid}/`,
                      ),
                    )
                  }
                  aria-label={`Revoke ${role.role_name}`}
                >
                  <Trash2 className="h-4 w-4" />
                </Button>
              )}
            </div>
          ))}
        </div>

        {granting && (
          <GrantForm
            roles={roles}
            facilities={facilities}
            busy={busy}
            onCancel={() => setGranting(false)}
            onGrant={async (payload) => {
              await act(() =>
                api.post(`/admin/staff/${member.uuid}/roles/`, payload),
              );
              setGranting(false);
            }}
          />
        )}
      </section>
    </DetailPanel>
  );
}

/* -------------------------------------------------------------------------- */
/* Granting                                                                   */
/* -------------------------------------------------------------------------- */

interface GrantPayload {
  role_code: string;
  scope: string;
  facility_uuid?: string | null;
}

function GrantForm({
  roles,
  facilities,
  busy,
  onCancel,
  onGrant,
}: {
  roles: GrantableRole[];
  facilities: FacilityOption[];
  busy: boolean;
  onCancel: () => void;
  onGrant: (payload: GrantPayload) => Promise<void>;
}) {
  const grantable = useMemo(() => roles.filter((r) => r.grantable), [roles]);
  const refused = useMemo(() => roles.filter((r) => !r.grantable), [roles]);
  const [code, setCode] = useState(grantable[0]?.code ?? "");
  const [scope, setScope] = useState("facility");
  const [facility, setFacility] = useState(facilities[0]?.uuid ?? "");

  const chosen = roles.find((r) => r.code === code);
  // A scope wider than the role's own ceiling is refused by the server, so the
  // list is trimmed to what the role actually permits rather than letting
  // somebody choose something that cannot work.
  const ceiling = SCOPES.findIndex((s) => s.value === chosen?.max_scope);
  const allowedScopes = ceiling >= 0 ? SCOPES.slice(0, ceiling + 1) : SCOPES;
  const needsPlace = scope !== "organization" && scope !== "own";

  useEffect(() => {
    if (!allowedScopes.some((s) => s.value === scope)) {
      setScope(allowedScopes[allowedScopes.length - 1]?.value ?? "facility");
    }
  }, [allowedScopes, scope]);

  if (grantable.length === 0) {
    return (
      <Alert className="mt-4">
        <AlertTitle>Nothing you can grant</AlertTitle>
        <AlertDescription>
          None of your roles allow you to delegate another one. Ask an
          organization administrator.
        </AlertDescription>
      </Alert>
    );
  }

  return (
    <div className="mt-4 space-y-3 rounded-md border bg-muted/30 p-3">
      <div>
        <Label htmlFor="grant-role">Role</Label>
        <Select
          id="grant-role"
          value={code}
          onChange={(event) => setCode(event.target.value)}
        >
          {grantable.map((role) => (
            <option key={role.code} value={role.code}>
              {role.name} · {role.permission_count} permissions
            </option>
          ))}
        </Select>
        {chosen?.description && (
          <p className="mt-1 text-xs text-muted-foreground">
            {chosen.description}
          </p>
        )}
      </div>

      <div>
        <Label htmlFor="grant-scope">Where it applies</Label>
        <Select
          id="grant-scope"
          value={scope}
          onChange={(event) => setScope(event.target.value)}
        >
          {allowedScopes.map((option) => (
            <option key={option.value} value={option.value}>
              {option.label}
            </option>
          ))}
        </Select>
      </div>

      {needsPlace && (
        <div>
          <Label htmlFor="grant-facility">Facility</Label>
          <Select
            id="grant-facility"
            value={facility}
            onChange={(event) => setFacility(event.target.value)}
          >
            {facilities.map((option) => (
              <option key={option.uuid} value={option.uuid}>
                {option.name}
              </option>
            ))}
          </Select>
          <p className="mt-1 text-xs text-muted-foreground">
            A scope that names nowhere reaches nothing — the server refuses it.
          </p>
        </div>
      )}

      <div className="flex gap-2">
        <Button
          size="sm"
          disabled={busy || !code}
          onClick={() =>
            onGrant({
              role_code: code,
              scope,
              facility_uuid: needsPlace ? facility || null : null,
            })
          }
        >
          {busy && <Loader2 className="mr-2 h-3 w-3 animate-spin" />}
          Grant
        </Button>
        <Button size="sm" variant="ghost" onClick={onCancel}>
          Cancel
        </Button>
      </div>

      {refused.length > 0 && (
        /* Shown, not hidden. "Why can't I give somebody this role?" is a
           question an administrator will otherwise ask support, and the
           server already computes the answer. */
        <details className="pt-1">
          <summary className="cursor-pointer text-xs text-muted-foreground">
            <ShieldAlert className="mr-1 inline h-3 w-3" />
            {refused.length} roles you may not grant
          </summary>
          <ul className="mt-2 space-y-1 text-xs text-muted-foreground">
            {refused.map((role) => (
              <li key={role.code}>
                <span className="font-medium">{role.name}</span>
                {role.beyond_your_authority.length > 0 && (
                  <> — needs {role.beyond_your_authority.slice(0, 3).join(", ")}</>
                )}
              </li>
            ))}
          </ul>
        </details>
      )}
    </div>
  );
}

/* -------------------------------------------------------------------------- */
/* Inviting                                                                   */
/* -------------------------------------------------------------------------- */

function InvitePanel({
  open,
  roles,
  facilities,
  mayAssign,
  onClose,
  onInvited,
}: {
  open: boolean;
  roles: GrantableRole[];
  facilities: FacilityOption[];
  mayAssign: boolean;
  onClose: () => void;
  onInvited: () => Promise<void>;
}) {
  const [email, setEmail] = useState("");
  const [fullName, setFullName] = useState("");
  const [phone, setPhone] = useState("");
  const [withRole, setWithRole] = useState(false);
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);
  const grantable = useMemo(() => roles.filter((r) => r.grantable), [roles]);
  const [code, setCode] = useState("");
  const [facility, setFacility] = useState("");

  useEffect(() => {
    if (!open) return;
    setEmail("");
    setFullName("");
    setPhone("");
    setWithRole(false);
    setProblem(null);
    setCode(grantable[0]?.code ?? "");
    setFacility(facilities[0]?.uuid ?? "");
  }, [open, grantable, facilities]);

  async function submit() {
    setBusy(true);
    setProblem(null);
    try {
      await api.post("/admin/staff/", {
        email,
        full_name: fullName,
        phone,
        ...(withRole && code
          ? { role_code: code, scope: "facility", facility_uuid: facility }
          : {}),
      });
      await onInvited();
    } catch (err) {
      setProblem(
        err instanceof ApiError ? err.message : "Could not invite them.",
      );
    } finally {
      setBusy(false);
    }
  }

  return (
    <DetailPanel
      open={open}
      title="Invite someone"
      subtitle="They will be able to sign in once they set a password."
      onClose={onClose}
      footer={
        <Button disabled={busy || !email || !fullName} onClick={submit}>
          {busy && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
          Send invitation
        </Button>
      }
    >
      {problem && (
        <Alert variant="warning" className="mb-4">
          <AlertTitle>Not invited</AlertTitle>
          <AlertDescription>{problem}</AlertDescription>
        </Alert>
      )}

      <div className="space-y-3">
        <div>
          <Label htmlFor="invite-name">Full name</Label>
          <Input
            id="invite-name"
            value={fullName}
            onChange={(event) => setFullName(event.target.value)}
            placeholder="Sabina Rana"
          />
        </div>
        <div>
          <Label htmlFor="invite-email">Email</Label>
          <Input
            id="invite-email"
            type="email"
            value={email}
            onChange={(event) => setEmail(event.target.value)}
            placeholder="sabina@hospital.org.np"
          />
        </div>
        <div>
          <Label htmlFor="invite-phone">Phone</Label>
          <Input
            id="invite-phone"
            value={phone}
            onChange={(event) => setPhone(event.target.value)}
            placeholder="98…"
          />
        </div>

        {mayAssign && grantable.length > 0 && (
          <div className="rounded-md border p-3">
            <label className="flex items-center gap-2 text-sm">
              <input
                type="checkbox"
                checked={withRole}
                onChange={(event) => setWithRole(event.target.checked)}
                className="h-4 w-4"
              />
              <ShieldCheck className="h-4 w-4 text-muted-foreground" />
              Give them a role now
            </label>
            {withRole && (
              <div className="mt-3 space-y-3">
                <Select
                  value={code}
                  onChange={(event) => setCode(event.target.value)}
                  aria-label="Role"
                >
                  {grantable.map((role) => (
                    <option key={role.code} value={role.code}>
                      {role.name}
                    </option>
                  ))}
                </Select>
                <Select
                  value={facility}
                  onChange={(event) => setFacility(event.target.value)}
                  aria-label="Facility"
                >
                  {facilities.map((option) => (
                    <option key={option.uuid} value={option.uuid}>
                      {option.name}
                    </option>
                  ))}
                </Select>
              </div>
            )}
          </div>
        )}

        <p className={cn("text-xs text-muted-foreground")}>
          No password is set here. They choose their own — a password somebody
          else typed for you is not a credential.
        </p>
      </div>
    </DetailPanel>
  );
}
