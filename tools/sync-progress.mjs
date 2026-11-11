// Copies PROGRESS.json into PROGRESS.html so the page and its machine-readable twin can
// never drift. PROGRESS.json is the authority: edit it, then run this script.
//
//   node tools/sync-progress.mjs           write the JSON into the page
//   node tools/sync-progress.mjs --check   exit 1 when the page is out of date
import { readFile, writeFile } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";

const OPEN = '<script type="application/json" id="progress-data">';
const CLOSE = "</script>";

/** The exact text that belongs between the data script tags for this data. */
export function renderEmbedded(data) {
  // "<" is escaped so no value can ever close the script element early.
  return `\n${JSON.stringify(data, null, 2).replaceAll("<", "\\u003c")}\n`;
}

function bounds(html) {
  const start = html.indexOf(OPEN);
  const end = start === -1 ? -1 : html.indexOf(CLOSE, start + OPEN.length);
  if (start === -1 || end === -1) {
    throw new Error(`PROGRESS.html has no ${OPEN} block`);
  }
  return { start: start + OPEN.length, end };
}

/** The text currently between the data script tags. */
export function extractEmbedded(html) {
  const { start, end } = bounds(html);
  return html.slice(start, end);
}

/** The page with its data block replaced by this data. */
export function embed(html, data) {
  const { start, end } = bounds(html);
  return html.slice(0, start) + renderEmbedded(data) + html.slice(end);
}

async function main() {
  const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
  const jsonPath = path.join(root, "PROGRESS.json");
  const htmlPath = path.join(root, "PROGRESS.html");
  const data = JSON.parse(await readFile(jsonPath, "utf8"));
  const html = await readFile(htmlPath, "utf8");
  const next = embed(html, data);

  if (process.argv.includes("--check")) {
    if (next !== html) {
      process.stderr.write("PROGRESS.html is out of date. Run: node tools/sync-progress.mjs\n");
      process.exitCode = 1;
    }
    return;
  }
  if (next !== html) {
    await writeFile(htmlPath, next, "utf8");
    process.stdout.write("PROGRESS.html updated from PROGRESS.json\n");
  }
}

const isMain = process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url);
if (isMain) {
  await main();
}
