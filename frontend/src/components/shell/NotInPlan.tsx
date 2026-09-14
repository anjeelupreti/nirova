/**
 * The screen for a module the organization has not bought.
 *
 * Not a 403, and not a blank page. Somebody arrives here by a bookmark, a
 * link from a colleague, or a screen they used at their last job — and the
 * useful answer is what the module does, that it is not included, and who can
 * add it. A permission refusal says "you may not"; this says "we don't have
 * it", which is a different conversation and a sales signal rather than a
 * support ticket.
 */

import { Link } from "react-router-dom";
import { Lock } from "lucide-react";

import { Button, Card, CardContent } from "@/components/ui/primitives";
import { Page, PageHeader } from "@/components/ui/layout";

/** What each module is, said the way somebody deciding would say it. */
const MODULES: Record<string, { name: string; blurb: string }> = {
  clinic: { name: "Outpatients", blurb: "Appointments, the waiting queue and consultations." },
  hospital: { name: "Inpatients", blurb: "Wards and beds, emergency, theatre and intensive care." },
  pharmacy: { name: "Pharmacy", blurb: "Dispensing, the retail counter, batches and expiry." },
  laboratory: { name: "Laboratory", blurb: "Orders, samples, results and released reports." },
  radiology: { name: "Imaging", blurb: "Imaging orders, reporting and release." },
  blood_bank: { name: "Blood bank", blurb: "Donors, units, cross-matching and issue." },
  procurement: { name: "Procurement", blurb: "Suppliers, purchase orders and goods received." },
  insurance: { name: "Claims", blurb: "Payers, pre-authorisation, claims and settlement." },
  finance: { name: "Finance", blurb: "The ledger, trial balance, VAT return and bank." },
  hrms: { name: "People", blurb: "Staff records, attendance, rosters and leave." },
  payroll: { name: "Payroll", blurb: "Salaries, SSF and PF, payslips and tax." },
  patient_portal: { name: "Patient app", blurb: "Results, appointments and bills on the patient's phone." },
  api_access: { name: "Data and API", blurb: "Bulk import, export and programmatic access." },
};

export default function NotInPlan({ module }: { module: string }) {
  const known = MODULES[module];
  return (
    <Page>
      <PageHeader
        title={known ? known.name : "Not included"}
        description="This part of Nirova is not in your organization's plan."
      />
      <Card>
        <CardContent className="max-w-xl space-y-4 py-8">
          <Lock className="h-8 w-8 text-muted-foreground" />
          <p className="text-sm text-muted-foreground">
            {known ? known.blurb : "This module is not part of what your organization has."}
          </p>
          <p className="text-sm">
            Your administrator can add it from{" "}
            <Link to="/capacity" className="font-medium text-primary hover:underline">
              Plan &amp; usage
            </Link>
            . Nothing here is hidden from you personally — the organization has
            not bought this part.
          </p>
          <div className="flex gap-2 pt-2">
            <Button asChild>
              <Link to="/capacity">See the plan</Link>
            </Button>
            <Button variant="outline" asChild>
              <Link to="/">Back to work</Link>
            </Button>
          </div>
        </CardContent>
      </Card>
    </Page>
  );
}
