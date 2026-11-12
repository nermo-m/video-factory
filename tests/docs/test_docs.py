"""Keep the architecture document and the ADRs honest (build rule 9)."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from packages.core.enums import EpisodeState, JobStatus

ROOT = Path(__file__).resolve().parents[2]
ADR_DIR = ROOT / "docs" / "adr"
ARCHITECTURE = ROOT / "docs" / "architecture.md"

EXPECTED_ADRS = {
    "0001-local-web-app.md": "Local web app",
    "0002-postgres-job-queue.md": "Postgres",
    "0003-gpu-outside-docker.md": "GPU outside Docker",
    "0004-adapter-pattern.md": "adapter",
    "0005-spec-driven-rendering.md": "Spec-driven rendering",
    "0006-python-packaging.md": "Python",
    "0007-kokoro-without-gpl-dependencies.md": "Kokoro",
    "0008-host-bridge-for-the-command-line-tools.md": "host bridge",
    "0009-the-bridge-reads-claude-codes-streaming-output.md": "streaming output",
}
REQUIRED_SECTIONS = [
    "## Status",
    "## Context",
    "## Decision",
    "## Consequences",
    "## Alternatives considered",
]


def adr_files() -> list[Path]:
    return sorted(path for path in ADR_DIR.glob("[0-9][0-9][0-9][0-9]-*.md"))


def test_the_adrs_named_on_the_card_exist() -> None:
    assert {path.name for path in adr_files()} == set(EXPECTED_ADRS)


@pytest.mark.parametrize("name", sorted(EXPECTED_ADRS))
def test_every_adr_has_a_numbered_title_and_the_required_sections(name: str) -> None:
    text = (ADR_DIR / name).read_text(encoding="utf-8")
    number = int(name[:4])

    title = text.splitlines()[0]
    assert title.startswith(f"# ADR {number}: "), title
    assert EXPECTED_ADRS[name].lower() in title.lower()
    positions = [text.find(section) for section in REQUIRED_SECTIONS]
    assert all(position > 0 for position in positions), f"{name} is missing a section"
    assert positions == sorted(positions), f"{name} has its sections out of order"
    assert re.search(r"## Status\n\nAccepted, \d{4}-\d{2}-\d{2}\.", text), "status needs a date"


def test_the_index_lists_every_adr() -> None:
    index = (ADR_DIR / "README.md").read_text(encoding="utf-8")

    for path in adr_files():
        assert f"]({path.name})" in index, f"{path.name} is not in docs/adr/README.md"


def mermaid_blocks(text: str) -> list[str]:
    return re.findall(r"```mermaid\n(.*?)```", text, flags=re.DOTALL)


def test_the_state_machine_diagram_names_exactly_the_pipeline_states() -> None:
    blocks = mermaid_blocks(ARCHITECTURE.read_text(encoding="utf-8"))
    diagram = next(block for block in blocks if "stateDiagram" in block and "idea" in block)

    # Each transition line reads "from --> to", optionally followed by ": label".
    states: set[str] = set()
    for line in diagram.splitlines():
        transition = re.match(r"\s*(\[\*\]|[a-z_]+)\s*-->\s*(\[\*\]|[a-z_]+)", line)
        if transition:
            states.update(name for name in transition.groups() if name != "[*]")

    assert states == {state.value for state in EpisodeState}


def test_the_job_lifecycle_diagram_names_exactly_the_job_statuses() -> None:
    blocks = mermaid_blocks(ARCHITECTURE.read_text(encoding="utf-8"))
    diagram = next(block for block in blocks if "stateDiagram" in block and "queued" in block)

    for status in JobStatus:
        assert re.search(rf"\b{status.value}\b", diagram), f"{status.value} is missing"


def test_the_architecture_document_covers_every_component() -> None:
    text = ARCHITECTURE.read_text(encoding="utf-8")

    for component in ("web", "api", "worker", "db", "ComfyUI", "CLI bridge"):
        assert component in text
    for folder in ("apps/web", "apps/api", "apps/worker", "packages/core", "packages/adapters"):
        assert folder in text
    assert "host.docker.internal" in text
    assert "127.0.0.1" in text


def test_the_decisions_log_points_at_the_packaging_adr() -> None:
    log = (ROOT / "docs" / "decisions-log.md").read_text(encoding="utf-8")

    assert "adr/0006-python-packaging.md" in log
