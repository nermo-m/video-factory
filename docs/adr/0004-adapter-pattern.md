# ADR 4: Every external tool behind an adapter with a mock twin

## Status

Accepted, 2026-11-11. Design document goal G4 and sections 3.3 and 3.4.

## Context

The pipeline depends on tools that cost money, need a GPU or need the owner's accounts:
language models, an image model, Wan 2.2 through ComfyUI, a voice model and file storage.
The repository must run end to end for a reviewer who has none of them, and CI must never
spend money or need a secret.

## Decision

Each capability has an abstract interface in `packages/core` or `packages/adapters`, at
least one real implementation, and a mock that ships in the same pull request: language
model, image, clip, voice and storage. One setting, `PROVIDER_MODE`, chooses the set:
`demo` selects every mock, `subscription` uses the owner's plans through the host bridge,
and `api` uses paid APIs. No vendor SDK is imported outside `packages/adapters/`.

The mode never changes by itself. There is no fallback from a plan to a paid API, not on
errors, not on usage limits, not when keys happen to be present. API adapters start only
when `PROVIDER_MODE=api` and the "Use paid APIs" switch in Settings are both set.

## Consequences

- `PROVIDER_MODE=demo` completes the whole pipeline with no keys, no GPU and no accounts.
  CI, reviewers and all development use it.
- Mocks return recorded responses and bundled samples, so tests are deterministic.
- Swapping a provider touches one folder. The planner, the queue and the render engine do
  not know which provider answered.
- Every model call records who answered and how it was billed, in one place.
- A mock can drift from the real tool. Recorded responses are validated against the same
  schemas as live ones, and live runs on the owner's PC are a separate, manual test level.
- The interface must stay small enough to mock honestly. A feature only one vendor has
  does not belong in it.

## Alternatives considered

- **Call vendor SDKs where they are needed.** Less code at first, but no demo mode, tests
  that need keys, and vendor types spread through the code base.
- **Mock at the HTTP level only.** Keeps SDK calls everywhere and ties tests to wire
  formats that change with SDK versions.
- **Automatic fallback between providers.** Convenient, and exactly how an unattended run
  spends money the owner did not approve.
