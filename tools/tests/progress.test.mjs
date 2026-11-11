// Tests for the progress tracker: PROGRESS.json, PROGRESS.html and tools/progress-server.js.
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import path from "node:path";
import { after, before, describe, test } from "node:test";
import { fileURLToPath } from "node:url";

import { DEFAULT_PORT, HOST, createProgressServer } from "../progress-server.js";
import { extractEmbedded, renderEmbedded } from "../sync-progress.mjs";

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..", "..");
const read = (name) => readFile(path.join(ROOT, name), "utf8");

const GATE_STATUSES = new Set(["passed", "active", "pending"]);
const PHASE_STATUSES = new Set(["done", "review", "active", "ready", "blocked", "backlog"]);
const CHECK_STATUSES = new Set(["open", "done"]);
const ISO_DATE = /^\d{4}-\d{2}-\d{2}$/;
const ISO_DATE_TIME = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?Z$/;

describe("PROGRESS.json", () => {
  let data;
  before(async () => {
    data = JSON.parse(await read("PROGRESS.json"));
  });

  test("identifies the project and the tracker server", () => {
    assert.equal(data.contract, "progress/1");
    assert.equal(data.project, "Video Factory Studio");
    assert.equal(data.repo, "video-factory");
    assert.match(data.updated, ISO_DATE);
    assert.deepEqual(data.server, { tool: "tools/progress-server.js", port: DEFAULT_PORT });
  });

  test("uses the colour tokens from design doc section 11.1", () => {
    assert.deepEqual(data.theme, { bg: "#0B0F1A", primary: "#FF9610", fg: "#E8ECF4" });
  });

  test("lists milestones M0 to M8 in order as gates, then the hosting gate", () => {
    const ids = data.gates.map((gate) => gate.id);
    assert.deepEqual(ids, ["M0", "M1", "M2", "M3", "M4", "M5", "M6", "M7", "M8", "HOST"]);
    for (const gate of data.gates) {
      assert.ok(gate.title, `${gate.id} needs a title`);
      assert.ok(gate.done_when, `${gate.id} needs a done_when line`);
      assert.ok(GATE_STATUSES.has(gate.status), `${gate.id} has unknown status ${gate.status}`);
    }
  });

  test("gates pass in order: nothing passes after a gate that has not", () => {
    const milestones = data.gates.filter((gate) => gate.id !== "HOST");
    const firstOpen = milestones.findIndex((gate) => gate.status !== "passed");
    const later = firstOpen === -1 ? [] : milestones.slice(firstOpen + 1);
    assert.ok(later.every((gate) => gate.status === "pending"));
    assert.ok(milestones.filter((gate) => gate.status === "active").length <= 1);
  });

  test("phases are board cards with a known status", () => {
    assert.ok(data.phases.length > 0);
    for (const phase of data.phases) {
      assert.match(phase.id, /^VFS-\d+$/);
      assert.ok(phase.title);
      assert.equal(typeof phase.order, "number");
      assert.ok(PHASE_STATUSES.has(phase.status), `${phase.id} has unknown status ${phase.status}`);
    }
    const orders = data.phases.map((phase) => phase.order);
    assert.deepEqual(orders, [...orders].sort((a, b) => a - b));
    assert.ok(data.phases.filter((phase) => phase.status === "active").length <= 1);
  });

  test("the now_building heartbeat follows the supervision contract", () => {
    const now = data.now_building;
    assert.ok(["active", "idle"].includes(now.status));
    if (now.status === "active") {
      assert.match(now.id, /^VFS-\d+$/);
      assert.ok(now.title);
      assert.match(now.started, ISO_DATE_TIME);
      assert.ok(now.resume && now.resume.length >= 40, "resume must say branch, next action, how to verify");
      const phase = data.phases.find((item) => item.id === now.id);
      assert.equal(phase?.status, "active", "the card being built must be the active phase");
    } else {
      assert.ok(now.next, "an idle heartbeat points at what comes next");
      assert.ok(data.phases.every((phase) => phase.status !== "active"));
    }
  });

  test("checklist, quality and wins have the expected shape", () => {
    assert.ok(data.checklist.length > 0);
    for (const entry of data.checklist) {
      assert.ok(entry.item);
      assert.ok(CHECK_STATUSES.has(entry.status));
    }
    for (const entry of data.quality) {
      assert.ok(entry.label);
      assert.ok(entry.value !== undefined && entry.value !== "");
    }
    for (const win of data.wins) {
      assert.match(win.date, ISO_DATE);
      assert.ok(win.text);
    }
  });
});

