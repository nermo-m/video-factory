"""Tests for scripts/check_commits.py: conventional commit messages (design doc 14.3)."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from scripts import check_commits


@pytest.mark.parametrize(
    "subject",
    [
        "feat: add the resolver",
        "fix(render): keep captions inside the safe area",
        "chore(deps): bump fastapi from 0.162.4 to 0.163.0",
        "feat!: change the spec format",
        "refactor(core/queue): split claim and heartbeat",
        "docs: record ADR 3",
        "test: cover the stale heartbeat case",
        "ci: add the render job",
        "build: pin the worker image",
        "perf: cache glyph outlines",
        "revert: feat: add the resolver",
        "style: format",
    ],
)
def test_conventional_subjects_pass(subject: str) -> None:
    assert check_commits.check_subject(subject) is None


@pytest.mark.parametrize(
    ("subject", "reason"),
    [
        ("Add the resolver", "must start with a type"),
        ("feature: add the resolver", "must start with a type"),
        ("feat add the resolver", "must start with a type"),
        ("feat:add the resolver", "must start with a type"),
        ("feat: ", "must start with a type"),
        ("Feat: add the resolver", "must start with a type"),
        ("feat(Render): add", "must start with a type"),
        ("feat: " + "x" * 100, "longer than 100 characters"),
        ("", "is empty"),
    ],
)
def test_other_subjects_fail_with_a_reason(subject: str, reason: str) -> None:
    problem = check_commits.check_subject(subject)

    assert problem is not None
    assert reason in problem


def test_only_the_first_line_is_the_subject() -> None:
    message = "feat: add the resolver\n\nA body may say anything. Even: not conventional."

    assert check_commits.check_subject(message) is None


def test_title_mode_checks_a_pull_request_title(capsys: pytest.CaptureFixture[str]) -> None:
    assert check_commits.main(["--title", "feat: add the resolver"]) == 0
    assert check_commits.main(["--title", "Add the resolver"]) == 1
    assert "pull request title" in capsys.readouterr().err


def git(repo: Path, *args: str) -> str:
    result = subprocess.run(  # noqa: S603 - fixed git commands on a temporary repository
        ["git", *args],  # noqa: S607 - git comes from PATH, as everywhere in this project
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    git(tmp_path, "init", "--quiet", "--initial-branch", "main")
    git(tmp_path, "config", "user.name", "Test")
    git(tmp_path, "config", "user.email", "test@example.invalid")
    git(tmp_path, "config", "commit.gpgsign", "false")
    return tmp_path


def commit(repo: Path, subject: str) -> str:
    (repo / "file.txt").write_text(subject, encoding="utf-8")
    git(repo, "add", "file.txt")
    git(repo, "commit", "--quiet", "--no-verify", "--message", subject)
    return git(repo, "rev-parse", "HEAD")


def test_range_mode_passes_when_every_commit_is_conventional(repo: Path) -> None:
    base = commit(repo, "chore: initial commit")
    commit(repo, "feat: add the resolver")
    commit(repo, "fix: handle an empty spec")

    assert check_commits.main(["--range", f"{base}..HEAD", "--repo", str(repo)]) == 0


def test_range_mode_names_each_bad_commit(repo: Path, capsys: pytest.CaptureFixture[str]) -> None:
    base = commit(repo, "chore: initial commit")
    commit(repo, "feat: add the resolver")
    bad = commit(repo, "WIP stuff")

    assert check_commits.main(["--range", f"{base}..HEAD", "--repo", str(repo)]) == 1
    error = capsys.readouterr().err
    assert bad[:7] in error
    assert "WIP stuff" in error
    assert "add the resolver" not in error


def test_range_mode_fails_on_an_unknown_range(
    repo: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    commit(repo, "chore: initial commit")

    assert check_commits.main(["--range", "nowhere..HEAD", "--repo", str(repo)]) == 1
    assert "could not read the commits" in capsys.readouterr().err


def test_nothing_to_check_is_an_error(capsys: pytest.CaptureFixture[str]) -> None:
    assert check_commits.main([]) == 2
    assert "--range" in capsys.readouterr().err
