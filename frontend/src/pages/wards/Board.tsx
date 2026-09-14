/**
 * The bed board — the whiteboard at the nurses' station, made live.
 *
 * **What it replaced was a grid of pale boxes with a bed code and a name.**
 * Every ward whiteboard in the world carries more than that, because the
 * charge nurse runs the shift from it: how old, which night, going home today
 * or not, how sick at the last round, anything that changes how you approach
 * the bed. Those are the facts on each tile here, and nothing else — a tile
 * that tries to be the chart is a tile nobody can read from across a room.
 *
 * Every element earns its place by answering a question somebody at the desk
 * asks out loud:
 *
 *  - **The strip across the top** — "how full are we, and what can I admit
 *    into?" Each figure is also a filter, because the next thing anyone does
 *    after reading "3 free" is look for them.
 *  - **The occupancy bar per ward** — "which ward is the problem?" Occupied,
 *    being cleaned, out of service and free as one bar, so a ward with four
 *    broken beds reads as a maintenance problem rather than as a full ward.
 *  - **NEWS2 on the tile** — "who do I see first?" Quiet when routine, loud
 *    only when the score asks for a response; dashed when it is out of date.
 *  - **The due-home chip** — "whose bed frees up today?" The question every
 *    bed manager asks at ten in the morning.
 *  - **Free beds say what they can take** — a women's bay, oxygen, a monitor —
 *    because "a free bed" is not an answer to "where can this man on oxygen go?"
 *  - **Out-of-service beds are hatched and say why**, so nobody walks a
 *    patient to a bed with a broken rail.
 *
 * Clinical facts (diagnosis, NEWS2) arrive only for readers entitled to them;
 * the server decides, and a withheld value says it was withheld.
 */

import { useCallback, useEffect, useMemo, useState } from "react";
import {
  Activity,
  BedDouble,
  Clock,
  Gavel,
  HeartPulse,
  Home,
  Lock,
  RefreshCw,
  Search,
  ShieldAlert,
  Sparkles,
  UserPlus,
  Wind,
  Wrench,
} from "lucide-react";

import api, { ApiError } from "@/lib/api";
import { cn } from "@/lib/utils";
import { Button, Card, Input } from "@/components/ui/primitives";
import { EmptyState, ErrorState, Skeleton } from "@/components/ui/feedback";
import { News2Badge } from "@/components/clinical/News2";
import { formatTime } from "@/lib/dates";

/* -------------------------------------------------------------------------- */
/* Shape of GET /ipd/board/                                                    */
/* -------------------------------------------------------------------------- */

interface Occupant {
  admission: string;
  patient: string;
  name: string;
  mrn: string;
  gender: string;
  age: number | null;
  admitted_at: string;
  nights: number;
  expected_discharge: string | null;
  due: "today" | "overdue" | "tomorrow" | "discharging" | null;
  status: string;
  source: string;
  consultant: string;
  is_mlc: boolean;
  diagnosis: string | null;
  news2: {
    score: number;
    risk: string;
    recorded_at: string;
    stale: boolean;
    on_oxygen: boolean;
  } | null;
  clinical_restricted: boolean;
}

interface BoardBed {
  uuid: string;
  code: string;
  bay: string;
  status: "available" | "occupied" | "reserved" | "cleaning" | "maintenance" | "blocked";
  status_reason: string;
  status_changed_at: string;
  gender_restriction: "any" | "male" | "female";
  equipment: string[];
  is_isolation: boolean;
  occupant: Occupant | null;
}

interface Counts {
  beds: number;
  occupied: number;
  available: number;
  cleaning: number;
  reserved: number;
  out_of_service: number;
  due_home_today: number;
  discharging: number;
  high_news2: number;
}

interface BoardWard {
  uuid: string;
  code: string;
  name: string;
  ward_type: string;
  floor: string;
  building: string;
  is_critical_care: boolean;
  patients_per_nurse: string;
  is_gender_segregated: boolean;
  visiting_hours: string;
  counts: Counts;
  beds: BoardBed[];
}

