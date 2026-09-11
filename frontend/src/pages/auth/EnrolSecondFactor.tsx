/**
 * Shown instead of the application when the organization requires two-step
 * sign-in and this person has not set it up.
 *
 * The API refuses everything else in this state (`SecondFactorRequired`), so
 * showing the application would be a screen of refusals. This says what
 * changed, why, and walks through the setup — the same card as My account, so
 * there is one way to do it — and opens the application the moment it is done.
 */

import { LogOut, ShieldCheck } from "lucide-react";

import type { UseSession } from "@/hooks/useSession";
import { TwoStepSignIn } from "@/components/account/TwoStepSignIn";
import { Button } from "@/components/ui/primitives";
import { AuthShell } from "@/pages/auth/AuthShell";

export function EnrolSecondFactor({
  session,
  organization,
}: {
  session: UseSession;
  organization: string;
}) {
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
          <ShieldCheck className="h-10 w-10 text-hero-foreground/80" />
          <h2 className="mt-6 max-w-md font-display text-4xl font-semibold leading-tight tracking-tight">
            Your password, and your phone.
          </h2>
          <p className="mt-4 max-w-md text-[15px] leading-relaxed text-hero-foreground/85">
            Passwords are seen, guessed and shared on a busy shift. With a code
            from your phone as well, a password alone is no longer enough to
            open patient records in your name.
          </p>
        </div>
      }
    >
      <div className="w-full max-w-xl space-y-5">
        <div>
          <h1 className="font-display text-[1.75rem] font-semibold leading-tight tracking-tight">
            Set up two-step sign-in
          </h1>
          <p className="mt-1.5 text-muted-foreground">
            {organization} now requires it for everyone. It takes about a
            minute, and you will need a phone with an authenticator app.
          </p>
        </div>
        <TwoStepSignIn onEnabled={() => void session.refresh()} />
        <Button variant="ghost" size="sm" onClick={() => void session.refresh()}>
          I have finished — continue
        </Button>
      </div>
    </AuthShell>
  );
}
