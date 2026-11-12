# ADR 8: A host bridge runs the Claude Code and Codex command line tools

## Status

Accepted, 2026-11-12. Records the tool versions and flags that section 3.4 of the design
document asks to be confirmed before coding.

## Context

In `subscription` mode the app uses the owner's Claude and ChatGPT plans through the
official command line tools (section 3.4, FR-27). The tools are signed in on the Windows
host, not inside the containers, so a small service on the host has to start them for the
worker. The design fixes its outline: `127.0.0.1:8189`, `/health`, `/claude`, `/codex`,
prompt on standard input, one call at a time per tool, timeouts, an empty temporary
working folder, API key variables removed, and a usage limit reported as `plan_limit`.

It leaves open what the service is written in, which flags the tools get, how a usage
limit is recognised, and how a service on 127.0.0.1 is kept away from web pages, which can
reach that address too.

The flags were confirmed on 2026-11-12 against the versions installed on the owner's PC:

| Tool | Version | Confirmed with |
| --- | --- | --- |
| Claude Code | 2.1.300 | `claude --help`, `claude auth status --help` |
| Codex | 0.144.1 | `codex exec --help`, `codex login --help`, `codex features list` |

Beyond reading the help, each full command line was run with an empty prompt. Both tools
read their options first, so an unknown option is reported, and with every option known
they stop at the missing prompt. No model call is made that way and no plan usage is
spent. `make bridge-flags` repeats this check at any time.

## Decision

**The bridge is `tools/cli_bridge/`, plain Python with the standard library only.** It
runs on the host with `make bridge-start`, or with the stack: `make up` starts it and
`make down` stops it when `PROVIDER_MODE` is `subscription`. The folder is spelled with an
underscore, not `tools/cli-bridge/` as in the design, because Python cannot import a
folder with a dash and this repository imports code by its path (ADR 6).

**Claude Code** is started as:

```text
claude -p --output-format json
       --safe-mode --setting-sources "" --strict-mcp-config --disable-slash-commands
       --no-session-persistence --permission-prompts none
       --tools ""                                  (or, for research:)
       --tools WebSearch,WebFetch --allowed-tools WebSearch,WebFetch
       --max-turns N  [--model M]  [--effort E]
       [--system-prompt-file FILE]  [--json-schema SCHEMA]
```

| Flag | Why |
| --- | --- |
| `-p`, `--output-format json` | One run, one JSON result with the answer, token usage and duration. The prompt arrives on standard input |
| `--safe-mode`, `--setting-sources ""`, `--strict-mcp-config`, `--disable-slash-commands` | Nothing of the owner's setup is picked up: no `CLAUDE.md`, skills, plugins, hooks, MCP servers or settings files. Sign-in is not affected |
| `--no-session-persistence` | No session file is written |
| `--permission-prompts none` | Nobody can answer a permission question, so whatever would ask is refused |
| `--tools ""` | Tools are off by default. A research call gets web search and fetch and nothing else |
| `--max-turns` | 4 by default, 16 for research, or the request's own number up to 50. The flag is not in the help text of 2.1.300 but is accepted |
| `--system-prompt-file` | The system prompt, from a file outside the working folder. Also not in the help text, also accepted. A file has no length limit, a command line on Windows has |
| `--json-schema` | The schema for a structured answer, on the command line because the tool takes it no other way. The bridge refuses a schema that would not fit |

`--bare` is never passed: it makes the tool use an API key only.

**Codex** is started as:

```text
codex exec --json --color never --skip-git-repo-check
      --ephemeral --ignore-user-config --ignore-rules --strict-config
      --sandbox read-only --cd WORK
      --disable shell_tool --disable image_generation ... (14 features)
      --config web_search="disabled"
      [--model M]  [--config model_reasoning_effort="E"]  [--output-schema FILE]  -
```

| Flag | Why |
| --- | --- |
| `exec --json`, `-` | One run, events as JSON lines, the prompt on standard input |
| `--ephemeral`, `--ignore-user-config`, `--ignore-rules` | No session file, and nothing of the owner's configuration is read. That includes a configured model provider, which could be a paid one. Sign-in is not part of the configuration |
| `--strict-config` | An option this version does not know stops the call instead of being ignored |
| `--sandbox read-only`, `--cd WORK` | The tool works in the empty folder and may not write |
| `--disable ...`, `web_search="disabled"` | Everything that lets the model act is switched off: commands, images, apps, plugins, other agents, browsers, the desktop, hooks, web search. Codex refuses an unknown feature name, so a renamed feature fails the call instead of staying on |
| `--output-schema` | The schema for a structured answer, from a file |