interface BoardResponse {
  facility: { uuid: string; name: string };
  generated_at: string;
  clinical: boolean;
  totals: Counts;
  wards: BoardWard[];
}

type Focus = "all" | "free" | "home" | "review";

/* -------------------------------------------------------------------------- */

const clock = (iso: string) =>
  formatTime(iso);

const minutesSince = (iso: string) =>
  Math.max(0, Math.round((Date.now() - new Date(iso).getTime()) / 60_000));

const sexLetter = (gender: string) =>
  gender === "female" ? "F" : gender === "male" ? "M" : gender === "other" ? "X" : "";

function matchesFocus(bed: BoardBed, focus: Focus) {
  if (focus === "all") return true;
  if (focus === "free") return bed.status === "available" && !bed.occupant;
  if (focus === "home")
    return Boolean(bed.occupant && ["today", "overdue", "discharging"].includes(bed.occupant.due ?? ""));
  return Boolean(bed.occupant?.news2 && bed.occupant.news2.score >= 5);
}

function matchesSearch(bed: BoardBed, term: string) {
  if (!term) return true;
  const needle = term.toLowerCase();
  return (
    bed.code.toLowerCase().includes(needle) ||
    Boolean(bed.occupant?.name.toLowerCase().includes(needle)) ||
    Boolean(bed.occupant?.mrn.toLowerCase().includes(needle))
  );
}

/* -------------------------------------------------------------------------- */

