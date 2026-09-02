/**
 * The live OPD queue and today's provider availability.
 *
 * The screen a front desk keeps open all day. It polls rather than
 * subscribing: a queue changes every few minutes, not every few seconds, and
 * a WebSocket that must survive a Nepali clinic's connectivity is a lot of
 * machinery for a number that can be a few seconds stale without harm.
 */

import { useCallback, useEffect, useState } from "react";
import {
  BellRing,
  CheckCircle2,
  Clock,
  PlayCircle,
  Siren,
  Users,
} from "lucide-react";

import api from "@/lib/api";
import { cn } from "@/lib/utils";
import type { Facility, Paginated, QueueResponse, SessionAvailability } from "@/types";
import {
  Badge,
  Button,
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
  Progress,
  Select,
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/primitives";

const REFRESH_MS = 15000;

const STATUS_VARIANT: Record<
  string,
  "default" | "secondary" | "warning" | "success" | "destructive"
> = {
  waiting: "secondary",
  called: "warning",
  in_service: "default",
  completed: "success",
  skipped: "destructive",
  left: "destructive",
};

function StatTile({
  label,
  value,
  tone = "default",
  icon: Icon,
}: {
  label: string;
  value: number | string;
  tone?: "default" | "warning" | "danger";
  icon: typeof Users;
}) {
  const toneClass = {
    default: "text-foreground",
    warning: "text-amber-600",
    danger: "text-destructive",
  }[tone];

  return (
    <Card>
      <CardContent className="flex items-center gap-3 py-4">
        <Icon className="h-5 w-5 text-muted-foreground" />
        <div>
          <p className={cn("text-2xl font-semibold leading-none", toneClass)}>
            {value}
          </p>
          <p className="mt-1 text-xs text-muted-foreground">{label}</p>
        </div>
      </CardContent>
    </Card>
  );
}

export default function QueuePage() {
  const [facilities, setFacilities] = useState<Facility[]>([]);
  const [facilityUuid, setFacilityUuid] = useState("");
  const [queue, setQueue] = useState<QueueResponse | null>(null);
  const [sessions, setSessions] = useState<SessionAvailability[]>([]);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    api
      .get<Paginated<Facility>>("/org/facilities/")
      .then((page) => {
        const usable = page.results.filter((f) => f.status === "active");
        setFacilities(usable);
        const clinic =
          usable.find((f) => f.facility_type === "clinic") ?? usable[0];
        if (clinic) setFacilityUuid(clinic.uuid);
      })
      .catch(() => undefined);
  }, []);

  const load = useCallback(async () => {
    if (!facilityUuid) return;
    const [queueData, availability] = await Promise.all([
      api.get<QueueResponse>(`/clinical/queue/?facility=${facilityUuid}`),
      api.get<{ sessions: SessionAvailability[] }>(
        `/clinical/availability/?facility=${facilityUuid}`,
      ),
    ]);
    setQueue(queueData);
    setSessions(availability.sessions);
  }, [facilityUuid]);

  useEffect(() => {
    void load();
    const handle = setInterval(() => void load(), REFRESH_MS);
    return () => clearInterval(handle);
  }, [load]);

  async function act(path: string, body?: unknown) {
    setBusy(true);
    try {
      await api.post(path, body);
      await load();
    } finally {
      setBusy(false);
    }
  }

  const stats = queue?.statistics;

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <h1 className="text-xl font-semibold tracking-tight">Queue</h1>
          <p className="mt-1 text-sm text-muted-foreground">
            Live OPD queue, refreshing every {REFRESH_MS / 1000} seconds.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <Select
            className="h-9 w-auto"
            value={facilityUuid}
            onChange={(e) => setFacilityUuid(e.target.value)}
          >
            {facilities.map((facility) => (
              <option key={facility.uuid} value={facility.uuid}>
                {facility.name}
              </option>
            ))}
          </Select>
          <Button
            disabled={busy || !facilityUuid}
            onClick={() =>
              void act("/clinical/queue/call-next/", {
                facility_uuid: facilityUuid,
              })
            }
          >
            <BellRing className="h-4 w-4" />
            Call next
          </Button>
        </div>
      </div>

      {stats && (
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-5">
          <StatTile label="Waiting" value={stats.waiting} icon={Users} />
          <StatTile
            label="In consultation"
            value={stats.in_service}
            icon={PlayCircle}
          />
          <StatTile
            label="Completed"
            value={stats.completed}
            icon={CheckCircle2}
          />
          <StatTile
            label="Emergencies"
            value={stats.emergencies}
            tone={stats.emergencies > 0 ? "danger" : "default"}
            icon={Siren}
          />
          <StatTile
            label="Average wait (min)"
            value={stats.average_wait_minutes}
            // Thirty minutes is the point at which a waiting room starts to
            // feel broken, so that is where the colour changes.
            tone={
              stats.average_wait_minutes > 45
                ? "danger"
                : stats.average_wait_minutes > 30
                  ? "warning"
                  : "default"
            }
            icon={Clock}
          />
        </div>
      )}

      <div className="grid gap-6 lg:grid-cols-3">
        <Card className="lg:col-span-2">
          <CardHeader className="pb-3">
            <CardTitle>Now waiting</CardTitle>
            <CardDescription>
              Ordered as patients will actually be seen — priority first, then
              arrival.
            </CardDescription>
          </CardHeader>
          <CardContent>
            {!queue || queue.queue.length === 0 ? (
              <p className="text-sm text-muted-foreground">
                Nobody is in the queue.
              </p>
            ) : (
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Token</TableHead>
                    <TableHead>Patient</TableHead>
                    <TableHead>Status</TableHead>
                    <TableHead>Waited</TableHead>
                    <TableHead className="text-right">Action</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {queue.queue.map((token) => (
                    <TableRow
                      key={token.uuid}
                      className={token.is_emergency ? "bg-destructive/5" : undefined}
                    >
                      <TableCell className="font-mono font-medium">
                        {token.token_number}
                        {token.is_emergency && (
                          <Siren className="ml-1 inline h-3.5 w-3.5 text-destructive" />
                        )}
                      </TableCell>
                      <TableCell>
                        <div className="font-medium">{token.patient_name}</div>
                        <div className="text-xs text-muted-foreground">
                          {token.patient_mrn}
                        </div>
                      </TableCell>
                      <TableCell>
                        <Badge variant={STATUS_VARIANT[token.status] ?? "secondary"}>
                          {token.status.replace(/_/g, " ")}
                        </Badge>
                      </TableCell>
                      <TableCell
                        className={
                          token.waiting_minutes > 45
                            ? "font-medium text-destructive"
                            : undefined
                        }
                      >
                        {token.waiting_minutes}m
                      </TableCell>
                      <TableCell className="text-right">
                        {token.status === "called" && (
                          <Button
                            size="sm"
                            variant="outline"
                            disabled={busy}
                            onClick={() =>
                              void act(`/clinical/queue/${token.uuid}/start/`)
                            }
                          >
                            Start
                          </Button>
                        )}
                        {token.status === "in_service" && (
                          <Button
                            size="sm"
                            variant="outline"
                            disabled={busy}
                            onClick={() =>
                              void act(`/clinical/queue/${token.uuid}/complete/`)
                            }
                          >
                            Complete
                          </Button>
                        )}
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="pb-3">
            <CardTitle>Today's clinics</CardTitle>
            <CardDescription>Remaining capacity per session.</CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            {sessions.length === 0 ? (
              <p className="text-sm text-muted-foreground">
                No sessions run today.
              </p>
            ) : (
              sessions.map((session) => (
                <div key={session.schedule_uuid} className="space-y-1.5">
                  <div className="flex items-baseline justify-between gap-2">
                    <span className="text-sm font-medium">
                      {session.provider_name}
                    </span>
                    <span className="text-xs text-muted-foreground">
                      {session.start_time.slice(0, 5)}–
                      {session.end_time.slice(0, 5)}
                    </span>
                  </div>
                  <Progress
                    value={session.booked}
                    max={session.capacity}
                    tone={
                      session.remaining_capacity === 0
                        ? "danger"
                        : session.remaining_capacity <= 3
                          ? "warning"
                          : "default"
                    }
                  />
                  <p className="text-xs text-muted-foreground">
                    {session.booked} booked · {session.remaining_capacity} left
                    {session.next_free &&
                      ` · next ${session.next_free.slice(11, 16)}`}
                  </p>
                </div>
              ))
            )}
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
