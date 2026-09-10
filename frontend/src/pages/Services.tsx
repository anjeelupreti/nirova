/**
 * Services and what they cost.
 *
 * **A hospital cannot bill for anything that is not on this list**, and until
 * now nothing in the console could put something on it. `/billing/services/`
 * has always listed, created and edited service items; the billing screen read
 * that list to fill a dropdown and offered no way to add to it. So the price of
 * a consultation could only be set by somebody with an HTTP client.
 *
 * **The price here is the default, not the price.** A price list overrides it
 * per patient category and per payer, which is why an insurer pays one figure
 * and a walk-in another for the same procedure. The list of those is shown
 * beside the services so the relationship is visible rather than something you
 * have to be told.
 *
 * **Reading is `invoice.read` and changing is `catalog.manage`.** Anybody who
 * raises an invoice needs to see what things cost; changing what they cost is
 * a different authority, and putting the two together is the oldest till fraud
 * there is.
 */

import { useCallback, useEffect, useState } from "react";
import { Loader2, Plus, Receipt, Search, Tags, TriangleAlert } from "lucide-react";

import { useSession } from "@/hooks/useSession";
import api, { ApiError } from "@/lib/api";
import type { Paginated, PriceList, ServiceItem } from "@/types";
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
  DetailPanel,
  DetailRow,
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

const CATEGORIES = ["consultation", "registration", "procedure", "laboratory",
                    "radiology", "pharmacy", "consumable", "bed", "nursing",
                    "theatre", "ambulance", "diet", "package", "other"];
const TAX = ["exempt", "zero_rated", "standard"];

const BLANK = {
  code: "",
  name: "",
  category: "consultation",
  description: "",
  default_price: "",
  tax_treatment: "exempt",
  max_discount_percent: "",
  requires_prescription: false,
  is_recurring_daily: false,
  is_active: true,
};

type Draft = typeof BLANK;

function label(value: string): string {
  return value ? value.replace(/_/g, " ") : "";
}

const npr = (value: string | number) =>
  `NPR ${Number(value || 0).toLocaleString("en-IN", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  })}`;

