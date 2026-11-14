# Director mode, part 1: the shot list, the plain look and the switches

Date: 2026-11-14. Status: approved by the owner on 2026-11-14, with deleting
videos added at their request.

## Why

The owner writes detailed prompts and shot lists and wants the video to follow them. Today
the studio pushes every idea through a fixed chain of seven planning steps and one fixed
look, and each of them reshapes the idea: a hook, a fact, three steps and an outro are
added, pictures are drawn inside a scroll, names are replaced, lines are cut to a word
budget. The owner's words on 2026-11-14: "I don't want the videos to be so restricted.
They should follow the full instructions I give and not change them based on the preset."

Director mode makes the owner's prompt the plan. The studio fills in what the owner left
open, says what it filled in, and blocks nothing.

## The whole of Director mode, and what this document covers

Director mode is four parts, built and usable one after the other:

1. **This document:** one prompt becomes an editable shot list, a plain full-frame look,
   and switches for the things that used to be forced. Pictures come from the ChatGPT plan
   as they do today.
2. Clips: Wan 2.2 animates scenes on the owner's graphics card, and long scenes chain
   clips from the last frame of the one before.
3. Character reference pictures for the image model, and a local image model in ComfyUI
   that takes over a scene when the ChatGPT plan refuses it.
4. The rights check becomes a warning badge the owner can dismiss.

Parts 2 to 4 each get their own design. Part 1 stores what they need (the motion prompt,
the clip switch, the character sheet) so that they add to it and do not rework it.

## Goals

- The owner writes one prompt of any shape, up to the length the API takes today, and
  gets a shot list that says what the prompt says.
- Lines the owner wrote are spoken word for word. Scenes, order, characters, places,
  style and lengths the owner gave are kept.
- Everything the studio added, changed or could not do is listed in one place.
- Every field of the shot list can be edited before a picture is made.
- A character looks the same in every scene.
- The look puts the picture on the whole frame and adds no decoration of its own.
- Fact research and the critic are choices, off by default. The scroll look is no longer
  applied to new videos.

## Not in part 1

- Wan clips, clip chaining, reference pictures, the local image model, the rights badge
  (parts 2 to 4).
- Music or sound effects made to the owner's description. The studio can only make its
  own soft music bed today. A request it cannot meet goes on the change list.
- Other frame shapes than vertical 1080 by 1920, and videos longer than 180 seconds.
  Both limits exist today and stay for now.
- Automatic upload. It stays out for good.

## What would make this a failure

- The studio changes something the owner wrote and does not say so.
- The owner's prompt is refused or held back by a rule of the app.
- A prompt trick is used to get a picture past the image model's own filter. A refused
  picture is the owner's to replace by upload (today) or goes to a local model (part 3).
- A character, brand or story that belongs to someone else ends up in the public
  repository. The owner's episodes live in the data folder and the database, never in
  Git. Examples, recordings, tests and samples in the repository use only invented
  material.

## Approaches

- **A. Loosen the seven steps further**, as VFS-78 began. Least work. It keeps five model
  calls, each one a place where the idea is reshaped, and the scroll look. Dropped: it is
  the thing the owner is asking to leave.
- **B. Director mode beside the old chain, as a second mode.** Nothing existing breaks.
  It leaves two planning systems, twice the tests, and the preset still offered. Dropped.
- **C. One shot list step replaces the chain.** Chosen. The owner's outline says "cut the
  fixed seven-step planning chain", and one step is the only shape in which the owner's
  text is read once and nothing later can rewrite it. Research stays as an optional step
  before it.

How it is built was left to the builder by the owner. Everything below under "How" is the
designer's call unless it says "owner".

## How

### The pipeline

- The states stay as they are in the database. `brief`, `script` and `asset_plan` no
  longer have a job and are passed over, which the pipeline already does for a state with
  nothing to do. `research` has its job only when the episode asks for it. `direction`
  runs the new job `plan.shotlist` in place of `plan.direct`, and the plan gate follows it
  as today.
- The skills `brief`, `script`, `direct` and `assets` are removed with their recordings,
  examples and tests. `research`, `revise` and `package` stay. `research` takes the
  owner's prompt in place of the brief.
- What `plan.assets` did in code (create the rows for the pictures an episode has to get)
  now happens when the shot list is stored and again whenever the plan is edited.
