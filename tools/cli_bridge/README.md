# tools/cli_bridge

The host bridge of `subscription` mode (design doc section 3.4, FR-27). The Claude Code and
Codex command line tools are signed in on the PC, not inside the containers. This small
service runs on the PC, starts a tool for one model call at a time, and hands the answer
back. The worker reaches it at `http://host.docker.internal:8189`.

Why it is built the way it is, and every flag it passes to the tools, is in
[ADR 8](../../docs/adr/0008-host-bridge-for-the-command-line-tools.md). What the first
live calls showed and changed is in
[ADR 9](../../docs/adr/0009-the-bridge-reads-claude-codes-streaming-output.md).

## Run it

```bash
make bridge-start    # in the background. `make up` does this when PROVIDER_MODE=subscription
make bridge-status   # is it running, and is each tool signed in with a plan
make bridge-stop     # `make down` does this too
make bridge          # in this terminal, log on the screen
make bridge-flags    # ask the installed tools whether they accept every flag. No model call
```

It needs Python through `uv` and nothing else. A bridge started in the background writes
its log to `.run/cli-bridge.log`: one JSON line per call, with numbers only.

Optional settings, as environment variables or in `.env`:

| Variable | Default | Meaning |
| --- | --- | --- |
| `CLI_BRIDGE_PORT` | `8189` | The port on 127.0.0.1. Change `CLI_BRIDGE_URL` with it |
| `CLAUDE_BIN` | `claude` | The Claude Code program, as a name on the PATH or a full path |
| `CODEX_BIN` | `codex` | The Codex program |
| `CLI_BRIDGE_TIMEOUT_SECONDS` | `600` | How long one call may take when the request does not say |
| `CLI_BRIDGE_QUEUE_SECONDS` | `600` | How long a request waits while the same tool is busy |
| `CLI_BRIDGE_LOG` | `.run/cli-bridge.log` | Where a bridge started in the background writes its log |

There is no setting for the address. The bridge listens on 127.0.0.1 only.

## What it promises

- **Plan sign-in or nothing.** Before every call the tool is asked how it is signed in. With
  anything but a plan sign-in, such as an API key, the tool is not started.
- **No key reaches a tool.** Variables of the model providers and of the two tools are
  removed from the environment of everything the bridge starts (`environment.py`).
- **Tools are off.** A call can read its prompt and write its answer. A research call to
  `/claude` may also search and fetch web pages. Nothing can run commands or touch files.
- **An empty working folder** for every call, removed afterwards.
- **One call at a time per tool.** A second request waits for its turn.
- **Nothing personal in answers or logs.** Not the account the tools are signed in with, not
  a prompt, not an answer, not a key. The tools' credential files are never opened.
- **Web pages are refused**, although a browser on the same PC can reach 127.0.0.1.

## Contract `bridge/1`

Bodies are JSON, sent as `application/json`. Unknown fields are refused.

### `GET /health`

Starts no model call.

```json
{
  "service": "cli-bridge",
  "contract": "bridge/1",
  "pid": 1234,
  "tools": {
    "claude": {
      "installed": true, "version": "2.1.300", "signed_in": true,
      "billing": "plan", "plan": "max", "ready": true, "busy": false, "message": ""
    },
    "codex": {
      "installed": true, "version": "0.144.1", "signed_in": true,
      "billing": "plan", "plan": null, "ready": true, "busy": false, "message": ""
    }
  }
}
```

`billing` is `plan`, `api` or null. A tool is `ready` only when it is installed and signed in
with a plan. When it is not, `message` says what the owner has to do.

### `POST /claude` and `POST /codex`

| Field | Type | `/claude` | `/codex` | Meaning |
| --- | --- | --- | --- | --- |
| `prompt` | text | required | required | Goes to the tool on standard input |
| `system` | text | optional | optional | System prompt. Codex has none, so it is put in front of the prompt |
| `schema` | object | optional | optional | JSON Schema of the answer. The parsed answer comes back in `output` |
| `model` | text | optional | optional | Model name. Without it the tool's own default is used |
| `effort` | text | `low` to `max` | `low`, `medium`, `high` | Reasoning effort |
| `web_search` | true or false | optional | refused | Allow web search and fetch for this call |
| `max_turns` | 1 to 50 | optional | refused | Default 4, with web search 16 |
| `timeout_s` | seconds | optional | optional | At most 1800 |

