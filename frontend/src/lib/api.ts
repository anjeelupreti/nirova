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

/**
 * Fetch a file rather than a payload, and hand the browser the download.
 *
 * `request()` cannot do this: it reads the body as text and parses it as JSON,
 * which turns a CSV export into a syntax error. The headers still come from
 * the same two stores, so a download is authenticated and tenant-scoped
 * exactly like every other call -- which is the reason this lives here rather
 * than as a bare `fetch` inside a screen.
 *
 * The object URL is revoked immediately. The browser has already taken its own
 * reference by the time the click returns, and not revoking leaks the whole
 * file into memory for the life of the tab.
 */
export async function download(path: string, filename: string): Promise<void> {
  const headers: Record<string, string> = {};
  const token = tokenStore.get();
  if (token) headers.Authorization = `Bearer ${token}`;
  const organization = organizationStore.get();
  if (organization) headers["X-Organization"] = organization;

  const response = await fetch(`/api${path}`, { headers });
  if (!response.ok) {
    // The failure path still speaks JSON: an export refused for a missing
    // permission is the ordinary error envelope, and swallowing it here would
    // turn a 403 into a silently absent file.
    const text = await response.text();
    let envelope: ApiErrorBody | undefined;
    try {
      envelope = (JSON.parse(text)?.error as ApiErrorBody) ?? undefined;
    } catch {
      envelope = undefined;
    }
    throw new ApiError(
      response.status,
      envelope ?? {
        code: "export_failed",
        message: `Export failed with status ${response.status}.`,
        detail: {},
      },
    );
  }

  const url = URL.createObjectURL(await response.blob());
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  anchor.click();
  URL.revokeObjectURL(url);
}

/**
 * Open a server-rendered printable in a new tab.
 *
 * `window.open("/api/…")` cannot work here and quietly did not: the bearer
 * token lives in a header, not a cookie, so a bare navigation arrives
 * unauthenticated. The document has to be fetched by this client and then
 * handed to the tab.
 *
 * The tab is opened **synchronously, before the await**. A `window.open` after
 * an asynchronous gap is no longer attributable to the click and popup
 * blockers stop it — which is the difference between a print button that works
 * and one that appears to do nothing.
 *
 * The object URL is revoked on a timer rather than immediately: unlike a
 * download, where the browser takes its own reference as the click returns,
 * the new tab needs the URL to survive long enough to load it.
 */
export async function openPrintable(path: string): Promise<void> {
  const tab = window.open("", "_blank");
  const headers: Record<string, string> = {};
  const token = tokenStore.get();
  if (token) headers.Authorization = `Bearer ${token}`;
  const organization = organizationStore.get();
  if (organization) headers["X-Organization"] = organization;

  try {
    const response = await fetch(`/api${path}`, { headers });
    if (!response.ok) {
      tab?.close();
      const text = await response.text();
      let envelope: ApiErrorBody | undefined;
      try {
        envelope = (JSON.parse(text)?.error as ApiErrorBody) ?? undefined;
      } catch {
        envelope = undefined;
      }
      throw new ApiError(
        response.status,
        envelope ?? {
          code: "printable_failed",
          message: `Could not produce that document (${response.status}).`,
          detail: {},
        },
      );
    }
    const url = URL.createObjectURL(await response.blob());
    if (tab) tab.location.href = url;
    window.setTimeout(() => URL.revokeObjectURL(url), 60_000);
  } catch (problem) {
    tab?.close();
    throw problem;
  }
}

export const api = {
  get: <T>(path: string, opts?: RequestOptions) => request<T>(path, { ...opts }),
  post: <T>(path: string, body?: unknown, opts?: RequestOptions) =>
    request<T>(path, { ...opts, method: "POST", body }),
  download,
  openPrintable,
};

export default api;
