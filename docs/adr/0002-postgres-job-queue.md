# ADR 2: Postgres as the job queue

## Status

Accepted, 2026-11-11. Design document decision D8 and section 4.3.

## Context

Planning, image generation, voice, rendering and export are slow and must survive a
restart of any container. Some jobs need the GPU, of which there is exactly one. The whole
system runs on one PC for one user, so throughput is tens of jobs per episode, not
thousands per second.

## Decision

Jobs are rows in the `job` table of the same Postgres that holds the rest of the state.

- A worker claims a job with `SELECT ... FOR UPDATE SKIP LOCKED`, filtered by the job's
  tag, `cpu` or `gpu`.
- At most one `gpu` job runs at a time. Gpu claims take a transaction-scoped advisory lock
  and are refused while any gpu job is running.
- A running job sends a heartbeat every 10 seconds. After 60 seconds of silence it returns
  to the queue.
- A job gets at most three attempts, with waits of 10 and 60 seconds between them.
- The job's start time identifies the claim, so a worker that was replaced cannot
  overwrite the new result.
- Every job is idempotent: its output path comes from a hash of its type and input.

## Consequences

- One datastore to run, back up and restore. An episode's state and its jobs change in the
  same transaction, so they cannot disagree.
- The guarantees come from row locks, so they are tested against a real Postgres, not a
  stand-in.
- Polling once a second is fast enough here. The interface also polls, every 2 seconds.
- Failed jobs stay in the table with their error class and message, which is what the Jobs
  screen shows.
- If the worker ever moves to a second machine, it only needs a database connection.

## Alternatives considered

- **Redis with a queue library (Celery, RQ, Dramatiq).** A second service to run and back
  up, and state split across two stores, for throughput this system will never need.
- **A message broker (RabbitMQ, Kafka).** The same cost, more of it.
- **In-process background tasks.** Lost on restart, and no way to cap the GPU at one job
  across processes.
- **`LISTEN` and `NOTIFY` instead of polling.** Saves at most a second per job and adds a
  reconnect path that needs its own tests. It can be added later without changing the table.
