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

export interface UseSession {
  session: Session | null;
  loading: boolean;
  error: string | null;
  isAuthenticated: boolean;
  login: (email: string, password: string) => Promise<void>;
  logout: () => void;
  switchOrganization: (slug: string) => Promise<void>;
  /** Does the signed-in user hold this permission in the current org? */
  can: (permission: string) => boolean;
  /** Is this module included in the current subscription? */
  hasModule: (module: string) => boolean;
  refresh: () => Promise<void>;
}

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
      const result = await api.post<LoginResponse>("/auth/login/", {
        email,
        password,
      });
      tokenStore.set(result.access, result.refresh);
      if (result.default_organization) {
        organizationStore.set(result.default_organization);
      }
      setLoading(true);
      await load();
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

  const can = useCallback(
    (permission: string) => {
      const auth = session?.authorization;
      if (!auth) return false;
      if (auth.is_organization_owner) return true;
      return permission in auth.permissions;
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
    logout,
    switchOrganization,
    can,
    hasModule,
    refresh: load,
  };
}
