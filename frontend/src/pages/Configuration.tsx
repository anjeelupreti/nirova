/**
 * The lists that did not have a natural home, gathered into one.
 *
 * Payers, scheme packages, stock locations, theatres, diagnostic tests and
 * referral providers. Each is master data some daily screen depends on and
 * none of them could be created through the console — a hospital could accept
 * an insurer's patients only if a seed had already put that insurer in the
 * database.
 *
 * **Why one screen rather than six.** Each of these is visited rarely and by
 * few people. Six more sidebar entries would push the daily screens further
 * down a list that was already too long, which is the complaint that started
 * this pass. They are grouped here and the sidebar carries one entry.
 *
 * **The permissions are per list, not per screen.** Stock locations are
 * `catalog.manage`, theatres are `bed.manage`, payers are `config.update` —
 * because that is what the endpoints ask for, and a screen that asked for one
 * blanket permission would either lock out somebody entitled or let somebody
 * through who is not.
 */

import { useState } from "react";
import {
  Building,
  FlaskConical,
  Package,
  Scissors,
  Send,
  ShieldCheck,
} from "lucide-react";

import MasterData, { type MasterSpec } from "@/components/MasterData";
import { cn } from "@/lib/utils";

const PAYER_KINDS = ["insurer", "government", "corporate", "ngo", "self_pay",
                     "other"];
const MODALITIES = ["laboratory", "xray", "ultrasound", "ct", "mri",
                    "mammography", "ecg", "echo", "endoscopy", "other"];
const LOCATION_TYPES = ["main_store", "sub_store", "dispensary", "ward_stock",
                        "theatre", "emergency", "quarantine", "other"];
const THEATRE_TYPES = ["general", "orthopaedic", "cardiac", "neuro",
                       "obstetric", "day_care", "minor", "other"];
const PROVIDER_TYPES = ["hospital", "clinic", "laboratory", "imaging",
                        "specialist", "other"];

const PAYERS: MasterSpec = {
  title: "Payers",
  description:
    "Insurers, government schemes and corporate accounts. A claim cannot be " +
    "raised against somebody who is not on this list.",
  noun: "payer",
  endpoint: "/insurance/payers/",
  writePermission: "config.update",
  searchable: true,
  sortBy: "name",
  columns: [
    { key: "code", label: "Code" },
    { key: "name", label: "Payer" },
    { key: "kind", label: "Kind" },
    { key: "settlement_days", label: "Settles in", align: "right" },
    { key: "is_active", label: "Active" },
  ],
  fields: [
    { key: "code", label: "Code", required: true, fixedAfterCreate: true },
    { key: "name", label: "Name", required: true },
    { key: "kind", label: "Kind", kind: "select", options: PAYER_KINDS,
      required: true },
    { key: "registration_number", label: "Registration number" },
    { key: "pan_number", label: "PAN" },
    { key: "contact_name", label: "Contact", group: "Getting hold of them" },
    { key: "contact_phone", label: "Phone", group: "Getting hold of them" },
    { key: "contact_email", label: "Email", group: "Getting hold of them" },
    { key: "address", label: "Address", group: "Getting hold of them" },
    {
      key: "submission_window_days",
      label: "Claim window (days)",
      kind: "number",
      group: "Terms",
      help: "How long after discharge a claim may still be submitted.",
    },
    {
      key: "settlement_days",
      label: "Settles in (days)",
      kind: "number",
      group: "Terms",
    },
    {
      key: "preauthorisation_threshold",
      label: "Pre-authorisation above (NPR)",
      kind: "number",
      group: "Terms",
    },
    {
      key: "requires_preauthorisation",
      label: "Needs pre-authorisation",
      kind: "checkbox",
    },
    { key: "is_active", label: "Active", kind: "checkbox" },
  ],
};