- An episode gets an `options` column: `research` (true or false), `captions` (true or
  false), `music` (true or false). New episodes default to no research, captions on,
  music on, and always use the `plain` look.
- **The scroll look is not offered for new episodes in part 1.** Its scenes (title,
  scroll, stat, steps, outro) have a different shape from a shot, so offering it would
  mean a second answer format or a lossy translation. The theme and its renderer stay in
  the code for the episodes that use it. Bringing it back as a look for a shot list is a
  small design of its own, if the owner wants it.
- **Episodes that exist today** keep their plan and their scroll look. They can still be
  rendered, have a picture made again or uploaded, and be downloaded. Their plan is shown
  but can no longer be edited or revised in words, because the steps that kept an old
  plan and its pictures in step are removed. "Plan again" on such an episode makes a new
  shot list from its idea in the plain look. An old episode that has no plan yet is
  planned by the new step when it is run again.
- **The clip switch is stored and does nothing yet.** Until part 2, no clip job is queued
  for a scene with `clip` true: the scene shows its still picture with its camera move.
  The Plan tab says next to the switch that clips arrive with the next step.
- The critic has no job yet (it is a later milestone). Its setting defaults to off. No
  control for it is added until it exists.

### The shot list step

One skill, `shotlist`, one model call with high effort. Input: the owner's prompt, the
look's capabilities, the voice speed, and the claims when research ran. Output, a
document of its own (not the render plan):

- `title`
- `style`: the look of the pictures in the owner's words, or chosen by the model when the
  owner named none (then it is on the change list)
- `characters`: `id`, `name`, `description` (face, build, hair, clothes, colours: enough
  to draw the same person twice)
