# schemas

JSON Schemas (draft 2020-12) for the pipeline documents. They are the contract between
planning and production: model output is validated against them before anything else reads
it, and unknown properties are rejected.

| Schema | Document |
| --- | --- |
| `episode_spec.schema.json` | The authored spec: what the planner and the owner write. Timings may be left out |
| `resolved_spec.schema.json` | The resolved spec: every event has an absolute time, every asset its file. The render engine reads only this |
| `brief.schema.json` | Output of the brief skill |
| `claims.schema.json` | Output of the research skill. Defines `claim`, which both specs reuse |
| `asset_manifest.schema.json` | Output of the assets skill |
| `package.schema.json` | Output of the package skill |

Rules worth knowing:

- Each scene kind (`title`, `scroll`, `stat`, `steps`, `outro`) has its own required fields.
- A cue has exactly one anchor: `word` (counted from zero), `scene_start_s`,
  `after_narration_s` or `at_s` (absolute).
- A statistic on screen points at a claim through `claim_id`.
- What a schema cannot check (a `claim_id` or `asset_id` that exists, unique scene ids) is
  checked by the resolver. What the theme can draw is checked against its
  `capabilities.json`.

`fixtures/<schema>/valid/` holds example documents. `fixtures/<schema>/invalid/` holds
documents that must be rejected, each wrapped with `why` and `error_at` (the JSON pointer
where the problem must be reported). Validate from Python with
`packages.core.schemas.validate(name, document)`.
