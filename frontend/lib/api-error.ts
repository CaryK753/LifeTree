export function apiErrorMessage(
  status: number,
  path: string,
  details: unknown
): string {
  if (details && typeof details === "object") {
    const payload = details as {
      detail?: unknown;
      error?: { message?: unknown };
    };
    if (typeof payload.error?.message === "string") {
      return payload.error.message;
    }
    if (typeof payload.detail === "string") {
      return payload.detail;
    }
  }
  return `API ${status} on ${path}`;
}
