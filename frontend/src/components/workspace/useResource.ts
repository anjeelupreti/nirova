/**
 * One panel's data, with the three states kept apart.
 *
 * Extracted from `Dashboard.tsx` when the persona workspaces were built,
 * because six of them now need it and a second copy is two sets of loading
 * semantics that drift.
 *
 * **`enabled` is how permission gating reaches the fetch.** A panel the viewer
 * may not see never issues the request, so a receptionist's session does not
 * fill the audit log with 403s that read as probing.
 */

import * as React from "react";

import api, { ApiError } from "@/lib/api";

export interface Resource<T> {
  data: T | null;
  loading: boolean;
  /** Set when the request failed. **Never conflate this with an empty list.** */
  error: string | null;
  /** When the answer was read. A figure with no as-of time is a guess. */
  at: Date | null;
  /**
   * The organization did not buy this module. Not an error and not an empty
   * list: a panel about a module nobody bought should disappear, not sit
   * there in red saying something failed.
   */
  notIncluded: boolean;
  reload: () => void;
}

export function useResource<T>(path: string | null, enabled = true): Resource<T> {
  const [state, setState] = React.useState<Omit<Resource<T>, "reload">>({
    data: null,
    loading: Boolean(path) && enabled,
    error: null,
    at: null,
    notIncluded: false,
  });
  const [nonce, setNonce] = React.useState(0);

  React.useEffect(() => {
    if (!path || !enabled) {
      setState({ data: null, loading: false, error: null, at: null, notIncluded: false });
      return;
    }
    let cancelled = false;
    setState((current) => ({ ...current, loading: true }));

    void api
      .get<T>(path)
      .then((data) => {
        if (cancelled) return;
        setState({ data, loading: false, error: null, at: new Date(), notIncluded: false });
      })
      .catch((problem: unknown) => {
        if (cancelled) return;
        const notIncluded =
          problem instanceof ApiError && problem.isEntitlementProblem;
        setState({
          data: null,
          loading: false,
          // A module that was never bought is not a failure to report.
          error: notIncluded
            ? null
            : problem instanceof ApiError
              ? problem.message
              : "This could not be read.",
          at: null,
          notIncluded,
        });
      });

    return () => {
      cancelled = true;
    };
  }, [path, enabled, nonce]);

  const reload = React.useCallback(() => setNonce((value) => value + 1), []);

  return { ...state, reload };
}
