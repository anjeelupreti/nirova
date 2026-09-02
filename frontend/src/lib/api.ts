/**
 * The single door to the backend.
 *
 * Every request goes through `request()`, which is what makes three things
 * true everywhere rather than in most places:
 *
 *  1. The bearer token is attached.
 *  2. The active organization is sent as `X-Organization` — this is the
 *     whole mechanism behind the context switcher. Switching tenants changes
 *     one header; no screen needs to know it happened.
 *  3. Errors arrive as a typed `ApiError` carrying the backend's `code`, so
 *     callers branch on a stable identifier instead of matching prose.
 */

const TOKEN_KEY = "nirova.access";
const REFRESH_KEY = "nirova.refresh";
const ORG_KEY = "nirova.organization";

/** The error envelope every endpoint returns. See dev log entry 024. */
export interface ApiErrorBody {
  code: string;
  message: string;
  detail: Record<string, unknown>;
}

export class ApiError extends Error {
  readonly code: string;
  readonly status: number;
  readonly detail: Record<string, unknown>;

  constructor(status: number, body: ApiErrorBody) {
    super(body.message);
    this.name = "ApiError";
    this.status = status;
    this.code = body.code;
    this.detail = body.detail ?? {};
  }

  /** True when the subscription, not the user's permissions, is the blocker. */
  get isEntitlementProblem(): boolean {
    return (
      this.code === "quota_exceeded" ||
      this.code === "not_entitled" ||
      this.code === "subscription_inactive"
    );
  }
}

export const tokenStore = {
  get: () => localStorage.getItem(TOKEN_KEY),
  getRefresh: () => localStorage.getItem(REFRESH_KEY),
  set: (access: string, refresh: string) => {
    localStorage.setItem(TOKEN_KEY, access);
    localStorage.setItem(REFRESH_KEY, refresh);
  },
  clear: () => {
    localStorage.removeItem(TOKEN_KEY);
    localStorage.removeItem(REFRESH_KEY);
    localStorage.removeItem(ORG_KEY);
  },
};

export const organizationStore = {
  get: () => localStorage.getItem(ORG_KEY),
  set: (slug: string) => localStorage.setItem(ORG_KEY, slug),
  clear: () => localStorage.removeItem(ORG_KEY),
};

interface RequestOptions {
  method?: string;
  body?: unknown;
  /** Skip the organization header — for platform-console endpoints. */
  withoutOrganization?: boolean;
}

async function request<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const { method = "GET", body, withoutOrganization = false } = options;

  const headers: Record<string, string> = { "Content-Type": "application/json" };

  const token = tokenStore.get();
  if (token) headers.Authorization = `Bearer ${token}`;

  const organization = organizationStore.get();
  if (organization && !withoutOrganization) headers["X-Organization"] = organization;

  const response = await fetch(`/api${path}`, {
    method,
    headers,
    body: body === undefined ? undefined : JSON.stringify(body),
  });

  // 204 and empty bodies are normal for logout and some deletes.
  const text = await response.text();
  const payload = text ? JSON.parse(text) : null;

  if (!response.ok) {
    const envelope = payload?.error as ApiErrorBody | undefined;
    throw new ApiError(
      response.status,
      envelope ?? {
        code: "unknown_error",
        message: `Request failed with status ${response.status}.`,
        detail: {},
      },
    );
  }

  return payload as T;
}

export const api = {
  get: <T>(path: string, opts?: RequestOptions) => request<T>(path, { ...opts }),
  post: <T>(path: string, body?: unknown, opts?: RequestOptions) =>
    request<T>(path, { ...opts, method: "POST", body }),
};

export default api;