export function WardBoard({
  facility,
  onOpen,
  onAdmit,
}: {
  facility: string;
  onOpen: (admission: string) => void;
  onAdmit: (wardUuid?: string) => void;
}) {
  const [board, setBoard] = useState<BoardResponse | null>(null);
  const [problem, setProblem] = useState<string | null>(null);
  const [refreshing, setRefreshing] = useState(false);
  const [focus, setFocus] = useState<Focus>("all");
  const [ward, setWard] = useState<string>("all");
  const [term, setTerm] = useState("");

  const load = useCallback(async () => {
    if (!facility) return;
    setRefreshing(true);
    try {
      setBoard(await api.get<BoardResponse>(`/ipd/board/?facility=${facility}`));
      setProblem(null);
    } catch (err) {
      setProblem(err instanceof ApiError ? err.message : "The bed board did not load.");
    } finally {
      setRefreshing(false);
    }
  }, [facility]);

  useEffect(() => {
    setBoard(null);
    setWard("all");
    void load();
    // A board on a wall is left open for a shift. Two minutes is fresher than
    // anyone walks past it, and far gentler than a socket per nurses' station.
    const timer = window.setInterval(() => void load(), 120_000);
    return () => window.clearInterval(timer);
  }, [load]);

  const visibleWards = useMemo(() => {
    if (!board) return [];
    return board.wards
      .filter((row) => ward === "all" || row.uuid === ward)
      .map((row) => ({
        ...row,
        shown: row.beds.filter((bed) => matchesFocus(bed, focus) && matchesSearch(bed, term.trim())),
      }))
      .filter((row) => row.shown.length > 0 || (focus === "all" && !term.trim()));
  }, [board, ward, focus, term]);

  if (problem && !board) {
    return <ErrorState description={problem} onRetry={() => void load()} />;
  }

  if (!board) {
    return (
      <div className="space-y-4">
        <div className="grid grid-cols-2 gap-3 lg:grid-cols-6">
          {Array.from({ length: 6 }, (_, index) => (
            <Skeleton key={index} className="h-[4.5rem] rounded-lg" />
          ))}
        </div>
        <Skeleton className="h-72 rounded-xl" />
      </div>
    );
  }

  if (board.wards.length === 0) {
    return (
      <Card>
        <EmptyState
          title="No wards at this facility"
          description="Wards and their beds are laid out under Wards & beds. Once a ward exists, its beds appear here."
        />
      </Card>
    );
  }

  const totals = board.totals;
  const usable = totals.beds - totals.out_of_service;
  const occupancy = usable ? Math.round((totals.occupied / usable) * 100) : 0;

  return (
    <div className="space-y-4">
      {/* -- the strip ------------------------------------------------------ */}
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-6">
        <Figure
          label="Occupancy"
          value={`${occupancy}%`}
          detail={`${totals.occupied} of ${usable} usable beds`}
          icon={BedDouble}
          tone={occupancy >= 95 ? "critical" : occupancy >= 85 ? "warning" : "neutral"}
        >
          <OccupancyBar counts={totals} className="mt-2" />
        </Figure>
        <Figure
          label="Free now"
          value={totals.available}
          detail="ready for a patient"
          icon={UserPlus}
          tone={totals.available === 0 ? "critical" : "good"}
          active={focus === "free"}
          onClick={() => setFocus(focus === "free" ? "all" : "free")}
        />
        <Figure
          label="Being cleaned"
          value={totals.cleaning}
          detail="back within the hour"
          icon={Sparkles}
          tone="neutral"
        />
        <Figure
          label="Out of service"
          value={totals.out_of_service}
          detail={totals.reserved ? `and ${totals.reserved} reserved` : "maintenance or blocked"}
          icon={Wrench}
          tone={totals.out_of_service > 0 ? "warning" : "neutral"}
        />
        <Figure
          label="Home today"
          value={totals.due_home_today + totals.discharging}
          detail={totals.discharging ? `${totals.discharging} already clearing` : "expected discharges"}
          icon={Home}
          tone="info"
          active={focus === "home"}
          onClick={() => setFocus(focus === "home" ? "all" : "home")}
        />
        <Figure
          label="Needs review"
          value={board.clinical ? totals.high_news2 : "—"}
          detail={board.clinical ? "NEWS2 of 5 or more" : "clinical access required"}
          icon={HeartPulse}
          tone={board.clinical && totals.high_news2 > 0 ? "critical" : "neutral"}
          active={focus === "review"}
          onClick={board.clinical ? () => setFocus(focus === "review" ? "all" : "review") : undefined}
        />
      </div>

      {/* -- controls ------------------------------------------------------- */}
      <div className="space-y-2">
        <div className="flex flex-wrap items-center gap-2">
          <div className="relative w-full sm:w-72">
            <Search className="pointer-events-none absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
            <Input
              value={term}
              onChange={(event) => setTerm(event.target.value)}
              placeholder="Find a patient, MRN or bed"
              className="h-9 pl-8"
              aria-label="Find a patient, MRN or bed"
            />
          </div>
          <div className="ml-auto flex items-center gap-2">
            <span className="hidden text-xs text-muted-foreground md:inline">
              Updated {clock(board.generated_at)}
            </span>
            <Button variant="ghost" size="icon" onClick={() => void load()} aria-label="Refresh the board">
              <RefreshCw className={cn("h-4 w-4", refreshing && "animate-spin")} />
            </Button>
            <Button size="sm" onClick={() => onAdmit(ward === "all" ? undefined : ward)}>
              <UserPlus className="h-4 w-4" />
              Admit
            </Button>
          </div>
        </div>
        <div className="flex max-w-full gap-1 overflow-x-auto rounded-lg border bg-muted/40 p-0.5" role="tablist" aria-label="Ward">
          <WardChip active={ward === "all"} onClick={() => setWard("all")} label="All wards" />
          {board.wards.map((row) => (
            <WardChip
              key={row.uuid}
              active={ward === row.uuid}
              onClick={() => setWard(row.uuid)}
              label={row.name}
              count={`${row.counts.occupied}/${row.counts.beds}`}
              alert={row.counts.high_news2 > 0}
            />
          ))}
        </div>
      </div>

      {focus !== "all" && (
        <div className="flex items-center gap-2 text-sm">
          <span className="text-muted-foreground">Showing</span>
          <span className="font-medium">
            {focus === "free" ? "free beds" : focus === "home" ? "patients going home today" : "patients scoring NEWS2 5 or more"}
          </span>
          <button
            type="button"
            className="text-primary underline-offset-4 hover:underline"
            onClick={() => setFocus("all")}
          >
            Show every bed
          </button>
        </div>
      )}

      {/* -- the wards ------------------------------------------------------ */}
      {visibleWards.length === 0 ? (
        <Card>
          <EmptyState
            illustration="search"
            title="Nothing matches"
            description={term ? `No bed or patient matches “${term}”.` : "No bed fits that filter right now."}
          />
        </Card>
      ) : (
        visibleWards.map((row) => (
          <WardSection
            key={row.uuid}
            ward={row}
            beds={row.shown}
            onOpen={onOpen}
            onAdmit={() => onAdmit(row.uuid)}
          />
        ))
      )}

      <Legend />
    </div>
  );
}

