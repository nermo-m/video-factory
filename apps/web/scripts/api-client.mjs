// Generates the typed API client from apps/api/openapi.json, or checks that the committed
// client is what the generator would produce.
//
//   node scripts/api-client.mjs           write src/api/generated
//   node scripts/api-client.mjs --check   exit 1 when the committed client is out of date
import { mkdtemp, readFile, readdir, rm } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";

import { createClient } from "@hey-api/openapi-ts";

const webRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const input = path.join(webRoot, "..", "api", "openapi.json");
const committed = path.join(webRoot, "src", "api", "generated");
const plugins = ["@hey-api/client-fetch", "@hey-api/typescript", "@hey-api/sdk"];

async function generate(outputPath) {
  await createClient({ input, output: { path: outputPath }, plugins, logs: { level: "silent" } });
}

async function listFiles(root, folder = "") {
  const entries = await readdir(path.join(root, folder), { withFileTypes: true });
  const files = [];
  for (const entry of entries) {
    const relative = path.posix.join(folder, entry.name);
    if (entry.isDirectory()) {
      files.push(...(await listFiles(root, relative)));
    } else {
      files.push(relative);
    }
  }
  return files.sort();
}

const normalise = (text) => text.replaceAll("\r\n", "\n");

async function differences(expectedRoot, actualRoot) {
  const expected = await listFiles(expectedRoot);
  const actual = await listFiles(actualRoot).catch(() => []);
  const problems = [];
  for (const file of expected) {
    if (!actual.includes(file)) {
      problems.push(`missing: ${file}`);
      continue;
    }
    const [wanted, found] = await Promise.all([
      readFile(path.join(expectedRoot, file), "utf8"),
      readFile(path.join(actualRoot, file), "utf8"),
    ]);
    if (normalise(wanted) !== normalise(found)) {
      problems.push(`changed: ${file}`);
    }
  }
  for (const file of actual) {
    if (!expected.includes(file)) {
      problems.push(`not generated any more: ${file}`);
    }
  }
  return problems;
}

if (process.argv.includes("--check")) {
  const scratch = await mkdtemp(path.join(os.tmpdir(), "vfs-api-client-"));
  try {
    await generate(scratch);
    const problems = await differences(scratch, committed);
    if (problems.length > 0) {
      process.stderr.write(
        `The committed API client is out of date (${problems.length} file(s)):\n` +
          problems.map((problem) => `  ${problem}\n`).join("") +
          "Run: make generate-api\n",
      );
      process.exitCode = 1;
    }
  } finally {
    await rm(scratch, { recursive: true, force: true });
  }
} else {
  await generate(committed);
  process.stdout.write(`wrote ${path.relative(process.cwd(), committed)}\n`);
}