The answer has the same shape for both tools:

```json
{
  "tool": "claude",
  "output": null,
  "text": "The answer.",
  "model": "claude-opus-5-5",
  "usage": {"input_tokens": 412, "cached_input_tokens": 100, "output_tokens": 18},
  "searches": 0,
  "sources": [],
  "plan_usage": null,
  "turns": 1,
  "duration_ms": 2400,
  "tool_duration_ms": 2310,
  "billing": "plan"
}
```

`input_tokens` counts everything the model read, cached or not. `model` is the model that
wrote the answer for Claude, and for Codex the model that was asked for, or null.
`duration_ms` is measured by the bridge, `tool_duration_ms` is the tool's own figure.

Two fields come from Claude Code only. `sources` lists the pages a research call
retrieved: `{"url", "title", "text"}`, where `text` is what was read from a fetched
page, or what the search said about its results. `plan_usage` is the tool's own report
of how much of the plan is used, for example
`{"five_hour": {"used": 0.61, "resets_at": "..."}, "seven_day": {...}}`, or null
when it reported nothing. Codex reports neither, and its answer leaves both out.

### Errors

```json
{"error": {"code": "plan_limit", "message": "You've hit your session limit · resets 3pm",
           "tool": "claude", "retry_at": "2026-11-12T15:00:00+02:00"}}
```

| Code | Status | Meaning | What the worker does (section 4.4) |
| --- | --- | --- | --- |
| `plan_limit` | 429 | The plan's usage limit is reached. `retry_at` is the reset time when the tool gave one | Waits until then. Never uses a paid API instead |
| `busy` | 503 | The tool was busy for longer than a request may wait | Retries |
| `timeout` | 504 | The call took too long and the tool was stopped | Retries |
| `tool_failed` | 502 | The tool reported an error or printed something unreadable | Retries |
| `invalid_output` | 502 | The answer does not contain the JSON document the schema asks for | The skill's one corrective retry |
| `not_installed` | 503 | The program was not found | Owner task |
| `not_signed_in` | 503 | The tool is not signed in | Owner task |
| `not_plan_sign_in` | 503 | The tool is signed in with an API key or another paid account | Owner task |
| `bad_request` | 400, 411 | The request is malformed | A bug in the caller |
| `forbidden` | 403 | The request came from a web page or was addressed to another name | |
| `not_found`, `method_not_allowed`, `unsupported_media_type`, `payload_too_large` | 404, 405, 415, 413 | As named | |
| `internal` | 500 | The bridge itself failed. Its log says where | Retries |

## Files

| File | What it does |
| --- | --- |
| `service.py` | The bridge: status of the tools, one call at a time, the log line per call |
| `claude.py`, `codex.py` | The command line for each tool, and how its output is read |
| `environment.py` | Which variables a started tool may see |
| `limits.py` | Recognises a usage limit and its reset time in a tool's own sentence |
| `process.py` | Starts a tool without a shell and stops it after the time limit |
| `contract.py` | What a request may contain |
| `server.py` | HTTP on 127.0.0.1, and the checks that keep web pages out |
| `cli.py` | `run`, `start`, `stop`, `status` |
| `tests/fake_tool.py` | A stand-in for both tools that prints the files in `tests/recorded/` |

The files in `tests/recorded/live/` were captured from the real tools on 2026-11-12, with
session numbers and everything about the PC removed. The other files in `tests/recorded/`
are hand-written in the same form, for cases that cannot be produced on purpose: a
usage limit, a crash, an answer that ignores its schema.

### `POST /codex/image`

One picture from Codex's image tool, on the ChatGPT plan (FR-30, ADR 10).

| Field | Type | Meaning |
| --- | --- | --- |
| `prompt` | text, required, at most 20 000 characters | What the picture shows |
| `model` | text | The model Codex is asked for. Left out, the tool chooses |
| `timeout_s` | number | Seconds the call may take |

The answer has `image_base64` (a complete PNG file), `media_type` (`image/png`), `bytes`,
`usage`, `turns`, `duration_ms` and `billing` (`plan`). What the model wrote is not passed
on. The picture is removed from the tool's own folder once it has been read.
