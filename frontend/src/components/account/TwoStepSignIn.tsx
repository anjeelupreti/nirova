/**
 * Turning two-step sign-in on, and living with it.
 *
 * Four states, each with one thing to do:
 *
 *  - **Off** — what it is and why, in a sentence, and one button.
 *  - **Scanning** — the QR code, the key written out for anyone whose camera
 *    will not focus on a screen, and a field for the first code. Nothing is
 *    switched on until that code proves the app has the secret; a half-set-up
 *    second factor is how people lock themselves out.
 *  - **Codes** — the ten recovery codes, shown this once, with copy and print.
 *    The server keeps only hashes, so the screen says plainly that this is the
 *    last time they can be seen.
 *  - **On** — when it was switched on, how many recovery codes are left, and
 *    the two things one occasionally needs: new codes, or turning it off —
 *    which asks for the password and a code, because a session left open on a
 *    ward computer must not be enough to weaken the account.
 */

import { useCallback, useEffect, useState } from "react";
import { Check, Copy, KeyRound, Printer, ShieldCheck, ShieldOff } from "lucide-react";

import api, { ApiError } from "@/lib/api";
import { printElement } from "@/lib/export";
import {
  Alert,
  AlertDescription,
  Badge,
  Button,
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
  Input,
  Label,
} from "@/components/ui/primitives";
import { Spinner } from "@/components/ui/loader";
import { formatDate } from "@/lib/dates";

interface Status {
  enabled: boolean;
  enabled_at: string | null;
  recovery_codes_left: number;
}

type Stage =
  | { kind: "idle" }
  | { kind: "scanning"; secret: string; uri: string; svg: string }
  | { kind: "codes"; codes: string[] }
  | { kind: "disabling" }
  | { kind: "regenerating" };

