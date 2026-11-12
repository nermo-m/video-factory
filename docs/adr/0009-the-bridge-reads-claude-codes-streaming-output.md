# ADR 9: The bridge reads Claude Code's streaming output

## Status

Accepted, 2026-11-12. Replaces two parts of ADR 8: the output form in which Claude Code is
asked to answer, and its section "Not verified".

## Context

ADR 8 was written before any model call had gone through the bridge. With the owner's
go-ahead (card VFS-65) the bridge's own command lines were run against the real tools on
2026-11-12: Claude Code 2.1.300 and Codex 0.144.1, signed in with the owner's plans, nine
short calls in all.

Everything ADR 8 assumed about the shape of an answer held. Both tools answered on the
first try, with and without a schema, and the readers understood the output unchanged.

The run also showed what the single-result form of Claude Code (`--output-format json`)
leaves out. Asked for every message of the run (`--output-format stream-json --verbose`),
the tool prints one JSON object per line, and among them:

- the session's first message, with the model of the session and `apiKeySource`, which is
  `none` for a call on the plan;
- for every web search, the links it returned and what the search said about them, and
  for every fetched page, its address and what was read from it;
- a usage report: how much of the 5 hour and the 7 day window of the plan is used, and
  when each resets, and whether a request was allowed or rejected.

Two readings of the single-result form were wrong for research calls. The model with the
most output tokens is not the session's model: a smaller model reads the search results
and writes more than the session's own model. And the search count in `usage` stays 0,
because the search runs as a tool of the session.

## Decision

The bridge asks Claude Code for the streaming form and reads these messages:

| Message | What the bridge takes from it |
| --- | --- |
| first `system` message | `model`, the model of the session. `apiKeySource`: anything but `none` fails the call as `not_plan_sign_in`, so a call that used a key is never counted as covered by the plan |
| `tool_use_result` of a search | one source per link (address, title), with what the search said about its results as the passage. The number of searches |
| `tool_use_result` of a fetch | one source with the page's address and what was read from it. It replaces a search's summary of the same page |
| `rate_limit_event` | `plan_usage` in the answer: the share of each window that is used and its reset time, reported by the tool. When a call fails on a limit and the event says `rejected`, its `resetsAt` is the reset time, exact and independent of the PC's clock |
| last `result` message | the answer, the structured output, token usage and turns, as before |

The answer of `/claude` gains two fields, `sources` and `plan_usage`. `ClaudeCliLLM`
passes the sources on, so the research skill can apply FR-02 in subscription mode as it
does in API mode. The single-result form is still understood, for older versions.

Reading a usage limit from the tool's sentence stays as the second way: it is what a
limit looks like when the tool prints no message at all.

The captured outputs are in `tools/cli_bridge/tests/recorded/live/`, with session numbers
and everything about the PC removed and nothing else changed. Tests read them with the
bridge's readers. The samples for cases that cannot be produced on purpose (a usage limit,
a crash, an answer that ignores its schema) stay hand-written, in the same streaming form.

## Consequences

- Research in subscription mode has retrieved passages. A passage from a search is the
  search's own summary of its results, shared by the links of that search. A passage from
  a fetch is what was read from that one page.
- The usage tracker can show a number "reported by the tool" for the Claude plan. Codex
  reports nothing of the kind, so the ChatGPT plan stays "counted by this app".
- The bridge depends on message shapes that are not documented as a contract. A message
  it does not understand is skipped, so a change costs the extra fields, not the answer.
  `make bridge-flags` still checks the flags without a model call.
- A real usage limit has not been seen yet. The `rejected` form of the usage report is
  written from the tool's program text. The first real limit will show whether it holds.

## Alternatives considered

- **Keep the single-result form and guess the model.** It cannot give sources or the
  usage report at all, and FR-02 needs the sources.
- **Ask the model to list its sources in the answer.** Then a claim would be checked
  against what the model says it read, not against what the tool retrieved.
- **A second call for the usage report.** Neither tool has a command for it. The report
  arrives with every call for free.