/* -------------------------------------------------------------------------- */

const TONES = {
  neutral: "text-foreground",
  good: "text-good",
  warning: "text-warning",
  critical: "text-critical",
  info: "text-info",
} as const;

function Figure({
  label,
  value,
  detail,
  icon: Icon,
  tone,
  active,
  onClick,
  children,
}: {
  label: string;
  value: string | number;
  detail: string;
  icon: typeof BedDouble;
  tone: keyof typeof TONES;
  active?: boolean;
  onClick?: () => void;
  children?: React.ReactNode;
}) {
  const Tag = onClick ? "button" : "div";
  return (
    <Tag
      type={onClick ? "button" : undefined}
      onClick={onClick}
      aria-pressed={onClick ? Boolean(active) : undefined}
      className={cn(
        "rounded-lg border bg-card p-3 text-left shadow-flat transition-colors",
        onClick && "hover:border-primary/40 hover:bg-accent/40",
        active && "border-primary ring-1 ring-primary",
      )}
    >
      <div className="flex items-center justify-between text-xs text-muted-foreground">
        {label}
        <Icon className="h-3.5 w-3.5" aria-hidden />
      </div>
      <p className={cn("mt-1 text-2xl font-semibold tabular-nums leading-none", TONES[tone])}>
        {value}
      </p>
      <p className="mt-1 truncate text-xs text-muted-foreground">{detail}</p>
      {children}
    </Tag>
  );
}

function OccupancyBar({ counts, className }: { counts: Counts; className?: string }) {
  const total = Math.max(1, counts.beds);
  const parts = [
    { key: "occupied", value: counts.occupied, className: "bg-primary", label: "occupied" },
    { key: "cleaning", value: counts.cleaning, className: "bg-warning/60", label: "being cleaned" },
    { key: "reserved", value: counts.reserved, className: "bg-info/50", label: "reserved" },
    { key: "out", value: counts.out_of_service, className: "bg-muted-foreground/40", label: "out of service" },
  ];
  return (
    <div
      className={cn("flex h-1.5 w-full gap-px overflow-hidden rounded-full bg-good/25", className)}
      role="img"
      aria-label={parts.map((part) => `${part.value} ${part.label}`).join(", ") + `, ${counts.available} free`}
    >
      {parts.map((part) =>
        part.value > 0 ? (
          <span
            key={part.key}
            className={cn("h-full", part.className)}
            style={{ width: `${(part.value / total) * 100}%` }}
          />
        ) : null,
      )}
    </div>
  );
}

function WardChip({
  active,
  onClick,
  label,
  count,
  alert,
}: {
  active: boolean;
  onClick: () => void;
  label: string;
  count?: string;
  alert?: boolean;
}) {
  return (
    <button
      type="button"
      role="tab"
      aria-selected={active}
      onClick={onClick}
      className={cn(
        "flex shrink-0 items-center gap-1.5 whitespace-nowrap rounded-md px-2.5 py-1 text-sm transition-colors",
        active ? "bg-background font-medium shadow-sm" : "text-muted-foreground hover:text-foreground",
      )}
    >
      {alert && <span className="h-1.5 w-1.5 rounded-full bg-critical" aria-label="has a patient needing review" />}
      {label}
      {count && <span className="text-xs tabular-nums text-muted-foreground">{count}</span>}
    </button>
  );
}

