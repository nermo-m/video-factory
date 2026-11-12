// What to tell the owner when a request fails (design doc section 11.3: errors say what
// happened and what to do next).

export const API_NOT_ANSWERING =
  "The API is not answering. Check that the stack is running with docker compose ps, then try again.";

/**
 * Why a request that brought no data failed. With no response at all the API was not
 * reached. Otherwise the API's own words when it sent an error body, or `fallback`.
 */
export function failureMessage(
  result: { error?: unknown; response?: Response },
  fallback: string,
): string {
  return result.response ? apiMessage(result.error, fallback) : API_NOT_ANSWERING;
}

function apiMessage(error: unknown, fallback: string): string {
  if (typeof error === "object" && error !== null && "error" in error) {
    const body = (error as { error: unknown }).error;
    if (typeof body === "object" && body !== null && "message" in body) {
      const message = (body as { message: unknown }).message;
      if (typeof message === "string" && message.trim()) {
        return message;
      }
    }
  }
  return fallback;
}

/** A request the API answered with an error, or did not answer at all. */
export class ApiFailure extends Error {
  constructor(
    message: string,
    /** Every single problem, when the API listed them (a spec that is not valid). */
    readonly problems: string[] = [],
    readonly status: number | null = null,
  ) {
    super(message);
  }
}

function problemsOf(error: unknown): string[] {
  if (typeof error !== "object" || error === null || !("error" in error)) {
    return [];
  }
  const details = (error as { error?: { details?: { problems?: unknown } } }).error?.details;
  return Array.isArray(details?.problems) ? details.problems.map(String) : [];
}

/** The data of an answer, or an ApiFailure that says what went wrong. */
export function unwrap<T>(
  result: { data?: T; error?: unknown; response?: Response },
  fallback: string,
): T {
  if (result.data !== undefined) {
    return result.data;
  }
  throw new ApiFailure(
    failureMessage(result, fallback),
    problemsOf(result.error),
    result.response?.status ?? null,
  );
}

export function failureOf(error: unknown): ApiFailure {
  return error instanceof ApiFailure ? error : new ApiFailure(API_NOT_ANSWERING);
}