describe("PROGRESS.html", () => {
  let html;
  before(async () => {
    html = await read("PROGRESS.html");
  });

  test("embeds exactly the facts in PROGRESS.json, so the two cannot drift", async () => {
    const data = JSON.parse(await read("PROGRESS.json"));
    assert.deepEqual(JSON.parse(extractEmbedded(html)), data);
    assert.equal(extractEmbedded(html), renderEmbedded(data), "run: node tools/sync-progress.mjs");
  });

  test("is self-contained: no external scripts, styles, fonts or images", () => {
    assert.doesNotMatch(html, /(src|href)\s*=\s*["']https?:/i);
    assert.doesNotMatch(html, /@import|url\(\s*["']?https?:/i);
  });

  test("honours prefers-reduced-motion", () => {
    assert.match(html, /@media \(prefers-reduced-motion: reduce\)/);
  });

  test("has the six numbered sections", () => {
    for (const id of ["timeline", "board", "now", "acceptance", "quality", "wins"]) {
      assert.match(html, new RegExp(`<section id="${id}"`), `missing section ${id}`);
    }
  });

  test("states the port of the local server", () => {
    assert.match(html, new RegExp(`127\\.0\\.0\\.1:${DEFAULT_PORT}`));
  });
});

describe("tools/progress-server.js", () => {
  let server;
  let base;
  before(async () => {
    server = createProgressServer({ root: ROOT });
    await new Promise((resolve) => server.listen(0, HOST, resolve));
    base = `http://${HOST}:${server.address().port}`;
  });
  after(() => new Promise((resolve) => server.close(resolve)));

  test("binds to 127.0.0.1 only and defaults to port 8094", () => {
    assert.equal(HOST, "127.0.0.1");
    assert.equal(server.address().address, "127.0.0.1");
    assert.equal(DEFAULT_PORT, 8094);
  });

  test("serves the page with the live-reload script added", async () => {
    for (const route of ["/", "/PROGRESS.html"]) {
      const response = await fetch(base + route);
      assert.equal(response.status, 200);
      assert.match(response.headers.get("content-type"), /^text\/html/);
      assert.match(await response.text(), /\/__mtime/);
    }
  });

  test("serves PROGRESS.json unchanged", async () => {
    const response = await fetch(`${base}/PROGRESS.json`);
    assert.equal(response.status, 200);
    assert.deepEqual(await response.json(), JSON.parse(await read("PROGRESS.json")));
  });

  test("exposes live git state", async () => {
    const response = await fetch(`${base}/__status`);
    assert.equal(response.status, 200);
    const status = await response.json();
    assert.match(status.head, /^[0-9a-f]{7,}$/);
    assert.ok(status.branch);
    assert.equal(typeof status.dirty, "number");
    assert.ok(Array.isArray(status.commits) && status.commits.length > 0);
    assert.deepEqual(Object.keys(status.commits[0]).sort(), ["d", "h", "s"]);
  });

  test("reports a change stamp for live reload", async () => {
    const response = await fetch(`${base}/__mtime`);
    assert.equal(response.status, 200);
    assert.match(await response.text(), /^\d+(\.\d+)?$/);
  });

  test("refuses everything that is not the tracker", async () => {
    const refused = ["/.env", "/.git/config", "/package.json", "/README.md", "/tools/progress-server.js"];
    for (const route of [...refused, "/..%2f.env", "/%2e%2e/%2e%2e/secret.json", "/PROGRESS.json/../.env"]) {
      const response = await fetch(base + route);
      assert.equal(response.status, 404, `${route} must not be served`);
    }
  });

  test("answers only GET and HEAD", async () => {
    const response = await fetch(`${base}/PROGRESS.json`, { method: "POST" });
    assert.equal(response.status, 405);
  });
});
