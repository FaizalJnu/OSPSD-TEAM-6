"""Post-deploy smoke check for POST /v1/review-meetings (design §4.3).

Against a deployed staging or demo URL:

1. GET /health reports the expected commit.
2. One request with a unique title, 300 days ahead, completes (201).
3. The effects are real, read back through the same implementations the service
   uses: the agenda's bytes, the tracker issue's exact title (marker included,
   Team 4's T4-3), and the event's start and end instants.
4. The same request again is 200 ``replayed`` with the same IDs.
5. Everything the run made is deleted, and anything that could not be is listed.

The deploy passes only when steps 1 to 4 pass and nothing is left behind.

    PRODUCT_API_KEY=... uv run --env-file .env python scripts/smoke_check.py \\
        https://meetings-staging.packapunch.xyz --commit "$RELEASE"

The provider settings (STORAGE_PROVIDER and the rest) must match the deployed
service's, so the check reads the same bucket, board and calendar. No credential,
title or provider message is printed.
"""

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from meeting_prep.agenda import agenda_path, render
from meeting_prep.config import ConfigError, Settings, provider_name
from meeting_prep.factories import Implementations, build_implementations
from meeting_prep.orchestrator import validate
from meeting_prep.run_record import MeetingRequest, meeting_title, record_path, run_id_for

type Send = Callable[[str, str, object | None], tuple[int, dict[str, object]]]


@dataclass
class Report:
    lines: list[str] = field(default_factory=list)
    failed: list[str] = field(default_factory=list)
    leftovers: list[str] = field(default_factory=list)

    def check(self, name: str, ok: bool, detail: str = "") -> bool:
        line = f"{name}: {detail}" if detail else name
        self.lines.append(("PASS " if ok else "FAIL ") + line)
        if not ok:
            self.failed.append(line)
        return ok

    @property
    def exit_code(self) -> int:
        return 0 if not self.failed and not self.leftovers else 1


def smoke_body(now: datetime, commit: str) -> dict[str, object]:
    start = (now + timedelta(days=300)).replace(minute=0, second=0, microsecond=0)
    return {
        "title": f"smoke {commit[:12]} {now:%Y%m%dT%H%M%S}",
        "start": start.isoformat(),
        "end": (start + timedelta(minutes=30)).isoformat(),
        "agenda": ["Smoke check"],
    }


def run_checks(
    send: Send,
    impl: Implementations,
    *,
    expected_commit: str | None,
    now: datetime | None = None,
) -> Report:
    report = Report()
    now = now or datetime.now(UTC)

    status, health = send("GET", "/health", None)
    commit = health.get("commit")
    report.check(
        "health",
        status == 200 and (expected_commit is None or commit == expected_commit),
        f"status {status}, commit {commit}",
    )

    body = smoke_body(now, expected_commit or "unknown")
    request = validate(body, now)
    run_id = run_id_for(request)
    status, first = send("POST", "/v1/review-meetings", body)
    run = _run_of(first)
    created = report.check(
        "create",
        status == 201 and first.get("status") == "completed",
        f"status {status}, run {run_id}" + _error_code(first),
    )

    try:
        if created:
            _check_effects(report, impl, request, run_id, run)
            status, again = send("POST", "/v1/review-meetings", body)
            same = all(
                _id(again, key) == _id(first, key) for key in ("issue", "event")
            ) and again.get("run_id") == first.get("run_id")
            report.check(
                "replay",
                status == 200 and again.get("replayed") is True and same,
                f"status {status}",
            )
    finally:
        _clean_up(report, impl, request, run_id, run)
    return report