- `scenes`, each with: `id`, `narration`, `on_screen_text` (lines with a position),
  `duration_s` (only for a scene without narration, or when the owner gave one),
  `image_prompt` (subject, pose, expression, outfit, setting, lighting, camera angle,
  lens), `characters` (ids of who is in the picture), `motion_prompt` (what moves, the
  camera move, the speed), `clip` (true when the owner wants it moving), `camera` (the
  move of the still picture, from the look's list)
- `changes`: one entry for everything added, changed, or asked for and not possible, each
  with `scene` (or none), `kind` (`added`, `changed`, `not_possible`), `what`, `why`

The owner's words on 2026-11-14: Claude writes "full on direction for every small detail",
with the scene backgrounds "based on exact details I have given", so that the image model
makes the pictures "exactly with the character design description and mood". So the
picture prompt of every scene is complete on its own: every detail the owner gave for
that scene, its background and its mood is in it, in the owner's words where they gave
them, and what the owner left open (lighting, lens, angle) is filled in to match the
owner's style and listed as `added`. A short or vague picture prompt is a failure of the
step. The motion prompt is written to the same standard, for part 2.

Rules given to the model: the owner's prompt is the plan. Keep its scenes, order, lines,
names and style. Fill in only what is missing. Never shorten, soften or replace. Names
stay as the owner wrote them, including ones that belong to someone else (the rule that
replaced them is removed). Mark a picture that names someone else's character or brand
with `contains_third_party_ip`, which part 4 turns into the badge.

Checks in code, not left to the model's word:

- Each scene says whether its narration is the owner's (`narration_from: "owner"`) or
  written by the studio (`"studio"`). A narration marked as the owner's must stand in the
  prompt word for word (compared the way `rules.owner_lines` compares today: case, spaces
  and punctuation aside). A narration marked as the studio's must have an entry on the
  change list for that scene. Either failure sends the answer back once, as invalid
  answers are today.
- Dropped lines: code takes from the prompt every passage in quotation marks and every
  line that follows a label such as "VO:", "Voiceover:", "Narration:" or "Narrator:".
  Each of them must appear in some scene's narration, in the prompt's order. A missing
  one sends the answer back. A prompt without such marks has no dropped-line check, and
  the first check still holds. This is a new rule, since `owner_lines` only counts scenes.
- A spoken line always wins over a length. A scene given fewer seconds than its line
  takes lasts as long as the line, and a total length shorter than the lines need becomes
  the length they need. Both are listed as `changed`.
- Every scene has a picture prompt. Every character id used exists. Only what the look
  can draw is named.
- The word budget check is gone. The episode's length is the owner's when they gave one,
  otherwise what the scenes need, between 15 and 180 seconds. When the owner's own lines
  need more than 180 seconds, the job stops with a message that says so. It does not cut.

The app then builds the render plan from the shot list in ordinary code: ids, format,
voice, seed, one generated picture per scene. The model never writes that part.

### The render plan (episode spec)

The schema grows, and its version becomes 2.1. Version 2.0 plans stay valid.

- Top level: `style`, `characters`, `changes`.
- A new scene kind `shot`: `narration`, `visual` (picture, `clip`, `camera`, `motion`),
  `text` (lines, each with a position `top`, `middle` or `bottom` and an optional cue),
  optional `duration_s`.
- A picture's entry keeps the scene's own `prompt` and lists its `characters`. The prompt
  sent to the image model is put together when the picture is made: style, then the
  description of each character in it, then the scene's prompt. So a character is
  described once, and editing that description changes every picture that shows the
  character. The Assets tab shows the prompt as it was sent.
- The channel's style block is not added in Director mode. The line that asks the image
  model for no written text in the picture stays, unless the scene's prompt asks for text.
- Editing a character or the style marks the pictures that use it as out of date, the
  same way an edited picture prompt does today.

### The plain look

A second theme folder, `plain`, next to `night_scrolls`:

- Scene kind `shot` only. The picture covers the whole frame, cropped from the centre.
- `camera` moves for a still picture: `none`, `push_in`, `pull_out`, `pan_left`,
  `pan_right`, `tilt_up`, `tilt_down`. The default is a slow `push_in`. A scene whose
  clip exists plays the clip instead (part 2).
- On-screen text in one neutral style (Inter, white with a dark edge), at `top`,
  `middle` or `bottom`.
- Captions as they work today, in the same neutral style, off when the episode says so.
- Transitions: `cut` and `fade`. No sprites, stamps, tags or sound effects.
- Music: the existing generated bed with neutral settings, off when the episode says so.
- No background art, no paper, no smoke.

A request for a move, sound or effect the look does not have is left out and listed as
`not_possible`.

### The screens

- **New episode:** one large text box, "Write your video". Under it, closed by default,
  "Options": Check facts with sources, Captions, Music. The
  45 or 60 second choice goes: the length comes from the prompt.
- **Plan tab:** a panel "What the studio changed" on top, listing `changes`, empty state
  "Nothing was changed". A "Characters" panel with each description editable. A "Style"
  field. Then one card per scene with every field editable: spoken line, on-screen text,
  seconds, picture prompt, who is in it, camera move, motion prompt, clip switch. The
  existing "ask for a change in words" (revise) stays and works on the new fields.
- Nothing is generated until the owner approves the plan, as today.

### Deleting videos (owner, 2026-11-14)

The owner wants to delete videos that were started, including the test episodes that
fill the Board.

- **Delete** on a video's card on the Board and on its own page, and a "Select" mode on
  the Board to delete several at once.
- A confirmation in the studio's own style names the video (or the number of videos) and
  says that its plan, pictures, voice and rendered files are removed for good.
- Deleting removes the episode, its plans, jobs, its own pictures and their versions,
  its renders, and its files in the data folder. Pictures of the shared library stay.
  The usage counts stay, because they are what the plan budgets are measured against.
- A video can be deleted in any state. Its queued jobs are cancelled. A job that is
  running at that moment is allowed to end and its result is thrown away.
- The Board shows that it worked or says why it did not. One `DELETE` call per episode,
  safe to repeat.

### Demo mode

Demo mode gets one recorded shot list for the lighthouse keeper sample, in the plain
look, with its bundled pictures, so the demo and the browser tests run without a model.

## Left to the builder

- The exact JSON shapes and field limits, migrations, and how the work is cut into cards
  and pull requests under the repository's rules (one card per pull request, tests
  first, tracker and decisions log updated, an ADR for replacing the planning chain, and
  the Notion design document's changelog).
- How the camera moves are drawn and the golden frames that pin them.
- How the browser screens are laid out, following the existing components.
- Whether `package` needs the title another way now that there is no brief.

## How it is checked

- Skill tests against the recording, rule tests for the checks above, schema fixtures for
  the new plan fields, golden frames for the plain look, the browser demo test on the new
  flow, the full existing check suite green.
- One live episode on the owner's plans from one of the owner's own shot lists, compared
  line by line with the prompt: every line spoken as written, every difference on the
  change list.
