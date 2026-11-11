# apps/worker

One process with two loops that claim jobs from the Postgres queue: a `cpu` loop with
configurable concurrency and a `gpu` loop fixed at one job at a time. Job handlers call
adapters and the render engine.

Arrives in M0 (worker loops and a no-op job).
