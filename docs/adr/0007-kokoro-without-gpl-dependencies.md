# ADR 7: The Kokoro voice runs on ONNX Runtime, with espeak-ng as a separate program

## Status

Accepted, 2026-11-12. Fills a gap in the design document, see question Q-020.

## Context

The design document names the voice: "Kokoro ONNX in the worker", local, English only, no
key and no GPU (D5, section 3.3). It does not name a library. The usual way to run the
model is the `kokoro-onnx` package.

`kokoro-onnx` is MIT licensed, but it cannot be installed without `phonemizer` and
`espeakng-loader`. `phonemizer` is GPL-3.0, and it loads the espeak-ng library, also
GPL-3.0, into the Python process. The model's own phoneme library, `misaki`, has the same
two packages behind its English mode, plus `num2words` (LGPL). The build rules forbid
"installing a dependency with a licence that is not permissive", and this repository is
MIT licensed and public.

A voice still needs text turned into phonemes, and espeak-ng is the tool the model's
English voices were prepared with.

## Decision

The adapter in `packages/adapters/tts/` runs the model file directly with ONNX Runtime
(MIT). Around it, this project has its own small pieces: the token table of the model
(Apache-2.0, copied from the model's `config.json`), the choice of style row, splitting of
very long passages, WAV output, pause detection and the word timing estimate.

Phonemes come from the `espeak-ng` program. The worker image installs it from Debian, and
the adapter starts it as a separate process for each run of words, with an argument list
and no shell. Nothing from espeak-ng is imported, linked or copied into this repository.
This is the arrangement the design already requires for FFmpeg, which is GPL in the builds
that encode H.264.

espeak-ng writes standard phonetic symbols. They are rewritten into the alphabet the model
was trained on, following the mapping published in `misaki` (Apache-2.0).

No GPL or LGPL package is in `pyproject.toml` or `uv.lock`.

## Consequences

- The licence rule holds: every Python dependency is permissive.
- The worker image contains a GPL program, as it also will with FFmpeg. An image that
  includes GPL programs must keep their licence texts, which the Debian packages do.
- The real voice runs only where espeak-ng is installed: in the worker image. On a
  developer's Windows or macOS machine the unit tests use a stand-in for the model and the
  program, and `make voice-test` runs the real voice inside the image.
- About 850 lines of adapter code are ours to maintain instead of a package's. They are
  checked against the real model file by tests, and the model file is pinned by checksum,
  so its inputs cannot change unnoticed.
- Features of `kokoro-onnx` that are not needed are not there: streaming, voice blending,
  other languages.
- The pronunciation dictionary is exact: a dictionary word's phonemes go to the model
  untouched, without passing through espeak-ng.

## Alternatives considered

- **Use `kokoro-onnx` as it is.** The least code. It makes a GPL-3.0 library part of the
  worker process and of the dependency list of an MIT repository, which the build rules
  rule out.
- **Use `misaki` for phonemes.** It is the model's own library and sounds slightly better
  on common words, but its English mode imports an LGPL package and falls back to the same
  GPL packages for unknown words.
- **Write a phoneme dictionary lookup of our own.** Fully permissive, but any word outside
  the dictionary, every name and every number would need handling that espeak-ng already
  does well.
- **Run a ready-made Kokoro server in its own container.** Keeps GPL code out of the worker
  process too, but adds a fifth service, a network hop and an HTTP contract for something
  that is one function call, and the design asks for the voice inside the worker.
