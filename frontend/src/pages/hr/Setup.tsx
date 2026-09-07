/**
 * The four lists an HR department configures, none of which the console could
 * touch.
 *
 * The holiday calendar decides which days are worked, which decides attendance,
 * which decides pay. Shift patterns decide when somebody is late. Leave types
 * carry entitlements and whether the leave is paid. Positions are the org
 * chart. Every one was loadable only with an HTTP client.
 *
 * **These are descriptions, not screens.** The shape lives in `MasterData`,
 * written after hand-building three of these and watching the fourth start to
 * drift. What is here is only what actually differs between a holiday and a
 * shift.
 *
 * **The permissions differ and are not guesses.** Holidays and leave types sit
 * behind `config.update`; shifts and positions behind `employee.manage`, which
 * is what an HR manager holds. Both were settled in log 215, after a first
 * attempt left only the organization administrator able to add a public
 * holiday.
 */

import { useState } from "react";
import { Briefcase, CalendarDays, Clock, Plane } from "lucide-react";

import MasterData, { type MasterSpec } from "@/components/MasterData";
import { cn } from "@/lib/utils";

const SHIFT_TYPES = ["morning", "evening", "night", "general", "split",
                     "on_call", "rotating"];

const HOLIDAYS: MasterSpec = {
  title: "Holiday calendar",
  description:
    "Which days are not worked. Attendance and payroll both read this, so a " +
    "missing festival is a day everybody is marked absent for.",
  noun: "holiday",
  endpoint: "/hr/holidays/",
  writePermission: "config.update",
  sortBy: "date",
  emptyHint: "Add the public holidays before the first payroll run.",
  columns: [
    { key: "date", label: "Date" },
    { key: "name", label: "Holiday" },
    { key: "applies_to", label: "Applies to" },
    { key: "is_optional", label: "Optional" },
  ],
  fields: [
    { key: "name", label: "Name", required: true },
    { key: "date", label: "Date", kind: "date", required: true },
    { key: "name_nepali", label: "Name in Nepali" },
    {
      key: "applies_to",
      label: "Applies to",
      help: "Leave blank for everybody.",
    },
    { key: "notes", label: "Notes", kind: "textarea" },
    {
      key: "is_optional",
      label: "Optional - staff may choose to work it",
      kind: "checkbox",
    },
  ],
};

const SHIFTS: MasterSpec = {
  title: "Shift patterns",
  description:
    "When a shift starts and ends, and how much lateness is tolerated before " +
    "it counts as late.",
  noun: "shift pattern",
  endpoint: "/hr/shifts/",
  writePermission: "employee.manage",
  sortBy: "code",
  columns: [
    { key: "code", label: "Code" },
    { key: "name", label: "Shift" },
    {
      key: "starts_at",
      label: "Hours",
      render: (row) =>
        `${row.starts_at ?? "-"} - ${row.ends_at ?? "-"}${
          row.crosses_midnight ? " (overnight)" : ""
        }`,
    },
    { key: "grace_minutes", label: "Grace", align: "right" },
    { key: "is_active", label: "Active" },
  ],
  fields: [
    { key: "code", label: "Code", required: true, fixedAfterCreate: true },
    { key: "name", label: "Name", required: true },
    { key: "shift_type", label: "Type", kind: "select", options: SHIFT_TYPES },
    { key: "starts_at", label: "Starts", kind: "time", required: true },
    { key: "ends_at", label: "Ends", kind: "time", required: true },
    { key: "break_minutes", label: "Break (minutes)", kind: "number" },
    {
      key: "grace_minutes",
      label: "Grace (minutes)",
      kind: "number",
      help: "Lateness tolerated before a mark counts as late.",
    },
    { key: "minimum_rest_hours", label: "Minimum rest (hours)", kind: "number" },
    { key: "crosses_midnight", label: "Runs past midnight", kind: "checkbox" },
    { key: "is_active", label: "Active", kind: "checkbox" },
  ],
};

