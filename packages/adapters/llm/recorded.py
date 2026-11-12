"""The language model mock: recorded responses for demo mode (design doc 3.3, FR-16).

Demo mode needs no key and no account. Every skill has one recording,
`samples/recordings/<skill>.json`, and it answers whatever the prompt is: the demo tells
one story, the sample episode. A recording looks like this:

    {"skill": "brief", "skill_version": "1.0", "output": {...},
     "input_tokens": 812, "output_tokens": 96, "sources": [], "searches": 0}

A recording is checked against the schema the caller asks for and against the skill's
version, so a recording that has fallen behind its skill fails loudly instead of feeding
the pipeline something stale.
"""

from __future__ import annotations

import json
import re
import time
from decimal import Decimal
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

from packages.adapters.llm.base import LLMRequest, LLMResponse, Source
from packages.core.enums import ErrorClass, Provider
from packages.core.queue import InvalidOutputError, JobError

RECORDED_MODEL = "recorded"
_SKILL_NAME = re.compile(r"[a-z][a-z0-9_]{0,39}")


class RecordedLLM:
    """LLMAdapter that replays recordings from a folder."""

    def __init__(self, folder: Path) -> None:
        self.folder = folder

    def complete(self, request: LLMRequest) -> LLMResponse:
        started = time.perf_counter()
        if not _SKILL_NAME.fullmatch(request.skill):
            raise JobError(
                f"'{request.skill}' is not a skill name (lower-case letters, digits, underscores).",
                error_class=ErrorClass.BUG,
            )
        path = self.folder / f"{request.skill}.json"
        if not path.is_file():
            raise JobError(
                f"Demo mode has no recorded response for the skill '{request.skill}': "
                f"{path.name} is missing from {self.folder.as_posix()}.",
                error_class=ErrorClass.BUG,
            )
        try:
            recording: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
            output = recording["output"]
            version = recording["skill_version"]
        except (json.JSONDecodeError, KeyError, TypeError) as error:
            raise InvalidOutputError(
                f"The recording {path.name} cannot be read: {error}"
            ) from error

        if version != request.skill_version:
            raise InvalidOutputError(
                f"The recording {path.name} was made for version {version} of the skill, "
                f"which is now at version {request.skill_version}. Record it again."
            )
        if request.output_schema is not None:
            problems = sorted(
                Draft202012Validator(dict(request.output_schema)).iter_errors(output),
                key=lambda problem: list(problem.absolute_path),
            )
            if problems:
                first = problems[0]
                where = "/".join(str(part) for part in first.absolute_path) or "the document"
                raise InvalidOutputError(
                    f"The recording {path.name} no longer fits its skill's output schema: "
                    f"{where}: {first.message}"
                )

        text = output if isinstance(output, str) else json.dumps(output, ensure_ascii=False)
        return LLMResponse(
            output=output,
            text=text,
            provider=Provider.DEMO,
            model=RECORDED_MODEL,
            input_tokens=int(recording.get("input_tokens", 0)),
            output_tokens=int(recording.get("output_tokens", 0)),
            cost_usd=Decimal("0"),
            latency_ms=round((time.perf_counter() - started) * 1000),
            sources=tuple(
                Source(item["url"], item["title"], item["cited_text"])
                for item in recording.get("sources", [])
            ),
            searches=int(recording.get("searches", 0)),
        )
