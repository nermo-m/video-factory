# ADR 10: Pictures through the Codex image tool

## Status

Accepted, 2026-11-13. Fills in the endpoint `POST /codex/image` that ADR 8 left for its
own card (VFS-60), and departs from one sentence of design doc section 3.4.

## Context

In subscription mode pictures are made on the owner's ChatGPT plan, through the Codex
command line tool (FR-30). Section 3.4 asks to confirm on the installed version that the
image tool exists, where it saves files and how references are passed.

Checked on 2026-11-13 with Codex 0.144.1, signed in with the owner's plan:

- `codex features list` names the feature `image_generation` as stable and on.
- A run with the bridge's usual lock-down (read-only sandbox, no session file, no user
  configuration, every other feature switched off) and only `image_generation` left on
  made one picture from a prompt on standard input in about 40 seconds.
- The tool did not write into its working folder. It saved a PNG below its own home
  folder, in `generated_images/<session id>/`, where the session id is the `thread_id` of
  the first event it prints.
- Asked to, it answers with the full path of the saved file.
- The events do not name the image model, and report token counts only.

Reference images were not tried. The pictures of an episode are made one by one from
prompts that carry the channel's style block.

## Decision

`POST /codex/image` takes `prompt`, and optionally `model` and `timeout_s`. It runs one
`codex exec` call as for a text call, with `image_generation` as the only feature left
on, and a fixed instruction in front of the prompt: create exactly one image, write no
file yourself, answer with the path of the saved file.

**Finding the file.** The bridge follows the session id the tool printed, and only an id
that has the form of one. When the environment says where the tool keeps its files
(`CODEX_HOME`), the folder is `<that place>/generated_images/<session id>`. Otherwise the
folder is taken from a path the tool reported, and only when the path has exactly the
shape `.../generated_images/<this session's id>/<name>.png`. The bridge's source never
names a tool's home folder, which is where the tools keep their credentials, and the test
that guards that rule is unchanged.

**Returning it.** The answer carries the picture itself, as base64 in the JSON document,
with its size in bytes. The file is then removed from the tool's folder.

**What can go wrong.** A usage limit is `plan_limit` with its reset time, also when the
tool only says so in words. A run without a picture, or with a file that is not a PNG, is
`tool_failed` with what the tool said. A tool that is not signed in with a plan is not
started.

## Deviation from the design

Section 3.4 says the endpoint "moves the saved file from the Codex output folder into
the app's storage and returns its path". The bridge runs on the owner's PC and the app's
storage is a Docker volume it cannot reach, so the bridge returns the picture and the
worker stores it through the storage adapter. The file still leaves the tool's folder.

## Consequences

- A picture answer is a few megabytes of JSON. Requests stay small, so the request size
  limit is unchanged.
- Pictures come in the size the tool chooses (1122 by 1402 and 1672 by 941 were seen).
  The render engine fits a picture into its frame, so no size is asked for.
- What the model writes is never passed on to the worker, only the picture and numbers.
- `make bridge-flags` now also checks that the installed Codex accepts the picture call's
  flags and still has the image tool.

## Alternatives considered

- **Look into the tool's home folder directly.** Simplest, and the first version did. The
  tools keep their credentials there, the bridge's source must not name that folder, and
  a guard test enforces it. Refused.
- **Let Codex copy the picture into its working folder.** That needs the shell tool and a
  writable sandbox, which every other call keeps switched off. More that can go wrong for
  a file the bridge can read where it is.
- **Give the bridge the app's storage as a shared host folder**, so it can move the file
  as section 3.4 says. It would turn the data volume into a host path for every user of
  the Compose file, for one endpoint.
- **Call the image service behind ChatGPT directly.** Not an option: only `codex exec` is
  used, and no credential file is read.

## Not verified

Reference images, a real usage limit on images, and what the tool says when the plan has
no image generation at all. Each of these fails as `plan_limit` or `tool_failed` with the
tool's own words, and becomes visible on the episode page.