function WardSection({
  ward,
  beds,
  onOpen,
  onAdmit,
}: {
  ward: BoardWard;
  beds: BoardBed[];
  onOpen: (admission: string) => void;
  onAdmit: () => void;
}) {
  // Grouped by bay, in the order the beds are numbered, because that is the
  // order you walk them in.
  const bays = useMemo(() => {
    const groups = new Map<string, BoardBed[]>();
    for (const bed of beds) {
      const key = bed.bay || "";
      groups.set(key, [...(groups.get(key) ?? []), bed]);
    }
    return [...groups.entries()];
  }, [beds]);

  const c = ward.counts;
  const where = [ward.floor, ward.building].filter(Boolean).join(" · ");

  return (
    <section className="rounded-xl border bg-card shadow-flat" aria-labelledby={`ward-${ward.uuid}`}>
      <header className="flex flex-wrap items-center gap-x-6 gap-y-2 border-b px-4 py-3">
        <div className="min-w-0">
          <h3 id={`ward-${ward.uuid}`} className="flex items-center gap-2 font-semibold">
            {ward.name}
            {ward.is_critical_care && (
              <span className="rounded bg-critical-subtle px-1.5 py-0.5 text-[11px] font-medium text-critical-subtle-foreground">
                Critical care
              </span>
            )}
          </h3>
          <p className="text-xs text-muted-foreground">
            {where || ward.code}
            {ward.visiting_hours && ` · visiting ${ward.visiting_hours}`}
          </p>
        </div>
        <div className="ml-auto flex items-center gap-5 text-xs">
          <div className="w-40">
            <div className="mb-1 flex justify-between text-muted-foreground">
              <span>
                <span className="font-semibold text-foreground tabular-nums">{c.occupied}</span>/{c.beds} occupied
              </span>
              <span className="text-good">{c.available} free</span>
            </div>
            <OccupancyBar counts={c} />
          </div>
          <div className="hidden text-muted-foreground sm:block" title="Planned staffing">
            <span className="font-semibold text-foreground tabular-nums">
              1:{Number(ward.patients_per_nurse)}
            </span>{" "}
            nurse ratio
          </div>
          {c.high_news2 > 0 && (
            <div className="flex items-center gap-1 font-medium text-critical">
              <Activity className="h-3.5 w-3.5" />
              {c.high_news2} to review
            </div>
          )}
          {c.due_home_today + c.discharging > 0 && (
            <div className="hidden items-center gap-1 text-info md:flex">
              <Home className="h-3.5 w-3.5" />
              {c.due_home_today + c.discharging} home today
            </div>
          )}
        </div>
      </header>

      <div className="space-y-4 p-4">
        {bays.map(([bay, rows]) => (
          <div key={bay || "beds"}>
            {bay && bays.length > 1 && (
              <p className="mb-2 text-xs font-medium text-muted-foreground">{bay}</p>
            )}
            <div className="grid grid-cols-2 gap-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5 xl:grid-cols-6">
              {rows.map((bed) => (
                <BedTile key={bed.uuid} bed={bed} onOpen={onOpen} onAdmit={onAdmit} />
              ))}
            </div>
          </div>
        ))}
      </div>
    </section>
  );
}

/* -------------------------------------------------------------------------- */
/* Tiles                                                                       */
/* -------------------------------------------------------------------------- */

const TILE = "relative flex min-h-[7.25rem] flex-col rounded-lg border p-2.5 text-left";

