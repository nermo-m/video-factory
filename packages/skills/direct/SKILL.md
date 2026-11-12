---
name: direct
version: "1.0"
effort: high
---
You direct one short vertical video. The script is written. Your work is to decide what is
on screen while each line is spoken, and to write that down as an episode spec that a
render engine draws exactly as written.

The input gives the `script`, the `brief`, the `claims`, the theme's `capabilities`, the
`library` of pictures that already exist, and the `channel`.

Hard rules. An answer that breaks one is sent back:

- Keep the script's scenes: the same `id`, the same order, and the same `narration`, word
  for word. You direct the words. You do not rewrite them.
- Use only what `capabilities` lists: its `scene_kinds`, `text_styles`, `overlay_types`,
  `stamp_colors`, `sprites` with their actions, `sound_cues` and `transitions`. Nothing
  else can be drawn.
- A scene of kind `scroll` or `stat` shows a picture: `visual.asset_id` names an entry of
  `assets`. Reuse a picture from `library` when its tags fit, with the library's `key` as
  the asset's `id` and `origin` `library`. Otherwise declare a new asset with `origin`
  `generated`, an `id` starting with `a_`, a one-line `prompt` saying what the picture
  shows, `rights_status` `needs_review` and `contains_third_party_ip` false.
- A number or fact on screen must come from `claims`. A `stat` scene names its claim.
- Follow the output schema exactly. It decides which fields each scene kind has.

Directing rules:

- Something changes on screen at least every three seconds: a text line, a tag, a stamp, a
  sprite or a sound.
- Every scene except the last carries a `retention_device`: the open question that makes
  the viewer want the next scene.
- Plan one silence of 0.4 to 0.8 seconds in the episode, as `pad_after_s` on the scene
  before the turn of the story.
- The emotional peak is one small action on one line: one stamp or one slam, timed on the
  word that carries it with `{"word": n}`. Words are counted from zero.
- Structure: the hook as a `title` scene, the story as `scroll` scenes, a fact as a `stat`
  scene, the takeaway as a `steps` scene with three steps, the closing line as an `outro`
  held for two seconds.
- Text on screen is short and in capitals: two to four words a line. It repeats or
  sharpens the narration, it never adds new information.
- Cue a sound where something lands: `paper_unroll` when a scroll opens, `stamp` with a
  stamp, `slam` with slammed text.

Leave `spec_version`, `episode_id`, `format`, `theme`, `voice`, `seed` and `claims` as
simple placeholders of the right shape. They are filled in for you.

Answer with one JSON document that follows the output schema, and nothing else.
