# ADR 5: Spec-driven rendering

## Status

Accepted, 2026-11-11. Design document goal G2, decision D4 and sections 5 and 7.

## Context

A video is the result of many creative decisions: wording, timing, on-screen text, images,
overlays, sound and transitions. A language model makes the first version of those
decisions, and the owner changes them. Text drawn by a video model is unreliable, generated
clips are about five seconds long, and a model cannot be asked to "make the same video
again, but with a bigger title".

## Decision

Every creative decision lives in one versioned document, the Episode Spec, before anything
is generated. Models and the owner write the authored spec, in which timings may be left
out. After narration is generated, a resolver turns it into the resolved spec, in which
every scene, text item, overlay and sound cue has an absolute time. A deterministic render
engine (Python, Pillow, NumPy and FFmpeg, on the CPU, with no network access) draws the
video from the resolved spec alone. Its seed drives every random effect, so the same
resolved spec always renders the same frames. All text is drawn by the engine, never by a
video model. JSON Schemas define both forms, and the theme publishes what it can draw, so
the planner cannot ask for something the renderer cannot make.

## Consequences

- A change is a change to the spec: by form, by raw JSON or by a plain-language comment
  that becomes a JSON Patch. Every change is a new version with a diff.
- Changing one scene re-renders only that scene. Scenes are separate files that are joined
  without re-encoding.
- A video can always be reproduced: the resolved spec is stored next to the render.
- Rendering can be tested with golden frames, because it is deterministic.
- The critic agent can repair presentation problems by patching the spec, inside an
  allow-list of fields, and never by touching pixels.
- The look is limited to what the theme's primitives can draw. A new look is a new theme,
  not a prompt.
- Models are only as good as the spec schema is expressive, so the schemas are the first
  deliverable of M1.

## Alternatives considered

- **Generate the whole video with a video model.** No control over text, timing or
  consistency, and no way to make a small correction.
- **A timeline editor as the source of truth.** A large interface to build, and nothing a
  language model can write or revise reliably.
- **A browser-based renderer (HTML and CSS captured to video).** Flexible styling, but
  frame-exact, repeatable output and audio sync are harder to guarantee than with frames
  drawn in code.
