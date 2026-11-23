"""Settings: what startup reads, and how a bad setting stops it without showing the value."""

import pytest

from meeting_prep.config import ConfigError, load_settings

SECRET_URL = "postgresql://app:s3cret-password@db.example.com/meetings"

VALID = {
    "STORAGE_PROVIDER": "team6-s3",
    "TRACKER_PROVIDER": "team4-trello",
    "CALENDAR_PROVIDER": "team5-google",
    "DATABASE_URL": SECRET_URL,
}


def test_reads_the_provider_names_and_database_url():
    settings = load_settings(VALID)

    assert settings.storage_provider == "team6-s3"
    assert settings.tracker_provider == "team4-trello"
    assert settings.calendar_provider == "team5-google"
    assert settings.database_url == SECRET_URL


def test_provider_names_ignore_case_and_surrounding_spaces():
    settings = load_settings({**VALID, "CALENDAR_PROVIDER": "  Team5-Google \n"})

    assert settings.calendar_provider == "team5-google"


@pytest.mark.parametrize("name", sorted(VALID))
@pytest.mark.parametrize("value", [None, "", "   "], ids=["missing", "empty", "blank"])
def test_a_missing_setting_stops_startup_and_names_the_variable(name, value):
    env = {key: v for key, v in VALID.items() if key != name}
    if value is not None:
        env[name] = value

    with pytest.raises(ConfigError, match=f"^{name} is not set$"):
        load_settings(env)


def test_the_database_url_stays_out_of_repr():
    # A settings object in a log line or traceback must not show the password.
    assert "s3cret" not in repr(load_settings(VALID))