const LEAVE_TYPES: MasterSpec = {
  title: "Leave types",
  description:
    "What somebody may take, how much of it, and whether it is paid.",
  noun: "leave type",
  endpoint: "/hr/leave-types/",
  // Addressed by `code`, not by uuid. Measured: PATCHing by uuid returns 404.
  lookupField: "code",
  writePermission: "config.update",
  sortBy: "code",
  columns: [
    { key: "code", label: "Code" },
    { key: "name", label: "Leave" },
    { key: "annual_entitlement", label: "Days a year", align: "right" },
    { key: "is_paid", label: "Paid" },
    { key: "is_active", label: "Active" },
  ],
  fields: [
    { key: "code", label: "Code", required: true, fixedAfterCreate: true },
    { key: "name", label: "Name", required: true },
    {
      key: "annual_entitlement",
      label: "Days a year",
      kind: "number",
      group: "Entitlement",
    },
    {
      key: "minimum_notice_days",
      label: "Notice required (days)",
      kind: "number",
      group: "Entitlement",
    },
    {
      key: "maximum_consecutive_days",
      label: "Longest run (days)",
      kind: "number",
      group: "Entitlement",
    },
    {
      key: "document_required_after_days",
      label: "Document needed after (days)",
      kind: "number",
      group: "Entitlement",
    },
    { key: "is_paid", label: "Paid leave", kind: "checkbox" },
    { key: "accrues_monthly", label: "Accrues monthly", kind: "checkbox" },
    { key: "carry_forward", label: "May be carried forward", kind: "checkbox" },
    { key: "encashable", label: "May be encashed", kind: "checkbox" },
    { key: "requires_document", label: "Needs a document", kind: "checkbox" },
    { key: "is_active", label: "Active", kind: "checkbox" },
  ],
};

const POSITIONS: MasterSpec = {
  title: "Positions",
  description:
    "The org chart: what somebody is employed as, and whether the post needs " +
    "a licence to hold.",
  noun: "position",
  endpoint: "/hr/positions/",
  writePermission: "employee.manage",
  searchable: true,
  sortBy: "title",
  columns: [
    { key: "code", label: "Code" },
    { key: "title", label: "Position" },
    { key: "grade", label: "Grade" },
    { key: "budgeted_headcount", label: "Budgeted", align: "right" },
    { key: "is_clinical", label: "Clinical" },
  ],
  fields: [
    { key: "code", label: "Code", required: true, fixedAfterCreate: true },
    { key: "title", label: "Title", required: true },
    { key: "title_nepali", label: "Title in Nepali" },
    { key: "grade", label: "Grade" },
    { key: "budgeted_headcount", label: "Budgeted headcount", kind: "number" },
    { key: "job_description", label: "Job description", kind: "textarea" },
    { key: "is_clinical", label: "Clinical post", kind: "checkbox" },
    {
      key: "is_provider",
      label: "Sees patients in their own right",
      kind: "checkbox",
    },
    { key: "requires_licence", label: "Needs a current licence", kind: "checkbox" },
    { key: "is_active", label: "Active", kind: "checkbox" },
  ],
};

const SECTIONS = [
  { id: "holidays", label: "Holidays", icon: CalendarDays, spec: HOLIDAYS },
  { id: "shifts", label: "Shifts", icon: Clock, spec: SHIFTS },
  { id: "leave", label: "Leave types", icon: Plane, spec: LEAVE_TYPES },
  { id: "positions", label: "Positions", icon: Briefcase, spec: POSITIONS },
];

export default function HrSetup() {
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
      {/*
        Keyed on the section so switching lists resets the panel state. Without
        it, opening a holiday and then switching to shifts leaves the holiday's
        detail open over the wrong list.
      */}
      <MasterData key={active.id} spec={active.spec} />
    </div>
  );
}
