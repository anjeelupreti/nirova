/**
 * Telling everybody something.
 *
 * The one notification a person writes rather than the system raising. The
 * endpoint has existed since notifications were built and had no way in from
 * the console, so an owner who wanted to say "the OPD is closed on Saturday"
 * had a WhatsApp group and nothing else — which means it is not on the record
 * and the night staff who joined last week never see it.
 *
 * Two things it will not do.
 *
 * **It cannot be critical.** Critical is what a potassium of 6.9 is. A
 * category that cannot be silenced must be reserved for the things nobody may
 * silence, or people learn to ignore it — and then a real one arrives.
 *
 * **Email is a choice, not the default.** Most announcements belong on the
 * screen. The one that does not — a closure, a strike, a system outage — is
 * the sender's judgement, and they say so by ticking the box.
 */

import { useState } from "react";
import { Megaphone, Send } from "lucide-react";

import api, { ApiError } from "@/lib/api";
import {
  Alert,
  AlertDescription,
  Button,
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
  Input,
  Label,
  Select,
  Textarea,
} from "@/components/ui/primitives";

export function AnnouncementComposer({ onSent }: { onSent: () => void }) {
  const [open, setOpen] = useState(false);
  const [title, setTitle] = useState("");
  const [body, setBody] = useState("");
  const [category, setCategory] = useState("information");
  const [alsoEmail, setAlsoEmail] = useState(false);
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);
  const [sent, setSent] = useState<string | null>(null);

  async function send() {
    setBusy(true);
    setProblem(null);
    try {
      const body_ = await api.post<{ sent: number; emailed: boolean }>(
        "/notifications/announce/",
        { title, body, category, also_email: alsoEmail },
      );
      setSent(
        `Sent to ${body_.sent} ${body_.sent === 1 ? "person" : "people"}` +
          (body_.emailed ? ", and by email." : "."),
      );
      setTitle("");
      setBody("");
      setAlsoEmail(false);
      setOpen(false);
      onSent();
    } catch (err) {
      setProblem(err instanceof ApiError ? err.message : "That could not be sent.");
    } finally {
      setBusy(false);
    }
  }

  if (!open) {
    return (
      <div className="space-y-2">
        {sent ? (
          <Alert>
            <AlertDescription>{sent}</AlertDescription>
          </Alert>
        ) : null}
        <Button variant="outline" size="sm" onClick={() => setOpen(true)}>
          <Megaphone className="h-4 w-4" />
          Announce
        </Button>
      </div>
    );
  }

  return (
    <Card>
      <CardHeader className="pb-3">
        <CardTitle className="flex items-center gap-2 text-base">
          <Megaphone className="h-4 w-4 text-muted-foreground" />
          Tell everybody
        </CardTitle>
        <CardDescription>
          Goes to everyone with an account here, and stays on the record.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-3">
        {problem ? (
          <Alert variant="destructive">
            <AlertDescription>{problem}</AlertDescription>
          </Alert>
        ) : null}

        <div className="grid gap-3 sm:grid-cols-[1fr_12rem]">
          <div className="space-y-1">
            <Label className="text-xs">What is happening</Label>
            <Input
              autoFocus
              placeholder="Outpatients closed on Saturday"
              value={title}
              onChange={(event) => setTitle(event.target.value)}
            />
          </div>
          <div className="space-y-1">
            <Label className="text-xs">Kind</Label>
            <Select value={category} onChange={(event) => setCategory(event.target.value)}>
              <option value="information">Information</option>
              <option value="warning">Warning</option>
              <option value="reminder">Reminder</option>
            </Select>
          </div>
        </div>

        <div className="space-y-1">
          <Label className="text-xs">The detail people need</Label>
          <Textarea
            rows={3}
            placeholder="Emergency stays open. Booked appointments have been moved to Sunday and patients have been called."
            value={body}
            onChange={(event) => setBody(event.target.value)}
          />
        </div>

        <label className="flex items-center gap-2 text-sm">
          <input
            type="checkbox"
            className="h-4 w-4"
            checked={alsoEmail}
            onChange={(event) => setAlsoEmail(event.target.checked)}
          />
          Email it as well — for something people need to know before their next shift
        </label>

        <div className="flex gap-2">
          <Button disabled={!title.trim() || busy} onClick={() => void send()}>
            <Send className="h-4 w-4" />
            Send
          </Button>
          <Button variant="ghost" onClick={() => setOpen(false)}>
            Cancel
          </Button>
        </div>
      </CardContent>
    </Card>
  );
}
