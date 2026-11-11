"""Check that commit subjects and pull request titles are conventional commits.

Design doc section 14.3: main has a linear history of conventional commits. Pull requests
are squash-merged, so the pull request title becomes the commit subject on main and is
checked too.

    python scripts/check_commits.py --range origin/main..HEAD
    python scripts/check_commits.py --title "feat: add the resolver"

Standard library only.
"""

from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path

TYPES = (
    "build",
    "chore",
    "ci",
    "docs",
    "feat",
    "fix",
    "perf",
    "refactor",
    "revert",
    "style",
    "test",
)
MAX_SUBJECT = 100

_PATTERN = re.compile(rf"^(?:{'|'.join(TYPES)})(?:\([a-z0-9][a-z0-9._/-]*\))?!?: \S.*$")


def check_subject(message: str) -> str | None:
    """Return what is wrong with the first line of a commit message, or None when it is fine."""
    lines = message.splitlines()
    subject = lines[0].rstrip() if lines else ""
    if not subject:
        return "the subject is empty"
    if not _PATTERN.match(subject):
        return (
            f"must start with a type ({', '.join(TYPES)}), an optional scope in brackets, "
            'a colon and a space, for example "fix(render): keep captions in the safe area"'
        )
    if len(subject) > MAX_SUBJECT:
        return f"the subject is longer than {MAX_SUBJECT} characters"
    return None


def _subjects(revision_range: str, repo: Path) -> list[tuple[str, str]] | None:
    git = shutil.which("git")
    if git is None:
        return None
    # A fixed argument list with no shell. The range is one argument, and
    # --end-of-options stops git from reading it as an option.
    result = subprocess.run(  # noqa: S603
        [git, "log", "--format=%h%x00%s", "--end-of-options", revision_range],
        cwd=repo,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        return None
    commits = []
    for line in result.stdout.splitlines():
        short_hash, _, subject = line.partition("\0")
        commits.append((short_hash, subject))
    return commits


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Check conventional commit subjects")
    parser.add_argument(
        "--range", dest="revision_range", help="commits to check, for example origin/main..HEAD"
    )
    parser.add_argument("--title", help="a pull request title to check")
    parser.add_argument("--repo", type=Path, default=Path.cwd(), help="repository folder")
    args = parser.parse_args(argv)

    if args.revision_range is None and args.title is None:
        sys.stderr.write("Nothing to check. Pass --range, --title or both.\n")
        return 2

    problems: list[str] = []
    if args.title is not None:
        problem = check_subject(args.title)
        if problem is not None:
            problems.append(f'pull request title "{args.title}": {problem}')

    checked = 0
    if args.revision_range is not None:
        commits = _subjects(args.revision_range, args.repo)
        if commits is None:
            sys.stderr.write(f"could not read the commits in {args.revision_range}\n")
            return 1
        checked = len(commits)
        for short_hash, subject in commits:
            problem = check_subject(subject)
            if problem is not None:
                problems.append(f'{short_hash} "{subject}": {problem}')

    if problems:
        sys.stderr.write("\n".join(problems) + "\n")
        return 1
    sys.stdout.write(f"commit messages are conventional ({checked} commit(s) checked)\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
