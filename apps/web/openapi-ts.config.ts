import { defineConfig } from "@hey-api/openapi-ts";

// Kept for editor tooling and for running `openapi-ts` by hand. The project generates
// and checks the client with scripts/api-client.mjs, which uses the same three values.
export default defineConfig({
  input: "../api/openapi.json",
  output: { path: "src/api/generated" },
  plugins: ["@hey-api/client-fetch", "@hey-api/typescript", "@hey-api/sdk"],
});
