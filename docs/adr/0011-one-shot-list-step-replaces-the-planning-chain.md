# ADR 11: Deviation: one shot list step replaces the planning chain

## Status

Accepted, 2026-11-15. Replaces the planning chain of design doc section 6 and the fixed
theme of decision D10 for new videos. Built by cards VFS-81 to VFS-86. The design is in
`docs/superpowers/specs/2026-11-14-director-mode-design.md`.

## Context

Section 6 of the design plans a video in a chain: `brief`, `research`, `script`, `direct`
and `assets`, five model calls, each reading the answer of the one before. Decision D10
gives every video one look, `night_scrolls`, which shows a picture inside a paper scroll.

The owner writes detailed prompts: scenes, the line spoken over each, characters, a look,
music and a length. The chain reshaped them at every step. A brief of two sentences stood
between the prompt and the script. The script was held to a word budget and to a fixed
order of hook, story, fact, steps and outro. A name that belongs to someone else was
replaced. The look put every picture into a scroll, with no camera move of its own.

VFS-78 gave every step the owner's whole idea to read and kept the owner's lines word for
word. The steps and the look were still there. On 2026-11-14 the owner wrote: "I don't
want the videos to be so restricted. They should follow the full instructions I give and
not change them based on the preset", and asked for "full on direction for every small
detail".

## Decision

**The owner's prompt is the plan.** A new video is planned by one model call and by code.

1. **One skill, `shotlist`,** reads the prompt once. It writes the scenes in the owner's
   order with the owner's lines, a complete picture prompt and a motion prompt for each,
   every character described once, and a list of everything it added, changed or could
   not do.
2. **Code checks the answer against the prompt** (`rules.shotlist_follows_the_owner`). A
   line marked as the owner's must stand in the prompt. A line the studio wrote must be on
   the change list. A line the owner marked with a label such as `VO:` must be spoken, and
   a passage in quotation marks must be spoken, shown on screen or written into a picture.
3. **Code builds the plan** (`packages/skills/build.py`), in schema version 2.1: one
   `shot` scene and one generated picture per scene. The model never writes ids, format,
   voice or seed.
4. **A second look, `plain`,** draws a shot: the picture on the whole frame with a slow
   camera move, the owner's text, the captions, and nothing of the studio's own.
5. **Nothing is forced.** Research runs only when the video asks for it. Captions and
   music are switches. The plan is as long as its lines need, from 15 to 180 seconds, and
   a spoken line always wins over a given length.
6. **The owner sees and can change everything before anything is generated:** the change
   list, the look, the characters, and every field of every shot.

The states of section 4.1 stay as they are. `direction` runs `plan.shotlist`, and `brief`,
`script` and `asset_plan` have no job and are passed over.

## Deviation from the design

- Section 6: "The planner runs skills in a fixed order: brief, research, script, direct,
  assets." A new video runs `research` only when asked, and then `shotlist`.
- Section 6: the word budget, "target_duration_s times 2.3 words per second". A plan of
  shots has no budget. Its length is what its lines need.
- Section 5.2: the resolver fails "when the total is more than 2 seconds off the target".
  That rule, and the same check after the render, hold for plans of the first design only.
- Decision D10: "v1 has one theme, night_scrolls." There are two looks. New videos use
  `plain`.
- Section 11.2: New episode asks for a "target duration (45 or 60)". It asks for the
  prompt only.
- The rule of D-052 that a name belonging to someone else is replaced in the narration and
  kept out of the picture prompts is removed. Names stay as the owner wrote them, and the
  picture is marked, for the owner to see.

## Consequences

- The owner's text passes through one model call. What that call did to it is listed, and
  the parts that code can check are checked.
- A prompt without labels or quotation marks has no dropped-line check. A detail of a
  picture that the model left out is not detected by code. The change list and the
  editable shot list are how the owner catches it, before a picture is made.
- Sounds and music made to the owner's description are not possible yet. Such a request
  is listed as not possible. Clips are stored as a wish per scene and made by VFS-29.
- The image model of the ChatGPT plan has its own rules about what it draws. This design
  does not try to get around them. A picture it refuses is replaced by the owner's upload
  today, and by a local image model in a later part.
- Nothing that belongs to someone else is committed to the repository. The owner's
  prompts and plans live in the database and the data folder. Examples, recordings and
  tests use the lighthouse keeper sample.
- The skills `brief`, `script`, `direct` and `assets` are no longer run. VFS-87 removes
  them. Until then plans of the first design stay editable.
- Demo mode replays one recorded shot list whatever is typed, and that plan is not held
  against the typed text.

## Alternatives considered

- **Loosen the chain further,** as VFS-78 began. Least work. It keeps five model calls,
  each a place where the prompt is reshaped, and the scroll look. It is what the owner
  asked to leave.
- **Director mode beside the chain, as a second mode.** Nothing existing breaks. It leaves
  two planning systems to keep working and the preset still offered.
- **Let the model write the render plan directly,** as `direct` did. One call fewer in
  code. The model would again write ids, format and seed, and a mistake there fails the
  whole answer. Building the plan in code keeps the model to what only it can write.
