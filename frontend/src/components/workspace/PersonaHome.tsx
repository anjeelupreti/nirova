/**
 * The right board for the person looking, in one place.
 *
 * Extracted from `Dashboard.tsx` when the workspace and the dashboard were
 * separated (§143). Two screens were both trying to be "your day": the
 * dashboard picked a board by role and the workspace listed approvals, so a
 * doctor's own workspace was an empty approvals inbox while the board they
 * needed sat on a different screen. They now mean different things —
 * *my day* and *the organization's day* — and this is the part they share.
 */

import {
  DoctorHome,
  FrontDeskHome,
  NurseHome,
  PeopleHome,
  PharmacyHome,
} from "@/components/workspace/homes";
import type { useResource } from "@/components/workspace/useResource";
import type { Persona } from "@/components/shell/personas";
import type { MyWorkspace } from "@/types";

export function PersonaHome({
  persona,
  workspace,
  oneFacility,
}: {
  persona: Persona;
  workspace: ReturnType<typeof useResource<MyWorkspace>>;
  /** One building: every personal board is about the place you are standing. */
  oneFacility: string | null;
}) {
  switch (persona.id) {
    case "nurse":
      return <NurseHome workspace={workspace} />;
    case "frontdesk":
      return <FrontDeskHome workspace={workspace} facility={oneFacility} />;
    case "doctor":
      return <DoctorHome workspace={workspace} facility={oneFacility} />;
    case "pharmacy":
      return <PharmacyHome workspace={workspace} facility={oneFacility} />;
    case "people":
      return <PeopleHome workspace={workspace} />;
    default:
      // Leadership, finance and the general case have no *personal* board:
      // their day is the organization's day, which is the dashboard. The
      // approvals below are what is theirs.
      return null;
  }
}
