/**
 * Settings: one page, with its sections down the side.
 *
 * **Settings used to be in three places.** Preferences were a tab of the
 * profile, the account menu carried five administrative links and the colour
 * switches, and Facilities, Privacy and the price list sat in the sidebar
 * beside the queue. Somebody looking for "where do I change this" had three
 * places to try and no way to know which was right.
 *
 * Now the sidebar is the work, the avatar is you (profile, settings, sign
 * out), and everything that configures -- your own preferences and sign-in
 * first, then how the organization is set up -- is here, one section at a
 * time. The section is in the address, so "Settings, Roles" is a link.
 *
 * Organization sections appear only to somebody who may open at least one
 * thing in them; a section of refusals is worse than no section.
 */

import { useCallback, useEffect, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";

import api, { ApiError } from "@/lib/api";
import { cn } from "@/lib/utils";
import { TwoStepSignIn } from "@/components/account/TwoStepSignIn";
import { Password, PreferencePanel, type Me } from "@/components/me/AccountForms";
import { APPEARANCE_KEYS, AppearanceCard } from "@/components/me/Appearance";
import { visibleSettingsGroups } from "@/components/shell/settingsMap";
import { useCan } from "@/components/ui/can";
import { CardSkeleton } from "@/components/ui/feedback";
import { Icon, type IconName } from "@/components/ui/icon";
import { Page, PageHeader, Section } from "@/components/ui/layout";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/primitives";

interface SectionSpec {
  id: string;
  label: string;
  icon: IconName;
  group: "you" | "organization";
}

const PERSONAL: SectionSpec[] = [
  { id: "preferences", label: "Preferences", icon: "settings", group: "you" },
  { id: "security", label: "Password & sign-in", icon: "access", group: "you" },
  { id: "notifications", label: "Notifications", icon: "notification", group: "you" },
];

export default function SettingsPage() {
  const can = useCan();
  const [params, setParams] = useSearchParams();
  const groups = visibleSettingsGroups(can);

  const sections: SectionSpec[] = [
    ...PERSONAL,
    ...groups.map((group) => ({
      id: group.id,
      label: group.label,
      icon: group.icon,
      group: "organization" as const,
    })),
  ];
  const current = sections.find((entry) => entry.id === params.get("section")) ?? sections[0];

  const choose = (id: string) =>
    setParams(
      (existing) => {
        const next = new URLSearchParams(existing);
        if (id === sections[0].id) next.delete("section");
        else next.set("section", id);
        return next;
      },
      { replace: true },
    );

  const [me, setMe] = useState<Me | null>(null);
  const [error, setError] = useState<string | null>(null);
  const load = useCallback(async () => {
    setError(null);
    try {
      setMe(await api.get<Me>("/auth/me/"));
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Your settings could not be loaded.");
    }
  }, []);
  useEffect(() => {
    void load();
  }, [load]);

  const group = groups.find((entry) => entry.id === current.id);

  return (
    <Page>
      <PageHeader
        title="Settings"
        description="Your preferences and sign-in, and how the organization is set up."
      />

      <div className="grid gap-6 lg:grid-cols-[13.5rem_minmax(0,1fr)]">
        <nav aria-label="Settings sections" className="min-w-0 lg:sticky lg:top-20 lg:self-start">
          {(["you", "organization"] as const).map((kind) => {
            const items = sections.filter((entry) => entry.group === kind);
            if (items.length === 0) return null;
            return (
              <div key={kind} className="mb-4">
                <p className="px-2 pb-1.5 type-eyebrow text-muted-foreground">
                  {kind === "you" ? "You" : "Organization"}
                </p>
                <ul className="flex gap-1 overflow-x-auto [scrollbar-width:none] lg:flex-col">
                  {items.map((entry) => {
                    const active = entry.id === current.id;
                    return (
                      <li key={entry.id} className="shrink-0">
                        <button
                          type="button"
                          onClick={() => choose(entry.id)}
                          aria-current={active ? "page" : undefined}
                          className={cn(
                            "flex w-full items-center gap-2.5 whitespace-nowrap rounded-md px-2.5 py-2 text-left text-sm transition-colors duration-quick",
                            active
                              ? "bg-primary-subtle font-medium text-primary-subtle-foreground"
                              : "text-muted-foreground hover:bg-accent hover:text-foreground",
                          )}
                        >
                          <Icon name={entry.icon} size="md" />
                          {entry.label}
                        </button>
                      </li>
                    );
                  })}
                </ul>
              </div>
            );
          })}
        </nav>

        <div className="min-w-0">
          {current.group === "you" && error ? (
            <Alert variant="warning">
              <AlertTitle>Not shown</AlertTitle>
              <AlertDescription>{error}</AlertDescription>
            </Alert>
          ) : null}

          {current.id === "preferences" ? (
            me ? (
              <div className="space-y-6">
                <AppearanceCard />
                <div className="max-w-2xl">
                  <PreferencePanel catalogue={me.preference_catalogue} exclude={APPEARANCE_KEYS} />
                </div>
              </div>
            ) : error ? null : (
              <CardSkeleton count={2} />
            )
          ) : null}

          {current.id === "security" ? (
            me ? (
              <div className="max-w-3xl space-y-6">
                <Password me={me} onChanged={() => void load()} />
                <TwoStepSignIn />
              </div>
            ) : error ? null : (
              <CardSkeleton count={2} />
            )
          ) : null}

          {current.id === "notifications" ? (
            <Section
              title="Notifications"
              description="Alerts and approvals arrive on the bell. Critical results reach you whatever you choose here."
            >
              <div className="grid gap-3 sm:grid-cols-2">
                <SettingsLink
                  to="/notifications?tab=preferences"
                  icon="settings"
                  label="What I am told about"
                  description="Turn categories on or off for the bell, email and SMS."
                />
                <SettingsLink
                  to="/notifications"
                  icon="notification"
                  label="All notifications"
                  description="Everything sent to you, and what is waiting on your decision."
                />
              </div>
            </Section>
          ) : null}

          {group ? (
            <Section title={group.label} description={group.description}>
              <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
                {group.items.map((item) => (
                  <SettingsLink
                    key={item.to}
                    to={item.to}
                    icon={item.icon}
                    label={item.label}
                    description={item.description}
                  />
                ))}
              </div>
            </Section>
          ) : null}
        </div>
      </div>
    </Page>
  );
}

function SettingsLink({
  to,
  icon,
  label,
  description,
}: {
  to: string;
  icon: IconName;
  label: string;
  description: string;
}) {
  return (
    <Link
      to={to}
      className={cn(
        "group flex gap-3 rounded-lg border bg-card p-4 shadow-raised",
        "transition-colors duration-quick ease-smooth",
        "hover:border-border-strong hover:bg-accent/40",
      )}
    >
      <span className="mt-0.5 flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-primary-subtle text-primary-subtle-foreground">
        <Icon name={icon} size="md" />
      </span>
      <span className="min-w-0">
        <span className="flex items-center gap-1 text-sm font-medium">
          {label}
          <Icon
            name="chevronRight"
            size="xs"
            className="text-muted-foreground opacity-0 transition-opacity duration-quick group-hover:opacity-100"
          />
        </span>
        <span className="mt-0.5 block type-caption">{description}</span>
      </span>
    </Link>
  );
}
