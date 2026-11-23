"""What every fake shares: a record of its calls, a failure plan, and a lock."""

import threading
from collections import defaultdict, deque
from dataclasses import dataclass


@dataclass(frozen=True)
class Call:
    """One call a fake received, with its arguments as they were passed."""

    operation: str
    args: tuple[object, ...]


@dataclass(frozen=True)
class _Failure:
    error: Exception
    applied: bool


class FailurePlan:
    """Errors a fake raises instead of, or after, doing an operation's work.

    ``fail_next`` queues an error for the next call to one operation. With
    ``applied=True`` a write takes effect first and the error is raised after
    it: the lost-response case, where the provider did the work but the caller
    never heard back. ``fail_always`` makes every call raise, like an outage,
    until it is called again with ``None``. A queued error wins over the
    standing one.
    """

    def __init__(self, operations: frozenset[str]) -> None:
        self._operations = operations
        self._queued: defaultdict[str, deque[_Failure]] = defaultdict(deque)
        self._always: Exception | None = None

    def fail_next(self, operation: str, error: Exception, *, applied: bool = False) -> None:
        if operation not in self._operations:
            known = ", ".join(sorted(self._operations))
            raise ValueError(f"unknown operation {operation!r}; this fake has: {known}")
        self._queued[operation].append(_Failure(error, applied))

    def fail_always(self, error: Exception | None) -> None:
        self._always = error

    def take(self, operation: str) -> _Failure | None:
        queued = self._queued[operation]
        if queued:
            return queued.popleft()
        if self._always is not None:
            return _Failure(self._always, applied=False)
        return None


class FakeBase:
    """Records calls and applies the failure plan around each operation.

    An operation calls ``_start`` first. It records the call, then raises a
    planned error that should stop the work. After the work, it calls
    ``_finish``, which raises a planned error that should follow the work.
    Operations hold ``_lock`` so a fake behind a threaded server stays consistent.
    """

    OPERATIONS: frozenset[str] = frozenset()

    def __init__(self) -> None:
        self.calls: list[Call] = []
        self.failures = FailurePlan(self.OPERATIONS)
        self._lock = threading.RLock()

    def operations_called(self) -> list[str]:
        """The names of the operations called so far, in order."""
        return [call.operation for call in self.calls]

    def _start(self, operation: str, *args: object) -> _Failure | None:
        self.calls.append(Call(operation, args))
        failure = self.failures.take(operation)
        if failure is not None and not failure.applied:
            _raise(failure)
        return failure

    @staticmethod
    def _finish(failure: _Failure | None) -> None:
        if failure is not None:
            _raise(failure)


def _raise(failure: _Failure) -> None:
    # A standing error is raised again and again. Dropping the old traceback
    # stops it from growing with every raise.
    raise failure.error.with_traceback(None)
