# packages/adapters

Every external tool sits behind an adapter here: language model, image, clip, voice and
storage. Each adapter ships with a mock twin in the same pull request.

Rule: this is the only place a vendor SDK may be imported.

So far: `storage/` (local folder, the v1 storage), `clip/probe.py` (is ComfyUI reachable),
`tts/` (the voice) and `llm/` (the language model).

## Provider mode (`factory.py`, `paid.py`)

`Adapters` in `factory.py` is built for each job from the settings and the owner's "Use
paid APIs" switch. It picks by `PROVIDER_MODE` and never falls back from one mode to
another. Every adapter that calls a paid API builds on `PaidApiAdapter` in `paid.py`:
it refuses to start unless the mode is `api` and the switch is on, and it keeps the key
out of anything that could be printed. A test fails when a module imports a paid SDK
without it.

## Language model (`llm/`)

One request is one skill call: a prompt in, a text or a JSON document out, with tokens,
cost, latency and, for research, the passages the model really retrieved.

| File | What it does |
| --- | --- |
| `base.py` | `LLMAdapter`, `LLMRequest`, `LLMResponse`, and the JSON parsing of an answer |
| `recorded.py` | The twin for demo mode: replays `samples/recordings/<skill>.json` and checks it against the skill's schema and version |
| `anthropic_api.py` | Claude through the paid API, with web search for research. Builds on `PaidApiAdapter` |

`Adapters.llm()` picks by mode: recordings in `demo`, the Anthropic API in `api` (only
with the owner's switch on), and in `subscription` an error that says the host bridge is
not built yet. Failures come back in the error classes the job queue acts on. The
Anthropic adapter is tested through the real SDK with a mock transport, so no test can
reach the network. Its check against the live API is card VFS-64.

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
