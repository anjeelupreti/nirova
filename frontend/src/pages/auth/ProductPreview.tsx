/**
 * Three real screens, composed: the bed board, a patient deteriorating, and
 * today's figures.
 *
 * Drawn from the same parts the real screens use — the NEWS2 badge is the
 * component itself — so it cannot drift into being a prettier lie than the
 * product. The cards are opaque and full-contrast on purpose: a preview a
 * buyer has to squint at is worse than none. Every name and number here is
 * illustrative, and the panel says so.
 */

import { AlertTriangle, BedDouble, Siren, Wallet } from "lucide-react";

import { cn } from "@/lib/utils";
import { News2Badge } from "@/components/clinical/News2";

const BEDS: { code: string; name?: string; facts?: string; news?: number; home?: boolean; state?: "free" | "cleaning" }[] = [
  { code: "MW-01", name: "Rekha Poudel", facts: "36F · night 5", news: 0, home: true },
  { code: "MW-02", name: "Sarita Rai", facts: "67F · night 4", news: 2 },
  { code: "MW-03", state: "free" },
  { code: "MW-04", name: "Gita Karki", facts: "52F · night 2", news: 1 },
  { code: "MW-05", name: "Durga Yadav", facts: "46F · night 4", news: 6 },
  { code: "MW-06", name: "Laxmi Thapa", facts: "80F · night 4", news: 0 },
  { code: "MW-07", state: "cleaning" },
  { code: "MW-08", name: "Asmita Lama", facts: "29F · night 1", news: 3 },
];

export function ProductPreview() {
  return (
    <div className="relative mx-auto h-[27rem] w-full max-w-[40rem]">
      {/* -- the bed board --------------------------------------------- */}
      <div className="absolute left-0 top-10 w-[27rem] rounded-xl border border-black/5 bg-card p-4 text-foreground shadow-modal">
        <div className="flex items-center justify-between">
          <div>
            <p className="text-sm font-semibold">Medical Ward</p>
            <p className="text-xs text-muted-foreground">2nd floor · Main block</p>
          </div>
          <div className="w-32 text-right text-xs text-muted-foreground">
            <span className="font-semibold text-foreground">13</span>/16 occupied
            <div className="mt-1 flex h-1.5 gap-px overflow-hidden rounded-full bg-good/25">
              <span className="w-[81%] bg-primary" />
              <span className="w-[6%] bg-warning/60" />
            </div>
          </div>
        </div>
        <div className="mt-3 grid grid-cols-4 gap-1.5">
          {BEDS.map((bed) => (
            <div
              key={bed.code}
              className={cn(
                "relative flex h-[4.6rem] flex-col overflow-hidden rounded-md border p-1.5",
                bed.state === "free" && "border-dashed border-good/50 bg-good-subtle/40",
                bed.state === "cleaning" && "bg-muted/60",
              )}
            >
              {bed.news !== undefined && bed.news >= 5 && (
                <span className="absolute inset-y-0 left-0 w-0.5 bg-warning" />
              )}
              <div className="flex items-center justify-between">
                <span className="text-[10px] font-semibold text-muted-foreground">{bed.code}</span>
                {bed.news !== undefined && <News2Badge score={bed.news} className="h-4 px-1 text-[9px]" />}
              </div>
              {bed.name ? (
                <>
                  <p className="mt-1 truncate text-[11px] font-semibold leading-tight">{bed.name}</p>
                  <p className="text-[10px] text-muted-foreground">{bed.facts}</p>
                  {bed.home && (
                    <span className="mt-auto w-fit rounded bg-info-subtle px-1 text-[9px] font-medium text-info-subtle-foreground">
                      Home today
                    </span>
                  )}
                </>
              ) : (
                <p className={cn("mt-auto text-[11px] font-medium", bed.state === "free" ? "text-good" : "text-muted-foreground")}>
                  {bed.state === "free" ? "Free" : "Cleaning"}
                </p>
              )}
            </div>
          ))}
        </div>
      </div>

      {/* -- today --------------------------------------------------------- */}
      <div className="absolute right-0 top-0 w-[13.5rem] rounded-xl border border-black/5 bg-card p-3.5 text-foreground shadow-modal">
        <p className="text-xs font-medium text-muted-foreground">Today · Bhaktapur</p>
        <dl className="mt-2 space-y-2 text-sm">
          <Row icon={Siren} label="Emergency arrivals" value="18" />
          <Row icon={BedDouble} label="Beds in use" value="41 / 60" />
          <Row icon={Wallet} label="Counter takings" value="Rs 24,580" />
        </dl>
        <div className="mt-3 flex h-10 items-end gap-1" aria-hidden>
          {[4, 6, 5, 9, 12, 10, 14, 11, 8, 13, 16, 12].map((value, index) => (
            <span
              key={index}
              className={cn("flex-1 rounded-t-sm", index === 11 ? "bg-primary" : "bg-primary/25")}
              style={{ height: `${(value / 16) * 100}%` }}
            />
          ))}
        </div>
      </div>

      {/* -- a patient asking for something ------------------------------ */}
      <div className="absolute bottom-0 right-4 w-[19rem] overflow-hidden rounded-xl border border-warning/50 bg-card text-foreground shadow-modal">
        <span className="absolute inset-y-0 left-0 w-1 bg-warning" />
        <div className="flex items-start gap-2.5 p-3.5 pb-2">
          <div className="grid h-9 w-9 shrink-0 place-items-center rounded-md bg-muted text-xs font-semibold">05</div>
          <div className="min-w-0 flex-1">
            <p className="truncate text-sm font-semibold">Durga Yadav</p>
            <p className="text-xs text-muted-foreground">46F · night 4 · Heart failure</p>
          </div>
          <News2Badge score={6} size="md" />
        </div>
        <div className="mx-3.5 mb-2 rounded-md bg-warning-subtle px-2.5 py-1.5 text-[11px] text-warning-subtle-foreground">
          <p className="flex items-center gap-1 font-semibold">
            <AlertTriangle className="h-3 w-3" />
            Clinician review within the hour
          </p>
          <p className="opacity-90">Resp 23 (+2) · SpO₂ 95% (+1) · Temp 38.6° (+1)</p>
        </div>
        <div className="grid grid-cols-4 border-t text-center">
          {[
            ["BP", "109/68", 1],
            ["Pulse", "105", 1],
            ["SpO₂", "95%", 1],
            ["Resp", "23", 2],
          ].map(([label, value, points]) => (
            <div key={label as string} className="border-r py-1.5 last:border-r-0">
              <p className="text-[10px] text-muted-foreground">{label}</p>
              <p className={cn("text-xs font-semibold", Number(points) > 0 && "text-warning")}>{value}</p>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

function Row({ icon: Icon, label, value }: { icon: typeof Siren; label: string; value: string }) {
  return (
    <div className="flex items-center gap-2">
      <Icon className="h-3.5 w-3.5 text-primary" aria-hidden />
      <dt className="flex-1 text-xs text-muted-foreground">{label}</dt>
      <dd className="font-semibold tabular-nums">{value}</dd>
    </div>
  );
}
