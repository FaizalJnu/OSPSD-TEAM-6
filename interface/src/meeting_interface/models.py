"""Shapes the interface reads from the API service.

The field names follow the review-meeting operation's documented results. The
interface only displays them; it never decides an outcome itself.
"""

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class StepStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    UNCERTAIN = "uncertain"
    SKIPPED = "skipped"

    @classmethod
    def parse(cls, value: object) -> "StepStatus":
        # An unknown status is never shown as success: it may or may not have happened.
        try:
            return cls(str(value))
        except ValueError:
            return cls.UNCERTAIN


@dataclass(frozen=True)
class RunRequest:
    project: str
    meeting_date: str
    title: str

    def to_json(self) -> dict[str, str]:
        return {"project": self.project, "meeting_date": self.meeting_date, "title": self.title}


@dataclass(frozen=True)
class StepOutcome:
    step: str
    status: StepStatus
    detail: str | None = None
    link: str | None = None

    @classmethod
    def from_json(cls, body: dict[str, Any]) -> "StepOutcome":
        detail = body.get("detail")
        link = body.get("link")
        return cls(
            step=str(body["step"]),
            status=StepStatus.parse(body.get("status")),
            detail=None if detail is None else str(detail),
            link=None if link is None else str(link),
        )


@dataclass(frozen=True)
class RunResult:
    run_id: str
    status: str
    steps: list[StepOutcome] = field(default_factory=list)

    @classmethod
    def from_json(cls, body: dict[str, Any]) -> "RunResult":
        return cls(
            run_id=str(body["run_id"]),
            status=str(body["status"]),
            steps=[StepOutcome.from_json(step) for step in body.get("steps", [])],
        )
