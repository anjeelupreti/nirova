/**
 * The discussion about one patient: staff talking to staff, on the record.
 *
 * **Where this conversation used to happen was a phone.** "BP dropping in bed
 * 4, can you review" went by text message or a shout down a corridor, and left
 * nothing: no time, no name, nothing the next shift could read. Here it is on
 * the patient, where the context is, visible to everybody treating them, and
 * kept.
 *
 * **Telling somebody is explicit.** A colleague added to a message is notified
 * through the bell -- with an urgent message raised as a warning -- and a link
 * straight back here. Nobody is paged by a message they were merely able to
 * read.
 *
 * **Live.** A new message rings the patient's doorbell, so a conversation on a
 * record two people have open reads like one. The list is re-read through the
 * API, where access to the patient is checked.
 */

import { useCallback, useEffect, useRef, useState } from "react";
import { AlertTriangle, Loader2, Send, X } from "lucide-react";

import api, { ApiError } from "@/lib/api";
import { listen } from "@/lib/live";
import { cn } from "@/lib/utils";
import { formatDateTime } from "@/lib/dates";
import { Avatar } from "@/components/ui/data";
import { EmptyState } from "@/components/ui/feedback";
import { StatusBadge } from "@/components/ui/status";
import { Alert, AlertDescription, Button, Input, Textarea } from "@/components/ui/primitives";

interface Colleague {
  id: string;
  name: string;
}

interface CareMessage {
  uuid: string;
  author_id: string | null;
  author_name: string;
  body: string;
  urgent: boolean;
  mentions: Colleague[];
  created_at: string;
  is_mine: boolean;
}

