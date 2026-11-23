"""The in-memory DocumentStorage follows the contract and our storage service's rules."""

import pytest
from cloud_storage_api import (
    ConflictError,
    InvalidOperationError,
    InvalidRequestError,
    NotFoundError,
    ProviderUnavailableError,
)

from meeting_prep.fakes import FakeStorage, failing_storage


@pytest.fixture
def storage():
    return FakeStorage()


def test_create_then_download_returns_the_exact_bytes(storage):
    info = storage.create("/reviews/agenda.md", b"# Agenda\n")

    assert storage.download("/reviews/agenda.md") == b"# Agenda\n"
    assert (info.path, info.name, info.size, info.id, info.type) == (
        "/reviews/agenda.md",
        "agenda.md",
        9,
        None,
        None,
    )
    assert info.modified_at is not None and info.modified_at.endswith("Z")
    assert info.etag


def test_create_refuses_an_existing_path_and_keeps_the_first_bytes(storage):
    storage.create("/review-runs/abc.json", b"first")

    with pytest.raises(ConflictError):
        storage.create("/review-runs/abc.json", b"second")
    assert storage.download("/review-runs/abc.json") == b"first"


def test_replace_changes_an_existing_file_and_never_creates_one(storage):
    storage.create("/a.txt", b"one")

    assert storage.replace("/a.txt", b"two").size == 3
    assert storage.download("/a.txt") == b"two"
    with pytest.raises(NotFoundError):
        storage.replace("/missing.txt", b"x")
    assert "/missing.txt" not in storage.files


def test_a_path_without_the_leading_slash_names_the_same_file(storage):
    storage.create("docs/a.txt", b"x")

    assert storage.get_metadata("/docs/a.txt").path == "/docs/a.txt"


@pytest.mark.parametrize(
    "path", ["", "/", "/docs/", "//a", "/a/./b", "/a/../b", "/a\nb", "/" + "a" * 1024]
)
def test_invalid_paths_are_refused(storage, path):
    with pytest.raises(InvalidRequestError):
        storage.create(path, b"x")


def test_missing_files_are_not_found(storage):
    for call in (storage.download, storage.get_metadata, storage.delete):
        with pytest.raises(NotFoundError):
            call("/missing.txt")


def test_list_returns_direct_children_sorted_with_folders(storage):
    for path in ("/reviews/b.md", "/reviews/a.md", "/reviews/2026/c.md", "/other.txt"):
        storage.create(path, b"x")

    listing = storage.list_files("/reviews")

    assert [(entry.path, entry.type) for entry in listing] == [
        ("/reviews/2026", "folder"),
        ("/reviews/a.md", "file"),
        ("/reviews/b.md", "file"),
    ]
    assert [entry.path for entry in storage.list_files("/")] == ["/other.txt", "/reviews"]


def test_list_of_an_empty_root_is_empty_but_a_missing_folder_is_not_found(storage):
    assert storage.list_files("/") == []
    with pytest.raises(NotFoundError):
        storage.list_files("/nothing")


def test_move_refuses_an_existing_destination(storage):
    storage.create("/a.txt", b"a")
    storage.create("/b.txt", b"b")

    with pytest.raises(ConflictError):
        storage.move("/a.txt", "/b.txt")
    moved = storage.move("/a.txt", "/c.txt")

    assert moved.path == "/c.txt"
    assert sorted(storage.files) == ["/b.txt", "/c.txt"]


def test_move_to_the_same_path_is_an_invalid_operation(storage):
    storage.create("/a.txt", b"a")

    with pytest.raises(InvalidOperationError):
        storage.move("/a.txt", "a.txt")
    assert storage.download("/a.txt") == b"a"


def test_move_that_changes_only_letter_case_is_an_invalid_operation(storage):
    storage.create("/Notes/A.md", b"a")

    with pytest.raises(InvalidOperationError):
        storage.move("/Notes/A.md", "/notes/a.md")
    assert sorted(storage.files) == ["/Notes/A.md"]


def test_move_of_a_folder_is_an_invalid_operation(storage):
    storage.create("/runs/1.json", b"1")

    with pytest.raises(InvalidOperationError):
        storage.move("/runs", "/archive")
    assert sorted(storage.files) == ["/runs/1.json"]


def test_move_onto_an_existing_folder_is_a_conflict(storage):
    storage.create("/a.txt", b"a")
    storage.create("/runs/1.json", b"1")

    with pytest.raises(ConflictError):
        storage.move("/a.txt", "/runs")
    assert sorted(storage.files) == ["/a.txt", "/runs/1.json"]


def test_delete_removes_a_folder_and_everything_in_it(storage):
    storage.create("/runs/1.json", b"1")
    storage.create("/runs/sub/2.json", b"2")
    storage.create("/runs2/3.json", b"3")

    storage.delete("/runs")

    assert sorted(storage.files) == ["/runs2/3.json"]


def test_calls_are_recorded_in_order(storage):
    storage.create("/a.txt", b"x")
    storage.download("/a.txt")

    assert storage.operations_called() == ["create", "download"]
    assert storage.calls[0].args == ("/a.txt", b"x")


def test_a_refused_write_changes_nothing(storage):
    storage.failures.fail_next("create", ProviderUnavailableError("down"))

    with pytest.raises(ProviderUnavailableError):
        storage.create("/a.txt", b"x")
    assert storage.files == {}


def test_a_lost_response_still_writes(storage):
    storage.failures.fail_next("create", ProviderUnavailableError("timed out"), applied=True)

    with pytest.raises(ProviderUnavailableError):
        storage.create("/a.txt", b"x")
    assert storage.download("/a.txt") == b"x"


def test_the_failing_storage_refuses_every_call():
    storage = failing_storage()

    for call in (lambda: storage.create("/a", b""), storage.check_health):
        with pytest.raises(ProviderUnavailableError):
            call()
    assert storage.files == {}
