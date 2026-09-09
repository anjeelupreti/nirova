/**
 * The live OPD queue and today's provider availability.
 *
 * The screen a front desk keeps open all day. It polls rather than
 * subscribing: a queue changes every few minutes, not every few seconds, and
 * a WebSocket that must survive a Nepali clinic's connectivity is a lot of
 * machinery for a number that can be a few seconds stale without harm.
 */

import { useCallback, useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import {
  BellRing,
  CheckCircle2,
  Clock,
  PlayCircle,
  Siren,
  Stethoscope,
  Users,
} from "lucide-react";

import api from "@/lib/api";
import type {
  Facility,
  Paginated,
  QueueResponse,
  QueueToken as QueueTokenRow,
  SessionAvailability,
} from "@/types";
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
import { Avatar, StatTile } from "@/components/ui/data";
import {
  EmptyState,
  StatSkeleton,
  TableSkeleton,
} from "@/components/ui/feedback";
import { Page, PageHeader, StatGrid } from "@/components/ui/layout";
import {
  RecordPanel,
  status,
  useRecordPanel,
} from "@/components/RecordPanel";

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


export default function QueuePage() {
  // Opening a token. The list row already carries the MRN, the chief
  // complaint, the priority, how long they have waited and how many times
  // they have been called -- the table shows three of those and this shows
  // the rest, without a second request.
  const panel = useRecordPanel<QueueTokenRow>();
  const navigate = useNavigate();
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

  /**
   * Open the consultation for a token.
   *
   * Creates the encounter first, then navigates. The server returns the
   * existing open encounter if there is one, so clicking twice lands on the
   * same chart rather than splitting a visit across two records.
   */
  async function openConsultation(token: QueueTokenRow) {
    setBusy(true);
    try {
      const encounter = await api.post<{ uuid: string }>(
        "/clinical/encounters/",
        {
          patient_uuid: token.patient_uuid,
          facility_uuid: facilityUuid,
          queue_token_uuid: token.uuid,
          chief_complaint: token.chief_complaint ?? "",
        },
      );
      navigate(`/consultation/${encounter.uuid}`);
    } finally {
      setBusy(false);
    }
  }

  const stats = queue?.statistics;

  return (
    <Page>
      <PageHeader
        title="Queue"
        description={`Live OPD queue, refreshing every ${REFRESH_MS / 1000} seconds.`}
        actions={
          <>
            <Select
              className="h-9 w-auto"
              value={facilityUuid}
              onChange={(e) => setFacilityUuid(e.target.value)}
              aria-label="Facility"
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
          </>
        }
      />

      {/* A skeleton in the shape of the tiles rather than nothing, so the
          page does not grow by 90px the moment the first poll returns. */}
      {!stats ? (
        <StatSkeleton count={5} />
      ) : (
        <StatGrid className="xl:grid-cols-5">
          <StatTile
            label="Waiting"
            value={stats.waiting}
            icon={<Users className="h-4 w-4" />}
          />
          <StatTile
            label="In consultation"
            value={stats.in_service}
            icon={<PlayCircle className="h-4 w-4" />}
          />
          <StatTile
            label="Completed"
            value={stats.completed}
            icon={<CheckCircle2 className="h-4 w-4" />}
          />
          <StatTile
            label="Emergencies"
            value={stats.emergencies}
            icon={<Siren className="h-4 w-4" />}
            delta={stats.emergencies > 0 ? "needs attention" : undefined}
            intent={stats.emergencies > 0 ? "bad" : "neutral"}
          />
          <StatTile
            label="Average wait"
            value={`${stats.average_wait_minutes} min`}
            icon={<Clock className="h-4 w-4" />}
            // Thirty minutes is where a waiting room starts to feel broken,
            // and forty-five is where people leave. The intent says what the
            // number means rather than which way it moved.
            delta={
              stats.average_wait_minutes > 45
                ? "too long"
                : stats.average_wait_minutes > 30
                  ? "getting long"
                  : "comfortable"
            }
            intent={
              stats.average_wait_minutes > 45
                ? "bad"
                : stats.average_wait_minutes > 30
                  ? "neutral"
                  : "good"
            }
          />
        </StatGrid>
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
            {!queue ? (
              <TableSkeleton rows={5} columns={5} />
            ) : queue.queue.length === 0 ? (
              <EmptyState
                illustration="people"
                title="Nobody is waiting"
                description={
                  "Tokens appear here as patients check in at the desk. "
                  + "The board refreshes on its own."
                }
              />
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
                      {...panel.rowProps(
                        token,
                        token.is_emergency ? "bg-destructive/5" : undefined,
                      )}
                    >
                      <TableCell className="font-mono font-medium">
                        {token.token_number}
                        {token.is_emergency && (
                          <Siren className="ml-1 inline h-3.5 w-3.5 text-destructive" />
                        )}
                      </TableCell>
                      <TableCell>
                        {/* An avatar, so a queue reads as people rather than
                            as a column of names. The colour is derived from
                            the name, so the same patient is the same colour
                            every time this board refreshes. */}
                        <div className="flex items-center gap-3">
                          <Avatar name={token.patient_name} size="sm" />
                          <div className="min-w-0">
                            <div className="truncate font-medium">
                              {token.patient_name}
                            </div>
                            <div className="text-xs text-muted-foreground">
                              {token.patient_mrn}
                            </div>
                          </div>
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
                      {/* The action cell stops the click: pressing Start
                          should start, not also open a panel behind it. */}
                      <TableCell className="text-right" {...panel.stopProps}>
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
                          <div className="flex justify-end gap-1.5">
                            <Button
                              size="sm"
                              disabled={busy}
                              onClick={() => void openConsultation(token)}
                            >
                              <Stethoscope className="h-4 w-4" />
                              Consult
                            </Button>
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
                          </div>
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

      <RecordPanel
        row={panel.open}
        onClose={panel.close}
        spec={{
          title: (token) => token.patient_name,
          subtitle: (token) =>
            `Token ${token.token_number} · ${token.patient_mrn}`,
          sections: [
            {
              heading: "In the queue",
              fields: [
                { label: "Status", value: (t) => status(t.status) },
                { label: "Waited", value: (t) => `${t.waiting_minutes} min` },
                {
                  label: "Called",
                  value: (t) =>
                    t.call_count === 1 ? "Once" : `${t.call_count} times`,
                  // Hidden rather than dashed when nobody has called them:
                  // "0 times" is noise on the row that matters least.
                  when: (t) => t.call_count > 0,
                },
                { label: "Counter", value: (t) => t.counter },
                {
                  label: "Priority",
                  value: (t) => (t.is_emergency ? "Emergency" : String(t.priority)),
                },
              ],
            },
            {
              heading: "Why they came",
              fields: [
                {
                  label: "Chief complaint",
                  value: (t) => t.chief_complaint ?? "",
                },
              ],
            },
          ],
          actions: (token) =>
            token.status === "in_service" ? (
              <Button className="w-full" onClick={() => void openConsultation(token)}>
                <Stethoscope className="mr-2 h-4 w-4" />
                Open consultation
              </Button>
            ) : null,
        }}
      />
    </Page>
  );
}
