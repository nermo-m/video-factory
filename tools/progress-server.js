// Local live server for the progress tracker.
//
//   node tools/progress-server.js   ->  http://127.0.0.1:8094/PROGRESS.html
//
// - Serves PROGRESS.html and PROGRESS.json, and nothing else from the repository.
// - /__status : live git state (HEAD, branch, dirty count, recent commits), cached for 2 s.
// - /__mtime  : change stamp of the two tracker files. A script added to the served page
//               reloads the browser when it changes.
//
// Local only by design: it binds to 127.0.0.1 and has no dependencies.
import { execFile } from "node:child_process";
import { readFile, stat } from "node:fs/promises";
import http from "node:http";
import path from "node:path";
import { fileURLToPath } from "node:url";

export const HOST = "127.0.0.1";
export const DEFAULT_PORT = 8094;

// The whole allow-list. Request paths are compared as sent, never decoded or joined to a
// folder, so there is no path to anything else in the repository.
const FILES = {
  "/": { name: "PROGRESS.html", type: "text/html; charset=utf-8" },
  "/PROGRESS.html": { name: "PROGRESS.html", type: "text/html; charset=utf-8" },
  "/PROGRESS.json": { name: "PROGRESS.json", type: "application/json; charset=utf-8" },
};

const LIVE_RELOAD = `<script>
(function () {
  var last = null;
  setInterval(function () {
    fetch("/__mtime").then(function (r) { return r.text(); }).then(function (stamp) {
      if (last !== null && stamp !== last) { location.reload(); }
      last = stamp;
    }).catch(function () {});
  }, 2000);
})();
</script>`;

function git(root, args) {
  return new Promise((resolve) => {
    execFile("git", args, { cwd: root, windowsHide: true }, (error, stdout) => {
      resolve(error ? null : stdout.trim());
    });
  });
}

async function readGitStatus(root) {
  const [head, branch, porcelain, log] = await Promise.all([
    git(root, ["rev-parse", "--short", "HEAD"]),
    git(root, ["rev-parse", "--abbrev-ref", "HEAD"]),
    git(root, ["status", "--porcelain"]),
    git(root, ["log", "-12", "--date=short", "--pretty=format:%h|%ad|%s"]),
  ]);
  const commits = (log ?? "")
    .split("\n")
    .filter(Boolean)
    .map((line) => {
      const [h, d, ...subject] = line.split("|");
      return { h, d, s: subject.join("|") };
    });
  return {
    head: head ?? "?",
    branch: branch ?? "?",
    dirty: porcelain ? porcelain.split("\n").filter(Boolean).length : 0,
    commits,
    at: new Date().toISOString(),
  };
}

async function changeStamp(root) {
  const stamps = await Promise.all(
    ["PROGRESS.html", "PROGRESS.json"].map((name) =>
      stat(path.join(root, name)).then(
        (info) => info.mtimeMs,
        () => 0,
      ),
    ),
  );
  return String(Math.max(...stamps));
}

function send(response, status, type, body) {
  response.writeHead(status, { "Content-Type": type, "Cache-Control": "no-store" });
  response.end(body);
}

export function createProgressServer({ root }) {
  let cached = { at: 0, body: null };

  return http.createServer(async (request, response) => {
    try {
      if (request.method !== "GET" && request.method !== "HEAD") {
        response.setHeader("Allow", "GET, HEAD");
        send(response, 405, "text/plain; charset=utf-8", "method not allowed");
        return;
      }
      const route = (request.url ?? "/").split("?")[0];

      if (route === "/__status") {
        if (!cached.body || Date.now() - cached.at > 2000) {
          cached = { at: Date.now(), body: JSON.stringify(await readGitStatus(root)) };
        }
        send(response, 200, "application/json; charset=utf-8", cached.body);
        return;
      }
      if (route === "/__mtime") {
        send(response, 200, "text/plain; charset=utf-8", await changeStamp(root));
        return;
      }

      const file = Object.hasOwn(FILES, route) ? FILES[route] : null;
      if (!file) {
        send(response, 404, "text/plain; charset=utf-8", "not found");
        return;
      }
      let body = await readFile(path.join(root, file.name), "utf8");
      if (file.name.endsWith(".html")) {
        body = body.replace("</body>", `${LIVE_RELOAD}</body>`);
      }
      send(response, 200, file.type, body);
    } catch {
      send(response, 500, "text/plain; charset=utf-8", "tracker file could not be read");
    }
  });
}

const isMain = process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url);
if (isMain) {
  const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
  const server = createProgressServer({ root });
  server.on("error", (error) => {
    const reason = error.code === "EADDRINUSE" ? `port ${DEFAULT_PORT} is already in use` : error.message;
    process.stderr.write(`progress server could not start: ${reason}\n`);
    process.exitCode = 1;
  });
  server.listen(DEFAULT_PORT, HOST, () => {
    process.stdout.write(`progress page: http://${HOST}:${DEFAULT_PORT}/PROGRESS.html\n`);
  });
}