export default function ServicesPage() {
  const { can } = useSession();
  const mayEdit = can("catalog.manage");

  const [services, setServices] = useState<ServiceItem[]>([]);
  const [lists, setLists] = useState<PriceList[]>([]);
  const [term, setTerm] = useState("");
  const [category, setCategory] = useState("");
  const [loading, setLoading] = useState(true);
  const [open, setOpen] = useState<ServiceItem | null>(null);
  const [draft, setDraft] = useState<Draft | null>(null);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const query = new URLSearchParams({ page_size: "200" });
      if (term.trim()) query.set("search", term.trim());
      if (category) query.set("category", category);
      const page = await api.get<Paginated<ServiceItem>>(
        `/billing/services/?${query}`,
      );
      setServices(page.results);
    } catch (problem) {
      setError(
        problem instanceof ApiError
          ? problem.message
          : "The service list could not be loaded.",
      );
    } finally {
      setLoading(false);
    }
  }, [term, category]);

  useEffect(() => {
    const handle = setTimeout(() => void load(), 250);
    return () => clearTimeout(handle);
  }, [load]);

  useEffect(() => {
    api
      .get<Paginated<PriceList>>("/billing/price-lists/")
      .then((page) => setLists(page.results))
      .catch(() => undefined);
  }, []);

  async function save() {
    if (draft === null) return;
    setSaving(true);
    setError(null);
    try {
      // Empty optional fields are omitted rather than sent as "": a blank
      // price means "not priced yet", and posting an empty string writes that
      // as though somebody had decided it was free.
      const body: Record<string, unknown> = {};
      for (const [key, value] of Object.entries(draft)) {
        if (value !== "") body[key] = value;
      }
      const saved = open
        ? await api.patch<ServiceItem>(`/billing/services/${open.uuid}/`, body)
        : await api.post<ServiceItem>("/billing/services/", body);
      setDraft(null);
      setOpen(saved);
      await load();
    } catch (problem) {
      setError(
        problem instanceof ApiError ? problem.message : "That could not be saved.",
      );
    } finally {
      setSaving(false);
    }
  }

  function toDraft(service: ServiceItem): Draft {
    const source = service as unknown as Record<string, unknown>;
    const next = { ...BLANK } as Record<string, unknown>;
    for (const key of Object.keys(BLANK)) {
      if (source[key] !== null && source[key] !== undefined) {
        next[key] = source[key];
      }
    }
    return next as Draft;
  }

  function field(key: keyof Draft, value: unknown) {
    setDraft((current) => (current ? { ...current, [key]: value } : current));
  }

  return (
    <div className="space-y-6">
      <PageHeader
        title="Services and prices"
        description="Everything a patient can be charged for. Nothing can be billed that is not on this list."
        actions={
          <>
            {mayEdit ? (
              <Button onClick={() => { setOpen(null); setDraft({ ...BLANK }); }}>
                <Plus className="mr-1.5 h-4 w-4" />
                Add a service
              </Button>
            ) : null}
          </>
        }
      />

      {error && draft === null ? (
        <Alert variant="destructive">
          <TriangleAlert className="h-4 w-4" />
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      ) : null}

      <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_minmax(0,20rem)]">
        <Card>
          <CardHeader className="pb-3">
            <CardTitle className="flex items-center gap-2 text-base">
              <Receipt className="h-4 w-4 text-muted-foreground" />
              {services.length} {services.length === 1 ? "service" : "services"}
            </CardTitle>
            <CardDescription>
              The price shown is the default. A price list can override it for a
              category of patient or a named payer.
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-3">
            <div className="flex flex-wrap gap-2">
              <div className="relative min-w-[12rem] flex-1">
                <Search className="pointer-events-none absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
                <Input
                  value={term}
                  onChange={(event) => setTerm(event.target.value)}
                  placeholder="Name or code"
                  className="h-9 pl-8"
                />
              </div>
              <Select
                value={category}
                onChange={(event) => setCategory(event.target.value)}
                className="h-9 w-auto"
                aria-label="Category"
              >
                <option value="">All categories</option>
                {CATEGORIES.map((value) => (
                  <option key={value} value={value}>
                    {label(value)}
                  </option>
                ))}
              </Select>
            </div>

            {loading ? (
              <p className="py-6 text-sm text-muted-foreground">
                <Loader2 className="mr-2 inline h-4 w-4 animate-spin" />
                Loading services…
              </p>
            ) : services.length === 0 ? (
              <div className="py-10 text-center">
                <p className="text-sm font-medium">
                  {term || category ? "Nothing matches that." : "No services yet."}
                </p>
                <p className="mt-1 text-xs text-muted-foreground">
                  {term || category
                    ? "Try a different category, or clear the search."
                    : mayEdit
                      ? "Add a consultation fee to start charging for anything."
                      : "Somebody with catalogue permission needs to add them."}
                </p>
              </div>
            ) : (
              <div className="overflow-x-auto">
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead>Code</TableHead>
                      <TableHead>Service</TableHead>
                      <TableHead>Category</TableHead>
                      <TableHead className="text-right">Default price</TableHead>
                      <TableHead>Tax</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {services.map((service) => (
                      <TableRow
                        key={service.uuid}
                        onClick={() => { setOpen(service); setDraft(null); }}
                        className="cursor-pointer hover:bg-muted/50"
                      >
                        <TableCell className="font-mono text-xs">
                          {service.code}
                        </TableCell>
                        <TableCell className="font-medium">
                          {service.name}
                          {!service.is_active ? (
                            <Badge variant="secondary" className="ml-1.5 text-[10px]">
                              inactive
                            </Badge>
                          ) : null}
                        </TableCell>
                        <TableCell className="text-xs capitalize">
                          {label(service.category)}
                        </TableCell>
                        <TableCell className="text-right tabular-nums">
                          {/*
                            A service with no price is not free, it is unpriced
                            -- and a bill that silently charges nothing is worse
                            than one that refuses.
                          */}
                          {Number(service.default_price) > 0
                            ? npr(service.default_price)
                            : (
                              <span className="text-xs text-muted-foreground">
                                not priced
                              </span>
                            )}
                        </TableCell>
                        <TableCell className="text-xs">
                          {label(service.tax_treatment)}
                        </TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </div>
            )}
          </CardContent>
        </Card>

        <Card className="h-fit">
          <CardHeader className="pb-3">
            <CardTitle className="flex items-center gap-2 text-base">
              <Tags className="h-4 w-4 text-muted-foreground" />
              Price lists
            </CardTitle>
            <CardDescription>
              What overrides the default, and for whom.
            </CardDescription>
          </CardHeader>
          <CardContent>
            {lists.length === 0 ? (
              <p className="text-sm text-muted-foreground">
                None yet, so every patient pays the default price.
              </p>
            ) : (
              <div className="space-y-2">
                {lists.map((list) => (
                  <div key={list.uuid} className="border-b pb-2 last:border-b-0">
                    <p className="text-sm font-medium">{list.name}</p>
                    <p className="text-xs text-muted-foreground">
                      {list.patient_category
                        ? label(list.patient_category)
                        : "any patient"}
                      {list.payer_reference ? ` · ${list.payer_reference}` : ""}
                      {" · priority "}
                      {list.priority}
                    </p>
                  </div>
                ))}
              </div>
            )}
          </CardContent>
        </Card>
      </div>

      <DetailPanel
        open={open !== null && draft === null}
        onClose={() => setOpen(null)}
        title={open?.name ?? ""}
        subtitle={open ? `${open.code} · ${label(open.category)}` : undefined}
        footer={
          mayEdit && open ? (
            <Button className="w-full" onClick={() => setDraft(toDraft(open))}>
              Edit this service
            </Button>
          ) : (
            <p className="text-xs text-muted-foreground">
              Changing what things cost needs the catalogue permission.
            </p>
          )
        }
      >
        {open ? (
          <div className="space-y-6">
            <section>
              <h3 className="mb-1 text-xs font-medium uppercase tracking-wide text-muted-foreground">
                What it costs
              </h3>
              <DetailRow label="Default price">
                {Number(open.default_price) > 0 ? npr(open.default_price) : null}
              </DetailRow>
              <DetailRow label="Tax">{label(open.tax_treatment)}</DetailRow>
              <DetailRow label="Effective tax rate">
                {open.effective_tax_rate ? `${open.effective_tax_rate}%` : null}
              </DetailRow>
              <DetailRow label="Discount limit">
                {open.max_discount_percent
                  ? `${open.max_discount_percent}%`
                  : null}
              </DetailRow>
            </section>
            <section>
              <h3 className="mb-1 text-xs font-medium uppercase tracking-wide text-muted-foreground">
                How it behaves
              </h3>
              <DetailRow label="Category">{label(open.category)}</DetailRow>
              <DetailRow label="Status">
                {open.is_active ? "Active" : "Inactive"}
              </DetailRow>
            </section>
          </div>
        ) : null}
      </DetailPanel>

      <DetailPanel
        open={draft !== null}
        onClose={() => setDraft(null)}
        title={open ? "Edit service" : "Add a service"}
        subtitle={open ? open.code : "A code, a name and a category are required"}
        footer={
          <div className="flex gap-2">
            <Button
              className="flex-1"
              disabled={saving || !draft?.code.trim() || !draft?.name.trim()}
              onClick={() => void save()}
            >
              {saving ? "Saving…" : open ? "Save changes" : "Add service"}
            </Button>
            <Button variant="outline" onClick={() => setDraft(null)}>
              Cancel
            </Button>
          </div>
        }
      >
        {draft ? (
          <div className="space-y-4">
            {error ? (
              <Alert variant="destructive">
                <TriangleAlert className="h-4 w-4" />
                <AlertDescription>{error}</AlertDescription>
              </Alert>
            ) : null}
            <div className="grid gap-3 sm:grid-cols-2">
              <div className="space-y-1">
                <Label htmlFor="svc-code">
                  Code <span className="text-destructive">*</span>
                </Label>
                <Input
                  id="svc-code"
                  value={draft.code}
                  onChange={(event) => field("code", event.target.value)}
                  // Charges reference the code, and an issued invoice snapshots
                  // it. Changing it after the fact would leave old invoices
                  // pointing at a service that no longer answers to that name.
                  disabled={open !== null}
                />
              </div>
              <div className="space-y-1">
                <Label htmlFor="svc-name">
                  Name <span className="text-destructive">*</span>
                </Label>
                <Input
                  id="svc-name"
                  value={draft.name}
                  onChange={(event) => field("name", event.target.value)}
                />
              </div>
              <div className="space-y-1">
                <Label htmlFor="svc-cat">
                  Category <span className="text-destructive">*</span>
                </Label>
                <Select
                  id="svc-cat"
                  value={draft.category}
                  onChange={(event) => field("category", event.target.value)}
                >
                  {CATEGORIES.map((value) => (
                    <option key={value} value={value}>
                      {label(value)}
                    </option>
                  ))}
                </Select>
              </div>
              <div className="space-y-1">
                <Label htmlFor="svc-price">Default price</Label>
                <Input
                  id="svc-price"
                  type="number"
                  step="0.01"
                  value={draft.default_price}
                  onChange={(event) =>
                    field("default_price", event.target.value)
                  }
                />
              </div>
              <div className="space-y-1">
                <Label htmlFor="svc-tax">Tax treatment</Label>
                <Select
                  id="svc-tax"
                  value={draft.tax_treatment}
                  onChange={(event) => field("tax_treatment", event.target.value)}
                >
                  {TAX.map((value) => (
                    <option key={value} value={value}>
                      {label(value)}
                    </option>
                  ))}
                </Select>
              </div>
              <div className="space-y-1">
                <Label htmlFor="svc-disc">Discount limit (%)</Label>
                <Input
                  id="svc-disc"
                  type="number"
                  value={draft.max_discount_percent}
                  onChange={(event) =>
                    field("max_discount_percent", event.target.value)
                  }
                />
              </div>
            </div>
            <div className="space-y-2 border-t pt-3">
              <label className="flex items-center gap-2 text-sm">
                <input
                  type="checkbox"
                  checked={draft.is_recurring_daily}
                  onChange={(event) =>
                    field("is_recurring_daily", event.target.checked)
                  }
                />
                Charged every day of a stay
              </label>
              <label className="flex items-center gap-2 text-sm">
                <input
                  type="checkbox"
                  checked={draft.is_active}
                  onChange={(event) => field("is_active", event.target.checked)}
                />
                Active
              </label>
            </div>
          </div>
        ) : null}
      </DetailPanel>
    </div>
  );
}
