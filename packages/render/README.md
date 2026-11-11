# packages/render

The deterministic render engine: resolver, timeline, primitives, the `night_scrolls` theme,
compositor, audio and encode. Pure Python with FFmpeg, CPU only.

Rule: no network access anywhere in this package. The same resolved spec and seed always
render the same frames.

So far: `resolver.py` turns an authored spec plus voice timings into a resolved spec with
absolute times, and reports every problem it finds with its location. `theme/` holds the
`night_scrolls` theme: its artwork, sounds and fonts, what it can draw
(`capabilities.json`) and where things go (`theme.json`).
