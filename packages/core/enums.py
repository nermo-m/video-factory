"""Fixed value sets used across the pipeline (design doc sections 3.4, 3.5, 4 and 9).

They are stored as text with CHECK constraints, not as native database enums, so a later
milestone can add a value with an ordinary migration.
"""

from __future__ import annotations

from enum import StrEnum


class EpisodeState(StrEnum):
    """Pipeline states in order (section 4.1)."""

    IDEA = "idea"
    BRIEF = "brief"
    RESEARCH = "research"
    SCRIPT = "script"
    DIRECTION = "direction"
    ASSET_PLAN = "asset_plan"
    ASSET_GEN = "asset_gen"
    VOICE = "voice"
    RENDER = "render"
    QC = "qc"
    CRITIQUE = "critique"
    PACKAGE = "package"
    EXPORT = "export"
    DONE = "done"


class JobStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


class JobTag(StrEnum):
    """Capability a job needs. At most one gpu job runs at a time (D8)."""

    CPU = "cpu"
    GPU = "gpu"


class ErrorClass(StrEnum):
    """How a failed job is treated (section 4.4, plus plan_limit from section 3.4)."""

    RETRYABLE = "retryable"
    INVALID_OUTPUT = "invalid_output"
    NEEDS_OWNER = "needs_owner"
    BUG = "bug"
    PLAN_LIMIT = "plan_limit"


class SpecKind(StrEnum):
    AUTHORED = "authored"
    RESOLVED = "resolved"


class SpecAuthor(StrEnum):
    MODEL = "model"
    OWNER = "owner"


class AssetKind(StrEnum):
    IMAGE = "image"
    CLIP = "clip"
    AUDIO = "audio"
    SPRITE = "sprite"


class AssetOrigin(StrEnum):
    GENERATED = "generated"
    UPLOADED = "uploaded"
    LIBRARY = "library"


class RightsStatus(StrEnum):
    CLEARED = "cleared"
    NEEDS_REVIEW = "needs_review"
    BLOCKED = "blocked"


class RenderKind(StrEnum):
    PREVIEW = "preview"
    DRAFT = "draft"
    FINAL = "final"


class ReviewVerdict(StrEnum):
    FINISHED = "finished"
    ADJUST = "adjust"
    REMAKE = "remake"


class AgentName(StrEnum):
    CRITIC = "critic"
    PRODUCER = "producer"


class AgentRunStatus(StrEnum):
    RUNNING = "running"
    FINISHED = "finished"
    LIMIT_REACHED = "limit_reached"
    FAILED = "failed"
    STOPPED_BY_OWNER = "stopped_by_owner"


class Provider(StrEnum):
    """Who answered a model call. `demo` is the recorded-response provider."""

    DEMO = "demo"
    CLAUDE_PLAN = "claude_plan"
    CHATGPT_PLAN = "chatgpt_plan"
    ANTHROPIC_API = "anthropic_api"
    OPENAI_API = "openai_api"


class UsageKind(StrEnum):
    TEXT = "text"
    IMAGE = "image"


class Billing(StrEnum):
    DEMO = "demo"
    PLAN = "plan"
    API = "api"


class ProviderState(StrEnum):
    OK = "ok"
    NEAR_BUDGET = "near_budget"
    PAUSED_BY_BUDGET = "paused_by_budget"
    LIMITED = "limited"


class StatusSource(StrEnum):
    """Whether a provider status came from the tool itself or from this app's own count."""

    TOOL = "tool"
    APP = "app"
