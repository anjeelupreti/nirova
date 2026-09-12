/**
 * Sign in — the first thing anybody sees, including a buyer.
 *
 * The form is deliberately plain and deliberately complete. Plain, because a
 * nurse signing in at the start of a night shift wants two fields and a
 * button. Complete, because every question somebody has on this screen should
 * have its answer on this screen:
 *
 *  - **"I've forgotten my password."** A link by email (see
 *    `auth/PasswordReset.tsx`): single-use, thirty minutes, every session
 *    signed out, and a second factor still asked for where one is on. The
 *    administrator's temporary password remains for anybody without mail.
 *  - **"Is it me, or is it down?"** The footer says whether the service is up.
 *  - **"We don't have an account — how do we start?"** Top right, and again
 *    under the form: register the hospital.
 *  - **"Who sees what I open?"** Every record opened is logged against the
 *    person, and the screen says so before they start.
 *
 * The right side is the product, legibly — see `AuthShell`.
 */

import { useState } from "react";
import { Link } from "react-router-dom";
import { ArrowRight, Eye, EyeOff, Info, Lock, Mail, ShieldCheck } from "lucide-react";

import { ApiError, SIGN_IN_NOTICE_KEY } from "@/lib/api";
import type { UseSession } from "@/hooks/useSession";
import { Spinner } from "@/components/ui/loader";
import { Alert, AlertDescription, Button, Input, Label } from "@/components/ui/primitives";
import { AuthShell } from "@/pages/auth/AuthShell";
import { ProductPreview } from "@/pages/auth/ProductPreview";
import { SecondFactorStep } from "@/pages/auth/SecondFactorStep";