def _check_effects(
    report: Report,
    impl: Implementations,
    request: MeetingRequest,
    run_id: str,
    run: dict[str, object],
) -> None:
    issue_id, event_id = _id(run, "issue"), _id(run, "event")
    try:
        expected = render(request, run_id, issue_id=str(issue_id), event_id=str(event_id))
        report.check("agenda", impl.storage.download(agenda_path(request, run_id)) == expected)
    except Exception as error:
        report.check("agenda", False, type(error).__name__)
    try:
        title = impl.tracker.get_issue(str(issue_id), fresh=True).title
        report.check("issue", title == meeting_title(request, run_id), "exact title")
    except Exception as error:
        report.check("issue", False, type(error).__name__)
    try:
        event = impl.calendar.get(str(event_id))
        same = _instant(event.start) == _instant(request.start) and _instant(event.end) == _instant(
            request.end
        )
        report.check("event", same, "start and end instants")
    except Exception as error:
        report.check("event", False, type(error).__name__)


def _clean_up(
    report: Report,
    impl: Implementations,
    request: MeetingRequest,
    run_id: str,
    run: dict[str, object],
) -> None:
    if not run:
        report.check("cleanup", True, "nothing was created")
        return
    steps: list[tuple[str, Callable[[], object]]] = []
    if (event_id := _id(run, "event")) is not None:
        steps.append(("event", lambda: impl.calendar.delete(str(event_id))))
    if (issue_id := _id(run, "issue")) is not None:
        steps.append(("issue", lambda: impl.tracker.delete_issue(str(issue_id))))
    if run.get("agenda"):
        steps.append(("agenda", lambda: impl.storage.delete(agenda_path(request, run_id))))
    steps.append(("run record", lambda: impl.storage.delete(record_path(run_id))))
    for name, delete in steps:
        try:
            delete()
        except Exception as error:
            report.leftovers.append(f"{name} ({type(error).__name__})")
    report.check("cleanup", not report.leftovers, ", ".join(report.leftovers) or "all removed")


def _run_of(body: dict[str, object]) -> dict[str, object]:
    if "error" in body:
        run = body.get("run")
        return run if isinstance(run, dict) else {}
    return body


def _id(body: dict[str, object], key: str) -> object:
    value = body.get(key)
    return value.get("id") if isinstance(value, dict) else None


def _error_code(body: dict[str, object]) -> str:
    error = body.get("error")
    if isinstance(error, dict):
        return f", {error.get('code')} at {error.get('step')}"
    return ""


def _instant(text: str) -> datetime:
    # Clients compare instants, not strings (calendar-contract v0.1.0).
    return datetime.fromisoformat(text.replace("Z", "+00:00")).astimezone(UTC)


def http_sender(base_url: str, api_key: str, timeout: float = 180.0) -> Send:
    def send(method: str, path: str, body: object | None) -> tuple[int, dict[str, object]]:
        data = None if body is None else json.dumps(body).encode()
        request = urllib.request.Request(
            base_url.rstrip("/") + path,
            data=data,
            method=method,
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return response.status, json.loads(response.read() or b"{}")
        except urllib.error.HTTPError as error:
            try:
                return error.code, json.loads(error.read() or b"{}")
            except ValueError:
                return error.code, {}

    return send


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Post-deploy smoke check (design §4.3).")
    parser.add_argument("base_url", help="for example https://meetings-staging.packapunch.xyz")
    parser.add_argument("--commit", help="the commit /health must report")
    args = parser.parse_args(argv)
    key = os.environ.get("PRODUCT_API_KEY", "").strip()
    if not key:
        print("error: PRODUCT_API_KEY is not set", file=sys.stderr)
        return 2
    try:
        # Only the provider settings: the check never touches the database.
        settings = Settings(
            storage_provider=provider_name(os.environ, "STORAGE_PROVIDER"),
            tracker_provider=provider_name(os.environ, "TRACKER_PROVIDER"),
            calendar_provider=provider_name(os.environ, "CALENDAR_PROVIDER"),
            database_url="",
        )
        impl = build_implementations(settings)
    except ConfigError as error:
        print(f"error: {error}", file=sys.stderr)
        return 2
    report = run_checks(http_sender(args.base_url, key), impl, expected_commit=args.commit)
    print("\n".join(report.lines))
    return report.exit_code


if __name__ == "__main__":
    sys.exit(main())
