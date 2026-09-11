/**
 * Register your hospital.
 *
 * **What signing up means here, said on the page.** Not an instant account:
 * a hospital system is not bought from a form, and provisioning a database
 * for whoever fills one in would let anyone on the internet create databases
 * on our servers. Signing up tells the platform team who you are and what you
 * run; they call, and your own workspace follows. The right-hand panel says
 * exactly that, step by step, so nobody submits expecting a login and gets
 * silence.
 *
 * Three short steps rather than one long form, each a question a hospital
 * director can answer without looking anything up — what you run, what you
 * need, who we should talk to. The kind of organization is chosen from cards,
 * not a dropdown, because it is the answer that shapes everything after and
 * it deserves to be seen whole.
 */

import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import {
  ArrowLeft,
  ArrowRight,
  Building2,
  Check,
  CheckCircle2,
  FlaskConical,
  Hospital,
  Network,
  Pill,
  ScanLine,
  Stethoscope,
  Warehouse,
} from "lucide-react";

import api, { ApiError } from "@/lib/api";
import { cn } from "@/lib/utils";
import { Alert, AlertDescription, Button, Input, Label, Select, Textarea } from "@/components/ui/primitives";
import { Spinner } from "@/components/ui/loader";
import { AuthShell } from "@/pages/auth/AuthShell";

const TYPES = [
  { id: "hospital", label: "Hospital", detail: "Inpatient beds, emergency, theatre", icon: Hospital },
  { id: "clinic", label: "Clinic", detail: "Outpatient consultations", icon: Stethoscope },
  { id: "polyclinic", label: "Polyclinic", detail: "Several specialties, one site", icon: Building2 },
  { id: "pharmacy", label: "Pharmacy", detail: "Counter sales and dispensing", icon: Pill },
  { id: "laboratory", label: "Laboratory", detail: "Samples, results, reports", icon: FlaskConical },
  { id: "diagnostic", label: "Diagnostic centre", detail: "Imaging and tests", icon: ScanLine },
  { id: "group", label: "Group or chain", detail: "More than one organization", icon: Network },
  { id: "distributor", label: "Distributor", detail: "Pharmaceutical wholesale", icon: Warehouse },
] as const;

const MODULES: { group: string; items: { id: string; label: string }[] }[] = [
  {
    group: "Patient care",
    items: [
      { id: "clinic", label: "Outpatients & appointments" },
      { id: "hospital", label: "Wards, emergency, theatre" },
      { id: "laboratory", label: "Laboratory" },
      { id: "radiology", label: "Imaging" },
      { id: "blood_bank", label: "Blood bank" },
    ],
  },
  {
    group: "Pharmacy & supply",
    items: [
      { id: "pharmacy", label: "Pharmacy & counter" },
      { id: "inventory", label: "Inventory" },
      { id: "procurement", label: "Purchasing" },
    ],
  },
  {
    group: "Running the organization",
    items: [
      { id: "finance", label: "Billing & accounts" },
      { id: "insurance", label: "Insurance claims" },
      { id: "hrms", label: "Staff & attendance" },
      { id: "payroll", label: "Payroll (SSF, PF, TDS)" },
      { id: "analytics", label: "Reports & analytics" },
    ],
  },
  {
    group: "Patients at home",
    items: [
      { id: "patient_portal", label: "Patient portal" },
      { id: "telemedicine", label: "Telemedicine" },
    ],
  },
];

/** What each kind of organization usually starts with — a starting point, not a rule. */
const SUGGESTED: Record<string, string[]> = {
  hospital: ["clinic", "hospital", "laboratory", "pharmacy", "finance"],
  clinic: ["clinic", "finance"],
  polyclinic: ["clinic", "laboratory", "pharmacy", "finance"],
  pharmacy: ["pharmacy", "inventory"],
  laboratory: ["laboratory", "finance"],
  diagnostic: ["laboratory", "radiology", "finance"],
  group: ["clinic", "hospital", "pharmacy", "finance", "analytics"],
  distributor: ["inventory", "procurement", "finance"],
};

const PROVINCES = ["Koshi", "Madhesh", "Bagmati", "Gandaki", "Lumbini", "Karnali", "Sudurpashchim"];

const STEPS = ["Your organization", "What you need", "Who to talk to"] as const;

