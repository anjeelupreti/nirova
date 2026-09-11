/**
 * The second step of signing in, when two-step sign-in is on.
 *
 * One field. Six digits from the authenticator app, typed on whatever keyboard
 * the person has — `inputMode="numeric"` brings up the number pad on a phone,
 * and `autoComplete="one-time-code"` lets the operating system offer the code
 * itself. It submits the moment the sixth digit arrives, because the code is
 * about to expire and every extra tap is a chance to miss the window.
 *
 * The way out of a lost phone is on the same screen — a recovery code — so a
 * nurse at the start of a night shift is not sent looking for it.
 */

import { useEffect, useRef, useState } from "react";
import { ArrowLeft, KeyRound, ShieldCheck } from "lucide-react";

import { ApiError } from "@/lib/api";
import type { UseSession } from "@/hooks/useSession";
import { Spinner } from "@/components/ui/loader";
import { Alert, AlertDescription, Button, Input, Label } from "@/components/ui/primitives";

export function SecondFactorStep({
  session,
  challenge,
  onBack,
}: {
  session: UseSession;
  challenge: string;
  onBack: () => void;
}) {
  const [code, setCode] = useState("");
  const [recovery, setRecovery] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const field = useRef<HTMLInputElement>(null);

  const submit = async (value: string) => {
    if (busy) return;
    setBusy(true);
    setError(null);
    try {
      await session.verifySecondFactor(challenge, value);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not check the code. Try again.");
      setCode("");
      if (err instanceof ApiError && err.code === "challenge_expired") onBack();
      window.setTimeout(() => field.current?.focus(), 0);
    } finally {
      setBusy(false);
    }
  };

  useEffect(() => {
    field.current?.focus();
  }, [recovery]);

  return (
    <div className="w-full max-w-[22rem]">
      <span className="grid h-12 w-12 place-items-center rounded-2xl bg-primary/10 text-primary">
        <ShieldCheck className="h-6 w-6" />
      </span>
      <h1 className="mt-5 font-display text-[1.75rem] font-semibold leading-tight tracking-tight">
        Two-step sign-in
      </h1>
      <p className="mt-1.5 text-muted-foreground">
        {recovery
          ? "Enter one of the recovery codes you saved when you set this up. Each works once."
          : "Enter the six-digit code from your authenticator app."}
      </p>

      <form
        className="mt-7 space-y-4"
        onSubmit={(event) => {
          event.preventDefault();
          void submit(code);
        }}
      >
        <div className="space-y-1.5">
          <Label htmlFor="second-factor">{recovery ? "Recovery code" : "Code"}</Label>
          <Input
            ref={field}
            id="second-factor"
            value={code}
            disabled={busy}
            autoComplete="one-time-code"
            inputMode={recovery ? "text" : "numeric"}
            placeholder={recovery ? "abcd-efgh" : "123 456"}
            maxLength={recovery ? 9 : 6}
            onChange={(event) => {
              const next = recovery
                ? event.target.value.toLowerCase()
                : event.target.value.replace(/\D/g, "").slice(0, 6);
              setCode(next);
              if (!recovery && next.length === 6) void submit(next);
            }}
            className={
              recovery
                ? "h-12 font-mono text-lg tracking-widest"
                : "h-14 text-center font-mono text-2xl tracking-[0.5em]"
            }
          />
        </div>

        {error && (
          <Alert variant="destructive">
            <AlertDescription>{error}</AlertDescription>
          </Alert>
        )}

        <Button type="submit" className="h-11 w-full" disabled={busy || code.length < (recovery ? 9 : 6)}>
          {busy ? <Spinner size="sm" /> : null}
          Verify
        </Button>
      </form>

      <div className="mt-6 flex items-center justify-between text-sm">
        <button
          type="button"
          onClick={onBack}
          className="flex items-center gap-1 text-muted-foreground hover:text-foreground"
        >
          <ArrowLeft className="h-4 w-4" />
          Back
        </button>
        <button
          type="button"
          onClick={() => {
            setRecovery((value) => !value);
            setCode("");
            setError(null);
          }}
          className="flex items-center gap-1 font-medium text-primary hover:underline"
        >
          <KeyRound className="h-4 w-4" />
          {recovery ? "Use the app instead" : "Use a recovery code"}
        </button>
      </div>
      <p className="mt-6 text-xs text-muted-foreground">
        Lost your phone and your recovery codes? Your administrator can reset
        two-step sign-in after checking it is you.
      </p>
    </div>
  );
}