export default function LoginPage({ session }: { session: UseSession }) {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  // Why they are here, when it was not by choice: the session expired, the
  // password changed, or they have just reset it. Shown once.
  const [notice] = useState<string | null>(() => {
    try {
      const value = sessionStorage.getItem(SIGN_IN_NOTICE_KEY);
      sessionStorage.removeItem(SIGN_IN_NOTICE_KEY);
      return value;
    } catch {
      return null;
    }
  });
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  // Set when the password was right and two-step sign-in is on.
  const [challenge, setChallenge] = useState<string | null>(null);

  async function handleSubmit(event: React.FormEvent) {
    event.preventDefault();
    setError(null);
    setBusy(true);
    try {
      const result = await session.login(email, password);
      if (result && "challenge" in result) setChallenge(result.challenge);
    } catch (err) {
      // The backend deliberately returns one message for both "no such user"
      // and "wrong password", so it is shown verbatim rather than
      // interpreted — reconstructing a distinction here would undo that.
      setError(err instanceof ApiError ? err.message : "Could not sign in. Try again.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <AuthShell
      corner={
        <span className="text-muted-foreground">
          New to Nirova?{" "}
          <Link to="/signup" className="font-medium text-primary hover:underline">
            Register your hospital
          </Link>
        </span>
      }
      aside={<LoginAside />}
    >
      {challenge ? (
        <SecondFactorStep
          session={session}
          challenge={challenge}
          onBack={() => {
            setChallenge(null);
            setPassword("");
          }}
        />
      ) : (
      <div className="w-full max-w-[22rem]">
        <h1 className="font-display text-[2rem] font-semibold leading-tight tracking-tight">
          Welcome back
        </h1>
        <p className="mt-1.5 text-muted-foreground">Sign in to your hospital's workspace.</p>

        {notice ? (
          <Alert className="mt-6">
            <Info className="h-4 w-4" />
            <AlertDescription>{notice}</AlertDescription>
          </Alert>
        ) : null}

        <form onSubmit={handleSubmit} className="mt-8 space-y-5" noValidate={false}>
          <div className="space-y-1.5">
            <Label htmlFor="email">Work email</Label>
            <div className="relative">
              <Mail className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
              <Input
                id="email"
                type="email"
                autoComplete="username"
                autoFocus
                placeholder="you@hospital.com.np"
                value={email}
                onChange={(event) => setEmail(event.target.value)}
                required
                className="h-11 pl-9"
              />
            </div>
          </div>

          <div className="space-y-1.5">
            <div className="flex items-center justify-between">
              <Label htmlFor="password">Password</Label>
              <Link to="/forgot-password" className="text-sm font-medium text-primary hover:underline">
                Forgot password?
              </Link>
            </div>
            <div className="relative">
              <Lock className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
              <Input
                id="password"
                type={showPassword ? "text" : "password"}
                autoComplete="current-password"
                value={password}
                onChange={(event) => setPassword(event.target.value)}
                required
                className="h-11 pl-9 pr-10"
              />
              {/*
                A reveal toggle, because the alternative is a nurse with
                gloves on mistyping a strong password three times and being
                locked out by the failed-login counter.
              */}
              <button
                type="button"
                onClick={() => setShowPassword((shown) => !shown)}
                aria-label={showPassword ? "Hide password" : "Show password"}
                className="absolute right-2 top-1/2 -translate-y-1/2 rounded-sm p-1.5 text-muted-foreground hover:text-foreground"
              >
                {showPassword ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
              </button>
            </div>
          </div>


          {error && (
            <Alert variant="destructive">
              <AlertDescription>{error}</AlertDescription>
            </Alert>
          )}

          <Button type="submit" className="h-11 w-full text-[15px]" disabled={busy}>
            {busy ? (
              <>
                <Spinner size="sm" className="mr-2" />
                Signing in…
              </>
            ) : (
              <>
                Sign in
                <ArrowRight className="h-4 w-4" />
              </>
            )}
          </Button>
        </form>

        <p className="mt-5 flex items-start gap-2 text-xs text-muted-foreground">
          <ShieldCheck className="mt-px h-4 w-4 shrink-0 text-good" />
          Every patient record you open is logged against your name, and your
          organization's data is held in its own database.
        </p>

        <div className="mt-10 border-t pt-6 text-sm text-muted-foreground">
          Running a hospital, clinic or pharmacy that isn't on Nirova yet?{" "}
          <Link to="/signup" className="font-medium text-primary hover:underline">
            Tell us about it
          </Link>
          .
        </div>
      </div>
      )}
    </AuthShell>
  );
}

function LoginAside() {
  return (
    <>
      <div className="max-w-xl">
        <p className="text-sm font-medium text-hero-foreground/80">Hospital operating system</p>
        <h2 className="mt-3 font-display text-4xl font-semibold leading-[1.1] tracking-tight xl:text-[2.75rem]">
          The whole hospital,
          <br />
          on one record.
        </h2>
        <p className="mt-4 max-w-md text-[15px] leading-relaxed text-hero-foreground/85">
          Emergency, wards, theatre, pharmacy and the bill — every department
          working from the same patient, as it happens.
        </p>
      </div>

      <div className="flex flex-1 items-center py-8">
        <ProductPreview />
      </div>

      <ul className="grid gap-4 text-sm text-hero-foreground/90 xl:grid-cols-3">
        <li>
          <p className="font-semibold text-hero-foreground">Built for Nepal</p>
          <p className="mt-0.5 text-hero-foreground/75">Bikram Sambat fiscal years and payroll months, PAN and VAT invoices, SSF and PF, and a patient app in Nepali.</p>
        </li>
        <li>
          <p className="font-semibold text-hero-foreground">Every access accountable</p>
          <p className="mt-0.5 text-hero-foreground/75">Roles you configure, break-glass with a reason, a full audit trail.</p>
        </li>
        <li>
          <p className="font-semibold text-hero-foreground">Your data, your database</p>
          <p className="mt-0.5 text-hero-foreground/75">Each organization on its own database, never pooled.</p>
        </li>
      </ul>
      <p className="mt-6 text-xs text-hero-foreground/60">Names and figures shown are illustrative.</p>
    </>
  );
}
