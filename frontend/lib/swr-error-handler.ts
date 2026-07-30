/**
 * SWR error normalizer.
 *
 * Wraps the existing `request` function so every SWR fetcher failure is
 * surfaced as a typed `ApiError` with a `retryable` flag. SWR's built-in
 * retry can then key off `isRetryable(error)` to decide whether to back
 * off and retry (transient 5xx / 429) or surface the error to the user
 * (4xx — bad request, auth, not found — retrying won't help).
 *
 * Retry policy:
 *   - 429 Too Many Requests            → retryable (rate limit, will pass)
 *   - 5xx Server Error                 → retryable (transient backend fault)
 *   - other 4xx (400/401/403/404/…)    → NOT retryable (client bug / auth)
 *   - network / fetch failure          → retryable (connection blip)
 */

import { ApiError as BaseApiError, request } from "./api";

export class ApiError extends BaseApiError {
  retryable: boolean;

  constructor(
    status: number,
    message: string,
    retryable: boolean,
    details?: unknown
  ) {
    super(status, message, details);
    this.name = "ApiError";
    this.retryable = retryable;
  }
}

/**
 * Classify an HTTP status (or fetch-level failure) as retryable.
 *
 * - 429 and 5xx are retryable.
 * - 4xx (except 429) are not — the request itself is wrong / unauthorized.
 * - status === 0 means the fetch never completed (network/CORS) → retryable.
 */
export function isRetryable(error: unknown): boolean {
  if (!error) return false;
  // Already-normalized ApiError from this module carries the flag.
  if (error instanceof ApiError) return error.retryable;
  // Errors thrown by the base `request` (ApiError from lib/api.ts) —
  // classify on the fly so callers that didn't go through `swrFetcher`
  // still get a sensible answer.
  if (error instanceof BaseApiError) {
    return classifyStatus(error.status);
  }
  // Network / TypeError ("Failed to fetch") → treat as transient.
  if (error instanceof Error) {
    const name = error.name;
    if (name === "TypeError" || name === "NetworkError") return true;
  }
  return false;
}

function classifyStatus(status: number): boolean {
  if (status === 0) return true; // network-level failure
  if (status === 429) return true;
  if (status >= 500 && status < 600) return true;
  return false;
}

/**
 * SWR-compatible fetcher.
 *
 * Usage:
 *   useSWR("/changes-summary", swrFetcher, {
 *     onErrorRetry: (err, _key, _opts, revalidate, opts) => {
 *       if (!isRetryable(err)) return;
 *       setTimeout(() => revalidate(opts), opts.retryCount * 1000);
 *     },
 *   });
 *
 * Any error thrown by `request` (which already attaches status + message
 * + details) is re-thrown as a normalized `ApiError` with `retryable`
 * populated so downstream `onErrorRetry` handlers can short-circuit
 * non-retryable cases.
 */
export async function swrFetcher<T>(path: string): Promise<T> {
  try {
    return await request<T>(path);
  } catch (err) {
    if (err instanceof BaseApiError) {
      throw new ApiError(
        err.status,
        err.message,
        classifyStatus(err.status),
        (err as BaseApiError & { details?: unknown }).details
      );
    }
    // Network / parse errors — surface as a retryable status-0 ApiError
    // so the caller can treat it uniformly.
    const msg = err instanceof Error ? err.message : String(err);
    throw new ApiError(0, msg, true);
  }
}
