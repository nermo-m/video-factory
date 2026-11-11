import path from "node:path";
import { fileURLToPath } from "node:url";

const repositoryRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..", "..");

/** @type {import("next").NextConfig} */
const nextConfig = {
  // A self-contained server for the container image.
  output: "standalone",
  // The app lives in a pnpm workspace, so file tracing starts at the repository root.
  outputFileTracingRoot: repositoryRoot,
  poweredByHeader: false,
  reactStrictMode: true,
};

export default nextConfig;
