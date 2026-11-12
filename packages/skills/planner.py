"""The planner service (design doc section 6).

A skill is a folder under `packages/skills/<name>/`:

    SKILL.md             instructions for the model, with name and version on top
    input.schema.json    what the skill is given
    output.schema.json   what it must answer with
    examples/            an input and the answer wanted for it
    tests/               its tests

`run_skill` is one skill call: it checks the input, asks the language model, checks the
answer against the output schema and the skill's own rules, and applies the retry rule of
section 4.4: an answer that fails is asked for once more with the problems appended, and
then the job fails as invalid output.

The planner never chooses a model or a mode. It is handed an `LLMAdapter`.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from functools import cache
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

from packages.adapters.llm.base import LLMAdapter, LLMRequest, LLMResponse
from packages.core import schemas
from packages.core.enums import ErrorClass
from packages.core.queue import InvalidOutputError, JobError

SKILLS_DIR = Path(__file__).resolve().parent
SKILL_NAMES = ("brief", "research", "script", "direct", "assets", "package", "revise")
MAX_PROBLEMS_SHOWN = 12

# A skill's own rules: problems with an answer that the schema cannot express.
Check = Callable[[Mapping[str, Any], dict[str, Any], LLMResponse], list[str]]
# A skill's own clean-up of an answer before it is checked, for example dropping what
# has no source. Returns the answer to keep and a note per thing it removed.
Repair = Callable[[dict[str, Any], LLMResponse], tuple[dict[str, Any], list[str]]]


@dataclass(frozen=True)
class Skill:
    name: str
    version: str
    instructions: str
    input_schema: dict[str, Any]
    output_schema: dict[str, Any]
    web_search: bool = False
    effort: str | None = None
    # Set when the answer is one of the shared schemas in `schemas/`.
    shared_output: str | None = None


@dataclass(frozen=True)
class SkillResult:
    output: dict[str, Any]
    skill: str
    skill_version: str
    # Every model call that was made: one, or two after a corrective retry.
    calls: tuple[LLMResponse, ...]
    # What the skill's clean-up removed from the answer, in plain words.
    removed: tuple[str, ...] = ()


def _schema(path: Path) -> tuple[dict[str, Any], str | None]:
    """A skill's schema file, and the name of the shared schema it stands for, if any.

    `{"$ref": "brief.schema.json"}` stands for a shared schema. The model is sent that
    schema as one self-contained document.
    """
    loaded: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    reference = loaded.get("$ref")
    if isinstance(reference, str) and reference.endswith(".schema.json"):
        name = reference.removesuffix(".schema.json")
        return schemas.bundled_schema(name), name
    return loaded, None


@cache
def load_skill(name: str) -> Skill:
    """Read a skill folder. Raises ValueError when the folder is not a complete skill."""
    if name not in SKILL_NAMES:
        raise ValueError(f"There is no skill named '{name}'. Known: {', '.join(SKILL_NAMES)}.")
    folder = SKILLS_DIR / name
    text = (folder / "SKILL.md").read_text(encoding="utf-8")
    if not text.startswith("---\n") or "\n---\n" not in text[4:]:
        raise ValueError(f"{name}/SKILL.md must start with a block between two '---' lines.")
    head, instructions = text[4:].split("\n---\n", 1)
    fields = dict(line.split(":", 1) for line in head.splitlines() if ":" in line)
    fields = {key.strip(): value.strip().strip('"') for key, value in fields.items()}
    if fields.get("name") != name or not fields.get("version"):
        raise ValueError(f"{name}/SKILL.md must name the skill '{name}' and give its version.")
    output_schema, shared = _schema(folder / "output.schema.json")
    return Skill(
        name=name,
        version=fields["version"],
        instructions=instructions.strip(),
        input_schema=_schema(folder / "input.schema.json")[0],
        output_schema=output_schema,
        shared_output=shared,
        web_search=fields.get("web_search") == "true",
        effort=fields.get("effort") or None,
    )


def _problems(schema: Mapping[str, Any], document: Any) -> list[str]:
    validator = Draft202012Validator(
        dict(schema), format_checker=Draft202012Validator.FORMAT_CHECKER
    )
    errors = sorted(validator.iter_errors(document), key=lambda error: list(error.absolute_path))
    return [
        f"{'/'.join(str(part) for part in error.absolute_path) or 'the document'}: {error.message}"
        for error in errors
    ]


def render_prompt(inputs: Mapping[str, Any]) -> str:
    return "Input:\n" + json.dumps(inputs, ensure_ascii=False, indent=2)


def run_skill(
    llm: LLMAdapter,
    skill: Skill,
    inputs: Mapping[str, Any],
    *,
    check: Check | None = None,
    repair: Repair | None = None,
) -> SkillResult:
    """One skill call with validation and the single corrective retry."""
    wrong_input = _problems(skill.input_schema, dict(inputs))
    if wrong_input:
        raise JobError(
            f"The input of the skill '{skill.name}' is not valid: {'; '.join(wrong_input[:3])}",
            error_class=ErrorClass.BUG,
        )

    prompt = render_prompt(inputs)
    calls: list[LLMResponse] = []
    problems: list[str] = []
    for attempt in range(2):
        if attempt:
            listed = "\n".join(f"- {problem}" for problem in problems[:MAX_PROBLEMS_SHOWN])
            prompt = (
                f"{render_prompt(inputs)}\n\nYour previous answer was not accepted:\n{listed}\n"
                "Answer again with the complete corrected JSON document."
            )
        request = LLMRequest(
            skill=skill.name,
            skill_version=skill.version,
            prompt=prompt,
            system=skill.instructions,
            output_schema=skill.output_schema,
            web_search=skill.web_search,
            effort=skill.effort,
        )
        try:
            response = llm.complete(request)
        except InvalidOutputError as error:
            # The adapter could not even read a JSON document out of the answer.
            problems = [str(error)]
            continue
        calls.append(response)
        output = response.output
        if not isinstance(output, dict):
            problems = ["the answer is not a JSON object"]
            continue
        removed: list[str] = []
        if repair is not None:
            output, removed = repair(output, response)
        if skill.shared_output is not None:
            problems = [str(found) for found in schemas.validate(skill.shared_output, output)]
        else:
            problems = _problems(skill.output_schema, output)
        if not problems and check is not None:
            problems = check(inputs, output, response)
        if not problems:
            return SkillResult(
                output=output,
                skill=skill.name,
                skill_version=skill.version,
                calls=tuple(calls),
                removed=tuple(removed),
            )
    raise InvalidOutputError(
        f"The skill '{skill.name}' gave an answer that was not accepted, twice: "
        + "; ".join(problems[:3])
    )
