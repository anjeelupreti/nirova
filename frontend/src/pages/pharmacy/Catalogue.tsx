/**
 * The medicine catalogue: the list, one product, and editing it.
 *
 * **Nothing in this console could add a medicine.** The endpoint existed and
 * was reachable, and no screen called it -- so a new customer's catalogue could
 * only be loaded by somebody with an HTTP client, and a pharmacy that started
 * stocking a new drug had nowhere to record it. That is the gap this closes,
 * and it is the same shape as most of what the last few days have found:
 * capability with no way in.
 *
 * **Editing needs `catalog.manage`, and reading does not.** Somebody without it
 * sees every product and its details and no form -- rather than a form whose
 * save button returns 403, which is a worse way to learn the same thing.
 *
 * **`code` and `generic_name` are the only required fields**, deliberately
 * mirroring the serializer rather than inventing a stricter form. A pharmacy
 * entering forty products at go-live should not be made to fill in a
 * therapeutic class it has not decided on yet.
 */

import { useCallback, useEffect, useState } from "react";
import { Loader2, Package, Plus, Search, Snowflake, TriangleAlert } from "lucide-react";

import { useSession } from "@/hooks/useSession";
import api, { ApiError } from "@/lib/api";
import type { Paginated, PharmacyProduct } from "@/types";
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

const CATEGORIES = ["medicine", "consumable", "device", "surgical", "reagent",
                    "other"];
const FORMS = ["", "tablet", "capsule", "syrup", "suspension", "injection",
               "infusion", "cream", "ointment"];
const STORAGE = ["ambient", "cool", "refrigerated", "cold_chain", "frozen",
                 "protect_light"];
const SCHEDULES = ["none", "prescription_only", "controlled", "narcotic",
                   "psychotropic"];

/** A blank product, in the shape the form edits. */
const BLANK = {
  code: "",
  generic_name: "",
  brand_name: "",
  strength: "",
  dosage_form: "",
  manufacturer: "",
  therapeutic_class: "",
  category: "medicine",
  base_unit: "",
  pack_size: "",
  pack_unit: "",
  storage_condition: "ambient",
  control_schedule: "none",
  requires_prescription: false,
  reorder_level: "",
  is_formulary: true,
  is_active: true,
};

type Draft = typeof BLANK;

function toDraft(product: PharmacyProduct): Draft {
  const source = product as unknown as Record<string, unknown>;
  const draft = { ...BLANK } as Record<string, unknown>;
  for (const key of Object.keys(BLANK)) {
    if (source[key] !== null && source[key] !== undefined) {
      draft[key] = source[key];
    }
  }
  return draft as Draft;
}

function label(value: string): string {
  return value ? value.replace(/_/g, " ") : "";
}

