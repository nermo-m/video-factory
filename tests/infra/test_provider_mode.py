"""Guard tests for the provider mode (design doc section 3.4, FR-28).

* "The mode never changes by itself." Nothing in the source can change it: settings are
  frozen, and no code assigns the mode, passes a different one on, or writes the
  environment.
* "API adapters refuse to start." A paid SDK may only be imported in a module that builds
  on PaidApiAdapter, whose constructor is the refusal.

These are scans of the source, so they also hold for code that is written later.
"""

from __future__ import annotations

import ast
import dataclasses
from pathlib import Path

import pytest

from packages.core.settings import Settings
from tests.infra.test_boundaries import ROOT, SOURCE_ROOTS, imported_modules, python_files

PAID_SDKS = frozenset({"anthropic", "openai"})
# The one place that reads PROVIDER_MODE from the environment and builds Settings from it.
SETTINGS_MODULE = "packages/core/settings.py"


def source_files() -> list[Path]:
    """Every Python file that ships, without tests."""
    return [path for path in python_files(*SOURCE_ROOTS) if "tests" not in path.parts]


def mode_changes(source: str) -> list[str]:
    """Every place in a source text that sets or passes on a provider mode."""
    found: list[str] = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Assign | ast.AugAssign | ast.AnnAssign):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            for target in targets:
                if isinstance(target, ast.Attribute) and target.attr == "provider_mode":
                    found.append(f"line {node.lineno}: assigns .provider_mode")
        if isinstance(node, ast.Call):
            for keyword in node.keywords:
                # Handing the loaded mode on unchanged (`provider_mode=settings.provider_mode`)
                # is reading it. Anything else is choosing one.
                same = isinstance(keyword.value, ast.Attribute) and (
                    keyword.value.attr == "provider_mode"
                )
                if keyword.arg == "provider_mode" and not same:
                    found.append(f"line {node.lineno}: passes provider_mode=")
            called = ast.unparse(node.func)
            written = " ".join(ast.unparse(argument) for argument in node.args)
            sets = called.endswith("setattr__") or called == "setattr"
            if sets and "provider_mode" in written:
                found.append(f"line {node.lineno}: calls {called} on provider_mode")
    return found


def environment_writes(source: str) -> list[str]:
    """Every place in a source text that changes the process environment."""
    found: list[str] = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Assign | ast.Delete):
            for target in node.targets:
                if isinstance(target, ast.Subscript) and "environ" in ast.unparse(target.value):
                    found.append(f"line {node.lineno}: writes os.environ")
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            owner = ast.unparse(node.func.value)
            if node.func.attr == "putenv" or (
                "environ" in owner and node.func.attr in {"update", "setdefault", "pop", "clear"}
            ):
                found.append(f"line {node.lineno}: calls {owner}.{node.func.attr}")
    return found


def test_the_scanners_see_what_they_are_meant_to_see() -> None:
    planted = (
        "import os\n"
        "settings.provider_mode = 'api'\n"
        "other = replace(settings, provider_mode='api')\n"
        "setattr(settings, 'provider_mode', 'api')\n"
        "os.environ['PROVIDER_MODE'] = 'api'\n"
        "os.environ.setdefault('PROVIDER_MODE', 'api')\n"
        "os.putenv('PROVIDER_MODE', 'api')\n"
    )

    assert len(mode_changes(planted)) == 3
    assert len(environment_writes(planted)) == 3
    assert mode_changes("mode = settings.provider_mode\n") == []
    assert mode_changes("Response(provider_mode=settings.provider_mode)\n") == []
    assert environment_writes("value = os.environ.get('PROVIDER_MODE')\n") == []


def test_fr28_no_code_path_changes_the_provider_mode() -> None:
    offenders = {
        path.relative_to(ROOT).as_posix(): found
        for path in source_files()
        if path.relative_to(ROOT).as_posix() != SETTINGS_MODULE
        and (found := mode_changes(path.read_text(encoding="utf-8")))
    }

    assert offenders == {}, "the provider mode is set once, from the environment, at start-up"


def test_fr28_no_code_writes_the_environment() -> None:
    offenders = {
        path.relative_to(ROOT).as_posix(): found
        for path in source_files()
        if (found := environment_writes(path.read_text(encoding="utf-8")))
    }

    assert offenders == {}, "a changed environment could change the mode of a later start"


def test_fr28_the_mode_is_read_from_the_environment_in_one_place() -> None:
    readers = [
        path.relative_to(ROOT).as_posix()
        for path in source_files()
        if '"PROVIDER_MODE"' in path.read_text(encoding="utf-8")
    ]

    assert readers == [SETTINGS_MODULE]


def test_fr28_settings_cannot_be_changed_after_they_are_loaded() -> None:
    settings = Settings(database_url="postgresql+psycopg://vfs:secret@db:5432/vfs")

    with pytest.raises(dataclasses.FrozenInstanceError):
        settings.provider_mode = "api"  # type: ignore[misc]


def test_fr28_a_paid_sdk_is_only_imported_next_to_the_guard() -> None:
    offenders = []
    for path in python_files(*SOURCE_ROOTS):
        source = path.read_text(encoding="utf-8")
        if not imported_modules(source) & PAID_SDKS:
            continue
        bases = {
            ast.unparse(base)
            for node in ast.walk(ast.parse(source))
            if isinstance(node, ast.ClassDef)
            for base in node.bases
        }
        if not any(base.endswith("PaidApiAdapter") for base in bases):
            offenders.append(path.relative_to(ROOT).as_posix())

    assert offenders == [], "a module that imports a paid SDK must build on PaidApiAdapter"
