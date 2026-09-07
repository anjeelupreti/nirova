/**
 * What everybody is paid out of, and what the state takes.
 *
 * Pay components, salary structures, tax slabs and contribution schemes: the
 * four tables every payslip is computed from, and none of them had a screen.
 * A hospital could run payroll only against whatever a seed had put there.
 *
 * **Tax slabs are statutory.** They are not a preference — they are published
 * by the government each fiscal year, and entering them wrongly does not
 * produce an argument, it produces an under-deduction the hospital owes.
 * Which is why they sit behind `payroll.process` alongside everything else
 * here rather than under a general configuration permission.
 *
 * **Three of these are addressed by `code`, not uuid.** Measured, not assumed:
 * components and structures both 404 when patched by uuid, and that failure
 * reads as a permissions problem.
 */

import { useState } from "react";
import { Calculator, Coins, Landmark, Layers } from "lucide-react";

import MasterData, { type MasterSpec } from "@/components/MasterData";
import { cn } from "@/lib/utils";

const COMPONENT_TYPES = ["earning", "deduction", "employer_contribution"];
const BASES = ["fixed", "percent_of_basic", "percent_of_gross", "formula",
               "per_day", "per_hour"];
const REGIMES = ["individual", "couple"];

const COMPONENTS: MasterSpec = {
  title: "Pay components",
  description:
    "The lines a payslip is built from: basic, allowances, deductions and " +
    "what the employer contributes on top.",
  noun: "component",
  endpoint: "/payroll/components/",
  lookupField: "code",
  writePermission: "payroll.process",
  writeScope: "facility",
  sortBy: "code",
  columns: [
    { key: "code", label: "Code" },
    { key: "name", label: "Component" },
    { key: "component_type", label: "Type" },
    { key: "basis", label: "Basis" },
    { key: "is_taxable", label: "Taxable" },
  ],
  fields: [
    { key: "code", label: "Code", required: true, fixedAfterCreate: true },
    { key: "name", label: "Name", required: true },
    {
      key: "component_type",
      label: "Type",
      kind: "select",
      options: COMPONENT_TYPES,
      required: true,
    },
    { key: "basis", label: "Calculated as", kind: "select", options: BASES },
    { key: "rate", label: "Rate", kind: "number" },
    { key: "amount", label: "Fixed amount", kind: "number" },
    { key: "sequence", label: "Order on the payslip", kind: "number" },
    { key: "is_taxable", label: "Taxable", kind: "checkbox" },
    {
      key: "counts_towards_contribution_base",
      label: "Counts towards contributions",
      kind: "checkbox",
    },
    { key: "is_prorated", label: "Prorated for part months", kind: "checkbox" },
    { key: "is_statutory", label: "Statutory", kind: "checkbox" },
    { key: "is_active", label: "Active", kind: "checkbox" },
  ],
};

const STRUCTURES: MasterSpec = {
  title: "Salary structures",
  description:
    "Named sets of components. An employee is put on a structure rather than " +
    "having their payslip assembled by hand.",
  noun: "structure",
  endpoint: "/payroll/structures/",
  lookupField: "code",
  writePermission: "payroll.process",
  writeScope: "facility",
  sortBy: "code",
  columns: [
    { key: "code", label: "Code" },
    { key: "name", label: "Structure" },
    { key: "is_active", label: "Active" },
  ],
  fields: [
    { key: "code", label: "Code", required: true, fixedAfterCreate: true },
    { key: "name", label: "Name", required: true },
    { key: "description", label: "Description", kind: "textarea" },
    { key: "is_active", label: "Active", kind: "checkbox" },
  ],
};

const TAX_SLABS: MasterSpec = {
  title: "Tax slabs",
  description:
    "Published by the government each fiscal year. These are not a " +
    "preference: entering them wrongly produces an under-deduction the " +
    "hospital owes, not an argument.",
  noun: "slab",
  endpoint: "/payroll/tax-slabs/",
  writePermission: "payroll.process",
  writeScope: "facility",
  sortBy: "fiscal_year",
  emptyHint: "Enter this year's slabs before the first payroll run.",
  columns: [
    { key: "fiscal_year", label: "Year" },
    { key: "regime", label: "Regime" },
    { key: "lower_bound", label: "From", align: "right" },
    { key: "upper_bound", label: "To", align: "right" },
    { key: "rate_percent", label: "Rate", align: "right" },
  ],
  fields: [
    {
      key: "fiscal_year",
      label: "Fiscal year",
      required: true,
      placeholder: "2082/83",
    },
    { key: "regime", label: "Regime", kind: "select", options: REGIMES },
    {
      key: "sequence",
      label: "Order",
      kind: "number",
      required: true,
      help: "Slabs are applied in this order, lowest band first.",
    },
    { key: "lower_bound", label: "From (NPR)", kind: "number", required: true },
    {
      key: "upper_bound",
      label: "To (NPR)",
      kind: "number",
      help: "Leave blank for the top band.",
    },
    { key: "rate_percent", label: "Rate (%)", kind: "number", required: true },
    { key: "label", label: "Label" },
    {
      key: "waived_for_ssf_contributors",
      label: "Waived for SSF contributors",
      kind: "checkbox",
    },
  ],
};

const SCHEMES: MasterSpec = {
  title: "Contribution schemes",
  description:
    "Social security, provident fund and the like: what the employee pays, " +
    "what the employer pays on top, and whether it reduces taxable income.",
  noun: "scheme",
  endpoint: "/payroll/schemes/",
  writePermission: "payroll.process",
  writeScope: "facility",
  sortBy: "code",
  columns: [
    { key: "code", label: "Code" },
    { key: "name", label: "Scheme" },
    { key: "fiscal_year", label: "Year" },
    { key: "employee_percent", label: "Employee", align: "right" },
    { key: "employer_percent", label: "Employer", align: "right" },
  ],
  fields: [
    { key: "code", label: "Code", required: true, fixedAfterCreate: true },
    { key: "name", label: "Name", required: true },
    {
      key: "fiscal_year",
      label: "Fiscal year",
      required: true,
      placeholder: "2082/83",
    },
    {
      key: "employee_percent",
      label: "Employee pays (%)",
      kind: "number",
      group: "Rates",
    },
    {
      key: "employer_percent",
      label: "Employer pays (%)",
      kind: "number",
      group: "Rates",
    },
    {
      key: "annual_deduction_ceiling",
      label: "Annual ceiling (NPR)",
      kind: "number",
      group: "Rates",
    },
    { key: "on_basic", label: "Calculated on basic only", kind: "checkbox" },
    {
      key: "is_tax_deductible",
      label: "Reduces taxable income",
      kind: "checkbox",
    },
    {
      key: "replaces_social_security_tax",
      label: "Replaces the social security tax",
      kind: "checkbox",
    },
    { key: "is_active", label: "Active", kind: "checkbox" },
  ],
};

const SECTIONS = [
  { id: "components", label: "Components", icon: Layers, spec: COMPONENTS },
  { id: "structures", label: "Structures", icon: Coins, spec: STRUCTURES },
  { id: "slabs", label: "Tax slabs", icon: Calculator, spec: TAX_SLABS },
  { id: "schemes", label: "Contributions", icon: Landmark, spec: SCHEMES },
];

export default function PayrollSetup() {
  const [section, setSection] = useState(SECTIONS[0].id);
  const active = SECTIONS.find((entry) => entry.id === section) ?? SECTIONS[0];

  return (
    <div className="space-y-4">
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
