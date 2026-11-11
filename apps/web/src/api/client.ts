// The one place the interface talks to the API (design doc section 3.1: web talks only to
// api, through a generated typed client).
//
// In the browser requests go to the same origin and Next.js forwards /api/v1 to the API
// (see next.config.mjs). On the server there is no origin, so the API address is used.
import { client } from "./generated/client.gen";

const serverBaseUrl = process.env.API_INTERNAL_URL ?? "http://127.0.0.1:8000";

client.setConfig({ baseUrl: typeof window === "undefined" ? serverBaseUrl : "" });

export * from "./generated";