const PACKAGES: MasterSpec = {
  title: "Scheme packages",
  description:
    "What a payer covers as a fixed-price package, and for how much.",
  noun: "package",
  endpoint: "/insurance/packages/",
  writePermission: "config.update",
  sortBy: "code",
  columns: [
    { key: "code", label: "Code" },
    { key: "name", label: "Package" },
    { key: "package_amount", label: "Amount", align: "right" },
    { key: "effective_from", label: "From" },
    { key: "is_active", label: "Active" },
  ],
  fields: [
    {
      key: "payer",
      label: "Payer",
      kind: "reference",
      optionsFrom: "/insurance/payers/",
      required: true,
    },
    { key: "code", label: "Code", required: true, fixedAfterCreate: true },
    { key: "name", label: "Name", required: true },
    { key: "package_amount", label: "Amount (NPR)", kind: "number",
      required: true },
    { key: "effective_from", label: "Effective from", kind: "date",
      required: true },
    { key: "effective_to", label: "Effective to", kind: "date" },
    { key: "maximum_per_year", label: "Maximum a year", kind: "number" },
    { key: "includes", label: "Includes", kind: "textarea" },
    { key: "excludes", label: "Excludes", kind: "textarea" },
    { key: "is_active", label: "Active", kind: "checkbox" },
  ],
};

const LOCATIONS: MasterSpec = {
  title: "Stock locations",
  description:
    "Where stock is held. Every batch lives in one of these, and a dispense " +
    "comes out of one.",
  noun: "location",
  endpoint: "/pharmacy/locations/",
  writePermission: "catalog.manage",
  sortBy: "code",
  columns: [
    { key: "code", label: "Code" },
    { key: "name", label: "Location" },
    { key: "facility_name", label: "Facility" },
    { key: "location_type", label: "Type" },
    { key: "is_dispensable", label: "Dispensable" },
  ],
  fields: [
    {
      key: "facility",
      label: "Facility",
      kind: "reference",
      optionsFrom: "/org/facilities/",
      required: true,
    },
    { key: "code", label: "Code", required: true, fixedAfterCreate: true },
    { key: "name", label: "Name", required: true },
    { key: "location_type", label: "Type", kind: "select",
      options: LOCATION_TYPES },
    {
      key: "is_dispensable",
      label: "Stock here may be dispensed",
      kind: "checkbox",
    },
    {
      key: "is_quarantine",
      label: "Quarantine — stock here is held, not sold",
      kind: "checkbox",
    },
    { key: "is_active", label: "Active", kind: "checkbox" },
  ],
};

const THEATRES: MasterSpec = {
  title: "Theatres",
  description: "Operating theatres, and how long each needs between cases.",
  noun: "theatre",
  endpoint: "/ot/theatres/",
  writePermission: "bed.manage",
  writeScope: "facility",
  sortBy: "code",
  columns: [
    { key: "code", label: "Code" },
    { key: "name", label: "Theatre" },
    { key: "theatre_type", label: "Type" },
    { key: "turnaround_minutes", label: "Turnaround", align: "right" },
    { key: "is_active", label: "Active" },
  ],
  fields: [
    {
      key: "facility",
      label: "Facility",
      kind: "reference",
      optionsFrom: "/org/facilities/",
      required: true,
    },
    { key: "code", label: "Code", required: true, fixedAfterCreate: true },
    { key: "name", label: "Name", required: true },
    { key: "theatre_type", label: "Type", kind: "select",
      options: THEATRE_TYPES },
    { key: "floor", label: "Floor" },
    {
      key: "turnaround_minutes",
      label: "Turnaround (minutes)",
      kind: "number",
      help: "Cleaning and setup between cases. The scheduler leaves this gap.",
    },
    { key: "session_starts_at", label: "Sessions start", kind: "time" },
    { key: "session_ends_at", label: "Sessions end", kind: "time" },
    { key: "has_laminar_flow", label: "Laminar flow", kind: "checkbox" },
    { key: "has_image_intensifier", label: "Image intensifier",
      kind: "checkbox" },
    { key: "has_microscope", label: "Microscope", kind: "checkbox" },
    { key: "is_active", label: "Active", kind: "checkbox" },
  ],
};

