/**
 * My account: who I am, my password, and how I want the interface to behave.
 *
 * The screen this product had no equivalent of. Signing in gave you a name in
 * the header and a Sign out button; there was no way to correct your own
 * surname, no way to change your password, and no preferences at all.
 *
 * **Three sections and they are deliberately not one form.** Details are typed
 * and submitted. A password is a different act with a different risk and its
 * own confirmation. Preferences save the moment they are touched, because a
 * theme toggle with a Save button underneath it is a theme toggle nobody
 * believes.
 */

import { useCallback, useEffect, useState } from "react";
import { Check, KeyRound, Loader2, ShieldAlert, UserCog } from "lucide-react";

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
  Input,
  Label,
  Select,
} from "@/components/ui/primitives";
import { TwoStepSignIn } from "@/components/account/TwoStepSignIn";
import { Avatar } from "@/components/ui/data";
import { CardSkeleton } from "@/components/ui/feedback";
import { Page, PageHeader, Section } from "@/components/ui/layout";
import { usePreferences, type Preferences } from "@/hooks/usePreferences";
import api, { ApiError, tokenStore } from "@/lib/api";

interface PreferenceChoice {
  value: string;
  label: string;
}

interface PreferenceSpec {
  key: keyof Preferences;
  label: string;
  description: string;
  kind: "choice" | "boolean";
  default: unknown;
  choices: PreferenceChoice[];
}

interface Me {
  uuid: string;
  email: string;
  full_name: string;
  preferred_name: string;
  phone: string;
  avatar_url: string;
  locale: string;
  timezone: string;
  mfa_enabled: boolean;
  must_change_password: boolean;
  password_changed_at: string | null;
  last_active_at: string | null;
  is_platform_staff: boolean;
  preferences: Preferences;
  preference_catalogue: PreferenceSpec[];
}

function when(value: string | null): string {
  if (!value) return "never";
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime())
    ? "never"
    : parsed.toLocaleDateString(undefined, {
        year: "numeric",
        month: "short",
        day: "numeric",
      });
}

export default function AccountPage() {
  const [me, setMe] = useState<Me | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setError(null);
    try {
      setMe(await api.get<Me>("/auth/me/"));
    } catch (err) {
      setError(
        err instanceof ApiError ? err.message : "Could not load your account.",
      );
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  if (error) {
    return (
      <Page>
        <PageHeader title="My account" />
        <Alert variant="warning">
          <AlertTitle>Not shown</AlertTitle>
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      </Page>
    );
  }

  if (!me) {
    return (
      <Page>
        <PageHeader title="My account" />
        <CardSkeleton count={3} />
      </Page>
    );
  }

  return (
    <Page>
      <PageHeader
        title="My account"
        description="Profile, password and preferences."
        actions={
          me.is_platform_staff ? (
            <Badge variant="secondary">Platform operator</Badge>
          ) : undefined
        }
      />

      {me.must_change_password && (
        <Alert variant="warning">
          <AlertTitle>Your password needs changing</AlertTitle>
          <AlertDescription>
            Somebody set this account up for you. Choose a password only you
            know before doing anything else.
          </AlertDescription>
        </Alert>
      )}

      <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_320px]">
        <div className="space-y-6">
          <Details me={me} onSaved={setMe} />
          <Password me={me} onChanged={load} />
          <TwoStepSignIn />
        </div>
        <PreferencePanel catalogue={me.preference_catalogue} />
      </div>
    </Page>
  );
}

/* -------------------------------------------------------------------------- */
/* Details                                                                     */
/* -------------------------------------------------------------------------- */

