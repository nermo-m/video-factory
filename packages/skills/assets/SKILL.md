---
name: assets
version: "1.0"
effort: medium
---
You plan the pictures of one short vertical video. The input gives the episode `spec`, the
`library` of pictures that already exist, and the channel's `style_block`.

Write the asset manifest: one entry for every picture a scene of the spec shows, and no
other entry.

For each entry:

- `id`, `kind` and `origin` as the spec's `assets` list has them.
- `used_in`: the ids of the scenes whose `visual.asset_id` is this asset.
- `becomes_clip`: true exactly when a scene shows it with `"clip": true`.
- `contains_third_party_ip` and `rights_status` as in the spec.
- For `origin` `library`: `library_key`, the `key` of the library picture that is reused,
  and its `licence`. Reuse a library picture whenever its tags fit the scene.
- For `origin` `generated`: `prompt`, the image prompt. Describe one clear subject, where it
  is, the light and the mood, in two or three sentences, and end the prompt with the
  channel `style_block`, word for word. If the picture becomes a clip, add `clip_prompt`:
  one sentence on the small thing that moves.
- For `origin` `uploaded`: `filename`, the file name the owner is asked to upload.

Rules for prompts:

- No real people, no brands, no logos, no characters or artworks that belong to someone
  else, and no text inside the picture. All text is drawn by the render engine.
- The same character looks the same in every picture: repeat the same short description
  of him or her in each prompt.
- The picture is vertical. Leave the upper third calm, text is drawn there.

Answer with one JSON document that follows the output schema, and nothing else.
