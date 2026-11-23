"""The implementation registry: every name builds, and nothing falls back.

Building an implementation makes no network call: boto3 builds its client
offline, Team 4's provider reads its settings on each call, and Team 5's
package authorizes on the first call.
"""

import socket

import pytest
from cloud_storage_api import DocumentStorage
from issue_tracker_contract import IssueProvider

from meeting_prep import factories
from meeting_prep.config import ConfigError, Settings
from meeting_prep.factories import (
    CALENDAR_BUILDERS,
    DEFAULT_SOCKET_TIMEOUT_SECONDS,
    STORAGE_BUILDERS,
    TRACKER_BUILDERS,
    build_implementations,
)
from meeting_prep.fakes import FakeCalendar, FakeStorage, FakeTracker

SECRET = "do-not-print-me"


@pytest.fixture(autouse=True)
def restore_socket_timeout():
    before = socket.getdefaulttimeout()
    yield
    socket.setdefaulttimeout(before)


@pytest.fixture
def provider_env(tmp_path):
    """Settings for every real implementation, with made-up values."""
    token_file = tmp_path / "calendar-token.json"
    token_file.write_text("{}")
    return {
        "S3_ENDPOINT": "https://objectstorage.example.com",
        "S3_REGION": "us-ashburn-1",
        "S3_BUCKET": "review-runs",
        "S3_ACCESS_KEY": "access",
        "S3_SECRET_KEY": SECRET,
        "TRELLO_API_KEY": "key",
        "TRELLO_TOKEN": SECRET,
        "TRELLO_LIST_ID": "list",
        "CALENDAR_TOKEN_FILE": str(token_file),
    }


def settings(storage: str = "fake", tracker: str = "fake", calendar: str = "fake") -> Settings:
    return Settings(
        storage_provider=storage,
        tracker_provider=tracker,
        calendar_provider=calendar,
        database_url="sqlite://",
    )


def has_calendar_operations(calendar: object) -> bool:
    # CalendarService is a Protocol that cannot be checked with isinstance.
    operations = ("create", "get", "replace", "delete")
    return all(callable(getattr(calendar, name, None)) for name in operations)


@pytest.mark.parametrize("name", sorted(STORAGE_BUILDERS))
def test_every_storage_name_builds_a_document_storage(name, provider_env):
    built = build_implementations(settings(storage=name), provider_env)

    assert isinstance(built.storage, DocumentStorage)


@pytest.mark.parametrize("name", sorted(TRACKER_BUILDERS))
def test_every_tracker_name_builds_an_issue_provider(name, provider_env):
    built = build_implementations(settings(tracker=name), provider_env)

    assert isinstance(built.tracker, IssueProvider)


@pytest.mark.parametrize("name", sorted(CALENDAR_BUILDERS))
def test_every_calendar_name_builds_a_calendar_service(name, provider_env):
    built = build_implementations(settings(calendar=name), provider_env)

    assert has_calendar_operations(built.calendar)


def test_the_registry_offers_one_real_name_and_two_fakes_per_vertical():
    assert set(STORAGE_BUILDERS) == {"team6-s3", "fake", "fake-failing"}
    assert set(TRACKER_BUILDERS) == {"team4-trello", "fake", "fake-failing"}
    assert set(CALENDAR_BUILDERS) == {"team5-google", "fake", "fake-failing"}


def test_real_names_build_the_partner_implementations(provider_env):
    built = build_implementations(
        settings(storage="team6-s3", tracker="team4-trello", calendar="team5-google"),
        provider_env,
    )

    assert type(built.storage).__module__ == "storage_service.shared_storage"
    assert type(built.tracker).__module__.startswith("team_4_issue_tracker_trello")
    assert type(built.calendar).__module__.startswith("team5_calendar")


def test_switching_the_calendar_changes_only_the_calendar():
    plain = build_implementations(settings())
    failing = build_implementations(settings(calendar="fake-failing"))

    assert type(failing.storage) is type(plain.storage) is FakeStorage
    assert type(failing.tracker) is type(plain.tracker) is FakeTracker
    assert isinstance(failing.calendar, FakeCalendar)
    assert isinstance(plain.calendar, FakeCalendar)
    assert failing.calendar.failures.take("create") is not None
    assert plain.calendar.failures.take("create") is None


def test_each_build_gets_fresh_fakes():
    first = build_implementations(settings())
    second = build_implementations(settings())

    assert first.storage is not second.storage


@pytest.mark.parametrize(
    ("variable", "kwargs"),
    [
        ("STORAGE_PROVIDER", {"storage": "dropbox"}),
        ("TRACKER_PROVIDER", {"tracker": "linear"}),
        ("CALENDAR_PROVIDER", {"calendar": "outlook"}),
    ],
)
def test_an_unknown_name_stops_startup_and_lists_the_known_names(variable, kwargs):
    with pytest.raises(ConfigError) as error:
        build_implementations(settings(**kwargs))

    message = str(error.value)
    assert message.startswith(f"{variable} must be one of: ")
    assert "fake-failing" in message
    assert next(iter(kwargs.values())) not in message


@pytest.mark.parametrize(
    ("kwargs", "missing"),
    [
        ({"storage": "team6-s3"}, "S3_BUCKET"),
        ({"tracker": "team4-trello"}, "TRELLO_LIST_ID"),
        ({"calendar": "team5-google"}, "CALENDAR_TOKEN_FILE"),
    ],
)
def test_a_missing_implementation_setting_stops_startup(kwargs, missing, provider_env):
    del provider_env[missing]

    with pytest.raises(ConfigError, match=missing):
        build_implementations(settings(**kwargs), provider_env)


def test_a_calendar_token_file_that_does_not_exist_stops_startup(provider_env, tmp_path):
    provider_env["CALENDAR_TOKEN_FILE"] = str(tmp_path / "missing.json")

    with pytest.raises(ConfigError, match="^CALENDAR_TOKEN_FILE does not name a file$"):
        build_implementations(settings(calendar="team5-google"), provider_env)


def test_a_builder_that_fails_stops_startup_without_its_message(monkeypatch):
    def broken(env):
        raise RuntimeError(f"bad token {SECRET}")

    monkeypatch.setitem(factories.TRACKER_BUILDERS, "broken", broken)

    with pytest.raises(ConfigError) as error:
        build_implementations(settings(tracker="broken"))

    assert str(error.value) == (
        "TRACKER_PROVIDER: the selected implementation could not be built (RuntimeError)"
    )
    assert error.value.__cause__ is None
    assert error.value.__suppress_context__


def test_startup_bounds_sockets_that_have_no_timeout():
    # Team 5's Calendar call opens its sockets without a timeout.
    socket.setdefaulttimeout(None)

    build_implementations(settings())

    assert socket.getdefaulttimeout() == DEFAULT_SOCKET_TIMEOUT_SECONDS == 30
