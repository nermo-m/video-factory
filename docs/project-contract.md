# Project contract

The owner's project standard asks for an explicit scope and colour decision at project
start. The owner works unsupervised on this project, so the answers below were derived from
the design document (v2.6) by the implementing agent on 2026-11-11 instead of by interview
(see `docs/decisions-log.md`, D-007). The owner can correct any line. Identifiers follow
the standard.

## Solution families

| ID | Family | Enabled | Basis |
| --- | --- | --- | --- |
| S1 | Public website | No | Local app only (D1) |
| S2 | Web application | Yes | Next.js interface (D2, section 11) |
| S3 | Backend/API service | Yes | FastAPI under `/api/v1` (section 10) |
| S4 | Mobile application | No | Responsive web only (D12) |
| S5 | Desktop application | No | |
| S6 | CLI/developer tool | No | The Makefile and host bridge are tooling, not a product |
| S7 | Library/SDK | No | Nothing is published as a package |
| S8 | Automation/workflow | Yes | Job pipeline, critic and producer agents (sections 4, 6.1) |
| S9 | Integration/connector | Yes | Adapters for ComfyUI, the CLI bridge and model APIs (3.3) |
| S10 | Data/analytics platform | No | Out of scope for v1 |
| S11 | AI/ML system | Yes | Planner skills and agents |
| S12 | Infrastructure/platform | No | Docker Compose on one PC |
| S13 | Embedded/IoT | No | |
| S14 | Prototype | No | Portfolio-quality product (G6) |

## Cross-cutting capabilities

| ID | Capability | Enabled | Basis |
| --- | --- | --- | --- |
| P1 | Visual user interface | Yes | Section 11 |
| P2 | Public content/marketing | No | |
| P3 | Authenticated product area | Limited | Only the password session when `LAN_ACCESS=true` (NFR-02) |
| P4 | Administration interface | No | Single owner |
| P5 | Multiple languages | No | English only (D5) |
| P6 | Formal accessibility deliverables | Yes | WCAG 2.1 AA with automated axe checks (UX-04, UX-05) |
| P7 | Offline operation and sync | No | |
| P8 | Search and filtering | Yes | Filters on Videos, Library and Jobs |
| P9 | Reports, dashboards, exports | Limited | Export pack and cost display, no reporting module |
| B1 | Authentication | Limited | One shared password, only with `LAN_ACCESS=true` |
| B2 | Roles and permissions | No | |
| B3 | Tenant separation | No | |
| B4 | Payments | No | |
| B5 | Scheduling or booking | No | |
| B6 | Notifications | Limited | In-product bell only |
| B7 | Files and media | Yes | Storage adapter, uploads, renders (D9) |
| B8 | Collaboration, approvals | Limited | Owner approval gates and review comments, single user |
| B9 | Real-time updates | No | Polling every 2 seconds, server-sent events later (3.2) |
| B10 | Audit/history | Yes | Spec versions, reviews, agent traces, model calls |
| B11 | Import or synchronization | No | |
| D1 | Persistent datastore | Yes | Postgres 16 |
| D2 | API | Yes | Internal, OpenAPI with a generated client |
| D3 | External integrations | Yes | ComfyUI, CLI bridge, Anthropic and OpenAI APIs |
| D4 | Background processing | Yes | Postgres-backed job queue with retries (D8, 4.3) |
| D5 | Explicit cache | No | |
| D6 | Durable event-driven architecture | No | |
| D7 | Analytics/telemetry | No | Out of scope. Provider usage is domain data, not telemetry |
| D8 | Sensitive or regulated data | No | No personal data. Secrets only in environment variables |
| D9 | AI-assisted behaviour | Yes | |
| O1 | Automated tests | Yes | Section 14.1 |
| O2 | Continuous integration | Yes | Section 14.2 |
| O3 | Automated delivery | Limited | Images to the container registry, no server deployment |
| O4 | Containers | Yes | Docker Compose |
| O5 | Infrastructure as code | No | |
| O6 | Logs, metrics, traces, alerts | Limited | Structured JSON logs (NFR-03), no metrics or alerting |
| O7 | Backups and recovery | Yes | `make backup` and `make restore` (NFR-05) |
| O8 | Performance verification | Limited | Render speed measured (RN-11), no load testing |
| O9 | Security review | Limited | Secret scan, dependency audit and CodeQL, no formal threat model |
| O10 | Documentation | Yes | README, architecture, GPU setup, ADRs |

## Family modules

| Group | Enabled | Not enabled |
| --- | --- | --- |
| Web | W2 server rendering (framework default), W8 purposeful motion with reduced-motion support | W1 search-engine discoverability, W3 pure single-page app, W4 content management, W5 progressive web app, W6 public forms, W7 commerce, W9 legacy browsers |
| API | API1 REST/JSON, API5 durable async jobs with retries | API2 GraphQL, API3 RPC, API4 webhooks, API6 service identity, API7 public versioning policy |
| Automation | A1 scheduled execution (limit check every 10 minutes), A3 human approval gates, A4 idempotent jobs, A5 retries with backoff, A8 operator view (Jobs screen) | A2 webhook triggers, A6 credential rotation, A7 reconciliation |
| AI | AI2 generation, AI4 tool-using agents, AI5 human review (final review is always human), AI7 evaluations (critic evaluation set), AI8 prompt, model and version records, AI9 guardrails and adversarial tests, AI10 cost, limit and fallback controls | AI1 custom training, AI3 retrieval, AI6 dataset tracking |

## Colour decision

Taken from design doc section 11.1. The mockups win where they differ.

| Token | Value |
| --- | --- |
| Background | `#0B0F1A` |
| Surface | `#141A2A` |
| Raised | `#1B2336` |
| Border | `#243049` |
| Text | `#E8ECF4` |
| Muted text | `#93A0B8` |
| Accent (next action only, dark text `#1A1200` on it) | `#FF9610` |
| Info | `#5B9DFF` |
| Success, warning, danger | `#3CCB7F`, `#F5B83D`, `#FF6B6B` |

## Architecture and toolchain

Fixed by design doc section 2: Next.js with TypeScript and Tailwind, FastAPI, Postgres 16,
one worker service, Docker Compose, a Python render engine with FFmpeg. Python tooling is
uv, Ruff, mypy and pytest. Node tooling is pnpm and ESLint.

## Risks, assumptions and deferred items

- Risks R1 to R10 are in design doc section 17.
- Everything in "Out of scope for v1" and section 18 is deferred.
- The implementation plan is the build board, mirrored per milestone in `docs/plan/`.
