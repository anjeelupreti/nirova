/**
 * Talking to the portal.
 *
 * Deliberately not a copy of the staff console's client. That one carries a
 * JWT, refreshes it, and switches organizations; none of that applies here and
 * importing it would put staff authentication code into a bundle patients
 * download.
 *
 * Two decisions worth stating.
 *
 * **The token lives in memory, and in sessionStorage — never localStorage.**
 * These pages are read on shared phones and borrowed computers far more often
 * than a clinician's workstation is. `sessionStorage` dies with the tab, which
 * is the behaviour somebody using an internet café actually wants and the one
 * they will not think to ask for.
 *
 * **A 401 signs the patient out rather than retrying.** The portal has no
 * refresh token: sessions are rows on the server, and one that has been
 * revoked should stop working immediately and visibly, not be papered over.
 */

const TOKEN_KEY = "nirova.portal.token";
const ORG_KEY = "nirova.portal.org";

export interface ApiErrorBody {
  code?: string;
  message?: string;
  detail?: Record<string, unknown>;
}

export class ApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly detail: Record<string, unknown>;

  constructor(status: number, body: ApiErrorBody) {
    super(body.message || "Something went wrong.");
    this.name = "ApiError";
    this.status = status;
    this.code = body.code || "error";
    this.detail = body.detail ?? {};
  }
}

/** Where the session token lives. See the note at the top of the file. */
export const session = {
  get token(): string | null {
    try {
      return sessionStorage.getItem(TOKEN_KEY);
    } catch {
      return null;
    }
  },
  set token(value: string | null) {
    try {
      if (value === null) sessionStorage.removeItem(TOKEN_KEY);
      else sessionStorage.setItem(TOKEN_KEY, value);
    } catch {
      /* Private browsing. The token stays in memory for this page only. */
    }
  },
  get organization(): string {
    try {
      return localStorage.getItem(ORG_KEY) ?? "";
    } catch {
      return "";
    }
  },
  set organization(value: string) {
    try {
      localStorage.setItem(ORG_KEY, value);
    } catch {
      /* ignore */
    }
  },
  clear() {
    this.token = null;
  },
};

let onUnauthenticated: (() => void) | null = null;

/** Called when the server says the session is gone, so the app can react. */
export function whenSignedOut(handler: () => void) {
  onUnauthenticated = handler;
}

async function request<T>(
  path: string,
  init: RequestInit = {},
  authenticated = true,
): Promise<T> {
  const headers = new Headers(init.headers);
  headers.set("Content-Type", "application/json");

  // Which hospital's database to look in. Not a secret — the session token has
  // to exist inside that tenant, so a wrong value simply finds nothing.
  if (session.organization) {
    headers.set("X-Organization", session.organization);
  }
  // A distinct scheme from the staff console's `Bearer`, so the two can never
  // be handed to the wrong authenticator.
  if (authenticated && session.token) {
    headers.set("Authorization", `Portal ${session.token}`);
  }

  const response = await fetch(`/api${path}`, { ...init, headers });

  if (response.status === 401 && authenticated) {
    session.clear();
    onUnauthenticated?.();
  }

  const text = await response.text();
  const body = text ? JSON.parse(text) : null;

  if (!response.ok) {
    throw new ApiError(response.status, body?.error ?? body ?? {});
  }
  return body as T;
}

export const api = {
  get: <T>(path: string) => request<T>(path, { method: "GET" }),
  post: <T>(path: string, data: unknown) =>
    request<T>(path, { method: "POST", body: JSON.stringify(data) }),
  /** For sign-in and registration, which have no session yet. */
  open: <T>(path: string, data: unknown) =>
    request<T>(path, { method: "POST", body: JSON.stringify(data) }, false),
};

export default api;
