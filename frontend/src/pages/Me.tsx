/**
 * My profile: everything about you, in one place.
 *
 * **It was four places.** "My account" held your name, password and
 * preferences; "Self service" held a second profile, check-in, leave, shift
 * swaps and payslips under a banner of its own; Settings repeated the colours;
 * and the account menu linked to all three. Somebody wanting their payslip had
 * to know which of two profiles it lived under.
 *
 * One header, one row of tabs, and the tab is in the address, so "my leave" is
 * a link somebody can be sent. The order follows how often each is opened:
 * the employment sections a person uses weekly come before the password they
 * change twice a year. Sections that do not apply -- no employee record, no
 * HR module in the plan, nobody reporting to you -- are not shown at all,
 * rather than shown empty.
 */

import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";

import api, { ApiError } from "@/lib/api";
import { useSession } from "@/hooks/useSession";
import { Details, type Me } from "@/components/me/AccountForms";
import { CheckInButton, useStaffSummary } from "@/components/me/staff";
import { Avatar } from "@/components/ui/data";
import { CardSkeleton } from "@/components/ui/feedback";
import { Page, PageHeader } from "@/components/ui/layout";
import {
  Alert,
  AlertDescription,
  AlertTitle,
  Badge,
} from "@/components/ui/primitives";
import { TabbedSection } from "@/components/ui/tabs";
import { SelfServiceSection } from "@/pages/SelfService";

export default function MePage() {
  const { hasModule } = useSession();
  const [me, setMe] = useState<Me | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setError(null);
    try {
      setMe(await api.get<Me>("/auth/me/"));
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Your profile could not be loaded.");
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const hr = hasModule("hrms");
  const staff = useStaffSummary(hr);
  const summary = staff.summary;
  const employee = summary?.employee;

  if (error) {
    return (
      <Page>
        <PageHeader title="My profile" />
        <Alert variant="warning">
          <AlertTitle>Not shown</AlertTitle>
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      </Page>
    );
  }

  if (!me) {
    return (
      <Page>
        <PageHeader title="My profile" />
        <CardSkeleton count={3} />
      </Page>
    );
  }

  const works = Boolean(employee);
  const reload = () => void staff.reload();

  return (
    <Page>
      <PageHeader
        title={
          <span className="flex items-center gap-3">
            <Avatar name={me.full_name || me.email} src={me.avatar_url} size="md" />
            {me.preferred_name || me.full_name || me.email}
          </span>
        }
        meta={
          me.is_platform_staff ? <Badge variant="secondary">Platform operator</Badge> : null
        }
        description={
          employee
            ? [employee.position, employee.department, employee.facility]
                .filter(Boolean)
                .join(" · ")
            : me.email
        }
        actions={summary ? <CheckInButton summary={summary} /> : null}
      />

      {me.must_change_password ? (
        <Alert variant="warning">
          <AlertTitle>Your password needs changing</AlertTitle>
          <AlertDescription>
            Somebody set this account up for you.{" "}
            <Link to="/settings?section=security" className="font-medium underline">
              Choose a password only you know
            </Link>{" "}
            before doing anything else.
          </AlertDescription>
        </Alert>
      ) : null}

      <TabbedSection
        tabs={[
          { id: "profile", label: "Profile", icon: "patientSingle" },
          { id: "time", label: "Attendance & shifts", icon: "attendance", hidden: !works },
          { id: "leave", label: "Leave", icon: "appointment", hidden: !works },
          { id: "pay", label: "Payslips", icon: "payroll", hidden: !works },
          {
            id: "swaps",
            label: "Shift swaps",
            icon: "transfer",
            hidden: !works,
            count: summary?.pending_incoming_swaps || null,
          },
          { id: "team", label: "Team requests", icon: "staff", hidden: !summary?.is_manager },
        ]}
      >
        {{
          profile: (
            <div className="space-y-6">
              <Details me={me} onSaved={setMe} />
              {summary ? (
                <SelfServiceSection section="profile" summary={summary} onSummaryChanged={reload} />
              ) : hr && !staff.loading ? (
                <p className="rounded-lg border border-dashed px-4 py-3 text-sm text-muted-foreground">
                  No employee record is linked to this sign-in, so attendance, leave and
                  payslips are not shown. HR can link one.
                </p>
              ) : null}
            </div>
          ),
          time: summary ? (
            <SelfServiceSection section="time" summary={summary} onSummaryChanged={reload} />
          ) : null,
          leave: summary ? (
            <SelfServiceSection section="leave" summary={summary} onSummaryChanged={reload} />
          ) : null,
          pay: summary ? (
            <SelfServiceSection section="pay" summary={summary} onSummaryChanged={reload} />
          ) : null,
          swaps: summary ? (
            <SelfServiceSection section="swaps" summary={summary} onSummaryChanged={reload} />
          ) : null,
          team: summary ? (
            <SelfServiceSection section="manager" summary={summary} onSummaryChanged={reload} />
          ) : null,
        }}
      </TabbedSection>
    </Page>
  );
}
