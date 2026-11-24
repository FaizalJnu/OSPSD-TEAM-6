"""Who may import what.

Each rule restricts some modules to the parts of ``meeting_prep`` that may use
them. The test reads every module's source, so it covers modules no other test
imports. It sees ``import`` statements only; ``importlib.import_module`` with a
computed name gets past it, so do not do that in src/.

Owners: when you add a package (``api``, ``agent``, ``adapters`` ...), check the
rules still say what you mean, and tighten them for your own area.
"""

import ast
from dataclasses import dataclass
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[1] / "src"


@dataclass(frozen=True)
class Rule:
    reason: str
    imports: tuple[str, ...]
    only_in: tuple[str, ...] | None = None  # None: anywhere not in never_in
    never_in: tuple[str, ...] = ()

    def forbids(self, module: str, imported: str) -> bool:
        if not _within(imported, self.imports):
            return False
        if self.only_in is not None and not _within(module, self.only_in):
            return True
        return _within(module, self.never_in)


RULES = (
    Rule(
        "Implementations are chosen by configuration, so only the registry names them",
        imports=("storage_service", "team_4_issue_tracker_trello", "team5_calendar"),
        only_in=("meeting_prep.factories",),
    ),
    Rule(
        "Provider SDKs stay inside the implementation packages",
        imports=("boto3", "botocore", "googleapiclient", "google_auth_oauthlib", "httplib2"),
        only_in=(),
    ),
    Rule(
        "Only adapters see contract types and exceptions; fakes and the registry implement "
        "or build them",
        imports=("cloud_storage_api", "issue_tracker_contract", "calendar_contract"),
        only_in=("meeting_prep.adapters", "meeting_prep.fakes", "meeting_prep.factories"),
    ),
    Rule(
        "Fakes are chosen through the registry, never imported by service code",
        imports=("meeting_prep.fakes",),
        only_in=("meeting_prep.fakes", "meeting_prep.factories"),
    ),
    Rule(
        "Database code stays in meeting_prep.db, so every query is in one place",
        imports=("sqlalchemy", "alembic", "psycopg"),
        only_in=("meeting_prep.db",),
    ),
    Rule(
        "The workflow, adapters and agent run without a web framework",
        imports=("fastapi", "starlette", "uvicorn"),
        only_in=("meeting_prep.api",),
    ),
    Rule(
        "The model provider's SDK stays inside the model client",
        imports=("groq",),
        only_in=("meeting_prep.agent.model",),
    ),
    Rule(
        "The agent service reaches providers only through the API service, which checks approval",
        imports=(
            "meeting_prep.factories",
            "meeting_prep.adapters",
            "meeting_prep.orchestrator",
            "meeting_prep.fakes",
        ),
        never_in=("meeting_prep.agent",),
    ),
)


def _within(name: str, prefixes: tuple[str, ...]) -> bool:
    return any(name == prefix or name.startswith(f"{prefix}.") for prefix in prefixes)


def imported_names(module: str, source: str, *, is_package: bool) -> set[str]:
    """Every module name ``source`` imports, with relative imports made absolute.

    ``from a import b`` yields both ``a`` and ``a.b``, since ``b`` may be a module.
    """
    package = module if is_package else module.rpartition(".")[0]
    names: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            base = node.module or ""
            if node.level:
                parts = package.split(".")
                parent = ".".join(parts[: len(parts) - node.level + 1])
                base = f"{parent}.{base}" if base else parent
            names.add(base)
            names.update(f"{base}.{alias.name}" for alias in node.names)
    return names


def violations(module: str, source: str, *, is_package: bool = False) -> list[str]:
    return [
        f"{module} imports {imported}: {rule.reason}"
        for imported in sorted(imported_names(module, source, is_package=is_package))
        for rule in RULES
        if rule.forbids(module, imported)
    ]


def source_modules() -> list[tuple[str, Path]]:
    modules = []
    for path in sorted(SRC.rglob("*.py")):
        parts = path.relative_to(SRC).with_suffix("").parts
        modules.append((".".join(parts), path))
    return modules


def test_finds_the_source_modules():
    names = {name for name, _ in source_modules()}

    assert "meeting_prep.factories" in names
    assert "meeting_prep.db.migrations.env" in names


def test_no_module_breaks_an_import_rule():
    found = []
    for name, path in source_modules():
        is_package = path.name == "__init__.py"
        module = name.removesuffix(".__init__")
        found += violations(module, path.read_text(), is_package=is_package)

    assert found == []


@pytest.mark.parametrize(
    ("module", "source", "is_package"),
    [
        ("meeting_prep.orchestrator", "import team5_calendar", False),
        ("meeting_prep.api.routes", "from storage_service.wiring import build_service", False),
        ("meeting_prep.orchestrator", "from calendar_contract import CalendarError", False),
        ("meeting_prep.api.routes", "from meeting_prep import fakes", False),
        ("meeting_prep.agent.loop", "from sqlalchemy import select", False),
        ("meeting_prep.orchestrator", "from fastapi import FastAPI", False),
        ("meeting_prep.agent.loop", "from ..factories import build_implementations", False),
        ("meeting_prep.agent", "from .. import adapters", True),
        ("meeting_prep.factories", "import boto3", False),
        ("meeting_prep.agent.loop", "from fastapi import FastAPI", False),
        ("meeting_prep.agent.app", "from starlette.applications import Starlette", False),
        ("meeting_prep.agent.tools", "from meeting_prep.orchestrator import Orchestrator", False),
        ("meeting_prep.agent.loop", "from meeting_prep.fakes import FakeCalendar", False),
        ("meeting_prep.agent.tools", "from meeting_prep.adapters import StepError", False),
        ("meeting_prep.agent.loop", "import groq", False),
        ("meeting_prep.orchestrator", "from groq import AsyncGroq", False),
    ],
)
def test_the_checker_catches_a_forbidden_import(module, source, is_package):
    assert violations(module, source, is_package=is_package)


@pytest.mark.parametrize(
    ("module", "source"),
    [
        ("meeting_prep.factories", "from team5_calendar import create_calendar_service"),
        ("meeting_prep.adapters.calendar", "from calendar_contract import CalendarError"),
        ("meeting_prep.db.engine", "from sqlalchemy import create_engine"),
        ("meeting_prep.api.main", "from fastapi import FastAPI"),
        ("meeting_prep.agent.model", "from groq import AsyncGroq"),
        ("meeting_prep.agent.loop", "from meeting_prep.agent.model import ModelClient"),
        ("meeting_prep.api.routes", "from meeting_prep.factories import build_implementations"),
    ],
)
def test_the_checker_allows_an_import_the_rules_permit(module, source):
    assert violations(module, source) == []
