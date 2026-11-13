import path from "node:path";
import { fileURLToPath } from "node:url";

const repositoryRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..", "..");

// Read when the app is built or started in development. The container image sets it to
// the api service.
const apiUrl = process.env.API_INTERNAL_URL ?? "http://127.0.0.1:8000";

/** @type {import("next").NextConfig} */
const nextConfig = {
  // A self-contained server for the container image.
  output: "standalone",
  // The app lives in a pnpm workspace, so file tracing starts at the repository root.
  outputFileTracingRoot: repositoryRoot,
  poweredByHeader: false,
  // The browser talks only to this origin. Requests to /api/v1 are forwarded to the API,
  // so there is no cross-origin setup and no API address in the browser bundle.
  async rewrites() {
    return [{ source: "/api/v1/:path*", destination: `${apiUrl}/api/v1/:path*` }];
  },
  experimental: {
    // An uploaded picture passes through this forwarding. Its default limit is 10 MB, and
    // a larger body is cut off and answered with a bare 500. The API takes pictures up to
    // 20 MB (MAX_BYTES in packages/core/uploads.py) and refuses larger ones in words, so
    // this limit sits above it.
    proxyClientMaxBodySize: 24 * 1024 * 1024,
  },
  reactStrictMode: true,
};

export default nextConfig;