export default function Catalogue() {
  const { can } = useSession();
  const mayEdit = can("catalog.manage");

  const [products, setProducts] = useState<PharmacyProduct[]>([]);
  const [term, setTerm] = useState("");
  const [loading, setLoading] = useState(true);
  const [open, setOpen] = useState<PharmacyProduct | null>(null);
  const [draft, setDraft] = useState<Draft | null>(null);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async (search: string) => {
    setLoading(true);
    try {
      const query = search.trim()
        ? `?search=${encodeURIComponent(search.trim())}`
        : "";
      const page = await api.get<Paginated<PharmacyProduct>>(
        `/pharmacy/products/${query}`,
      );
      setProducts(page.results);
    } catch (problem) {
      setError(
        problem instanceof ApiError
          ? problem.message
          : "The catalogue could not be loaded.",
      );
    } finally {
      setLoading(false);
    }
  }, []);

  // Debounced, so typing a drug name is one request rather than one per key.
  useEffect(() => {
    const handle = setTimeout(() => void load(term), 250);
    return () => clearTimeout(handle);
  }, [term, load]);

  function startNew() {
    setOpen(null);
    setDraft({ ...BLANK });
    setError(null);
  }

  function startEdit(product: PharmacyProduct) {
    setOpen(product);
    setDraft(null);
    setError(null);
  }

  async function save() {
    if (draft === null) return;
    setSaving(true);
    setError(null);
    try {
      // Empty strings are dropped rather than sent. A blank optional field
      // means "not decided", and posting "" writes that indecision into the
      // record as though somebody had chosen it.
      const body: Record<string, unknown> = {};
      for (const [key, value] of Object.entries(draft)) {
        if (value !== "") body[key] = value;
      }
      const saved = open
        ? await api.patch<PharmacyProduct>(
            `/pharmacy/products/${open.uuid}/`, body,
          )
        : await api.post<PharmacyProduct>("/pharmacy/products/", body);
      setDraft(null);
      setOpen(saved);
      await load(term);
    } catch (problem) {
      setError(
        problem instanceof ApiError
          ? problem.message
          : "That could not be saved.",
      );
    } finally {
      setSaving(false);
    }
  }

  function field(key: keyof Draft, value: unknown) {
    setDraft((current) => (current ? { ...current, [key]: value } : current));
  }

  return (
    <div className="space-y-4">
      <Card>
        <CardHeader className="flex-row items-start justify-between space-y-0">
          <div>
            <CardTitle className="flex items-center gap-2 text-base">
              <Package className="h-4 w-4 text-muted-foreground" />
              Catalogue
            </CardTitle>
            <CardDescription>
              Everything this pharmacy can dispense or sell. Stock is counted
              per batch; this is the list of what a batch can be of.
            </CardDescription>
          </div>
          {mayEdit ? (
            <Button size="sm" onClick={startNew}>
              <Plus className="mr-1.5 h-4 w-4" />
              Add a product
            </Button>
          ) : null}
        </CardHeader>
        <CardContent className="space-y-3">
          <div className="relative max-w-sm">
            <Search className="pointer-events-none absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
            <Input
              value={term}
              onChange={(event) => setTerm(event.target.value)}
              placeholder="Generic name, brand or code"
              className="h-9 pl-8"
            />
          </div>

          {error && draft === null ? (
            <Alert variant="destructive">
              <TriangleAlert className="h-4 w-4" />
              <AlertDescription>{error}</AlertDescription>
            </Alert>
          ) : null}

          {loading ? (
            <p className="py-6 text-sm text-muted-foreground">
              <Loader2 className="mr-2 inline h-4 w-4 animate-spin" />
              Loading the catalogue…
            </p>
          ) : products.length === 0 ? (
            /*
              An empty state that says what to do next. An empty table with
              headings tells somebody the screen works and nothing else.
            */
            <div className="py-10 text-center">
              <p className="text-sm font-medium">
                {term ? "Nothing matches that." : "No products yet."}
              </p>
              <p className="mt-1 text-xs text-muted-foreground">
                {term
                  ? "Try the generic name rather than the brand."
                  : mayEdit
                    ? "Add the first one to start dispensing."
                    : "Somebody with catalogue permission needs to add them."}
              </p>
            </div>
          ) : (
            <div className="overflow-x-auto">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Code</TableHead>
                    <TableHead>Product</TableHead>
                    <TableHead>Form</TableHead>
                    <TableHead>Class</TableHead>
                    <TableHead>Flags</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {products.map((product) => (
                    <TableRow
                      key={product.uuid}
                      onClick={() => startEdit(product)}
                      className="cursor-pointer hover:bg-muted/50"
                    >
                      <TableCell className="font-mono text-xs">
                        {product.code}
                      </TableCell>
                      <TableCell>
                        <span className="font-medium">
                          {product.brand_name || product.generic_name}
                        </span>
                        {product.brand_name ? (
                          <span className="block text-xs text-muted-foreground">
                            {product.generic_name}
                          </span>
                        ) : null}
                      </TableCell>
                      <TableCell className="text-xs capitalize">
                        {label(product.dosage_form)} {product.strength}
                      </TableCell>
                      <TableCell className="text-xs">
                        {product.therapeutic_class || "—"}
                      </TableCell>
                      <TableCell>
                        <span className="flex flex-wrap gap-1">
                          {product.needs_cold_chain ? (
                            <Badge variant="outline" className="gap-1 text-[10px]">
                              <Snowflake className="h-3 w-3" />
                              cold chain
                            </Badge>
                          ) : null}
                          {product.is_controlled ? (
                            <Badge variant="destructive" className="text-[10px]">
                              controlled
                            </Badge>
                          ) : null}
                          {!product.is_active ? (
                            <Badge variant="secondary" className="text-[10px]">
                              inactive
                            </Badge>
                          ) : null}
                        </span>
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
          )}
        </CardContent>
      </Card>

      {/* Viewing one product. */}
      <DetailPanel
        open={open !== null && draft === null}
        onClose={() => setOpen(null)}
        title={open ? open.brand_name || open.generic_name : ""}
        subtitle={open ? `${open.code} · ${open.generic_name}` : undefined}
        footer={
          mayEdit && open ? (
            <Button
              className="w-full"
              onClick={() => setDraft(toDraft(open))}
            >
              Edit this product
            </Button>
          ) : (
            <p className="text-xs text-muted-foreground">
              Changing the catalogue needs the catalogue permission.
            </p>
          )
        }
      >
        {open ? (
          <div className="space-y-6">
            <section>
              <h3 className="mb-1 text-xs font-medium uppercase tracking-wide text-muted-foreground">
                What it is
              </h3>
              <DetailRow label="Generic">{open.generic_name}</DetailRow>
              <DetailRow label="Brand">{open.brand_name}</DetailRow>
              <DetailRow label="Strength">{open.strength}</DetailRow>
              <DetailRow label="Form">{label(open.dosage_form)}</DetailRow>
              <DetailRow label="Category">{label(open.category ?? "")}</DetailRow>
              <DetailRow label="Class">{open.therapeutic_class}</DetailRow>
              <DetailRow label="Manufacturer">{open.manufacturer}</DetailRow>
            </section>

            <section>
              <h3 className="mb-1 text-xs font-medium uppercase tracking-wide text-muted-foreground">
                How it is counted
              </h3>
              <DetailRow label="Base unit">{open.base_unit}</DetailRow>
              <DetailRow label="Pack">
                {open.pack_size ? `${open.pack_size} ${open.pack_unit ?? ""}` : ""}
              </DetailRow>
              <DetailRow label="Reorder at">{open.reorder_level}</DetailRow>
              <DetailRow label="Barcode">{open.barcode}</DetailRow>
            </section>

            <section>
              <h3 className="mb-1 text-xs font-medium uppercase tracking-wide text-muted-foreground">
                Handling
              </h3>
              <DetailRow label="Storage">
                {label(open.storage_condition)}
                {open.needs_cold_chain ? " · cold chain" : ""}
              </DetailRow>
              {/*
                A controlled drug is called out rather than left as a code in a
                field. It changes who may dispense it and what has to be
                recorded, and that is not something to read past.
              */}
              <DetailRow label="Schedule">
                {open.is_controlled ? (
                  <span className="font-medium text-destructive">
                    {label(open.control_schedule)}
                  </span>
                ) : (
                  label(open.control_schedule)
                )}
              </DetailRow>
              <DetailRow label="Prescription">
                {open.requires_prescription ? "Required" : "Not required"}
              </DetailRow>
              <DetailRow label="Formulary">
                {open.is_formulary ? "On formulary" : "Off formulary"}
              </DetailRow>
              <DetailRow label="Status">
                {open.is_active ? "Active" : "Inactive"}
              </DetailRow>
            </section>
          </div>
        ) : null}
      </DetailPanel>

      {/* Adding one, or editing the one that is open. */}
      <DetailPanel
        open={draft !== null}
        onClose={() => setDraft(null)}
        title={open ? "Edit product" : "Add a product"}
        subtitle={open ? open.code : "Only a code and a generic name are required"}
        footer={
          <div className="flex gap-2">
            <Button
              className="flex-1"
              disabled={
                saving || !draft?.code.trim() || !draft?.generic_name.trim()
              }
              onClick={() => void save()}
            >
              {saving ? "Saving…" : open ? "Save changes" : "Add product"}
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
                <Label htmlFor="code">
                  Code <span className="text-destructive">*</span>
                </Label>
                <Input
                  id="code"
                  value={draft.code}
                  onChange={(event) => field("code", event.target.value)}
                  // The code is the handle everything else refers to, so it is
                  // fixed once the product exists rather than quietly editable.
                  disabled={open !== null}
                />
              </div>
              <div className="space-y-1">
                <Label htmlFor="generic">
                  Generic name <span className="text-destructive">*</span>
                </Label>
                <Input
                  id="generic"
                  value={draft.generic_name}
                  onChange={(event) =>
                    field("generic_name", event.target.value)
                  }
                />
              </div>
              <div className="space-y-1">
                <Label htmlFor="brand">Brand name</Label>
                <Input
                  id="brand"
                  value={draft.brand_name}
                  onChange={(event) => field("brand_name", event.target.value)}
                />
              </div>
              <div className="space-y-1">
                <Label htmlFor="strength">Strength</Label>
                <Input
                  id="strength"
                  value={draft.strength}
                  onChange={(event) => field("strength", event.target.value)}
                  placeholder="500 mg"
                />
              </div>
              <div className="space-y-1">
                <Label htmlFor="form">Form</Label>
                <Select
                  id="form"
                  value={draft.dosage_form}
                  onChange={(event) => field("dosage_form", event.target.value)}
                >
                  {FORMS.map((value) => (
                    <option key={value} value={value}>
                      {value ? label(value) : "—"}
                    </option>
                  ))}
                </Select>
              </div>
              <div className="space-y-1">
                <Label htmlFor="category">Category</Label>
                <Select
                  id="category"
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
                <Label htmlFor="unit">Base unit</Label>
                <Input
                  id="unit"
                  value={draft.base_unit}
                  onChange={(event) => field("base_unit", event.target.value)}
                  placeholder="tablet"
                />
              </div>
              <div className="space-y-1">
                <Label htmlFor="reorder">Reorder level</Label>
                <Input
                  id="reorder"
                  type="number"
                  value={draft.reorder_level}
                  onChange={(event) =>
                    field("reorder_level", event.target.value)
                  }
                />
              </div>
              <div className="space-y-1">
                <Label htmlFor="storage">Storage</Label>
                <Select
                  id="storage"
                  value={draft.storage_condition}
                  onChange={(event) =>
                    field("storage_condition", event.target.value)
                  }
                >
                  {STORAGE.map((value) => (
                    <option key={value} value={value}>
                      {label(value)}
                    </option>
                  ))}
                </Select>
              </div>
              <div className="space-y-1">
                <Label htmlFor="schedule">Control schedule</Label>
                <Select
                  id="schedule"
                  value={draft.control_schedule}
                  onChange={(event) =>
                    field("control_schedule", event.target.value)
                  }
                >
                  {SCHEDULES.map((value) => (
                    <option key={value} value={value}>
                      {label(value)}
                    </option>
                  ))}
                </Select>
              </div>
            </div>

            <div className="space-y-2 border-t pt-3">
              {[
                ["requires_prescription", "Needs a prescription"],
                ["is_formulary", "On the formulary"],
                ["is_active", "Active"],
              ].map(([key, text]) => (
                <label key={key} className="flex items-center gap-2 text-sm">
                  <input
                    type="checkbox"
                    checked={Boolean(draft[key as keyof Draft])}
                    onChange={(event) =>
                      field(key as keyof Draft, event.target.checked)
                    }
                  />
                  {text}
                </label>
              ))}
            </div>
          </div>
        ) : null}
      </DetailPanel>
    </div>
  );
}
