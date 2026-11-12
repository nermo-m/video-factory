# Architecture decision records

One record per decision that would be expensive to change later. Each says what was
decided, why, what follows from it and what was turned down. Smaller choices are in the
[decisions log](../decisions-log.md), and open points about the design are in
[questions](../questions.md).

| # | Decision |
| --- | --- |
| 1 | [Local web app on the owner's PC](0001-local-web-app.md) |
| 2 | [Postgres as the job queue](0002-postgres-job-queue.md) |
| 3 | [GPU outside Docker](0003-gpu-outside-docker.md) |
| 4 | [Every external tool behind an adapter with a mock twin](0004-adapter-pattern.md) |
| 5 | [Spec-driven rendering](0005-spec-driven-rendering.md) |
| 6 | [One Python project, imports mirror folder paths](0006-python-packaging.md) |
| 7 | [The Kokoro voice runs on ONNX Runtime, with espeak-ng as a separate program](0007-kokoro-without-gpl-dependencies.md) |

## Adding a record

Copy the section headings of an existing record, give it the next number, and add it to
the table above. A test checks the headings and the table. A record is never rewritten
after it is accepted: a later decision that changes it gets its own record and says which
one it replaces. A departure from the design document is titled "Deviation: <topic>" and
quotes the requirement it departs from.
