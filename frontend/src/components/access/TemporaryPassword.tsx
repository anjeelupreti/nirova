/**
 * "Issue a temporary password" — how somebody without one gets signed in.
 *
 * Shown once. The screen says how to hand it over, because the failure mode
 * of every temporary password is a sticky note on a monitor: read it out or
 * hand it over in person, and the holder replaces it the first time they sign
 * in (the server forces that; see `issue_temporary_password`).
 */

import { useState } from "react";
import { Check, Copy, KeyRound, Loader2 } from "lucide-react";

import api, { ApiError } from "@/lib/api";
import { Button } from "@/components/ui/primitives";

export function TemporaryPassword({ uuid, name }: { uuid: string; name: string }) {
  const [issued, setIssued] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);
  const [confirming, setConfirming] = useState(false);

  async function issue() {
    setBusy(true);
    setProblem(null);
    try {
      const result = await api.post<{ temporary_password: string }>(
        `/admin/staff/${uuid}/password/`,
        { reason: "Issued by an administrator" },
      );
      setIssued(result.temporary_password);
      setConfirming(false);
    } catch (err) {
      setProblem(err instanceof ApiError ? err.message : "No password was issued.");
    } finally {
      setBusy(false);
    }
  }

  if (issued) {
    return (
      <div className="w-full rounded-lg border border-primary/30 bg-primary/5 p-3 text-sm">
        <p className="font-medium">Temporary password for {name}</p>
        <div className="mt-2 flex items-center gap-2">
          <code className="flex-1 rounded-md border bg-background px-3 py-2 text-base font-semibold tracking-wider">
            {issued}
          </code>
          <Button
            size="icon"
            variant="outline"
            aria-label="Copy"
            onClick={() => {
              void navigator.clipboard?.writeText(issued);
              setCopied(true);
            }}
          >
            {copied ? <Check className="h-4 w-4 text-good" /> : <Copy className="h-4 w-4" />}
          </Button>
        </div>
        <p className="mt-2 text-xs text-muted-foreground">
          Shown once. Read it out or hand it over in person — not by message.
          They will be asked to choose their own the first time they sign in.
        </p>
      </div>
    );
  }

  return (
    <div className="flex flex-col items-start gap-1">
      {confirming ? (
        <div className="flex flex-wrap items-center gap-2 text-sm">
          <span className="text-muted-foreground">Their current password will stop working.</span>
          <Button size="sm" onClick={() => void issue()} disabled={busy}>
            {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : <KeyRound className="h-4 w-4" />}
            Issue it
          </Button>
          <Button size="sm" variant="ghost" onClick={() => setConfirming(false)}>
            Cancel
          </Button>
        </div>
      ) : (
        <Button variant="outline" onClick={() => setConfirming(true)}>
          <KeyRound className="mr-2 h-4 w-4" />
          Issue temporary password
        </Button>
      )}
      {problem && <p className="text-xs text-destructive">{problem}</p>}
    </div>
  );
}
