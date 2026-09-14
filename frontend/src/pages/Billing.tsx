/**
 * The billing counter: charge, invoice, take payment, cash up.
 *
 * Built for someone standing at a window with a patient in front of them.
 * The whole flow is one screen and the running total is always visible,
 * because the first question every patient asks is "how much?" and the clerk
 * should never have to navigate to answer it.
 */

import { useCallback, useEffect, useState } from "react";
import {
  AlertTriangle,
  Banknote,
  CheckCircle2,
  FileText,
  Plus,
  Receipt,
  Search,
  Wallet,
} from "lucide-react";

import api, { ApiError } from "@/lib/api";
import type {
  Charge,
  Facility,
  Invoice,
  OnlineAttempt,
  OnlineProviderOption,
  OnlineStart,
  Paginated,
  PatientAccount,
  Patient,
  ServiceItem,
} from "@/types";
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
  Label,
  Select,
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/primitives";
import { PageHeader } from "@/components/ui/layout";
import { InvoiceDocument } from "@/components/documents/InvoiceDocument";
import { DocumentPreview } from "@/components/documents/DocumentPreview";
import { useSession } from "@/hooks/useSession";
import { formatDate } from "@/lib/dates";

const PAYMENT_METHODS = [
  ["cash", "Cash"],
  ["esewa", "eSewa"],
  ["khalti", "Khalti"],
  ["fonepay", "Fonepay"],
  ["card", "Card"],
  ["bank_transfer", "Bank transfer"],
  ["credit", "On account"],
] as const;

const STATUS_VARIANT: Record<
  string,
  "default" | "secondary" | "warning" | "success" | "destructive"
> = {
  draft: "secondary",
  issued: "warning",
  partially_paid: "warning",
  paid: "success",
  credited: "destructive",
  cancelled: "secondary",
};

/** NPR with no decimals — Nepali counters rarely deal in paisa. */
function npr(value: string | number): string {
  return new Intl.NumberFormat("en-NP", {
    style: "currency",
    currency: "NPR",
    maximumFractionDigits: 0,
  }).format(Number(value));
}

