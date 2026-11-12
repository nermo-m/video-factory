# packages/render

The deterministic render engine: resolver, timeline, primitives, the `night_scrolls` theme,
compositor, audio and encode. Pure Python with FFmpeg, CPU only.

Rule: no network access anywhere in this package. The same resolved spec and seed always
render the same frames.

So far: `resolver.py` turns an authored spec plus voice timings into a resolved spec with
absolute times, and reports every problem it finds with its location. `theme/` holds the
`night_scrolls` theme: its artwork, sounds and fonts, what it can draw
(`capabilities.json`) and where things go (`theme.json`).
`compositor.py` draws frame N of scene S from the resolved spec, using the drawing functions
in `primitives.py` and the caption grouping and font fitting in `text.py`.

`timeline.py` puts everything that happens into one time-ordered list. `audio.py` mixes
narration, the theme's sound cues and a synthesised music bed, ducks the music under the
voice and brings the result to -14 LUFS with true peak under -1 dB. `loudness.py` measures
that (ITU-R BS.1770) and `wav.py` reads and writes the files.

Tests: `make test` runs the unit tests. `make render-test` compares golden frames and
checks the audio mix with FFmpeg's loudness meter inside the worker image, and `make render-golden-update` approves the frames as drawn now.
