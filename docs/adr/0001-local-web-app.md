# ADR 1: Local web app on the owner's PC

## Status

Accepted, 2026-11-11. Design document decisions D1, D2 and D12.

## Context

The studio has one user, the owner. It needs his RTX 3090 for clip generation and his own
signed-in command line tools for planning in subscription mode. The repository is also a
public portfolio project, so a reviewer must be able to run it with no GPU, no API keys and
no accounts.

## Decision

The studio is a web application that runs on one PC with Docker Compose and is used in the
browser at `http://localhost:3000`. It has four services: `web` (Next.js), `api` (FastAPI),
`worker` and `db` (Postgres 16). Every published port binds to `127.0.0.1`. There are no
user accounts. Access from a phone on the home network is optional, off by default, and
when switched on requires a password on every page and API route.

## Consequences

- No authentication, tenancy or hosting work in v1, and no personal data to protect.
- Secrets exist only in the owner's `.env` file. The repository holds placeholders.
- A browser interface instead of a desktop app means the same screens work on a phone.
- `docker compose up` is the whole installation, for the owner and for a reviewer.
- The loopback binding is a security boundary, so a test fails the build if any service
  publishes a port more widely.
- Nothing is reachable from outside the PC, so any future remote use needs real
  authentication first.

## Alternatives considered

- **Hosted service.** Needs accounts, a public address, a GPU in the cloud or a tunnel to
  the PC, and running costs. None of that helps a single owner.
- **Desktop application.** Packaging, signing and updates for every platform, and no phone
  access, for no gain over a browser tab.
- **Command line tool only.** The owner approves plans, assets and videos by looking at
  them. That needs an interface.
