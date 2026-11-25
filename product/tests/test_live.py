"""Real-provider runs of POST /v1/review-meetings (design §3.3), marked ``provider``.

They run the app in-process on the real registry entries and check the effects in
each provider with the smoke check's own checks (scripts/smoke_check.py), then
delete everything they made. Run from product/:

    uv run --env-file .env pytest -m provider tests/test_live.py

On macOS, set SSL_CERT_FILE to certifi's bundle first: uv's Python has no system CA
certificates, and Team 4's package uses urllib, so Trello calls otherwise fail TLS:

    export SSL_CERT_FILE="$(uv run python -c 'import certifi; print(certifi.where())')"

The run of 2026-11-25 is recorded in TESTING.md.

Each test needs only its own providers' settings, and is skipped with the missing
names otherwise. Values are never read or printed here; the builders read them.

* storage only: S3_* (real OCI bucket; tracker and calendar are fakes)
* all three: S3_*, TRELLO_API_KEY, TRELLO_TOKEN, TRELLO_LIST_ID, CALENDAR_TOKEN_FILE
"""

import importlib.util
import os
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest
from fastapi.testclient import TestClient

from meeting_prep.adapters.calendar import EventCalendarAdapter
from meeting_prep.adapters.storage import DocumentStorageAdapter
from meeting_prep.adapters.tracker import IssueTrackerAdapter
from meeting_prep.api.main import build_app
from meeting_prep.config import Settings
from meeting_prep.factories import Implementations, build_implementations
from meeting_prep.orchestrator import Orchestrator

pytestmark = pytest.mark.provider

S3 = ("S3_ENDPOINT", "S3_REGION", "S3_BUCKET", "S3_ACCESS_KEY", "S3_SECRET_KEY")
TRELLO = ("TRELLO_API_KEY", "TRELLO_TOKEN", "TRELLO_LIST_ID")
GOOGLE = ("CALENDAR_TOKEN_FILE",)
KEY = "live-test-key"


def _smoke() -> ModuleType:
    path = Path(__file__).resolve().parents[1] / "scripts" / "smoke_check.py"
    spec = importlib.util.spec_from_file_location("smoke_check", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


smoke = _smoke()


def needs(*names: str) -> None:
    missing = [name for name in names if not os.environ.get(name, "").strip()]
    if missing:
        pytest.skip(f"not set: {', '.join(missing)}")


def implementations(storage: str, tracker: str, calendar: str) -> Implementations:
    settings = Settings(storage, tracker, calendar, database_url="")
    return build_implementations(settings, os.environ)


def client_for(impl: Implementations) -> TestClient:
    storage = DocumentStorageAdapter(impl.storage)
    app = build_app(
        Orchestrator(
            storage, IssueTrackerAdapter(impl.tracker), EventCalendarAdapter(impl.calendar)
        ),
        api_key=KEY,
        commit="live",
        storage_health=storage.check_health,
        tracker_health=lambda: None,
    )
    return TestClient(app)


def sender(client: TestClient) -> Callable[[str, str, object | None], tuple[int, Any]]:
    def send(method: str, path: str, body: object | None) -> tuple[int, Any]:
        response = client.request(
            method, path, json=body, headers={"Authorization": f"Bearer {KEY}"}
        )
        return response.status_code, response.json()

    return send


def test_full_run_on_oci_storage():
    """The real bucket holds the run record and the agenda; tracker and calendar are fakes."""
    needs(*S3)
    impl = implementations("team6-s3", "fake", "fake")

    report = smoke.run_checks(sender(client_for(impl)), impl, expected_commit="live")

    assert report.failed == [], report.lines
    assert report.leftovers == [], report.lines


def test_full_run_on_all_three_providers():
    """Design §3.3: a Trello card with the exact marker title (T4-3), a Google event at
    the same instants, and the agenda's bytes in OCI; then the replay; then cleanup."""
    needs(*S3, *TRELLO, *GOOGLE)
    impl = implementations("team6-s3", "team4-trello", "team5-google")

    report = smoke.run_checks(sender(client_for(impl)), impl, expected_commit="live")

    assert report.failed == [], report.lines
    assert report.leftovers == [], report.lines


def test_resume_after_a_calendar_failure_makes_one_card():
    """Design §3.3, failure reporting: fake-failing calendar first, then the real one."""
    needs(*S3, *TRELLO, *GOOGLE)
    now = datetime.now(UTC)
    body = smoke.smoke_body(now, "live-resume")
    failing = implementations("team6-s3", "team4-trello", "fake-failing")
    real = implementations("team6-s3", "team4-trello", "team5-google")

    status, first = sender(client_for(failing))("POST", "/v1/review-meetings", body)
    try:
        assert status == 503, first
        assert first["error"]["step"] == "create_event"
        assert first["error"]["retryable"] is True
        assert first["run"]["status"] == "partial"
        issue_id = first["run"]["issue"]["id"]

        status, second = sender(client_for(real))("POST", "/v1/review-meetings", body)

        assert status == 201, second
        assert second["issue"]["id"] == issue_id
    finally:
        request = smoke.validate(body, now)
        run_id = smoke.run_id_for(request)
        last = locals().get("second") or first
        report = smoke.Report()
        smoke._clean_up(report, real, request, run_id, smoke._run_of(dict(last)))
        assert report.leftovers == [], report.lines