export default function SignupPage() {
  const [step, setStep] = useState(0);
  const [form, setForm] = useState({
    organization_name: "",
    business_type: "",
    province: "Bagmati",
    district: "",
    facility_count: "1",
    bed_count: "",
    modules: [] as string[],
    current_system: "",
    contact_name: "",
    contact_role: "",
    contact_email: "",
    contact_phone: "",
    pan_number: "",
    message: "",
    website: "", // the honeypot; invisible to people
  });
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);
  const [done, setDone] = useState<string | null>(null);

  const set = <K extends keyof typeof form>(key: K, value: (typeof form)[K]) =>
    setForm((current) => ({ ...current, [key]: value }));

  const valid = useMemo(
    () => [
      form.organization_name.trim().length > 1 && Boolean(form.business_type),
      form.modules.length > 0,
      form.contact_name.trim().length > 1 && /\S+@\S+\.\S+/.test(form.contact_email),
    ],
    [form],
  );

  function chooseType(id: string) {
    setForm((current) => ({
      ...current,
      business_type: id,
      // Suggest a starting set the first time, and never overwrite a choice
      // somebody has already made.
      modules: current.modules.length ? current.modules : SUGGESTED[id] ?? [],
    }));
  }

  async function submit() {
    setBusy(true);
    setProblem(null);
    try {
      const result = await api.post<{ reference: string }>("/auth/register/", {
        ...form,
        facility_count: Number(form.facility_count) || 1,
        bed_count: Number(form.bed_count) || 0,
      });
      setDone(result.reference);
    } catch (err) {
      setProblem(err instanceof ApiError ? err.message : "Your request did not reach us. Try again.");
    } finally {
      setBusy(false);
    }
  }

  const corner = (
    <span className="text-muted-foreground">
      Already on Nirova?{" "}
      <Link to="/" className="font-medium text-primary hover:underline">
        Sign in
      </Link>
    </span>
  );

  if (done) {
    return (
      <AuthShell corner={corner} aside={<NextSteps highlight={1} />}>
        <div className="w-full max-w-md text-center">
          <CheckCircle2 className="mx-auto h-12 w-12 text-good" />
          <h1 className="mt-4 font-display text-[1.75rem] font-semibold tracking-tight">
            Thank you — we have it
          </h1>
          <p className="mt-2 text-muted-foreground">
            Your reference is <span className="font-semibold text-foreground">{done}</span>. Someone
            from our team will call {form.contact_name.split(" ")[0] || "you"} within one working
            day to arrange a walkthrough on {form.organization_name || "your organization"}'s own
            workflow.
          </p>
          <Button asChild variant="outline" className="mt-8">
            <Link to="/">Back to sign in</Link>
          </Button>
        </div>
      </AuthShell>
    );
  }

  return (
    <AuthShell corner={corner} aside={<NextSteps highlight={0} />}>
      <div className="w-full max-w-xl">
        <h1 className="font-display text-[2rem] font-semibold leading-tight tracking-tight">
          Register your organization
        </h1>
        <p className="mt-1.5 text-muted-foreground">
          Three short steps. We'll call you to set up your own workspace.
        </p>

        {/* -- the stepper ---------------------------------------------- */}
        <ol className="mt-6 flex items-center gap-2" aria-label="Progress">
          {STEPS.map((label, index) => (
            <li key={label} className="flex flex-1 items-center gap-2">
              <span
                className={cn(
                  "grid h-7 w-7 shrink-0 place-items-center rounded-full border text-xs font-semibold",
                  index < step && "border-primary bg-primary text-primary-foreground",
                  index === step && "border-primary text-primary",
                  index > step && "text-muted-foreground",
                )}
                aria-current={index === step ? "step" : undefined}
              >
                {index < step ? <Check className="h-3.5 w-3.5" /> : index + 1}
              </span>
              <span className={cn("hidden text-sm sm:inline", index === step ? "font-medium" : "text-muted-foreground")}>
                {label}
              </span>
              {index < STEPS.length - 1 && <span className="h-px flex-1 bg-border" />}
            </li>
          ))}
        </ol>

        <form
          className="mt-6 space-y-5"
          onSubmit={(event) => {
            event.preventDefault();
            if (!valid[step]) return;
            if (step < STEPS.length - 1) setStep(step + 1);
            else void submit();
          }}
        >
          {step === 0 && (
            <>
              <div className="space-y-1.5">
                <Label htmlFor="org">Organization name</Label>
                <Input id="org" className="h-11" value={form.organization_name} autoFocus
                  placeholder="e.g. Himalaya Community Hospital"
                  onChange={(event) => set("organization_name", event.target.value)} />
              </div>
              <fieldset>
                <legend className="mb-2 text-sm font-medium">What do you run?</legend>
                <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
                  {TYPES.map(({ id, label, detail, icon: Icon }) => (
                    <button
                      key={id}
                      type="button"
                      onClick={() => chooseType(id)}
                      aria-pressed={form.business_type === id}
                      className={cn(
                        "flex flex-col items-start gap-1 rounded-lg border p-3 text-left transition-colors",
                        form.business_type === id
                          ? "border-primary bg-primary/5 ring-1 ring-primary"
                          : "hover:border-primary/40 hover:bg-accent/40",
                      )}
                    >
                      <Icon className={cn("h-5 w-5", form.business_type === id ? "text-primary" : "text-muted-foreground")} />
                      <span className="text-sm font-medium">{label}</span>
                      <span className="text-xs leading-snug text-muted-foreground">{detail}</span>
                    </button>
                  ))}
                </div>
              </fieldset>
              <div className="grid gap-4 sm:grid-cols-2">
                <div className="space-y-1.5">
                  <Label htmlFor="province">Province</Label>
                  <Select id="province" value={form.province} onChange={(event) => set("province", event.target.value)}>
                    {PROVINCES.map((province) => (
                      <option key={province}>{province}</option>
                    ))}
                  </Select>
                </div>
                <div className="space-y-1.5">
                  <Label htmlFor="district">District</Label>
                  <Input id="district" value={form.district} placeholder="e.g. Lalitpur"
                    onChange={(event) => set("district", event.target.value)} />
                </div>
                <div className="space-y-1.5">
                  <Label htmlFor="sites">Sites</Label>
                  <Input id="sites" inputMode="numeric" value={form.facility_count}
                    onChange={(event) => set("facility_count", event.target.value.replace(/\D/g, ""))} />
                </div>
                {["hospital", "group", "polyclinic"].includes(form.business_type) && (
                  <div className="space-y-1.5">
                    <Label htmlFor="beds">Beds, roughly</Label>
                    <Input id="beds" inputMode="numeric" value={form.bed_count} placeholder="e.g. 50"
                      onChange={(event) => set("bed_count", event.target.value.replace(/\D/g, ""))} />
                  </div>
                )}
              </div>
            </>
          )}

          {step === 1 && (
            <>
              <p className="text-sm text-muted-foreground">
                We've ticked what a {TYPES.find((row) => row.id === form.business_type)?.label.toLowerCase() ?? "organization"} usually
                starts with. Change anything — you can add more later.
              </p>
              {MODULES.map((group) => (
                <fieldset key={group.group}>
                  <legend className="mb-2 text-sm font-medium">{group.group}</legend>
                  <div className="flex flex-wrap gap-2">
                    {group.items.map((item) => {
                      const on = form.modules.includes(item.id);
                      return (
                        <button
                          key={item.id}
                          type="button"
                          aria-pressed={on}
                          onClick={() =>
                            set("modules", on ? form.modules.filter((code) => code !== item.id) : [...form.modules, item.id])
                          }
                          className={cn(
                            "flex items-center gap-1.5 rounded-full border px-3 py-1.5 text-sm transition-colors",
                            on ? "border-primary bg-primary/10 text-primary" : "text-muted-foreground hover:border-primary/40 hover:text-foreground",
                          )}
                        >
                          {on && <Check className="h-3.5 w-3.5" />}
                          {item.label}
                        </button>
                      );
                    })}
                  </div>
                </fieldset>
              ))}
              <div className="space-y-1.5">
                <Label htmlFor="current-system">What do you use today?</Label>
                <Input id="current-system" value={form.current_system}
                  placeholder="Paper registers, Excel, another system…"
                  onChange={(event) => set("current_system", event.target.value)} />
              </div>
            </>
          )}

          {step === 2 && (
            <>
              <div className="grid gap-4 sm:grid-cols-2">
                <div className="space-y-1.5">
                  <Label htmlFor="name">Your name</Label>
                  <Input id="name" className="h-11" value={form.contact_name} autoFocus
                    onChange={(event) => set("contact_name", event.target.value)} />
                </div>
                <div className="space-y-1.5">
                  <Label htmlFor="role">Your role</Label>
                  <Input id="role" className="h-11" value={form.contact_role} placeholder="Medical director, owner…"
                    onChange={(event) => set("contact_role", event.target.value)} />
                </div>
                <div className="space-y-1.5">
                  <Label htmlFor="work-email">Work email</Label>
                  <Input id="work-email" type="email" className="h-11" value={form.contact_email}
                    onChange={(event) => set("contact_email", event.target.value)} />
                </div>
                <div className="space-y-1.5">
                  <Label htmlFor="phone">Phone</Label>
                  <Input id="phone" type="tel" className="h-11" value={form.contact_phone} placeholder="+977 98…"
                    onChange={(event) => set("contact_phone", event.target.value)} />
                </div>
              </div>
              <div className="space-y-1.5">
                <Label htmlFor="pan">PAN <span className="font-normal text-muted-foreground">(optional)</span></Label>
                <Input id="pan" inputMode="numeric" value={form.pan_number} placeholder="Nine digits"
                  onChange={(event) => set("pan_number", event.target.value.replace(/\D/g, "").slice(0, 9))} />
              </div>
              <div className="space-y-1.5">
                <Label htmlFor="message">Anything we should know? <span className="font-normal text-muted-foreground">(optional)</span></Label>
                <Textarea id="message" rows={3} value={form.message}
                  placeholder="Go-live date, number of users, what is hurting most…"
                  onChange={(event) => set("message", event.target.value)} />
              </div>
              {/* Honeypot: off-screen, out of the tab order, labelled for bots. */}
              <div aria-hidden className="absolute -left-[9999px] h-0 w-0 overflow-hidden">
                <label htmlFor="website">Website</label>
                <input id="website" tabIndex={-1} autoComplete="off" value={form.website}
                  onChange={(event) => set("website", event.target.value)} />
              </div>
            </>
          )}

          {problem && (
            <Alert variant="destructive">
              <AlertDescription>{problem}</AlertDescription>
            </Alert>
          )}

          <div className="flex items-center justify-between gap-3 pt-2">
            {step > 0 ? (
              <Button type="button" variant="ghost" onClick={() => setStep(step - 1)}>
                <ArrowLeft className="h-4 w-4" />
                Back
              </Button>
            ) : (
              <span />
            )}
            <Button type="submit" className="h-11 min-w-40" disabled={!valid[step] || busy}>
              {busy && <Spinner size="sm" className="mr-2" />}
              {step < STEPS.length - 1 ? (
                <>
                  Continue
                  <ArrowRight className="h-4 w-4" />
                </>
              ) : (
                "Send request"
              )}
            </Button>
          </div>
        </form>
      </div>
    </AuthShell>
  );
}