Codex has no system prompt option, so a system text is put in front of the prompt.
`model_reasoning_effort` is not checked by the tool, so the bridge accepts only `low`,
`medium` and `high`.

**Plan sign-in is checked before every call.** `claude auth status --json` must report
`"authMethod": "claude.ai"`, and `codex login status` must print "Logged in using
ChatGPT". With any other sign-in, for example an API key, the tool is not started and the
answer is `not_plan_sign_in`. The check runs in the same cleaned environment as the call.
This is the bridge's own guard against a call that is billed per use (FR-28). It costs
about a quarter of a second per call.

**The environment of every started tool is cleaned.** Every variable whose name starts
with `ANTHROPIC_`, `OPENAI_`, `CLAUDE_` or `CODEX_` is removed, and every variable with
`API_KEY` in its name. Three are let through by name because the tools need them and they
hold no secret: `CLAUDE_CONFIG_DIR`, `CLAUDE_CODE_GIT_BASH_PATH` and `CODEX_HOME`. Removing
a whole prefix also removes the variables of a Claude Code session the bridge may have
been started from.

**A usage limit is recognised from the tool's own sentence.** Neither tool reports a limit
in a form meant for programs. The sentences were read from the program text of the two
versions: "You've hit your session limit · resets 3pm" (Claude Code, with other limit
names and a date when the reset is not today) and "You've hit your usage limit. ... try
again at 3:15 PM." (Codex). The reset time is in the PC's own clock. A limit without a
readable time is still `plan_limit`, with no time.

**Web pages are kept out without a password.** The bridge listens on 127.0.0.1 only, and
there is no setting for another address. A browser on the same PC can still reach it, so:
the `Host` header must be `127.0.0.1`, `localhost` or `host.docker.internal` with the
bridge's port, a request with an `Origin` header or a `Sec-Fetch-Site` other than `none`
is refused, and a body must be `application/json`. A page cannot send that type to another
origin without asking first, and the bridge never says yes.

**Credential files are never touched.** The bridge asks the tools whether they are signed
in. It does not open, copy or log their files, and a test fails if its source names one.
The sign-in report also names the account. The bridge reads only the fields above and
passes none of the rest on.

## Consequences

- The host needs Python through `uv`, which development already uses. Demo mode and API
  mode never start the bridge and need neither.
- The bridge follows the tools' versions. An option that a later version drops fails the
  call with the tool's own message, and `make bridge-flags` shows it before a call does.
- Limit detection depends on English sentences that can change. An unknown sentence makes
  a limit look like an ordinary tool failure, which is retried and then shown to the
  owner. It can never turn into a paid call.
- Windows: only a real program (`.exe`) is started. A `.cmd` wrapper would be run by the
  command interpreter, which reads the arguments a second time. Both tools install as real
  programs today.
- A call that is stopped by `make down` or a time limit leaves no session behind, but the
  plan usage it had spent is spent.

## Not verified

No model call has been made through the bridge. Development makes no live calls unless the
owner asks for them (section 16), and a plan call uses the owner's own allowance. Tested
with the real tools: every flag, the sign-in reports, the bridge started on the PC and
reached from a container. Tested only with fake tools that print sample output: the shape
of a real answer, of a real structured answer, and of a real usage limit. The sample
outputs in `tools/cli_bridge/tests/recorded/` were written from the tools' documented
output and program text, not captured. Card VFS-65 is the live check and replaces them
with captured ones.

## Alternatives considered

- **Node, like the progress server.** It would keep the folder name of the design. Python
  was chosen because the bridge is security code: it gets the same strict type checks,
  lint rules, source scans and coverage gate as the rest of the Python code.
- **A shared password between worker and bridge.** It would also stop other programs on
  the PC. Those can already start `claude` themselves, so it would protect nothing more,
  and it would add a secret to create, store and rotate. The checks above stop the one
  caller that has no business there, a web page.
- **Trusting the sign-in instead of checking it per call.** Faster by a quarter second,
  but a change of sign-in between two calls would go unnoticed, and the price of missing
  it is a bill.
- **Removing only the three variables the design names.** The design says "and similar
  variables". A list of names is always one name short, so whole prefixes are removed and
  the exceptions are listed instead.
- **Passing the Claude schema inside the prompt.** No length limit, but then the tool does
  not check the answer against the schema. The limit is generous for this project's
  schemas, and a larger one is refused with a clear message.
