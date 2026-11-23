"""The interface reaches providers and the database only through our API service."""

import ast
from pathlib import Path

import meeting_interface

FORBIDDEN = {
    "boto3",
    "botocore",
    "google",
    "googleapiclient",
    "trello",
    "cloud_storage_api",
    "storage_service",
    "sqlalchemy",
    "psycopg",
    "sqlite3",
}


def imported_roots(source: str) -> set[str]:
    roots = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            roots |= {alias.name.split(".")[0] for alias in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            roots.add(node.module.split(".")[0])
    return roots


def test_no_module_imports_a_provider_sdk_or_database():
    package = Path(meeting_interface.__file__).parent
    offenders = {
        path.name: sorted(imported_roots(path.read_text()) & FORBIDDEN)
        for path in package.rglob("*.py")
    }

    assert {name: found for name, found in offenders.items() if found} == {}


def test_the_check_itself_catches_a_forbidden_import():
    assert imported_roots("import boto3\nfrom google.oauth2 import x") >= {"boto3", "google"}
