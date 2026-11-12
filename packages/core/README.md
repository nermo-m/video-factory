# packages/core

Shared domain code: database models, the pipeline state machine, the job queue and the
storage interface. No web framework and no vendor SDK is imported here.

The pipeline is three modules. `stages.py` holds the rules: the order of states, the
jobs each state creates and which states are gates. `stale.py` works out which scenes an
edit of the spec makes stale. Both are pure. `pipeline.py` applies them on the database:
advance, approve, reject, re-run, and `job_succeeded`, which the worker calls when it
stores a result.
