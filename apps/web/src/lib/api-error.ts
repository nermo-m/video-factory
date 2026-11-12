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
