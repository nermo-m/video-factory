# apps/worker

One process with two loops that claim jobs from the Postgres queue: a `cpu` loop with
configurable concurrency and a `gpu` loop fixed at one job at a time. Job handlers call
adapters and the render engine.

So far:

- The worker loops and a no-op job (M0).
- `demo_render.py` renders the bundled sample episode in one command (`make demo-render`):
  voice, resolve, render, format checks.
- `handlers/plan.py`: the planning jobs, one skill call each.
- `handlers/pictures.py`: `gen.image` makes one picture and stores it as a version of its
  asset. `gen.clip` finishes without a clip until the ComfyUI adapter exists.
- `handlers/produce.py`: the same steps as `demo_render.py`, as queued jobs. `gen.voice`
  speaks one scene, `render.scene` encodes one scene, `render.join` mixes, joins, checks
  the format and stores the draft render. Scene files live in `episodes/<id>/scenes` below
  the data folder and are kept between renders. Each joined video has its own folder.

The pipeline rests after the render (`LAST_BUILT_STATE` in `packages/core/stages.py`).
Pictures are the ones bundled with the sample episode until the asset library exists (M3).