export default function BillingPage() {
  const [facilities, setFacilities] = useState<Facility[]>([]);
  const [facilityUuid, setFacilityUuid] = useState("");
  const [services, setServices] = useState<ServiceItem[]>([]);

  const [term, setTerm] = useState("");
  const [matches, setMatches] = useState<Patient[]>([]);
  const [patient, setPatient] = useState<Patient | null>(null);

  const [charges, setCharges] = useState<Charge[]>([]);
  const [account, setAccount] = useState<PatientAccount | null>(null);
  const [serviceUuid, setServiceUuid] = useState("");
  const [quantity, setQuantity] = useState("1");

  const [paymentMethod, setPaymentMethod] = useState("cash");
  const [paymentAmount, setPaymentAmount] = useState("");
  const [paymentReference, setPaymentReference] = useState("");

  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  /*
    The invoice being previewed, by *number*. The account summary carries
    numbers and not UUIDs, so the preview resolves the full invoice itself
    rather than this page guessing.
  */
  const [viewing, setViewing] = useState<string | null>(null);
  const { session } = useSession();

  useEffect(() => {
    void (async () => {
      const [facilityPage, servicePage] = await Promise.all([
        api.get<Paginated<Facility>>("/org/facilities/"),
        api.get<Paginated<ServiceItem>>("/billing/services/?page_size=200"),
      ]);
      const usable = facilityPage.results.filter((f) => f.status === "active");
      setFacilities(usable);
      const clinic =
        usable.find((f) => f.facility_type === "clinic") ?? usable[0];
      if (clinic) setFacilityUuid(clinic.uuid);
      setServices(servicePage.results.filter((s) => s.is_active));
      if (servicePage.results.length) setServiceUuid(servicePage.results[0].uuid);
    })().catch(() => undefined);
  }, []);

  // Debounced search, same shape as the patients screen.
  useEffect(() => {
    if (term.trim().length < 2) {
      setMatches([]);
      return;
    }
    const handle = setTimeout(() => {
      api
        .get<{ results: Patient[] }>(
          `/clinical/patients/search/?q=${encodeURIComponent(term.trim())}`,
        )
        .then((data) => setMatches(data.results))
        .catch(() => setMatches([]));
    }, 300);
    return () => clearTimeout(handle);
  }, [term]);

  const loadPatient = useCallback(
    async (selected: Patient) => {
      setPatient(selected);
      setMatches([]);
      setTerm("");
      const [chargePage, accountData] = await Promise.all([
        api.get<Paginated<Charge>>(
          `/billing/charges/?patient=${selected.uuid}&pending=true`,
        ),
        api.get<PatientAccount>(`/billing/patients/${selected.uuid}/account/`),
      ]);
      setCharges(chargePage.results);
      setAccount(accountData);
    },
    [],
  );

  async function reload() {
    if (patient) await loadPatient(patient);
  }

  async function addCharge() {
    if (!patient || !serviceUuid) return;
    setError(null);
    setBusy(true);
    try {
      await api.post("/billing/charges/", {
        patient_uuid: patient.uuid,
        facility_uuid: facilityUuid,
        service_uuid: serviceUuid,
        quantity: Number(quantity) || 1,
      });
      setQuantity("1");
      await reload();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not add the charge.");
    } finally {
      setBusy(false);
    }
  }

  async function raiseInvoice() {
    if (!patient) return;
    setError(null);
    setNotice(null);
    setBusy(true);
    try {
      const invoice = await api.post<Invoice>("/billing/invoices/", {
        patient_uuid: patient.uuid,
        facility_uuid: facilityUuid,
        issue: true,
      });
      setNotice(`${invoice.number} issued for ${npr(invoice.total)}`);
      // Pre-fill the payment box with the full amount: settling in full is
      // the common case, and retyping a number that is already on screen is
      // an invitation to mistype it.
      setPaymentAmount(String(invoice.total));
      await reload();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not raise the invoice.");
    } finally {
      setBusy(false);
    }
  }

  async function takePayment(invoice: Invoice) {
    setError(null);
    setNotice(null);
    setBusy(true);
    try {
      const result = await api.post<{ payment: { receipt_number: string } }>(
        `/billing/invoices/${invoice.uuid}/pay/`,
        {
          amount: paymentAmount || invoice.balance_due,
          method: paymentMethod,
          reference: paymentReference,
        },
      );
      setNotice(`Receipt ${result.payment.receipt_number}`);
      setPaymentAmount("");
      setPaymentReference("");
      await reload();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not take payment.");
    } finally {
      setBusy(false);
    }
  }

  const pendingTotal = charges.reduce(
    (sum, charge) => sum + Number(charge.total),
    0,
  );
  const unpaid = (account?.invoices ?? []).filter(
    (invoice) => Number(invoice.balance) > 0 && !invoice.is_credit_note,
  );

  return (
    <div className="space-y-6">
      <PageHeader
        title="Billing"
        description="Charges, invoices and payments."
        actions={
          <>
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
          </>
        }
      />

      <OnlineNeedingAttention />

      {!patient ? (
        <Card>
          <CardHeader className="pb-3">
            <CardTitle>Find the patient</CardTitle>
            <CardDescription>Name, MRN or phone number.</CardDescription>
          </CardHeader>
          <CardContent className="space-y-3">
            <div className="relative">
              <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
              <Input
                className="pl-9"
                autoFocus
                value={term}
                onChange={(e) => setTerm(e.target.value)}
                placeholder="Search…"
              />
            </div>
            {matches.length > 0 && (
              <div className="divide-y rounded-md border">
                {matches.map((match) => (
                  <button
                    key={match.uuid}
                    type="button"
                    className="flex w-full items-center justify-between px-3 py-2 text-left text-sm hover:bg-accent"
                    onClick={() => void loadPatient(match)}
                  >
                    <span>
                      <span className="font-medium">{match.full_name}</span>
                      <span className="ml-2 font-mono text-xs text-muted-foreground">
                        {match.mrn}
                      </span>
                    </span>
                    <Badge variant="secondary">{match.category}</Badge>
                  </button>
                ))}
              </div>
            )}
          </CardContent>
        </Card>
      ) : (
        <>
          <div className="flex flex-wrap items-center justify-between gap-3 rounded-lg border bg-card p-4">
            <div>
              <p className="font-medium">{patient.full_name}</p>
              <p className="text-sm text-muted-foreground">
                {patient.mrn} · {patient.category}
                {account && Number(account.outstanding) > 0 && (
                  <span className="ml-2 font-medium text-destructive">
                    {npr(account.outstanding)} outstanding
                  </span>
                )}
              </p>
            </div>
            <Button variant="outline" size="sm" onClick={() => setPatient(null)}>
              Change patient
            </Button>
          </div>

          {error && (
            <Alert variant="destructive">
              <AlertTriangle className="h-4 w-4" />
              <AlertDescription>{error}</AlertDescription>
            </Alert>
          )}
          {notice && (
            <Alert variant="info">
              <CheckCircle2 className="h-4 w-4" />
              <AlertDescription>{notice}</AlertDescription>
            </Alert>
          )}

          <div className="grid gap-6 lg:grid-cols-2">
            {/* -- charges ------------------------------------------------ */}
            <Card>
              <CardHeader className="pb-3">
                <CardTitle className="flex items-center gap-2">
                  <Plus className="h-4 w-4 text-muted-foreground" />
                  Charges
                </CardTitle>
                <CardDescription>
                  Priced for this patient's category automatically.
                </CardDescription>
              </CardHeader>
              <CardContent className="space-y-4">
                <div className="flex gap-2">
                  <div className="flex-1 space-y-1">
                    <Label className="text-xs">Service</Label>
                    <Select
                      value={serviceUuid}
                      onChange={(e) => setServiceUuid(e.target.value)}
                    >
                      {services.map((service) => (
                        <option key={service.uuid} value={service.uuid}>
                          {service.code} — {service.name}
                        </option>
                      ))}
                    </Select>
                  </div>
                  <div className="w-20 space-y-1">
                    <Label className="text-xs">Qty</Label>
                    <Input
                      type="number"
                      min={1}
                      value={quantity}
                      onChange={(e) => setQuantity(e.target.value)}
                    />
                  </div>
                  <div className="flex items-end">
                    <Button size="sm" disabled={busy} onClick={() => void addCharge()}>
                      Add
                    </Button>
                  </div>
                </div>

                {charges.length === 0 ? (
                  <p className="text-sm text-muted-foreground">
                    No uninvoiced charges.
                  </p>
                ) : (
                  <>
                    <Table>
                      <TableHeader>
                        <TableRow>
                          <TableHead>Service</TableHead>
                          <TableHead>Qty</TableHead>
                          <TableHead className="text-right">Amount</TableHead>
                        </TableRow>
                      </TableHeader>
                      <TableBody>
                        {charges.map((charge) => (
                          <TableRow key={charge.uuid}>
                            <TableCell>
                              {charge.service_name}
                              <span className="ml-1 font-mono text-xs text-muted-foreground">
                                {charge.service_code}
                              </span>
                            </TableCell>
                            <TableCell>{Number(charge.quantity)}</TableCell>
                            <TableCell className="text-right tabular-nums">
                              {npr(charge.total)}
                            </TableCell>
                          </TableRow>
                        ))}
                      </TableBody>
                    </Table>

                    <div className="flex items-center justify-between border-t pt-3">
                      <span className="text-sm font-medium">To invoice</span>
                      <span className="text-lg font-semibold tabular-nums">
                        {npr(pendingTotal)}
                      </span>
                    </div>

                    <Button
                      className="w-full"
                      disabled={busy}
                      onClick={() => void raiseInvoice()}
                    >
                      <FileText className="h-4 w-4" />
                      Raise invoice
                    </Button>
                  </>
                )}
              </CardContent>
            </Card>

            {/* -- payment ------------------------------------------------ */}
            <Card>
              <CardHeader className="pb-3">
                <CardTitle className="flex items-center gap-2">
                  <Wallet className="h-4 w-4 text-muted-foreground" />
                  Payment
                </CardTitle>
                <CardDescription>
                  {unpaid.length === 0
                    ? "Nothing outstanding."
                    : `${unpaid.length} unpaid invoice${unpaid.length > 1 ? "s" : ""}.`}
                </CardDescription>
              </CardHeader>
              <CardContent className="space-y-4">
                {unpaid.length > 0 && (
                  <>
                    <div className="space-y-2">
                      {unpaid.map((invoice) => (
                        <div
                          key={invoice.number}
                          className="flex items-center justify-between rounded-md border px-3 py-2 text-sm"
                        >
                          <span className="font-mono text-xs">{invoice.number}</span>
                          <span className="tabular-nums">
                            {npr(invoice.balance)} due
                          </span>
                        </div>
                      ))}
                    </div>

                    <div className="grid gap-2 sm:grid-cols-2">
                      <div className="space-y-1">
                        <Label className="text-xs">Method</Label>
                        <Select
                          value={paymentMethod}
                          onChange={(e) => setPaymentMethod(e.target.value)}
                        >
                          {PAYMENT_METHODS.map(([value, label]) => (
                            <option key={value} value={value}>
                              {label}
                            </option>
                          ))}
                        </Select>
                      </div>
                      <div className="space-y-1">
                        <Label className="text-xs">Amount</Label>
                        <Input
                          inputMode="decimal"
                          value={paymentAmount}
                          onChange={(e) => setPaymentAmount(e.target.value)}
                        />
                      </div>
                    </div>

                    {paymentMethod !== "cash" && (
                      <div className="space-y-1">
                        <Label className="text-xs">Reference</Label>
                        <Input
                          value={paymentReference}
                          placeholder="Transaction or cheque number"
                          onChange={(e) => setPaymentReference(e.target.value)}
                        />
                      </div>
                    )}

                    <PayButtons
                      account={account}
                      busy={busy}
                      onPay={(invoiceUuid) =>
                        void takePayment({ uuid: invoiceUuid } as Invoice)
                      }
                    />

                    <CollectOnline account={account} onPaid={() => void reload()} />
                  </>
                )}

                {account && (
                  <div className="space-y-1 border-t pt-3 text-sm">
                    <div className="flex justify-between">
                      <span className="text-muted-foreground">Total billed</span>
                      <span className="tabular-nums">
                        {npr(account.total_billed)}
                      </span>
                    </div>
                    <div className="flex justify-between">
                      <span className="text-muted-foreground">Total paid</span>
                      <span className="tabular-nums">{npr(account.total_paid)}</span>
                    </div>
                    <div className="flex justify-between font-medium">
                      <span>Outstanding</span>
                      <span className="tabular-nums">
                        {npr(account.outstanding)}
                      </span>
                    </div>
                  </div>
                )}
              </CardContent>
            </Card>
          </div>

          {/* -- history --------------------------------------------------- */}
          {account && account.invoices.length > 0 && (
            <Card>
              <CardHeader className="pb-3">
                <CardTitle className="flex items-center gap-2">
                  <Receipt className="h-4 w-4 text-muted-foreground" />
                  Invoice history
                </CardTitle>
              </CardHeader>
              <CardContent>
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead>Number</TableHead>
                      <TableHead>Issued</TableHead>
                      <TableHead className="text-right">Total</TableHead>
                      <TableHead className="text-right">Paid</TableHead>
                      <TableHead>Status</TableHead>
                      <TableHead className="text-right">
                        <span className="sr-only">Print</span>
                      </TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {account.invoices.map((invoice) => (
                      <TableRow key={invoice.number}>
                        <TableCell className="font-mono text-xs">
                          {invoice.number}
                          {invoice.is_credit_note && (
                            <Badge variant="destructive" className="ml-2">
                              credit
                            </Badge>
                          )}
                        </TableCell>
                        <TableCell className="text-sm text-muted-foreground">
                          {invoice.issued_at
                            ? formatDate(invoice.issued_at)
                            : "—"}
                        </TableCell>
                        <TableCell className="text-right tabular-nums">
                          {npr(invoice.total)}
                        </TableCell>
                        <TableCell className="text-right tabular-nums">
                          {npr(invoice.paid)}
                        </TableCell>
                        <TableCell>
                          <Badge variant={STATUS_VARIANT[invoice.status] ?? "secondary"}>
                            {invoice.status.replace(/_/g, " ")}
                          </Badge>
                        </TableCell>
                        <TableCell className="text-right">
                          {invoice.number ? (
                            <Button
                              size="sm"
                              variant="ghost"
                              onClick={() => setViewing(invoice.number)}
                            >
                              View &amp; print
                            </Button>
                          ) : null}
                        </TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </CardContent>
            </Card>
          )}
        </>
      )}

      {patient && viewing ? (
        <InvoicePreview
          patientUuid={patient.uuid}
          number={viewing}
          facility={facilities.find((entry) => entry.uuid === facilityUuid) ?? null}
          organization={session?.organization?.display_name ?? "Nirova"}
          printedBy={session?.user.display_name}
          onClose={() => setViewing(null)}
        />
      ) : null}
    </div>
  );
}

/**
 * The full invoice behind a row in the history, on paper.
 *
 * Fetched when opened rather than with the account: the account summary is one
 * request for the whole history, and pulling every line of every invoice a
 * patient has ever had to print one of them is a lot of payload for a counter
 * that prints two a day.
 */
function InvoicePreview({
  patientUuid,
  number,
  facility,
  organization,
  printedBy,
  onClose,
}: {
  patientUuid: string;
  number: string;
  facility: Facility | null;
  organization: string;
  printedBy?: string;
  onClose: () => void;
}) {
  const [invoice, setInvoice] = useState<Invoice | null>(null);
  const [problem, setProblem] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    api
      .get<Paginated<Invoice>>(`/billing/invoices/?patient=${patientUuid}&page_size=200`)
      .then((page) => {
        if (cancelled) return;
        const found = page.results.find((entry) => entry.number === number);
        if (found) setInvoice(found);
        else setProblem(`Invoice ${number} could not be found for this patient.`);
      })
      .catch((failure) => {
        if (cancelled) return;
        setProblem(
          failure instanceof ApiError ? failure.message : "The invoice could not be read.",
        );
      });
    return () => {
      cancelled = true;
    };
  }, [patientUuid, number]);

  return (
    <DocumentPreview
      open
      onClose={onClose}
      title={`Invoice ${number}`}
      subtitle={invoice?.bill_to_name}
      printTarget={invoice ? `invoice-${invoice.uuid}` : "none"}
    >
      {problem ? (
        <p className="p-6 text-sm text-critical">{problem}</p>
      ) : !invoice ? (
        <p className="p-6 type-caption">Reading the invoice…</p>
      ) : (
        <InvoiceDocument
          invoice={invoice}
          organization={organization}
          facility={facility}
          printedBy={printedBy}
        />
      )}
    </DocumentPreview>
  );
}

/**
 * A pay button per unpaid invoice.
 *
 * Split out because the account summary carries invoice *numbers*, while
 * paying needs the UUID — so the buttons re-fetch the invoice list rather
 * than guessing.
 */
function PayButtons({
  account,
  busy,
  onPay,
}: {
  account: PatientAccount | null;
  busy: boolean;
  onPay: (invoiceUuid: string) => void;
}) {
  const [invoices, setInvoices] = useState<Invoice[]>([]);

  useEffect(() => {
    if (!account) return;
    api
      .get<Paginated<Invoice>>(
        `/billing/invoices/?patient=${account.patient_uuid}&unpaid=true`,
      )
      .then((page) => setInvoices(page.results))
      .catch(() => setInvoices([]));
  }, [account]);

  if (invoices.length === 0) return null;

  return (
    <div className="space-y-2">
      {invoices.map((invoice) => (
        <Button
          key={invoice.uuid}
          className="w-full"
          disabled={busy}
          onClick={() => onPay(invoice.uuid)}
        >
          <Banknote className="h-4 w-4" />
          Take payment
          {/* The number only when there is a choice to make: one unpaid
              invoice needs no disambiguation, and a button carrying
              "INV-MKC-KTM-2083/84-000010" reads as a reference, not an act. */}
          {invoices.length > 1 ? (
            <span className="font-mono text-xs opacity-80">{invoice.number}</span>
          ) : null}
        </Button>
      ))}
    </div>
  );
}


/**
 * Collect by eSewa or Khalti at the counter.
 *
 * The wallet opens in its own tab so the till keeps its place, and the
 * patient pays on the screen or on their own phone. This side then asks the
 * provider — through our own API — every few seconds until it has an answer,
 * because a payer who closes the wallet's tab tells us nothing.
 *
 * Nothing here records a payment: the receipt appears because the provider
 * confirmed it (`apps/billing/online.py`).
 */
function CollectOnline({
  account,
  onPaid,
}: {
  account: PatientAccount | null;
  onPaid: () => void;
}) {
  const [providers, setProviders] = useState<OnlineProviderOption[]>([]);
  const [invoices, setInvoices] = useState<Invoice[]>([]);
  const [attempt, setAttempt] = useState<OnlineAttempt | null>(null);
  const [problem, setProblem] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    api
      .get<{ providers: OnlineProviderOption[] }>("/billing/online/")
      .then((body) => setProviders(body.providers))
      .catch(() => setProviders([]));
  }, []);

  useEffect(() => {
    if (!account) return;
    api
      .get<Paginated<Invoice>>(`/billing/invoices/?patient=${account.patient_uuid}&unpaid=true`)
      .then((page) => setInvoices(page.results))
      .catch(() => setInvoices([]));
  }, [account]);

  // Ask until the provider knows. Stops on any settled answer, and after
  // three minutes -- the reconciler picks up anything later.
  useEffect(() => {
    if (!attempt || !["initiated", "pending"].includes(attempt.status)) return;
    let tries = 0;
    const timer = window.setInterval(() => {
      tries += 1;
      if (tries > 36) {
        window.clearInterval(timer);
        return;
      }
      void api
        .post<OnlineAttempt>("/billing/online/", { action: "check", attempt: attempt.uuid })
        .then((answer) => {
          setAttempt(answer);
          if (answer.status === "completed") onPaid();
        })
        .catch(() => undefined);
    }, 5000);
    return () => window.clearInterval(timer);
  }, [attempt, onPaid]);

  if (providers.length === 0 || invoices.length === 0) return null;

  async function collect(invoice: Invoice, provider: OnlineProviderOption) {
    setProblem(null);
    setBusy(true);
    const tab = window.open("", "_blank");
    try {
      const start = await api.post<OnlineStart>(
        `/billing/invoices/${invoice.uuid}/pay-online/`,
        { provider: provider.provider },
      );
      if (start.redirect_url && tab) tab.location.href = start.redirect_url;
      else if (start.form && tab) tab.document.write(autoPostForm(start.form));
      setAttempt({
        uuid: start.uuid, status: "initiated", status_label: "Started",
        amount: start.amount, provider_label: provider.label, invoice: invoice.number ?? "",
        receipt: "", needs_attention: "",
      });
    } catch (err) {
      tab?.close();
      setProblem(err instanceof ApiError ? err.message : "That wallet could not be opened.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="space-y-2 border-t pt-3">
      <p className="text-xs font-medium text-muted-foreground">
        Collect online{providers[0]?.test_mode ? " · test mode" : ""}
      </p>
      {invoices.map((invoice) => (
        <div key={invoice.uuid} className="flex flex-wrap items-center gap-2">
          <span className="font-mono text-xs text-muted-foreground">{invoice.number}</span>
          {providers.map((provider) => (
            <Button
              key={provider.provider}
              size="sm"
              variant="outline"
              disabled={busy}
              onClick={() => void collect(invoice, provider)}
            >
              <Wallet className="h-3.5 w-3.5" />
              {provider.label}
            </Button>
          ))}
        </div>
      ))}

      {problem && (
        <Alert variant="destructive">
          <AlertDescription>{problem}</AlertDescription>
        </Alert>
      )}

      {attempt && (
        <div className="rounded-md border px-3 py-2 text-sm">
          <div className="flex items-center justify-between gap-2">
            <span>
              {attempt.provider_label} · {npr(attempt.amount)}
            </span>
            <Badge
              variant={
                attempt.status === "completed"
                  ? "success"
                  : attempt.status === "pending" || attempt.status === "initiated"
                    ? "warning"
                    : "secondary"
              }
            >
              {attempt.status_label}
            </Badge>
          </div>
          <p className="mt-1 text-xs text-muted-foreground">
            {attempt.needs_attention
              ? attempt.needs_attention
              : attempt.status === "completed"
                ? `Receipt ${attempt.receipt || "—"}`
                : "Waiting for the wallet. This updates itself."}
          </p>
        </div>
      )}
    </div>
  );
}

/** A page that posts eSewa's signed fields the moment it opens. */
function autoPostForm(form: { action: string; fields: Record<string, string> }): string {
  const escape = (value: string) =>
    value.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
  const fields = Object.entries(form.fields)
    .map(([name, value]) => `<input type="hidden" name="${escape(name)}" value="${escape(value)}">`)
    .join("");
  return (
    `<!doctype html><title>Opening eSewa…</title>` +
    `<body style="font:14px system-ui;padding:2rem">Opening eSewa…` +
    `<form id="f" method="POST" action="${escape(form.action)}">${fields}</form>` +
    `<script>document.getElementById("f").submit()</script></body>`
  );
}


/**
 * Online payments that took money and could not be applied.
 *
 * Almost always one invoice settled at the counter while the payer was in
 * their wallet. The money is with the provider and somebody has to refund it,
 * so it is shown where billing is done rather than left in a log — silence
 * here is the failure mode that costs a patient their money.
 */
function OnlineNeedingAttention() {
  const [rows, setRows] = useState<OnlineAttempt[]>([]);

  useEffect(() => {
    api
      .get<{ results: OnlineAttempt[] }>("/billing/online/?attention=1")
      .then((body) => setRows(body.results))
      .catch(() => setRows([]));
  }, []);

  if (rows.length === 0) return null;

  return (
    <Alert variant="destructive">
      <AlertTriangle className="h-4 w-4" />
      <AlertDescription>
        <p className="font-medium">
          {rows.length} online payment{rows.length > 1 ? "s" : ""} need attention
        </p>
        <ul className="mt-1 space-y-0.5 text-sm">
          {rows.slice(0, 5).map((row) => (
            <li key={row.uuid}>
              {row.provider_label} {npr(row.amount)} · {row.invoice} — {row.needs_attention}
            </li>
          ))}
        </ul>
      </AlertDescription>
    </Alert>
  );
}
