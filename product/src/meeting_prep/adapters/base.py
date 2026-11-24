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
    ) -> None:
        super().__init__(f"{step}: {code}")
        self.step: Step = step
        self.code: ErrorCode = code
        self.retryable = retryable
        self.may_have_applied = may_have_applied
        self.provider_code = provider_code


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
    """The issue tracker. Every error names the step ``create_issue``.

    Team 4's package also has ``create_tagged_issue(title, token)`` and
    ``find_tagged_issue(token)``, outside the contract (design §2.3 step 2). The
    adapter checks for both when it is built and reports the answer in ``tagged``.
    The orchestrator calls the tagged pair only when ``tagged`` is true; otherwise
    it falls back to ``create_issue`` and the title marker search.
    """

    @property
    def tagged(self) -> bool:
        """Whether the implementation has the tagged pair, decided when the adapter was built."""
        ...

    def create_tagged_issue(self, step: Step, title: str, token: str) -> str:
        """Create an issue with this title, tagged with ``token``, and return its ID."""
        ...

    def find_tagged_issue(self, step: Step, token: str) -> str | None:
        """The ID of the issue tagged with ``token``, archived or renamed included, or None."""
        ...

    def create_issue(self, title: str) -> str:
        """Create an issue with exactly this title and return its ID."""
        ...

    def list_issues(self, limit: int) -> list[IssueSummary]:
        """Up to ``limit`` issues, newest first, read fresh from the provider."""
        ...


class CalendarAdapter(Protocol):
    """The calendar. Every error names the step ``create_event``.

    A timeout or a lost response is ``provider_error`` with ``may_have_applied`` true.
    """

    def create(self, title: str, start: str, end: str) -> str:
        """Create an event and return its ID. ``start`` and ``end`` are RFC 3339 in UTC."""
        ...
