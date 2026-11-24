"""What the orchestrator needs from each vertical, and the one error the adapters raise.

The orchestrator calls these protocols only, never a contract (design §2.4). This
module imports no contract either, so an adapter for any implementation can plug
in without changing the orchestrator.

Every failure reaches the orchestrator as a ``StepError`` that names the step and
one of the operation's codes (design §1.4). Translating a contract's exceptions
into it, with the tables in design §1.5, is each adapter's job. A ``StepError``
never carries provider text: the orchestrator writes every message itself.
"""

from dataclasses import dataclass
from typing import Literal, Protocol

Step = Literal["claim_run", "create_issue", "create_event", "write_agenda", "finish_run"]

# The codes an adapter may report. The orchestrator adds invalid_request,
# run_in_progress and outcome_unknown itself.
ErrorCode = Literal[
    "permission_denied",
    "provider_error",
    "provider_unavailable",
    "run_record_invalid",
    "internal_error",
]


class StepError(Exception):
    """A step failed. ``may_have_applied`` says whether its write may have happened.

    ``provider_code`` is the provider's or contract's own name for the failure, for
    the failure log line only. It never reaches a response.
    """

    def __init__(
        self,
        step: Step,
        code: ErrorCode,
        *,
        retryable: bool,
        may_have_applied: bool,
        provider_code: str | None = None,
        provider_cause: str | None = None,
    ) -> None:
        super().__init__(f"{step}: {code}")
        self.step: Step = step
        self.code: ErrorCode = code
        self.retryable = retryable
        self.may_have_applied = may_have_applied
        self.provider_code = provider_code
        self.provider_cause = provider_cause


@dataclass(frozen=True)
class IssueSummary:
    id: str
    title: str


class StorageAdapter(Protocol):
    """Document storage, for the run record and the agenda. ``step`` names the caller's step."""

    def create(self, step: Step, path: str, content: bytes) -> bool:
        """Create the file. Return False, writing nothing, if a file already exists at path."""
        ...

    def replace(self, step: Step, path: str, content: bytes) -> None:
        """Replace an existing file. A missing file is ``run_record_invalid``."""
        ...

    def download(self, step: Step, path: str) -> bytes:
        """The file's exact bytes. A missing file is ``run_record_invalid``."""
        ...


class TrackerAdapter(Protocol):
    """The issue tracker. Every error names the step ``create_issue``."""

    def create_issue(self, title: str, token: str) -> str:
        """Create an issue with this title and a stable token when supported."""
        ...

    def recover_issue(self, token: str, title_marker: str) -> str | None:
        """Find an earlier attempt by token or the documented title fallback."""
        ...


class CalendarAdapter(Protocol):
    """The calendar. Every error names the step ``create_event``.

    A timeout or a lost response is ``provider_error`` with ``may_have_applied`` true.
    """

    def create(self, title: str, start: str, end: str) -> str:
        """Create an event and return its ID. ``start`` and ``end`` are RFC 3339 in UTC."""
        ...
