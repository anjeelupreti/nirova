/**
 * Session state: who is signed in, which organization they are in, what they
 * may do, and what their subscription allows.
 *
 * All four come from a single `GET /api/auth/session/` call. That is
 * deliberate on the backend side (see its docstring) and it matters here
 * too: if permissions and entitlements were separate requests, a screen
 * could render with one loaded and the other not, and would have to guard
 * against a state that has no real-world meaning.
 */

import { useCallback, useEffect, useState } from "react";

import api, { ApiError, organizationStore, tokenStore } from "@/lib/api";
import type { Session } from "@/types";

interface LoginResponse {
  access: string;
  refresh: string;
  default_organization: string | null;
}

/** The password was right and a second factor is on: finish with a code. */
interface SecondFactorRequired {
  mfa_required: true;
  challenge: string;
  expires_in: number;
}

export interface UseSession {
  session: Session | null;
  loading: boolean;
  error: string | null;
  isAuthenticated: boolean;
  /**
   * Resolves with a challenge when two-step sign-in is on — the password was
   * right and a code is still needed — and with nothing when signed in.
   */
  login: (email: string, password: string) => Promise<{ challenge: string } | void>;
  /** The second step: a code from the authenticator app, or a recovery code. */
  verifySecondFactor: (challenge: string, code: string) => Promise<{ recoveryCodesLeft?: number }>;
  logout: () => void;
  switchOrganization: (slug: string) => Promise<void>;
  /**
   * Does the signed-in user hold this permission, at least at this scope?
   *
   * The scope defaults to `own` — "do they hold it at all" — because that is
   * the right question for a screen whose endpoints ask for the narrowest
   * grant, and the wrong one everywhere else.
   */
  can: (permission: string, scope?: string) => boolean;
  /** Is this module included in the current subscription? */
  hasModule: (module: string) => boolean;
  refresh: () => Promise<void>;
}

/**
 * The scope ladder, narrowest first — the same order the backend uses.
 *
 * Duplicated here rather than fetched because it is a fixed vocabulary, not
 * data; if it ever stops matching `apps/rbac/permissions.py` the sidebar
 * quietly starts lying, so the two belong in one commit whenever it changes.
 */
const SCOPE_LADDER = [
  "own",
  "own_patients",
  "unit",
  "department",
  "facility",
  "multi_facility",
  "organization",
];

export function useSession(): UseSession {
  const [session, setSession] = useState<Session | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    if (!tokenStore.get()) {
      setSession(null);
      setLoading(false);
      return;
    }
    try {
      const data = await api.get<Session>("/auth/session/");
      setSession(data);
      // Pin the organization so subsequent requests carry the header even
      // after a reload, when nothing else remembers which tenant we were in.
      if (data.organization) organizationStore.set(data.organization.slug);
      setError(null);
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) {
        tokenStore.clear();
        setSession(null);
      } else {
        setError(err instanceof Error ? err.message : "Could not load session.");
      }
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const login = useCallback(
    async (email: string, password: string) => {
      setError(null);
      const result = await api.post<LoginResponse | SecondFactorRequired>("/auth/login/", {
        email,
        password,
      });
      if ("mfa_required" in result) return { challenge: result.challenge };
      tokenStore.set(result.access, result.refresh);
      if (result.default_organization) {
        organizationStore.set(result.default_organization);
      }
      setLoading(true);
      await load();
    },
    [load],
  );

  const verifySecondFactor = useCallback(
    async (challenge: string, code: string) => {
      setError(null);
      const result = await api.post<LoginResponse & { recovery_codes_left?: number }>(
        "/auth/login/verify/",
        { challenge, code },
      );
      tokenStore.set(result.access, result.refresh);
      if (result.default_organization) {
        organizationStore.set(result.default_organization);
      }
      setLoading(true);
      await load();
      return { recoveryCodesLeft: result.recovery_codes_left };
    },
    [load],
  );

  const logout = useCallback(() => {
    // Fire and forget: the token is stateless, so the local clear is what
    // actually signs the user out. Waiting on the network would leave them
    // staring at a spinner to accomplish nothing.
    void api.post("/auth/logout/").catch(() => undefined);
    tokenStore.clear();
    setSession(null);
  }, []);

  const switchOrganization = useCallback(
    async (slug: string) => {
      // Validate server-side first. Setting the header optimistically would
      // leave every subsequent request failing if the user is not a member.
      await api.post("/auth/switch/", { organization: slug });
      organizationStore.set(slug);
      setLoading(true);
      await load();
    },
    [load],
  );

  /**
   * May this person do `permission`, at least at `scope`?
   *
   * **The scope half is not optional in practice.** Holding a permission and
   * holding it widely enough are different questions, and answering only the
   * first produced a sidebar where a doctor saw eleven screens that returned
   * 403 — every one of them a permission they hold at *department* scope
   * against an endpoint that asks for *facility*.
   *
   * The ladder is the backend's, in the backend's order. A grant satisfies a
   * requirement when it sits at or above it: someone with organization scope
   * passes a facility check, and someone with department scope does not.
   */
  const can = useCallback(
    (permission: string, scope: string = "own") => {
      const auth = session?.authorization;
      if (!auth) return false;
      if (auth.is_organization_owner) return true;
      const granted = auth.permissions[permission];
      if (!granted) return false;
      const held = SCOPE_LADDER.indexOf(granted.scope);
      const needed = SCOPE_LADDER.indexOf(scope);
      // An unrecognised scope on either side is treated as "cannot tell", and
      // the honest answer there is to show the item and let the API refuse --
      // hiding something somebody can use is the worse mistake.
      if (held === -1 || needed === -1) return true;
      return held >= needed;
    },
    [session],
  );

  const hasModule = useCallback(
    (module: string) => Boolean(session?.entitlements?.modules?.[module]),
    [session],
  );

  return {
    session,
    loading,
    error,
    isAuthenticated: Boolean(session?.user),
    login,
    verifySecondFactor,
    logout,
    switchOrganization,
    can,
    hasModule,
    refresh: load,
  };
}
