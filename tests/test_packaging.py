"""Other teams can use the shared DocumentStorage adapter without our HTTP service (#99).

The web framework is only required by the ``server`` extra, the adapter's import
chain never imports it, and ``document_storage_from_env`` builds a working adapter
from the same settings the service reads.
"""

import re
import subprocess
import sys
from importlib.metadata import requires

import pytest
from cloud_storage_api import DocumentStorage

from storage_service.config import ConfigError
from storage_service.wiring import document_storage_from_env

SERVER_PACKAGES = {"fastapi", "python-multipart", "uvicorn"}
WEB_MODULES = ("fastapi", "starlette", "uvicorn", "multipart", "python_multipart")


def _name(requirement: str) -> str:
    return re.split(r"[\s;<>=!~\[@]", requirement, maxsplit=1)[0].lower().replace("_", "-")


def _marker(requirement: str) -> str:
    """The environment marker, without spaces and with one quote style."""
    _, _, marker = requirement.partition(";")
    return marker.replace(" ", "").replace('"', "'")


def _import_without_web_framework(module: str) -> subprocess.CompletedProcess[str]:
    """Import ``module`` in a fresh interpreter where every web module fails to import."""
    code = "\n".join(
        [
            "import sys",
            f"for name in {WEB_MODULES!r}:",
            "    sys.modules[name] = None  # importing it now raises ModuleNotFoundError",
            f"import {module}",
        ]
    )
    return subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, timeout=60, check=False
    )


def test_only_the_server_extra_requires_the_web_framework():
    requirements = requires("storage-service") or []
    by_name: dict[str, list[str]] = {}
    for requirement in requirements:
        by_name.setdefault(_name(requirement), []).append(requirement)

    for package in SERVER_PACKAGES:
        assert by_name.get(package), f"{package} is missing from the package metadata"
        for requirement in by_name[package]:
            assert _marker(requirement) == "extra=='server'", requirement


def test_the_adapter_imports_without_the_web_framework():
    result = _import_without_web_framework("storage_service.wiring")

    assert result.returncode == 0, result.stderr


def test_the_http_app_still_needs_the_web_framework():
    # Control: blocking the web modules does stop an import that needs them, so
    # the test above cannot pass just because the block had no effect.
    result = _import_without_web_framework("storage_service.main")

    assert result.returncode != 0
    assert "import of fastapi halted" in result.stderr


def test_document_storage_from_env_builds_a_working_adapter():
    storage = document_storage_from_env({"STORAGE_BACKEND": "memory"})

    assert isinstance(storage, DocumentStorage)
    created = storage.create("/notes/a.txt", b"hello")
    assert created.path == "/notes/a.txt"
    assert storage.download("/notes/a.txt") == b"hello"


def test_document_storage_from_env_names_a_missing_setting():
    with pytest.raises(ConfigError, match="S3_BUCKET"):
        document_storage_from_env(
            {
                "STORAGE_BACKEND": "s3",
                "S3_ENDPOINT": "https://example.invalid",
                "S3_REGION": "r",
                "S3_ACCESS_KEY": "a",
                "S3_SECRET_KEY": "s",
            }
        )