export function CareDiscussion({ patientUuid }: { patientUuid: string }) {
  const [messages, setMessages] = useState<CareMessage[] | null>(null);
  const [refused, setRefused] = useState<string | null>(null);
  const [problem, setProblem] = useState<string | null>(null);
  const [body, setBody] = useState("");
  const [urgent, setUrgent] = useState(false);
  const [notify, setNotify] = useState<Colleague[]>([]);
  const [search, setSearch] = useState("");
  const [suggestions, setSuggestions] = useState<Colleague[]>([]);
  const [sending, setSending] = useState(false);
  const bottom = useRef<HTMLDivElement | null>(null);

  const load = useCallback(async () => {
    try {
      const response = await api.get<{ results: CareMessage[] }>(
        `/clinical/patients/${patientUuid}/discussion/`,
      );
      setMessages(response.results);
      setRefused(null);
    } catch (err) {
      if (err instanceof ApiError && err.status === 403) setRefused(err.message);
      else setProblem(err instanceof ApiError ? err.message : "The discussion could not be read.");
    }
  }, [patientUuid]);

  useEffect(() => {
    void load();
    return listen(`patient.${patientUuid}`, () => void load());
  }, [load, patientUuid]);

  useEffect(() => {
    bottom.current?.scrollIntoView({ block: "nearest" });
  }, [messages?.length]);

  // Colleague search: two letters before asking, and only the latest answer.
  useEffect(() => {
    const term = search.trim();
    if (term.length < 2) {
      setSuggestions([]);
      return;
    }
    let live = true;
    const timer = window.setTimeout(() => {
      void api
        .get<{ results: Colleague[] }>(`/clinical/colleagues/?q=${encodeURIComponent(term)}`)
        .then((response) => {
          if (live) {
            setSuggestions(response.results.filter((row) => !notify.some((chosen) => chosen.id === row.id)));
          }
        })
        .catch(() => live && setSuggestions([]));
    }, 250);
    return () => {
      live = false;
      window.clearTimeout(timer);
    };
  }, [search, notify]);

  async function send() {
    if (!body.trim()) return;
    setSending(true);
    setProblem(null);
    try {
      await api.post(`/clinical/patients/${patientUuid}/discussion/`, {
        body,
        urgent,
        mentions: notify.map((row) => row.id),
      });
      setBody("");
      setUrgent(false);
      setNotify([]);
      await load();
    } catch (err) {
      setProblem(err instanceof ApiError ? err.message : "The message was not sent.");
    } finally {
      setSending(false);
    }
  }

  if (refused) {
    return (
      <EmptyState
        title="This discussion is closed to you"
        description={refused}
      />
    );
  }

  return (
    <div className="space-y-4">
      <div className="rounded-xl border border-border/60 bg-card p-4 shadow-raised">
        {messages === null ? (
          <p className="flex items-center gap-2 py-6 type-caption">
            <Loader2 className="h-4 w-4 animate-spin" /> Reading the discussion…
          </p>
        ) : messages.length === 0 ? (
          <EmptyState
            illustration="people"
            title="No discussion yet"
            description="Messages between the people treating this patient appear here, with who wrote them and when."
          />
        ) : (
          <ol className="space-y-4">
            {messages.map((message) => (
              <li
                key={message.uuid}
                className={cn("flex gap-3", message.is_mine && "flex-row-reverse text-right")}
              >
                <Avatar name={message.author_name || "?"} size="sm" />
                <div className={cn("min-w-0 max-w-[80%] space-y-1", message.is_mine && "items-end")}>
                  <p className="text-xs text-muted-foreground">
                    <span className="font-medium text-foreground">{message.author_name}</span>
                    {" · "}
                    {formatDateTime(message.created_at)}
                  </p>
                  <div
                    className={cn(
                      "inline-block whitespace-pre-line rounded-2xl px-3.5 py-2 text-left text-sm",
                      message.is_mine ? "bg-primary-subtle text-foreground" : "bg-muted",
                      message.urgent && "ring-2 ring-warning/60",
                    )}
                  >
                    {message.body}
                  </div>
                  {message.urgent || message.mentions.length > 0 ? (
                    <div className={cn("flex flex-wrap gap-1", message.is_mine && "justify-end")}>
                      {message.urgent ? <StatusBadge status="warning" label="Urgent" /> : null}
                      {message.mentions.map((person) => (
                        <span key={person.id} className="rounded-full bg-muted px-2 py-0.5 text-[0.6875rem] text-muted-foreground">
                          told {person.name}
                        </span>
                      ))}
                    </div>
                  ) : null}
                </div>
              </li>
            ))}
            <div ref={bottom} />
          </ol>
        )}
      </div>

      <div className="space-y-3 rounded-xl border border-border/60 bg-card p-4 shadow-raised">
        <Textarea
          aria-label="Message"
          rows={3}
          value={body}
          placeholder="Write to the team treating this patient…"
          onChange={(event) => setBody(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === "Enter" && (event.ctrlKey || event.metaKey)) void send();
          }}
        />

        <div className="flex flex-wrap items-start gap-2">
          <div className="relative min-w-[14rem] flex-1">
            <Input
              aria-label="Notify a colleague"
              placeholder="Notify a colleague…"
              value={search}
              onChange={(event) => setSearch(event.target.value)}
            />
            {suggestions.length > 0 ? (
              <ul className="absolute z-20 mt-1 w-full overflow-hidden rounded-lg border bg-popover shadow-floating">
                {suggestions.map((person) => (
                  <li key={person.id}>
                    <button
                      type="button"
                      className="flex w-full items-center gap-2 px-3 py-2 text-left text-sm hover:bg-accent"
                      onClick={() => {
                        setNotify((current) => [...current, person]);
                        setSearch("");
                        setSuggestions([]);
                      }}
                    >
                      <Avatar name={person.name} size="xs" />
                      {person.name}
                    </button>
                  </li>
                ))}
              </ul>
            ) : null}
          </div>
          <label className="flex h-9 items-center gap-2 text-sm">
            <input type="checkbox" checked={urgent} onChange={(event) => setUrgent(event.target.checked)} />
            <AlertTriangle className="h-4 w-4 text-warning" />
            Urgent
          </label>
          <Button disabled={sending || !body.trim()} onClick={() => void send()}>
            {sending ? <Loader2 className="mr-1.5 h-4 w-4 animate-spin" /> : <Send className="mr-1.5 h-4 w-4" />}
            Send
          </Button>
        </div>

        {notify.length > 0 ? (
          <div className="flex flex-wrap gap-1.5">
            {notify.map((person) => (
              <span key={person.id} className="inline-flex items-center gap-1.5 rounded-full bg-primary-subtle py-0.5 pl-1 pr-2 text-xs text-primary-subtle-foreground">
                <Avatar name={person.name} size="xs" />
                {person.name}
                <button
                  type="button"
                  aria-label={`Do not notify ${person.name}`}
                  onClick={() => setNotify((current) => current.filter((row) => row.id !== person.id))}
                >
                  <X className="h-3 w-3" />
                </button>
              </span>
            ))}
          </div>
        ) : null}

        <p className="text-xs text-muted-foreground">
          Visible to everybody treating this patient, and kept on the record. Only the colleagues
          you add are notified. Ctrl+Enter sends.
        </p>

        {problem ? (
          <Alert variant="destructive">
            <AlertDescription>{problem}</AlertDescription>
          </Alert>
        ) : null}
      </div>
    </div>
  );
}
