# packages/adapters

Every external tool sits behind an adapter here: language model, image, clip, voice and
storage. Each adapter ships with a mock twin in the same pull request.

Rule: this is the only place a vendor SDK may be imported.

So far: `storage/` (local folder, the v1 storage), `clip/probe.py` (is ComfyUI reachable)
and `tts/` (the voice).

## Voice (`tts/`)

`create_tts_adapter` returns the Kokoro voice when the model files from `make models` are
present, and its twin otherwise, which plays recordings bundled in `samples/voice/`.

| File | What it does |
| --- | --- |
| `base.py` | The `TTSAdapter` interface and the `Narration` it returns: WAV, length, word timings |
| `kokoro.py` | Runs the Kokoro model with ONNX Runtime, one passage per scene |
| `espeak.py` | Text to phonemes through the `espeak-ng` program, started as a separate process |
| `pronunciation.py` | The channel's pronunciation dictionary: whole words, any case |
| `timings.py` | Word timing estimate from the pauses measured in the audio |
| `audio.py` | WAV in and out, pause detection |
| `samples.py` | The twin: bundled recordings, found by text, voice and speed |

The real voice needs `espeak-ng`, which is in the worker image. `make voice-test` runs it
there. Why the `kokoro-onnx` package is not used: [ADR 7](../../docs/adr/0007-kokoro-without-gpl-dependencies.md).
