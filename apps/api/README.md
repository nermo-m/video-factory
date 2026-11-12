# apps/api

The FastAPI service: REST API under `/api/v1`, validation, the pipeline state machine,
job enqueueing and file serving. It never runs generation work itself.

So far: health, settings, providers with usage and budgets, and the episode routes
(lifecycle, spec versions, diff, revision, renders). `files.py` serves stored media below
the data folder with range requests: only media types, and never a path that leaves the
folder.
