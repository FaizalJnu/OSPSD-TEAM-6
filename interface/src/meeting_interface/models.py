"""Shapes the interface reads from the API service (design §1.4).

The interface only displays them; it never decides an outcome itself.
"""

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class StepStatus(StrEnum):
    OK = "ok"
    FAILED = "failed"
    UNKNOWN = "unknown"
    PENDING = "pending"

    @classmethod
    def parse(cls, value: object) -> "StepStatus":
        # A status we do not know is never shown as done: it may or may not have happened.
        try:
            return cls(str(value))
        except ValueError:
            return cls.UNKNOWN


@dataclass(frozen=True)
class RunRequest:
    title: str
    start: str  # RFC 3339 with an explicit offset, whole seconds
    end: str
    agenda: list[str]

    def to_json(self) -> dict[str, object]:
        return {"title": self.title, "start": self.start, "end": self.end, "agenda": self.agenda}


@dataclass(frozen=True)
class Step:
    name: str
    status: StepStatus


@dataclass(frozen=True)
class Run:
    run_id: str
    status: str  # completed, partial or failed
    steps: list[Step] = field(default_factory=list)
    issue_id: str | None = None
    event_id: str | None = None
    event_start: str | None = None
    event_end: str | None = None
    agenda_path: str | None = None

    @classmethod
    def from_json(cls, body: dict[str, Any]) -> "Run":
        event = _object(body.get("event"))
        return cls(
            run_id=str(body["run_id"]),
            status=str(body["status"]),
            steps=[
                Step(str(s["name"]), StepStatus.parse(s.get("status")))
                for s in body.get("steps", [])
            ],
            issue_id=_text(_object(body.get("issue")).get("id")),
            event_id=_text(event.get("id")),
            event_start=_text(event.get("start")),
            event_end=_text(event.get("end")),
            agenda_path=_text(_object(body.get("agenda")).get("path")),
        )


@dataclass(frozen=True)
class RunResult:
    replayed: bool
    run: Run

    @classmethod
    def from_json(cls, body: dict[str, Any]) -> "RunResult":
        return cls(replayed=body.get("replayed") is True, run=Run.from_json(body))


def _object(value: object) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _text(value: object) -> str | None:
    return None if value is None else str(value)
