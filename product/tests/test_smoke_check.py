"""scripts/smoke_check.py (design §4.3) against the app built over the fakes.

The same fakes back both the app and the check's own provider reads, the way a
deployed smoke check reads the providers the deployed service writes to.
"""

import importlib.util
from collections.abc import Callable
from pathlib import Path
from types import ModuleType

import pytest
from fastapi.testclient import TestClient

from meeting_prep.adapters.calendar import EventCalendarAdapter
from meeting_prep.adapters.storage import DocumentStorageAdapter
from meeting_prep.adapters.tracker import IssueTrackerAdapter
from meeting_prep.api.main import build_app
from meeting_prep.factories import Implementations
from meeting_prep.fakes import FakeCalendar, FakeStorage, FakeTracker
from meeting_prep.orchestrator import Orchestrator


def _load() -> ModuleType:
    path = Path(__file__).resolve().parents[1] / "scripts" / "smoke_check.py"
    spec = importlib.util.spec_from_file_location("smoke_check", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


smoke = _load()


class World:
    def __init__(self) -> None:
        self.calendar = FakeCalendar()
        self.impl = Implementations(FakeStorage(), FakeTracker(), self.calendar)
        storage = DocumentStorageAdapter(self.impl.storage)
        self.app = build_app(
            Orchestrator(
                storage,
                IssueTrackerAdapter(self.impl.tracker),
                EventCalendarAdapter(self.impl.calendar),
            ),
            api_key="key",
            commit="abc1234",
            storage_health=storage.check_health,
            tracker_health=lambda: None,
        )
        self.client = TestClient(self.app)

    def send(self) -> Callable[..., tuple[int, dict[str, object]]]:
        def send(
            method: str, path: str, body: object | None = None
        ) -> tuple[int, dict[str, object]]:
            headers = {"Authorization": "Bearer key"}
            response = self.client.request(method, path, json=body, headers=headers)
            return response.status_code, response.json()

        return send


def test_a_healthy_deploy_passes_every_check_and_leaves_nothing_behind():
    world = World()

    report = smoke.run_checks(world.send(), world.impl, expected_commit="abc1234")

    assert report.failed == [], report.lines
    assert report.leftovers == []
    names = [line.split(":")[0] for line in report.lines]
    assert names == [
        "PASS health",
        "PASS create",
        "PASS agenda",
        "PASS issue",
        "PASS event",
        "PASS replay",
        "PASS cleanup",
    ]
    assert world.impl.storage.list_files("/") == []


def test_a_wrong_commit_fails_health_but_still_runs_and_cleans_up():
    world = World()

    report = smoke.run_checks(world.send(), world.impl, expected_commit="0000000")

    assert report.failed[0].startswith("health")
    assert report.leftovers == []


def test_an_issue_title_trello_changed_fails_the_issue_check(monkeypatch):
    world = World()
    real = world.impl.tracker.get_issue

    def renamed(issue_id: str, *, fresh: bool = False):
        issue = real(issue_id, fresh=fresh)
        return issue.model_copy(update={"title": issue.title.replace("  ", " ") + " "})

    monkeypatch.setattr(world.impl.tracker, "get_issue", renamed)

    report = smoke.run_checks(world.send(), world.impl, expected_commit="abc1234")

    assert [f.split(":")[0] for f in report.failed] == ["issue"]


def test_a_run_that_fails_stops_after_create_and_reports_it():
    world = World()
    world.calendar.failures.fail_always(RuntimeError("down"))

    report = smoke.run_checks(world.send(), world.impl, expected_commit="abc1234")

    assert report.failed[0].startswith("create")
    assert "PASS replay" not in "\n".join(report.lines)
    assert report.leftovers == []  # the record and the card are still removed


def test_main_exits_non_zero_without_the_key(monkeypatch, capsys):
    monkeypatch.delenv("PRODUCT_API_KEY", raising=False)

    assert smoke.main(["https://staging.example"]) == 2
    assert "PRODUCT_API_KEY" in capsys.readouterr().err


@pytest.mark.parametrize("failed, leftovers, code", [([], [], 0), (["x"], [], 1), ([], ["y"], 1)])
def test_exit_code(failed, leftovers, code):
    assert smoke.Report(lines=[], failed=failed, leftovers=leftovers).exit_code == code
