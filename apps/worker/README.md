# apps/worker

One process with two loops that claim jobs from the Postgres queue: a `cpu` loop with
configurable concurrency and a `gpu` loop fixed at one job at a time. Job handlers call
adapters and the render engine.

So far: the worker loops and a no-op job (M0), and `demo_render.py`, which renders the
bundled sample episode in one command (`make demo-render`): voice, resolve, render, format
checks. The job handlers that run the same steps through the queue arrive in M2.
