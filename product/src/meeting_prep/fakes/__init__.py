"""In-memory storage, tracker and calendar, for tests and for staging checks.

Each fake follows its shared contract, records every call in ``calls``, and
takes planned failures through ``failures`` (see ``FailurePlan``). The registry
(``factories.py``) offers them as ``fake`` and ``fake-failing``, chosen through
the same variables as the real implementations. Service code never imports this
package; tests and the registry do (tests/test_import_boundary.py).
"""

from meeting_prep.fakes._failures import Call, FailurePlan
from meeting_prep.fakes.calendar import FakeCalendar, failing_calendar
from meeting_prep.fakes.storage import FakeStorage, failing_storage
from meeting_prep.fakes.tracker import FakeTracker, failing_tracker

__all__ = [
    "Call",
    "FailurePlan",
    "FakeCalendar",
    "FakeStorage",
    "FakeTracker",
    "failing_calendar",
    "failing_storage",
    "failing_tracker",
]
