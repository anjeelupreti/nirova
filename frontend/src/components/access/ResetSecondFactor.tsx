/**
 * "Reset two-step sign-in" — for the phone that is gone with the recovery
 * codes in the same pocket.
 *
 * Asks for a reason, because the server requires one and because it should:
 * this weakens how somebody signs in without them asking, and the audit trail
 * is where anyone reviewing it later will look. The prompt suggests what a
 * good reason says — that identity was checked, and how.
 */

import { useState } from "react";
import { Loader2, ShieldOff } from "lucide-react";

import api, { ApiError } from "@/lib/api";
import { Button, Input } from "@/components/ui/primitives";

export function ResetSecondFactor({
  uuid,
  name,
  onDone,
}: {
  uuid: string;
  name: string;
  onDone: () => void;
}) {
  const [open, setOpen] = useState(false);
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);

  const reset = async () => {
    setBusy(true);
    setProblem(null);
    try {
      await api.post(`/admin/staff/${uuid}/mfa-reset/`, { reason });
      setOpen(false);
      onDone();
    } catch (err) {
      setProblem(err instanceof ApiError ? err.message : "It was not reset.");
    } finally {
      setBusy(false);
    }
  };

  if (!open) {
    return (
      <Button variant="outline" onClick={() => setOpen(true)}>
        <ShieldOff className="mr-2 h-4 w-4" />
        Reset two-step sign-in
      </Button>
    );
  }

  return (
    <div className="w-full space-y-2 rounded-lg border p-3 text-sm">
      <p>
        {name} will sign in with their password alone until they set it up
        again. Why is it being reset?
      </p>
      <Input
        autoFocus
        value={reason}
        placeholder="Lost phone — identity checked in person on the ward"
        onChange={(event) => setReason(event.target.value)}
      />
      {problem && <p className="text-xs text-destructive">{problem}</p>}
      <div className="flex gap-2">
        <Button size="sm" disabled={busy || reason.trim().length < 5} onClick={() => void reset()}>
          {busy && <Loader2 className="h-4 w-4 animate-spin" />}
          Reset it
        </Button>
        <Button size="sm" variant="ghost" onClick={() => setOpen(false)}>
          Cancel
        </Button>
      </div>
    </div>
  );
}
