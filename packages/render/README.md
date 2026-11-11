# packages/render

The deterministic render engine: resolver, timeline, primitives, the `night_scrolls` theme,
compositor, audio and encode. Pure Python with FFmpeg, CPU only.

Rule: no network access anywhere in this package. The same resolved spec and seed always
render the same frames.

Arrives in M1.