function BedTile({
  bed,
  onOpen,
  onAdmit,
}: {
  bed: BoardBed;
  onOpen: (admission: string) => void;
  onAdmit: () => void;
}) {
  if (bed.occupant) return <OccupiedTile bed={bed} occupant={bed.occupant} onOpen={onOpen} />;

  if (bed.status === "available") {
    return (
      <div className={cn(TILE, "group border-dashed border-good/50 bg-good-subtle/30")}>
        <TileHead code={bed.code} bed={bed} />
        <p className="mt-auto flex items-center gap-1.5 text-sm font-medium text-good">
          <span className="h-1.5 w-1.5 rounded-full bg-good" />
          Free
        </p>
        <p className="text-xs text-muted-foreground">
          {bed.gender_restriction === "female"
            ? "Women only"
            : bed.gender_restriction === "male"
              ? "Men only"
              : "Any patient"}
        </p>
        <button
          type="button"
          onClick={onAdmit}
          className="absolute inset-x-2.5 bottom-2.5 hidden items-center justify-center gap-1 rounded-md bg-primary py-1.5 text-xs font-medium text-primary-foreground group-hover:flex group-focus-within:flex"
        >
          <UserPlus className="h-3.5 w-3.5" />
          Admit here
        </button>
      </div>
    );
  }

  if (bed.status === "cleaning") {
    return (
      <div className={cn(TILE, "bg-muted/50")}>
        <TileHead code={bed.code} bed={bed} />
        <p className="mt-auto flex items-center gap-1.5 text-sm font-medium">
          <Sparkles className="h-3.5 w-3.5 text-warning" />
          Being cleaned
        </p>
        <p className="text-xs text-muted-foreground">
          {minutesSince(bed.status_changed_at)} min since vacated
        </p>
      </div>
    );
  }

  if (bed.status === "reserved") {
    return (
      <div className={cn(TILE, "border-info/40 bg-info-subtle/40")}>
        <TileHead code={bed.code} bed={bed} />
        <p className="mt-auto text-sm font-medium text-info">Reserved</p>
        <p className="line-clamp-2 text-xs text-muted-foreground">{bed.status_reason || "Held for an admission"}</p>
      </div>
    );
  }

  // Maintenance or blocked: hatched, so it cannot be mistaken for free at a glance.
  return (
    <div
      className={cn(
        TILE,
        "bg-[repeating-linear-gradient(135deg,hsl(var(--muted))_0_6px,transparent_6px_12px)]",
      )}
    >
      <TileHead code={bed.code} bed={bed} />
      <p className="mt-auto flex items-center gap-1.5 text-sm font-medium">
        <Wrench className="h-3.5 w-3.5 text-muted-foreground" />
        {bed.status === "blocked" ? "Blocked" : "Out of service"}
      </p>
      <p className="line-clamp-2 text-xs text-muted-foreground">{bed.status_reason}</p>
    </div>
  );
}

function TileHead({ code, bed, children }: { code: string; bed: BoardBed; children?: React.ReactNode }) {
  return (
    <div className="flex items-center gap-1.5">
      <span className="text-xs font-semibold tabular-nums text-muted-foreground">{code}</span>
      {bed.is_isolation && (
        <ShieldAlert className="h-3.5 w-3.5 text-serious" aria-label="Isolation room" />
      )}
      {bed.equipment.includes("monitor") && (
        <HeartPulse className="h-3.5 w-3.5 text-muted-foreground/70" aria-label="Monitored bed" />
      )}
      <span className="ml-auto">{children}</span>
    </div>
  );
}

const DUE = {
  today: { label: "Home today", className: "bg-info-subtle text-info-subtle-foreground" },
  overdue: { label: "Home — overdue", className: "bg-serious-subtle text-serious-subtle-foreground" },
  tomorrow: { label: "Home tomorrow", className: "bg-muted text-muted-foreground" },
  discharging: { label: "Discharging", className: "bg-good-subtle text-good-subtle-foreground" },
} as const;

