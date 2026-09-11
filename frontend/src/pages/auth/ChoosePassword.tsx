/**
 * Choose your own password — before anything else.
 *
 * Shown instead of the whole application while `must_change_password` is set,
 * which is the case after an administrator has issued a temporary one. The
 * Account page used to carry a banner saying "you should change your
 * password" and nothing stopped anybody working on for months with a password
 * their administrator had read out to them — which is to say, a password two
 * people knew.
 *
 * The rules shown are the server's rules (ten characters, not common, not all
 * digits); the checklist ticks as they are met so nobody learns them from a
 * refusal.
 */

import { useState } from "react";
import { Check, KeyRound, LogOut } from "lucide-react";

import api, { ApiError } from "@/lib/api";
import { cn } from "@/lib/utils";
import type { UseSession } from "@/hooks/useSession";
import { Alert, AlertDescription, Button, Input, Label } from "@/components/ui/primitives";
import { Spinner } from "@/components/ui/loader";
import { AuthShell } from "@/pages/auth/AuthShell";

export function ChoosePassword({ session, name }: { session: UseSession; name: string }) {
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [again, setAgain] = useState("");
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);

  const rules = [
    { ok: next.length >= 10, label: "At least ten characters" },
    { ok: next.length > 0 && !/^\d+$/.test(next), label: "Not only numbers" },
    { ok: next.length > 0 && next !== current, label: "Different from the temporary one" },
    { ok: next.length > 0 && next === again, label: "Typed the same twice" },
  ];
  const ready = current.length > 0 && rules.every((rule) => rule.ok);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true);
    setProblem(null);
    try {
      await api.post("/auth/me/password/", { current_password: current, new_password: next });
      await session.refresh();
    } catch (err) {
      setProblem(err instanceof ApiError ? err.message : "Your password was not changed.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <AuthShell
      corner={
        <button
          type="button"
          onClick={session.logout}
          className="flex items-center gap-1.5 text-muted-foreground hover:text-foreground"
        >
          <LogOut className="h-4 w-4" />
          Sign out
        </button>
      }
      aside={
        <div className="flex h-full flex-col justify-center">
          <KeyRound className="h-10 w-10 text-hero-foreground/80" />
          <h2 className="mt-6 max-w-md font-display text-4xl font-semibold leading-tight tracking-tight">
            A password only you know.
          </h2>
          <p className="mt-4 max-w-md text-[15px] leading-relaxed text-hero-foreground/85">
            Every record you open is logged against your name. A password
            somebody else has read out to you is a password somebody else could
            use as you — so the temporary one stops working the moment you
            choose your own.
          </p>
        </div>
      }
    >
      <form onSubmit={submit} className="w-full max-w-[22rem] space-y-5">
        <div>
          <h1 className="font-display text-[1.75rem] font-semibold leading-tight tracking-tight">
            Choose your password
          </h1>
          <p className="mt-1.5 text-muted-foreground">
            Welcome{name ? `, ${name.split(" ")[0]}` : ""}. You signed in with a
            temporary password; replace it to continue.
          </p>
        </div>

        <div className="space-y-1.5">
          <Label htmlFor="current">Temporary password</Label>
          <Input id="current" type="password" autoComplete="current-password" value={current}
            onChange={(event) => setCurrent(event.target.value)} className="h-11" required />
        </div>
        <div className="space-y-1.5">
          <Label htmlFor="next">New password</Label>
          <Input id="next" type="password" autoComplete="new-password" value={next}
            onChange={(event) => setNext(event.target.value)} className="h-11" required />
        </div>
        <div className="space-y-1.5">
          <Label htmlFor="again">New password, again</Label>
          <Input id="again" type="password" autoComplete="new-password" value={again}
            onChange={(event) => setAgain(event.target.value)} className="h-11" required />
        </div>

        <ul className="space-y-1 text-sm">
          {rules.map((rule) => (
            <li key={rule.label} className={cn("flex items-center gap-2", rule.ok ? "text-good" : "text-muted-foreground")}>
              <Check className={cn("h-4 w-4", !rule.ok && "opacity-30")} />
              {rule.label}
            </li>
          ))}
        </ul>

        {problem && (
          <Alert variant="destructive">
            <AlertDescription>{problem}</AlertDescription>
          </Alert>
        )}

        <Button type="submit" className="h-11 w-full" disabled={!ready || busy}>
          {busy && <Spinner size="sm" className="mr-2" />}
          Save and continue
        </Button>
      </form>
    </AuthShell>
  );
}