function Details({ me, onSaved }: { me: Me; onSaved: (me: Me) => void }) {
  const [draft, setDraft] = useState({
    full_name: me.full_name,
    preferred_name: me.preferred_name,
    phone: me.phone,
  });
  const [saving, setSaving] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);

  const dirty =
    draft.full_name !== me.full_name ||
    draft.preferred_name !== me.preferred_name ||
    draft.phone !== me.phone;

  async function save() {
    setSaving(true);
    setProblem(null);
    try {
      const updated = await api.patch<Me>("/auth/me/", draft);
      onSaved(updated);
      setSaved(true);
      // The confirmation clears itself. A tick that stays forever stops
      // meaning "just saved" and starts meaning nothing.
      window.setTimeout(() => setSaved(false), 2500);
    } catch (err) {
      setProblem(
        err instanceof ApiError ? err.message : "That could not be saved.",
      );
    } finally {
      setSaving(false);
    }
  }

  return (
    <Card>
      <CardHeader>
        <div className="flex items-center gap-4">
          <Avatar name={me.full_name} src={me.avatar_url} size="lg" />
          <div className="min-w-0">
            <CardTitle className="flex items-center gap-2">
              <UserCog className="h-4 w-4 text-muted-foreground" />
              Your details
            </CardTitle>
            <CardDescription>{me.email}</CardDescription>
          </div>
        </div>
      </CardHeader>

      <CardContent className="space-y-4">
        {problem && (
          <Alert variant="warning">
            <AlertTitle>Not saved</AlertTitle>
            <AlertDescription>{problem}</AlertDescription>
          </Alert>
        )}

        <div className="grid gap-4 sm:grid-cols-2">
          <div>
            <Label htmlFor="full_name">Full name</Label>
            <Input
              id="full_name"
              value={draft.full_name}
              onChange={(event) =>
                setDraft({ ...draft, full_name: event.target.value })
              }
            />
          </div>
          <div>
            <Label htmlFor="preferred_name">Preferred name</Label>
            <Input
              id="preferred_name"
              value={draft.preferred_name}
              onChange={(event) =>
                setDraft({ ...draft, preferred_name: event.target.value })
              }
              placeholder="What colleagues call you"
            />
          </div>
          <div>
            <Label htmlFor="phone">Phone</Label>
            <Input
              id="phone"
              value={draft.phone}
              onChange={(event) =>
                setDraft({ ...draft, phone: event.target.value })
              }
              placeholder="98…"
            />
          </div>
          <div>
            <Label htmlFor="email">Email</Label>
            <Input id="email" value={me.email} disabled />
            {/* Said here rather than discovered by trying. An email is the
                login, so changing it needs a verified round trip to the new
                address, and nothing in this system can send one yet. */}
            <p className="mt-1 text-xs text-muted-foreground">
              This is your login. An administrator can move you to a new
              address.
            </p>
          </div>
        </div>
      </CardContent>

      <div className="flex items-center gap-3 border-t px-6 py-4">
        <Button disabled={!dirty || saving} onClick={() => void save()}>
          {saving && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
          Save changes
        </Button>
        {saved && (
          <span className="flex items-center gap-1.5 text-sm text-good animate-in fade-in-0">
            <Check className="h-4 w-4" />
            Saved
          </span>
        )}
      </div>
    </Card>
  );
}

/* -------------------------------------------------------------------------- */
/* Password                                                                    */
/* -------------------------------------------------------------------------- */