function OccupiedTile({
  bed,
  occupant,
  onOpen,
}: {
  bed: BoardBed;
  occupant: Occupant;
  onOpen: (admission: string) => void;
}) {
  const score = occupant.news2?.score ?? null;
  const accent =
    score === null || occupant.news2?.stale
      ? null
      : score >= 7
        ? "bg-critical"
        : score >= 5
          ? "bg-warning"
          : null;
  const facts = [
    occupant.age !== null ? `${occupant.age}${sexLetter(occupant.gender)}` : sexLetter(occupant.gender),
    `night ${Math.max(1, occupant.nights)}`,
  ].filter(Boolean);

  return (
    <button
      type="button"
      onClick={() => onOpen(occupant.admission)}
      title={[
        occupant.name,
        occupant.mrn,
        occupant.consultant && `Under ${occupant.consultant}`,
        occupant.expected_discharge && `Expected home ${occupant.expected_discharge}`,
      ]
        .filter(Boolean)
        .join(" · ")}
      className={cn(
        TILE,
        "overflow-hidden bg-card shadow-flat transition-[border-color,box-shadow] hover:border-primary/50 hover:shadow-raised focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
      )}
    >
      {accent && <span className={cn("absolute inset-y-0 left-0 w-1", accent)} aria-hidden />}
      <TileHead code={bed.code} bed={bed}>
        {occupant.news2 ? (
          <News2Badge
            score={occupant.news2.score}
            stale={occupant.news2.stale}
            recordedAt={occupant.news2.recorded_at}
          />
        ) : occupant.clinical_restricted ? (
          <Lock className="h-3.5 w-3.5 text-muted-foreground/60" aria-label="Clinical details restricted" />
        ) : (
          <span className="text-[11px] text-muted-foreground">No obs</span>
        )}
      </TileHead>

      <p className="mt-1.5 truncate text-sm font-semibold leading-tight">{occupant.name}</p>
      <p className="text-xs text-muted-foreground">{facts.join(" · ")}</p>
      {occupant.diagnosis ? (
        <p className="mt-1 line-clamp-1 text-xs">{occupant.diagnosis}</p>
      ) : occupant.clinical_restricted ? (
        <p className="mt-1 text-xs italic text-muted-foreground">Clinical details restricted</p>
      ) : null}

      <div className="mt-auto flex items-center gap-1 pt-1.5">
        {occupant.due && (
          <span className={cn("rounded px-1.5 py-0.5 text-[11px] font-medium", DUE[occupant.due].className)}>
            {DUE[occupant.due].label}
          </span>
        )}
        <span className="ml-auto flex items-center gap-1 text-muted-foreground">
          {occupant.news2?.on_oxygen && <Wind className="h-3.5 w-3.5 text-info" aria-label="On oxygen" />}
          {occupant.is_mlc && <Gavel className="h-3.5 w-3.5 text-serious" aria-label="Medico-legal case" />}
          {occupant.news2?.stale && <Clock className="h-3.5 w-3.5" aria-label="Observations out of date" />}
        </span>
      </div>
    </button>
  );
}

function Legend() {
  const item = (swatch: React.ReactNode, label: string) => (
    <span className="flex items-center gap-1.5">
      {swatch}
      {label}
    </span>
  );
  return (
    <div className="flex flex-wrap items-center gap-x-4 gap-y-2 text-xs text-muted-foreground">
      {item(<span className="h-3 w-4 rounded-sm border bg-card" />, "Occupied")}
      {item(<span className="h-3 w-4 rounded-sm border border-dashed border-good/60 bg-good-subtle/40" />, "Free")}
      {item(<span className="h-3 w-4 rounded-sm bg-muted" />, "Being cleaned")}
      {item(
        <span className="h-3 w-4 rounded-sm border bg-[repeating-linear-gradient(135deg,hsl(var(--muted-foreground)/0.35)_0_2px,transparent_2px_4px)]" />,
        "Out of service",
      )}
      {item(<span className="h-3 w-1 rounded-sm bg-warning" />, "NEWS2 5–6")}
      {item(<span className="h-3 w-1 rounded-sm bg-critical" />, "NEWS2 7+")}
      {item(<Wind className="h-3.5 w-3.5 text-info" />, "On oxygen")}
      {item(<ShieldAlert className="h-3.5 w-3.5 text-serious" />, "Isolation")}
      {item(<Gavel className="h-3.5 w-3.5 text-serious" />, "Medico-legal")}
    </div>
  );
}