function NextSteps({ highlight }: { highlight: number }) {
  const steps = [
    ["You tell us what you run", "Three minutes, on this page."],
    ["We call within one working day", "A walkthrough on your own departments and workflow — not a slideshow."],
    ["Your own workspace", "A private database provisioned for your organization, with your branding."],
    ["Go live with your team", "Your data moved in from registers or spreadsheets, and training on site."],
  ];
  return (
    <div className="flex h-full flex-col justify-center">
      <p className="text-sm font-medium text-hero-foreground/80">What happens next</p>
      <h2 className="mt-3 max-w-md font-display text-4xl font-semibold leading-tight tracking-tight">
        From first call to first patient.
      </h2>
      <ol className="mt-10 max-w-md space-y-0">
        {steps.map(([title, detail], index) => (
          <li key={title} className="relative flex gap-4 pb-8 last:pb-0">
            {index < steps.length - 1 && (
              <span className="absolute left-4 top-9 h-[calc(100%-2.25rem)] w-px bg-hero-foreground/25" aria-hidden />
            )}
            <span
              className={cn(
                "grid h-8 w-8 shrink-0 place-items-center rounded-full text-sm font-semibold",
                index <= highlight ? "bg-hero-foreground text-hero" : "border border-hero-foreground/40 text-hero-foreground/80",
              )}
            >
              {index < highlight ? <Check className="h-4 w-4" /> : index + 1}
            </span>
            <div>
              <p className="font-semibold">{title}</p>
              <p className="mt-0.5 text-sm text-hero-foreground/80">{detail}</p>
            </div>
          </li>
        ))}
      </ol>
    </div>
  );
}