function Password({ me, onChanged }: { me: Me; onChanged: () => void }) {
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [confirm, setConfirm] = useState("");
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);
  const [note, setNote] = useState<string | null>(null);

  // Checked here as well as on the server, because "the two do not match" is
  // a typo the person can fix without a round trip -- and the server never
  // sees the confirmation field at all, since it has nothing to do with it.
  const mismatch = confirm.length > 0 && next !== confirm;
  const ready = current.length > 0 && next.length > 0 && !mismatch;

  async function change() {
    setBusy(true);
    setProblem(null);
    setNote(null);
    try {
      const body = await api.post<{ note: string; access: string; refresh: string }>("/auth/me/password/", {
        current_password: current,
        new_password: next,
      });
      // The change ends every session that predates it, this one included;
      // the fresh pair keeps this device signed in.
      tokenStore.set(body.access, body.refresh);
      setCurrent("");
      setNext("");
      setConfirm("");
      setNote(body.note);
      onChanged();
    } catch (err) {
      setProblem(
        err instanceof ApiError ? err.message : "That could not be changed.",
      );
    } finally {
      setBusy(false);
    }
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <KeyRound className="h-4 w-4 text-muted-foreground" />
          Password
        </CardTitle>
        <CardDescription>
          Last changed {when(me.password_changed_at)}.
        </CardDescription>
      </CardHeader>

      <CardContent className="space-y-4">
        {problem && (
          <Alert variant="warning">
            <AlertTitle>Not changed</AlertTitle>
            <AlertDescription>{problem}</AlertDescription>
          </Alert>
        )}
        {note && (
          <Alert>
            <AlertTitle>Password changed</AlertTitle>
            <AlertDescription>{note}</AlertDescription>
          </Alert>
        )}

        <div className="grid gap-4 sm:grid-cols-3">
          <div>
            <Label htmlFor="current">Current password</Label>
            <Input
              id="current"
              type="password"
              autoComplete="current-password"
              value={current}
              onChange={(event) => setCurrent(event.target.value)}
            />
          </div>
          <div>
            <Label htmlFor="next">New password</Label>
            <Input
              id="next"
              type="password"
              autoComplete="new-password"
              value={next}
              onChange={(event) => setNext(event.target.value)}
            />
          </div>
          <div>
            <Label htmlFor="confirm">Repeat it</Label>
            <Input
              id="confirm"
              type="password"
              autoComplete="new-password"
              value={confirm}
              onChange={(event) => setConfirm(event.target.value)}
              aria-invalid={mismatch}
            />
            {mismatch && (
              <p className="mt-1 text-xs text-destructive">
                These two do not match.
              </p>
            )}
          </div>
        </div>

        <p className="flex items-start gap-2 text-xs text-muted-foreground">
          <ShieldAlert className="mt-0.5 h-3.5 w-3.5 shrink-0" />
          Your current password is required. Without it, anyone who found this
          screen already open could lock you out of your own account.
        </p>
      </CardContent>

      <div className="border-t px-6 py-4">
        <Button disabled={!ready || busy} onClick={() => void change()}>
          {busy && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
          Change password
        </Button>
      </div>
    </Card>
  );
}

/* -------------------------------------------------------------------------- */
/* Preferences                                                                 */
/* -------------------------------------------------------------------------- */

function PreferencePanel({ catalogue }: { catalogue: PreferenceSpec[] }) {
  const { preferences, update } = usePreferences();

  return (
    <Card className="h-fit">
      <CardHeader>
        <CardTitle>Preferences</CardTitle>
        <CardDescription>
          Saved as you change them, and they follow you to any machine you sign
          in on.
        </CardDescription>
      </CardHeader>

      <CardContent className="space-y-5">
        {/* Rendered from the server's catalogue, so a preference added in
            Python appears here next release with no change to this file. */}
        {catalogue.map((spec) => (
          <Section key={spec.key} className="space-y-1.5">
            <Label htmlFor={`pref-${spec.key}`} className="text-sm font-medium">
              {spec.label}
            </Label>

            {spec.kind === "boolean" ? (
              <label className="flex items-start gap-2 text-sm">
                <input
                  id={`pref-${spec.key}`}
                  type="checkbox"
                  className="mt-0.5 h-4 w-4"
                  checked={Boolean(preferences[spec.key])}
                  onChange={(event) =>
                    update({ [spec.key]: event.target.checked } as Partial<Preferences>)
                  }
                />
                <span className="text-muted-foreground">{spec.description}</span>
              </label>
            ) : (
              <>
                <Select
                  id={`pref-${spec.key}`}
                  value={String(preferences[spec.key])}
                  onChange={(event) =>
                    update({ [spec.key]: event.target.value } as Partial<Preferences>)
                  }
                >
                  {spec.choices.map((choice) => (
                    <option key={choice.value} value={choice.value}>
                      {choice.label}
                    </option>
                  ))}
                </Select>
                <p className="text-xs text-muted-foreground">
                  {spec.description}
                </p>
              </>
            )}
          </Section>
        ))}
      </CardContent>
    </Card>
  );
}
