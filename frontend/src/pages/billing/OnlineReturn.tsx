/**
 * Back from a wallet, in the tab the counter opened.
 *
 * Khalti sends the payer here when they are done. What the address bar says
 * is not evidence — the check below asks our API, which asks the provider
 * server to server — so this screen shows "checking" until there is an
 * answer, and never "paid" on the strength of a query parameter.
 */

import { useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { CheckCircle2, XCircle } from "lucide-react";

import api, { ApiError } from "@/lib/api";
import type { OnlineAttempt } from "@/types";
import { Spinner } from "@/components/ui/loader";
import {
  Alert,
  AlertDescription,
  Badge,
  Button,
  Card,
  CardContent,
  CardHeader,
  CardTitle,
} from "@/components/ui/primitives";

export default function OnlineReturnPage() {
  const [params] = useSearchParams();
  const attempt = params.get("attempt") ?? "";
  const [state, setState] = useState<OnlineAttempt | null>(null);
  const [problem, setProblem] = useState<string | null>(null);

  useEffect(() => {
    if (!attempt) {
      setProblem("This page needs the payment it is about.");
      return;
    }
    api
      .post<OnlineAttempt>("/billing/online/", { action: "check", attempt })
      .then(setState)
      .catch((err) =>
        setProblem(err instanceof ApiError ? err.message : "That payment could not be checked."),
      );
  }, [attempt]);

  const paid = state?.status === "completed" && !state.needs_attention;

  return (
    <div className="mx-auto max-w-md py-10">
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            {paid ? <CheckCircle2 className="h-5 w-5 text-good" /> : null}
            {state ? state.status_label : "Checking the payment"}
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          {!state && !problem ? (
            <p className="flex items-center gap-2 text-muted-foreground">
              <Spinner size="sm" /> Asking the provider…
            </p>
          ) : null}

          {problem ? (
            <Alert variant="destructive">
              <XCircle className="h-4 w-4" />
              <AlertDescription>{problem}</AlertDescription>
            </Alert>
          ) : null}

          {state ? (
            <div className="space-y-2 text-sm">
              <div className="flex items-center justify-between">
                <span className="text-muted-foreground">Invoice</span>
                <span className="font-mono">{state.invoice}</span>
              </div>
              <div className="flex items-center justify-between">
                <span className="text-muted-foreground">Amount</span>
                <span className="tabular-nums">NPR {state.amount}</span>
              </div>
              <div className="flex items-center justify-between">
                <span className="text-muted-foreground">Wallet</span>
                <Badge variant={paid ? "success" : "secondary"}>{state.provider_label}</Badge>
              </div>
              {state.receipt ? (
                <div className="flex items-center justify-between">
                  <span className="text-muted-foreground">Receipt</span>
                  <span className="font-mono">{state.receipt}</span>
                </div>
              ) : null}
              {state.needs_attention ? (
                <Alert variant="destructive">
                  <AlertDescription>{state.needs_attention}</AlertDescription>
                </Alert>
              ) : null}
            </div>
          ) : null}

          <Button className="w-full" onClick={() => window.close()}>
            Close
          </Button>
        </CardContent>
      </Card>
    </div>
  );
}
