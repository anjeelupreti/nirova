/**
 * Settings: the organization, reached from the avatar rather than the rail.
 *
 * The rail is **the work**; the avatar is **the system**. A hub, not a screen:
 * sections are gated on the permission that governs each destination, and a
 * section nobody in the room can open is not rendered -- rather than rendered
 * and refused.
 *
 * **Only the organization.** Your own profile, password, appearance, leave
 * and payslips are one place, `/me`, linked once at the top for anybody who
 * came here looking for them.
 */

import { Link } from "react-router-dom";

import { cn } from "@/lib/utils";
import { useCan } from "@/components/ui/can";
import { EmptyState } from "@/components/ui/feedback";
import { Icon } from "@/components/ui/icon";
import { Page, PageHeader, Section } from "@/components/ui/layout";
import { Button } from "@/components/ui/primitives";
import { visibleSettingsGroups } from "@/components/shell/settingsMap";
import { useSession } from "@/hooks/useSession";

export default function SettingsPage() {
  const can = useCan();
  const { session } = useSession();
  const visible = visibleSettingsGroups(can);

  return (
    <Page>
      <PageHeader
        title="Settings"
        description={
          session?.organization
            ? `${session.organization.display_name}: people, structure, prices and the plan.`
            : "People, structure, prices and the plan."
        }
        breadcrumbs={[{ label: "Settings" }]}
      />

      <Link
        to="/me"
        className={cn(
          "flex items-center justify-between gap-3 rounded-lg border border-dashed px-4 py-3",
          "text-sm transition-colors duration-quick hover:bg-accent/40",
        )}
      >
        <span className="flex items-center gap-2.5">
          <Icon name="patientSingle" size="md" className="text-muted-foreground" />
          <span>
            <span className="font-medium">Looking for your own settings?</span>{" "}
            <span className="text-muted-foreground">
              Profile, password, colours, leave and payslips are on your profile.
            </span>
          </span>
        </span>
        <Icon name="chevronRight" size="sm" className="text-muted-foreground" />
      </Link>

      {visible.length === 0 ? (
        <EmptyState
          title="Nothing to configure from your role"
          description="Organization settings are for administrators. Everything about you is on your profile."
          action={
            <Button asChild variant="outline">
              <Link to="/me">Open my profile</Link>
            </Button>
          }
        />
      ) : null}

      {visible.map((group) => (
        <Section key={group.label} title={group.label} description={group.description}>
          <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
            {group.items.map((item) => (
              <Link
                key={item.to}
                to={item.to}
                className={cn(
                  "group flex gap-3 rounded-lg border bg-card p-4 shadow-raised",
                  "transition-colors duration-quick ease-smooth",
                  "hover:border-border-strong hover:bg-accent/40",
                )}
              >
                <span className="mt-0.5 flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-primary-subtle text-primary-subtle-foreground">
                  <Icon name={item.icon} size="md" />
                </span>
                <span className="min-w-0">
                  <span className="flex items-center gap-1 text-sm font-medium">
                    {item.label}
                    <Icon
                      name="chevronRight"
                      size="xs"
                      className="text-muted-foreground opacity-0 transition-opacity duration-quick group-hover:opacity-100"
                    />
                  </span>
                  <span className="mt-0.5 block type-caption">{item.description}</span>
                </span>
              </Link>
            ))}
          </div>
        </Section>
      ))}
    </Page>
  );
}
