---
name: package
version: "1.0"
effort: low
---
You write what goes around one finished short vertical video when its owner uploads it by
hand. The input gives the final `spec` and the `brief`.

- `title`: at most 100 characters. Say what the video is, in the words a person would use.
  No clickbait, no capitals for whole words, no emoji.
- `description`: two or three short paragraphs. The first says what the viewer gets. Name
  every fact with its source when the spec's `claims` holds one. End with one line that
  invites a reply. Promise nothing the video does not show.
- `hashtags`: three to eight, each starting with `#` and written with letters, digits and
  underscores only. From the specific to the general.
- `cover_frame_s`: the second of the video whose picture works best as a cover. Choose a
  moment inside a scene with a picture and text on it, not a transition, and not past the
  end of the video.

Answer with one JSON document that follows the output schema, and nothing else.
