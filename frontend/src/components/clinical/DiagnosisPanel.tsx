/**
 * Recording a diagnosis, coded.
 *
 * **Diagnoses were displayed and never entered.** The patient record showed
 * them, the discharge summary printed them, the consultation had no way to
 * write one — so `icd10_code` was a column that filled up only from seed data,
 * and the ministry's monthly return, which is a count of codes, had nothing to
 * count.
 *
 * **The code is found by typing what a clinician says.** "sugar" finds type 2
 * diabetes, "bp" finds hypertension, "J18" finds pneumonia; an exact code wins,
 * and within each band the codes this hospital uses most come first.
 *
 * **A diagnosis without a code is still recordable.** The clinical fact matters
 * more than the classification, and a system that refuses the fact for want of
 * a code is one people work around. Uncoded ones are listed by the "Diagnoses
 * without a code" report, which is how they get coded later rather than never.
 */

import { useCallback, useEffect, useRef, useState } from "react";
import { Loader2, Star, Tag } from "lucide-react";

import api, { ApiError } from "@/lib/api";
import { cn } from "@/lib/utils";
import type { EncounterDetail } from "@/types";
import {
  Alert,
  AlertDescription,
  Badge,
  Button,
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
  Input,
  Select,
} from "@/components/ui/primitives";

interface CodeHit {
  code: string;
  title: string;
  chapter: string;
  is_common: boolean;
}

const CERTAINTY = [
  { value: "working", label: "Working diagnosis" },
  { value: "suspected", label: "Suspected" },
  { value: "confirmed", label: "Confirmed" },
  { value: "ruled_out", label: "Ruled out" },
];

export function DiagnosisPanel({
  encounter,
  onSaved,
}: {
  encounter: EncounterDetail;
  onSaved: () => void;
}) {
  const [term, setTerm] = useState("");
  const [hits, setHits] = useState<CodeHit[]>([]);
  const [chosen, setChosen] = useState<CodeHit | null>(null);
  const [certainty, setCertainty] = useState("working");
  const [primary, setPrimary] = useState(false);
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);
  const timer = useRef<number | undefined>(undefined);

  const lookup = useCallback((value: string) => {
    window.clearTimeout(timer.current);
    timer.current = window.setTimeout(() => {
      void api
        .get<{ results: CodeHit[] }>(`/clinical/diagnosis-codes/?q=${encodeURIComponent(value)}`)
        .then((body) => setHits(body.results))
        .catch(() => setHits([]));
    }, 200);
  }, []);

  // The common list, before anybody types.
  useEffect(() => {
    lookup("");
    return () => window.clearTimeout(timer.current);
  }, [lookup]);

  async function add(useCode: boolean) {
    const name = useCode ? chosen?.title ?? "" : term.trim();
    if (!name) return;
    setBusy(true);
    setProblem(null);
    try {
      await api.post(`/clinical/encounters/${encounter.uuid}/diagnoses/`, {
        name,
        icd10_code: useCode ? chosen?.code ?? "" : "",
        certainty,
        is_primary: primary,
      });
      setTerm("");
      setChosen(null);
      setPrimary(false);
      lookup("");
      onSaved();
    } catch (err) {
      setProblem(err instanceof ApiError ? err.message : "The diagnosis was not recorded.");
    } finally {
      setBusy(false);
    }
  }

  const existing = encounter.diagnoses ?? [];

  return (
    <Card>
      <CardHeader className="pb-3">
        <CardTitle className="flex items-center gap-2">
          <Tag className="h-4 w-4 text-muted-foreground" />
          Diagnosis
        </CardTitle>
        <CardDescription>
          Coded where it can be — the monthly return and every claim count codes,
          not words.
        </CardDescription>
      </CardHeader>

      <CardContent className="space-y-4">
        {existing.length > 0 ? (
          <ul className="space-y-1.5">
            {existing.map((diagnosis) => (
              <li key={diagnosis.uuid} className="flex flex-wrap items-center gap-2 text-sm">
                {diagnosis.is_primary ? (
                  <Star className="h-3.5 w-3.5 shrink-0 fill-warning text-warning" />
                ) : null}
                <span className="font-medium">{diagnosis.name}</span>
                {diagnosis.icd10_code ? (
                  <span className="rounded bg-muted px-1.5 py-0.5 type-code text-xs">
                    {diagnosis.icd10_code}
                  </span>
                ) : (
                  <Badge variant="outline" className="text-warning">
                    not coded
                  </Badge>
                )}
                <span className="text-xs text-muted-foreground">
                  {CERTAINTY.find((row) => row.value === diagnosis.certainty)?.label ??
                    diagnosis.certainty}
                </span>
              </li>
            ))}
          </ul>
        ) : null}

        <div className="space-y-2">
          <Input
            aria-label="Find a diagnosis"
            placeholder="Type a diagnosis or a code — sugar, bp, J18…"
            value={chosen ? `${chosen.code} · ${chosen.title}` : term}
            onChange={(event) => {
              setChosen(null);
              setTerm(event.target.value);
              lookup(event.target.value);
            }}
          />

          {!chosen && hits.length > 0 ? (
            <ul className="max-h-48 divide-y overflow-y-auto rounded-lg border">
              {hits.map((hit) => (
                <li key={hit.code}>
                  <button
                    type="button"
                    onClick={() => setChosen(hit)}
                    className="flex w-full items-baseline gap-2 px-3 py-2 text-left text-sm hover:bg-accent"
                  >
                    <span className="type-code text-xs text-muted-foreground">{hit.code}</span>
                    <span className="min-w-0 flex-1 truncate">{hit.title}</span>
                    <span className="hidden text-xs text-muted-foreground sm:block">
                      {hit.chapter}
                    </span>
                  </button>
                </li>
              ))}
            </ul>
          ) : null}

          <div className="flex flex-wrap items-center gap-2">
            <Select
              aria-label="How sure"
              className="h-9 w-auto"
              value={certainty}
              onChange={(event) => setCertainty(event.target.value)}
            >
              {CERTAINTY.map((row) => (
                <option key={row.value} value={row.value}>
                  {row.label}
                </option>
              ))}
            </Select>
            <label className="flex items-center gap-1.5 text-sm">
              <input
                type="checkbox"
                checked={primary}
                onChange={(event) => setPrimary(event.target.checked)}
              />
              Main reason for the visit
            </label>
            <Button disabled={busy || (!chosen && term.trim().length === 0)} onClick={() => void add(Boolean(chosen))}>
              {busy ? <Loader2 className="mr-1.5 h-4 w-4 animate-spin" /> : null}
              Add
            </Button>
            {!chosen && term.trim() ? (
              <Button
                variant="outline"
                disabled={busy}
                onClick={() => void add(false)}
                className={cn("text-muted-foreground")}
              >
                Record without a code
              </Button>
            ) : null}
          </div>
        </div>

        {problem ? (
          <Alert variant="destructive">
            <AlertDescription>{problem}</AlertDescription>
          </Alert>
        ) : null}
      </CardContent>
    </Card>
  );
}
