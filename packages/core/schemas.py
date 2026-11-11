"""Load the JSON Schemas in schemas/ and validate documents against them.

The schemas are the contract between planning and production (design doc section 5).
Model output is validated with them before anything else looks at it, and unknown
properties are rejected, so a drifting model cannot slip a typo past the renderer.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from functools import cache
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator, ValidationError
from referencing import Registry, Resource
from referencing.jsonschema import DRAFT202012

SCHEMA_DIR = Path(__file__).resolve().parents[2] / "schemas"
SCHEMA_NAMES = ("episode_spec", "resolved_spec", "brief", "claims", "asset_manifest", "package")


@dataclass(frozen=True)
class SchemaProblem:
    """One thing wrong with a document: where (a JSON pointer) and what."""

    path: str
    message: str

    def __str__(self) -> str:
        return f"{self.path or '(document)'}: {self.message}"


class SchemaValidationError(Exception):
    """A document does not match its schema. Carries every problem found."""

    def __init__(self, schema: str, problems: list[SchemaProblem]) -> None:
        listed = "\n".join(f"- {problem}" for problem in problems)
        super().__init__(f"The document is not a valid {schema}:\n{listed}")
        self.schema = schema
        self.problems = problems


def load_schema(name: str) -> dict[str, Any]:
    """The schema with this name, for example "episode_spec"."""
    if name not in SCHEMA_NAMES:
        raise KeyError(f"There is no schema named '{name}'. Known: {', '.join(SCHEMA_NAMES)}.")
    loaded: dict[str, Any] = json.loads(
        (SCHEMA_DIR / f"{name}.schema.json").read_text(encoding="utf-8")
    )
    return loaded


@cache
def _registry() -> Registry[Any]:
    """All six schemas by their $id, so they can refer to each other's definitions."""
    resources = [
        (f"{name}.schema.json", Resource.from_contents(load_schema(name), DRAFT202012))
        for name in SCHEMA_NAMES
    ]
    return Registry().with_resources(resources)


@cache
def _validator(name: str) -> Draft202012Validator:
    return Draft202012Validator(
        load_schema(name),
        registry=_registry(),
        # Formats such as date and date-time are enforced, not only documented.
        format_checker=Draft202012Validator.FORMAT_CHECKER,
    )


def _pointer(parts: Any) -> str:
    return "".join(f"/{part}" for part in parts)


def _problem(error: ValidationError) -> SchemaProblem:
    path = _pointer(error.absolute_path)
    if error.validator == "not" and error.validator_value == {}:
        # A property this kind of object may not have (the schemas mark it with
        # "not_allowed"). Say it plainly instead of quoting the schema.
        return SchemaProblem(path, f"'{error.absolute_path[-1]}' is not allowed here")
    return SchemaProblem(path, error.message)


def validate(name: str, document: Any) -> list[SchemaProblem]:
    """Every problem in the document, in document order. An empty list means it is valid."""
    errors = sorted(
        _validator(name).iter_errors(document),
        key=lambda error: [str(part) for part in error.absolute_path],
    )
    return [_problem(error) for error in errors]


def validate_or_raise(name: str, document: Any) -> None:
    """Raise SchemaValidationError when the document does not match its schema."""
    problems = validate(name, document)
    if problems:
        raise SchemaValidationError(name, problems)
