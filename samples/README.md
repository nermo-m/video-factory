# samples

The original demo episode, its assets and the recorded model responses that let the whole
pipeline run in demo mode with no keys, no GPU and no accounts.

Rule: every file in this folder needs a row in `ASSETS.md` (origin, licence, source).
Nothing here may contain third-party characters, footage, logos or music.

## The Lighthouse Keeper

An original 45 second story: a keeper who climbs the same hill every morning, on the
lesson that small unseen habits matter. It has no statistic, so it needs no source.

| Path | What it is |
| --- | --- |
| `lighthouse_keeper/episode_spec.json` | The authored Episode Spec: seven scenes in the `night_scrolls` theme |
| `lighthouse_keeper/assets/*.png` | Its four pictures, drawn in code by `scripts/sample_pictures.py` |
| `voice/*.wav` | Its narration, recorded once with the Kokoro voice by `make sample-voice` |

`make demo-render` turns it into a video in `export/demo/`, inside the worker image. The
recorded narration is used when the voice model is not installed, so the demo needs no
download. After changing a narration line, run `make models` and `make sample-voice`.

The recorded model responses for the planning steps arrive in M2.
