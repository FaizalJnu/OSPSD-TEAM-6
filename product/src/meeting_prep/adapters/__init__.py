"""Adapters: the only code that sees a shared contract's types and exceptions (design §1.1).

``base.py`` says what the orchestrator needs from each vertical and defines
``StepError``, the one error every adapter raises. The adapters for the three
contracts (storage, tracker, calendar) implement those protocols and translate
each contract's errors with the tables in design §1.5.
"""

from meeting_prep.adapters.base import (
    CalendarAdapter,
    ErrorCode,
    IssueSummary,
    Step,
    StepError,
    StorageAdapter,
    TrackerAdapter,
)

__all__ = [
    "CalendarAdapter",
    "ErrorCode",
    "IssueSummary",
    "Step",
    "StepError",
    "StorageAdapter",
    "TrackerAdapter",
]