export function TwoStepSignIn({ onEnabled }: { onEnabled?: () => void } = {}) {
  const [status, setStatus] = useState<Status | null>(null);
  const [stage, setStage] = useState<Stage>({ kind: "idle" });
  const [code, setCode] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      setStatus(await api.get<Status>("/auth/me/mfa/"));
    } catch {
      setStatus({ enabled: false, enabled_at: null, recovery_codes_left: 0 });
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const act = async <T,>(body: Record<string, unknown>): Promise<T | null> => {
    setBusy(true);
    setProblem(null);
    try {
      return await api.post<T>("/auth/me/mfa/", body);
    } catch (err) {
      setProblem(err instanceof ApiError ? err.message : "That did not work. Try again.");
      return null;
    } finally {
      setBusy(false);
    }
  };

  const begin = async () => {
    const started = await act<{ secret: string; uri: string }>({ action: "begin" });
    if (!started) return;
    // Loaded only here: the QR library has no business in the bundle every
    // page load pays for.
    const QRCode = await import("qrcode");
    const svg = await QRCode.toString(started.uri, { type: "svg", margin: 1, width: 184 });
    setCode("");
    setStage({ kind: "scanning", ...started, svg });
  };

  const confirm = async () => {
    const done = await act<{ recovery_codes: string[] }>({ action: "confirm", code });
    if (!done) return;
    setCode("");
    setStage({ kind: "codes", codes: done.recovery_codes });
    void load();
  };

  // Told once the recovery codes have been acknowledged, not at the moment it
  // switches on — lifting the enrolment gate would otherwise whisk the codes
  // off the screen before anybody saved them.
  const acknowledged = () => {
    setStage({ kind: "idle" });
    onEnabled?.();
  };

  const regenerate = async () => {
    const done = await act<{ recovery_codes: string[] }>({ action: "regenerate", code });
    if (!done) return;
    setCode("");
    setStage({ kind: "codes", codes: done.recovery_codes });
    void load();
  };

  const disable = async () => {
    const done = await act({ action: "disable", code, password });
    if (!done) return;
    setCode("");
    setPassword("");
    setStage({ kind: "idle" });
    void load();
  };

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <ShieldCheck className="h-4 w-4 text-muted-foreground" />
          Two-step sign-in
          {status?.enabled && <Badge variant="success">On</Badge>}
        </CardTitle>
        <CardDescription>
          A code from your phone as well as your password, so a password that
          is seen, guessed or shared is not enough to sign in as you.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        {problem && (
          <Alert variant="destructive">
            <AlertDescription>{problem}</AlertDescription>
          </Alert>
        )}

        {!status ? (
          <Spinner size="sm" />
        ) : stage.kind === "codes" ? (
          <RecoveryCodes codes={stage.codes} onDone={acknowledged} />
        ) : stage.kind === "scanning" ? (
          <div className="grid gap-5 sm:grid-cols-[auto_1fr]">
            <div
              className="h-[184px] w-[184px] overflow-hidden rounded-lg border bg-white p-1"
              aria-label="QR code for your authenticator app"
              // Generated locally from the otpauth link; no third-party QR service
              // ever sees the secret.
              dangerouslySetInnerHTML={{ __html: stage.svg }}
            />
            <div className="space-y-3 text-sm">
              <ol className="list-decimal space-y-1 pl-5 text-muted-foreground">
                <li>Open Google Authenticator, Microsoft Authenticator or a similar app.</li>
                <li>Add an account and scan this code.</li>
                <li>Type the six-digit code the app shows.</li>
              </ol>
              <details className="text-xs text-muted-foreground">
                <summary className="cursor-pointer">Can't scan? Enter the key instead</summary>
                <code className="mt-1 block break-all rounded bg-muted px-2 py-1 font-mono text-foreground">
                  {stage.secret.match(/.{1,4}/g)?.join(" ")}
                </code>
              </details>
              <div className="flex gap-2">
                <Input
                  aria-label="Code from the app"
                  inputMode="numeric"
                  autoComplete="one-time-code"
                  placeholder="123456"
                  maxLength={6}
                  value={code}
                  onChange={(event) => setCode(event.target.value.replace(/\D/g, "").slice(0, 6))}
                  className="h-10 w-32 text-center font-mono tracking-[0.3em]"
                />
                <Button disabled={busy || code.length !== 6} onClick={() => void confirm()}>
                  {busy && <Spinner size="sm" />}
                  Turn on
                </Button>
                <Button variant="ghost" onClick={() => setStage({ kind: "idle" })}>
                  Cancel
                </Button>
              </div>
            </div>
          </div>
        ) : status.enabled ? (
          <div className="space-y-4">
            <p className="text-sm text-muted-foreground">
              On since{" "}
              {status.enabled_at
                ? formatDate(status.enabled_at)
                : "—"}
              . {status.recovery_codes_left} of 10 recovery codes left
              {status.recovery_codes_left <= 3 && " — make new ones before you run out"}.
            </p>

            {stage.kind === "disabling" || stage.kind === "regenerating" ? (
              <div className="space-y-3 rounded-lg border p-3">
                {stage.kind === "disabling" && (
                  <div className="space-y-1.5">
                    <Label htmlFor="mfa-password">Your password</Label>
                    <Input
                      id="mfa-password"
                      type="password"
                      autoComplete="current-password"
                      value={password}
                      onChange={(event) => setPassword(event.target.value)}
                    />
                  </div>
                )}
                <div className="space-y-1.5">
                  <Label htmlFor="mfa-code">
                    {stage.kind === "disabling" ? "A code from the app, or a recovery code" : "A code from the app"}
                  </Label>
                  <Input
                    id="mfa-code"
                    autoComplete="one-time-code"
                    value={code}
                    onChange={(event) => setCode(event.target.value.trim())}
                    className="font-mono"
                  />
                </div>
                <div className="flex gap-2">
                  {stage.kind === "disabling" ? (
                    <Button variant="destructive" disabled={busy || !password || !code} onClick={() => void disable()}>
                      <ShieldOff className="h-4 w-4" />
                      Turn off
                    </Button>
                  ) : (
                    <Button disabled={busy || code.length !== 6} onClick={() => void regenerate()}>
                      <KeyRound className="h-4 w-4" />
                      Make new codes
                    </Button>
                  )}
                  <Button variant="ghost" onClick={() => setStage({ kind: "idle" })}>
                    Cancel
                  </Button>
                </div>
              </div>
            ) : (
              <div className="flex flex-wrap gap-2">
                <Button variant="outline" size="sm" onClick={() => { setCode(""); setStage({ kind: "regenerating" }); }}>
                  <KeyRound className="h-4 w-4" />
                  New recovery codes
                </Button>
                <Button variant="ghost" size="sm" onClick={() => { setCode(""); setStage({ kind: "disabling" }); }}>
                  <ShieldOff className="h-4 w-4" />
                  Turn off
                </Button>
              </div>
            )}
          </div>
        ) : (
          <Button onClick={() => void begin()} disabled={busy}>
            {busy ? <Spinner size="sm" /> : <ShieldCheck className="h-4 w-4" />}
            Set up two-step sign-in
          </Button>
        )}
      </CardContent>
    </Card>
  );
}

function RecoveryCodes({ codes, onDone }: { codes: string[]; onDone: () => void }) {
  const [copied, setCopied] = useState(false);

  return (
    <div className="space-y-3">
      <Alert variant="warning">
        <AlertDescription>
          Save these now — this is the only time they are shown. Each one signs
          you in once if you do not have your phone. Keep them somewhere other
          than the phone.
        </AlertDescription>
      </Alert>
      <div id="recovery-codes" data-printable className="rounded-lg border bg-muted/30 p-4">
        <p className="mb-2 hidden text-sm font-semibold print:block">Nirova recovery codes</p>
        <ol className="grid grid-cols-2 gap-x-6 gap-y-1.5 font-mono text-sm">
          {codes.map((code) => (
            <li key={code}>{code}</li>
          ))}
        </ol>
      </div>
      <div className="flex flex-wrap gap-2">
        <Button
          variant="outline"
          size="sm"
          onClick={() => {
            void navigator.clipboard?.writeText(codes.join("\n")).then(() => setCopied(true));
          }}
        >
          {copied ? <Check className="h-4 w-4" /> : <Copy className="h-4 w-4" />}
          {copied ? "Copied" : "Copy"}
        </Button>
        <Button variant="outline" size="sm" onClick={() => printElement("recovery-codes")}>
          <Printer className="h-4 w-4" />
          Print
        </Button>
        <Button size="sm" onClick={onDone}>
          I have saved them
        </Button>
      </div>
    </div>
  );
}
