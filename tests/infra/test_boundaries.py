"""Package boundaries from the build rules (design doc section 16, rule 5):

* No vendor SDK calls outside packages/adapters/.
* No network calls in packages/render/.

The boundaries are rules, not packaging walls (ADR 6), so this test is what enforces them.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SOURCE_ROOTS = ("apps", "packages", "scripts", "tools")

# SDKs of the external providers this project talks to.
VENDOR_SDKS = frozenset({"anthropic", "openai", "kokoro_onnx", "onnxruntime", "comfy", "comfyui"})
# Anything that can open a network connection.
NETWORK_MODULES = frozenset(
    {
        "aiohttp",
        "ftplib",
        "http",
        "httpx",
        "httpx2",
        "requests",
        "smtplib",
        "socket",
        "ssl",
        "urllib",
        "urllib3",
        "websockets",
    }
)


def python_files(*roots: str) -> list[Path]:
    files: list[Path] = []
    for root in roots:
        files.extend(
            path
            for path in (ROOT / root).rglob("*.py")
            if "node_modules" not in path.parts and ".venv" not in path.parts
        )
    return sorted(files)


def imported_modules(source: str) -> set[str]:
    """Top-level names of every module a Python source imports."""
    modules: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            modules.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            modules.add(node.module.split(".")[0])
    return modules


def imports_of(path: Path) -> set[str]:
    return imported_modules(path.read_text(encoding="utf-8"))


def test_the_import_scanner_sees_every_import_form() -> None:
    source = (
        "import openai\n"
        "import urllib.request as request\n"
        "from anthropic import Anthropic\n"
        "from http.client import HTTPConnection\n"
        "from . import sibling\n"
        "def later():\n"
        "    import socket\n"
    )

    assert imported_modules(source) == {"openai", "urllib", "anthropic", "http", "socket"}


def test_rule5_no_vendor_sdk_is_imported_outside_the_adapters() -> None:
    offenders = [
        f"{path.relative_to(ROOT).as_posix()}: {', '.join(sorted(found))}"
        for path in python_files(*SOURCE_ROOTS)
        if "adapters" not in path.relative_to(ROOT).parts[:2]
        and (found := imports_of(path) & VENDOR_SDKS)
    ]

    assert offenders == [], "vendor SDKs may only be imported in packages/adapters/"


def test_rule5_the_render_package_makes_no_network_calls() -> None:
    offenders = [
        f"{path.relative_to(ROOT).as_posix()}: {', '.join(sorted(found))}"
        for path in python_files("packages/render")
        if (found := imports_of(path) & (NETWORK_MODULES | VENDOR_SDKS))
    ]

    assert offenders == [], "packages/render/ must not import anything that opens a connection"


@pytest.mark.parametrize("package", ["packages/core", "packages/render"])
def test_shared_packages_do_not_import_the_apps(package: str) -> None:
    offenders = [
        path.relative_to(ROOT).as_posix()
        for path in python_files(package)
        if "apps" in imports_of(path)
    ]

    assert offenders == [], f"{package} is shared code and must not depend on apps/"