const TESTS: MasterSpec = {
  title: "Diagnostic tests",
  description:
    "What the laboratory and the imaging department can be asked for. " +
    "Nothing can be ordered that is not here.",
  noun: "test",
  endpoint: "/diagnostics/tests/",
  writePermission: "catalog.manage",
  searchable: true,
  sortBy: "code",
  columns: [
    { key: "code", label: "Code" },
    { key: "name", label: "Test" },
    { key: "modality", label: "Modality" },
    { key: "turnaround_minutes", label: "Turnaround", align: "right" },
    { key: "is_active", label: "Active" },
  ],
  fields: [
    { key: "code", label: "Code", required: true, fixedAfterCreate: true },
    { key: "name", label: "Name", required: true },
    { key: "modality", label: "Modality", kind: "select", options: MODALITIES,
      required: true },
    { key: "short_name", label: "Short name" },
    { key: "unit", label: "Unit", group: "Result" },
    { key: "decimal_places", label: "Decimal places", kind: "number",
      group: "Result" },
    {
      key: "turnaround_minutes",
      label: "Turnaround (minutes)",
      kind: "number",
      group: "Result",
      help: "Used to set the due time on every order, so lateness is measurable.",
    },
    { key: "specimen_type", label: "Specimen", group: "Collection" },
    { key: "collection_instructions", label: "Collection instructions",
      kind: "textarea", group: "Collection" },
    { key: "patient_preparation", label: "Patient preparation",
      kind: "textarea", group: "Collection" },
    { key: "is_panel", label: "A panel of other tests", kind: "checkbox" },
    { key: "is_outsourced", label: "Sent out to a partner", kind: "checkbox" },
    { key: "is_active", label: "Active", kind: "checkbox" },
  ],
};

const PROVIDERS: MasterSpec = {
  title: "Referral providers",
  description: "Where patients are referred to, and how that place is reached.",
  noun: "provider",
  endpoint: "/referrals/providers/",
  lookupField: "code",
  writePermission: "config.update",
  searchable: true,
  sortBy: "name",
  columns: [
    { key: "code", label: "Code" },
    { key: "name", label: "Provider" },
    { key: "provider_type", label: "Type" },
    { key: "district", label: "District" },
    { key: "is_active", label: "Active" },
  ],
  fields: [
    { key: "code", label: "Code", required: true, fixedAfterCreate: true },
    { key: "name", label: "Name", required: true },
    { key: "provider_type", label: "Type", kind: "select",
      options: PROVIDER_TYPES },
    { key: "contact_name", label: "Contact", group: "Getting hold of them" },
    { key: "phone", label: "Phone", group: "Getting hold of them" },
    { key: "email", label: "Email", group: "Getting hold of them" },
    { key: "address", label: "Address", group: "Getting hold of them" },
    { key: "district", label: "District", group: "Getting hold of them" },
    { key: "accepts_email", label: "Accepts referrals by email",
      kind: "checkbox" },
    { key: "accepts_paper", label: "Accepts paper referrals",
      kind: "checkbox" },
    { key: "is_active", label: "Active", kind: "checkbox" },
  ],
};

const SECTIONS = [
  { id: "payers", label: "Payers", icon: ShieldCheck, spec: PAYERS },
  { id: "packages", label: "Packages", icon: Building, spec: PACKAGES },
  { id: "locations", label: "Stock locations", icon: Package, spec: LOCATIONS },
  { id: "theatres", label: "Theatres", icon: Scissors, spec: THEATRES },
  { id: "tests", label: "Diagnostic tests", icon: FlaskConical, spec: TESTS },
  { id: "providers", label: "Referral providers", icon: Send, spec: PROVIDERS },
];

export default function ConfigurationPage() {
  const [section, setSection] = useState(SECTIONS[0].id);
  const active = SECTIONS.find((entry) => entry.id === section) ?? SECTIONS[0];

  return (
    <div className="space-y-4">
      <div>
        <h1 className="text-xl font-semibold tracking-tight">Configuration</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          The lists the daily screens depend on. Set up once, edited when
          something changes.
        </p>
      </div>

      <div className="flex flex-wrap gap-1.5">
        {SECTIONS.map(({ id, label, icon: Icon }) => (
          <button
            key={id}
            type="button"
            onClick={() => setSection(id)}
            className={cn(
              "flex items-center gap-1.5 rounded-md border px-3 py-1.5 text-sm",
              id === section
                ? "border-primary bg-muted font-medium"
                : "border-transparent text-muted-foreground hover:bg-muted/60",
            )}
          >
            <Icon className="h-4 w-4" />
            {label}
          </button>
        ))}
      </div>

      <MasterData key={active.id} spec={active.spec} />
    </div>
  );
}
