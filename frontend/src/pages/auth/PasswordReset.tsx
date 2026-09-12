/**
 * Forgotten passwords: ask for a link, then choose a new password from it.
 *
 * Two screens, one file, because they are one journey. The wording follows
 * the backend's rules and does not undo them: the first screen says the same
 * thing whether or not the address is registered, and the second checks the
 * link *before* asking for a password typed twice, so an expired link is
 * found out at the start rather than after the effort.
 */

import { useEffect, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { ArrowLeft, Check, Eye, EyeOff, KeyRound, Mail, MailCheck } from "lucide-react";

import api, { ApiError, SIGN_IN_NOTICE_KEY } from "@/lib/api";
import { cn } from "@/lib/utils";
import { Spinner } from "@/components/ui/loader";
import { Alert, AlertDescription, Button, Input, Label } from "@/components/ui/primitives";
import { AuthShell } from "@/pages/auth/AuthShell";

function Aside() {
  return (
    <div className="flex h-full flex-col justify-center">
      <KeyRound className="h-10 w-10 text-hero-foreground/80" />
      <h2 className="mt-6 max-w-md font-display text-4xl font-semibold leading-tight tracking-tight">
        Back in, safely.
      </h2>
      <ul className="mt-6 max-w-md space-y-3 text-[15px] leading-relaxed text-hero-foreground/85">
        <li>The link works once, for 30 minutes.</li>
        <li>Every device signed in to your account is signed out.</li>
        <li>If you use two-step sign-in, you still need your code.</li>
      </ul>
    </div>
  );
}

const backToSignIn = (
  <Link to="/login" className="flex items-center gap-1.5 text-muted-foreground hover:text-foreground">
    <ArrowLeft className="h-4 w-4" />
    Sign in
  </Link>
);

export function ForgotPasswordPage() {
  const [email, setEmail] = useState("");
  const [busy, setBusy] = useState(false);
  const [sent, setSent] = useState<string | null>(null);
  const [problem, setProblem] = useState<string | null>(null);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true);
    setProblem(null);
    try {
      const body = await api.post<{ detail: string }>("/auth/password/forgot/", { email });
      setSent(body.detail);
    } catch (err) {
      setProblem(err instanceof ApiError ? err.message : "That did not go through. Try again.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <AuthShell corner={backToSignIn} aside={<Aside />}>
      <div className="w-full max-w-[22rem]">
        {sent ? (
          <div className="space-y-4">
            <MailCheck className="h-10 w-10 text-primary" />
            <h1 className="font-display text-[1.75rem] font-semibold leading-tight tracking-tight">
              Check your email
            </h1>
            <p className="text-muted-foreground">{sent}</p>
            <p className="text-sm text-muted-foreground">
              Nothing after a few minutes? Check spam, or ask your administrator to
              issue a temporary password from People.
            </p>
            <div className="flex gap-2 pt-2">
              <Button variant="outline" onClick={() => setSent(null)}>
                Use another address
              </Button>
              <Button asChild>
                <Link to="/login">Sign in</Link>
              </Button>
            </div>
          </div>
        ) : (
          <form onSubmit={submit} className="space-y-5">
            <div>
              <h1 className="font-display text-[1.75rem] font-semibold leading-tight tracking-tight">
                Reset your password
              </h1>
              <p className="mt-1.5 text-muted-foreground">
                Enter your work email and we will send you a link.
              </p>
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="email">Work email</Label>
              <div className="relative">
                <Mail className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
                <Input
                  id="email"
                  type="email"
                  autoComplete="username"
                  autoFocus
                  required
                  placeholder="you@hospital.com.np"
                  value={email}
                  onChange={(event) => setEmail(event.target.value)}
                  className="h-11 pl-9"
                />
              </div>
            </div>
            {problem ? (
              <Alert variant="destructive">
                <AlertDescription>{problem}</AlertDescription>
              </Alert>
            ) : null}
            <Button type="submit" className="h-11 w-full" disabled={busy || !email.includes("@")}>
              {busy ? <Spinner size="sm" className="mr-2" /> : null}
              Send link
            </Button>
          </form>
        )}
      </div>
    </AuthShell>
  );
}

export function ResetPasswordPage() {
  const [params] = useSearchParams();
  const navigate = useNavigate();
  const uid = params.get("uid") ?? "";
  const token = params.get("token") ?? "";

  const [link, setLink] = useState<"checking" | "good" | "bad">("checking");
  const [linkProblem, setLinkProblem] = useState<string | null>(null);
  const [email, setEmail] = useState("");
  const [next, setNext] = useState("");
  const [again, setAgain] = useState("");
  const [shown, setShown] = useState(false);
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);

  useEffect(() => {
    if (!uid || !token) {
      setLink("bad");
      setLinkProblem("This link is incomplete. Open it from the email again, or ask for a new one.");
      return;
    }
    api
      .get<{ valid: boolean; email: string }>(
        `/auth/password/reset/?uid=${encodeURIComponent(uid)}&token=${encodeURIComponent(token)}`,
      )
      .then((body) => {
        setEmail(body.email);
        setLink("good");
      })
      .catch((err) => {
        setLink("bad");
        setLinkProblem(err instanceof ApiError ? err.message : "This link could not be checked.");
      });
  }, [uid, token]);

  const rules = [
    { ok: next.length >= 10, label: "At least 10 characters" },
    { ok: next.length > 0 && !/^\d+$/.test(next), label: "Not only numbers" },
    { ok: next.length > 0 && next === again, label: "Both entries match" },
  ];
  const ready = rules.every((rule) => rule.ok);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true);
    setProblem(null);
    try {
      await api.post("/auth/password/reset/", { uid, token, new_password: next });
      try {
        sessionStorage.setItem(SIGN_IN_NOTICE_KEY, "Password changed. Sign in with your new password.");
      } catch {
        /* storage blocked: sign-in shows no notice */
      }
      navigate("/login", { replace: true });
    } catch (err) {
      setProblem(err instanceof ApiError ? err.message : "Your password was not changed.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <AuthShell corner={backToSignIn} aside={<Aside />}>
      <div className="w-full max-w-[22rem]">
        {link === "checking" ? (
          <div className="flex items-center gap-2 text-muted-foreground">
            <Spinner size="sm" /> Checking your link…
          </div>
        ) : link === "bad" ? (
          <div className="space-y-4">
            <h1 className="font-display text-[1.75rem] font-semibold leading-tight tracking-tight">
              Link expired
            </h1>
            <p className="text-muted-foreground">{linkProblem}</p>
            <Button asChild>
              <Link to="/forgot-password">Send a new link</Link>
            </Button>
          </div>
        ) : (
          <form onSubmit={submit} className="space-y-5">
            <div>
              <h1 className="font-display text-[1.75rem] font-semibold leading-tight tracking-tight">
                Choose a new password
              </h1>
              <p className="mt-1.5 text-muted-foreground">For {email}</p>
            </div>
            {/* The username field lets a password manager save the pair. */}
            <input type="email" autoComplete="username" value={email} readOnly hidden />
            <div className="space-y-1.5">
              <Label htmlFor="next">New password</Label>
              <div className="relative">
                <Input
                  id="next"
                  type={shown ? "text" : "password"}
                  autoComplete="new-password"
                  autoFocus
                  required
                  value={next}
                  onChange={(event) => setNext(event.target.value)}
                  className="h-11 pr-10"
                />
                <button
                  type="button"
                  onClick={() => setShown((value) => !value)}
                  aria-label={shown ? "Hide password" : "Show password"}
                  className="absolute right-2 top-1/2 -translate-y-1/2 rounded-sm p-1.5 text-muted-foreground hover:text-foreground"
                >
                  {shown ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
                </button>
              </div>
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="again">Confirm password</Label>
              <Input
                id="again"
                type={shown ? "text" : "password"}
                autoComplete="new-password"
                required
                value={again}
                onChange={(event) => setAgain(event.target.value)}
                className="h-11"
              />
            </div>
            <ul className="space-y-1 text-sm">
              {rules.map((rule) => (
                <li key={rule.label} className={cn("flex items-center gap-2", rule.ok ? "text-good" : "text-muted-foreground")}>
                  <Check className={cn("h-4 w-4", !rule.ok && "opacity-30")} />
                  {rule.label}
                </li>
              ))}
            </ul>
            {problem ? (
              <Alert variant="destructive">
                <AlertDescription>{problem}</AlertDescription>
              </Alert>
            ) : null}
            <Button type="submit" className="h-11 w-full" disabled={!ready || busy}>
              {busy ? <Spinner size="sm" className="mr-2" /> : null}
              Save password
            </Button>
          </form>
        )}
      </div>
    </AuthShell>
  );
}
