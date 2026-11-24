"""Tools the agent may call: a name, a description, an argument model and a handler.

The argument model's JSON schema is what the model sees. The model's arguments are
validated against it before the handler runs, so a handler only ever receives a
valid instance. A handler returns a structured result (a pydantic model or a dict),
or raises ``ToolError`` with a code and a message meant for the model.

Validation errors keep each problem's location, type and message, never the input
value: the model's raw arguments can echo anything from the conversation.
"""

import json
import re
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, ValidationError

from meeting_prep.agent.model import ToolSpec

_NAME = re.compile(r"[a-zA-Z0-9_-]{1,64}")

ToolResult = BaseModel | Mapping[str, object]


class ToolError(Exception):
    """A handler's failure, reported to the model as ``{"error": {code, message}}``."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message


class UnknownTool(ToolError):
    def __init__(self, name: str, known: list[str]) -> None:
        available = ", ".join(known) or "none"
        super().__init__("unknown_tool", f"no tool named {name!r}; available: {available}")


class InvalidArguments(ToolError):
    """The arguments are not JSON, not an object, or break the tool's argument model."""

    def __init__(self, message: str, problems: list[dict[str, object]] | None = None) -> None:
        super().__init__("invalid_arguments", message)
        self.problems = problems or []


@dataclass(frozen=True)
class Tool[ArgsT: BaseModel]:
    name: str
    description: str
    arguments: type[ArgsT]
    handler: Callable[[ArgsT], Awaitable[ToolResult]]

    def __post_init__(self) -> None:
        if not _NAME.fullmatch(self.name):
            raise ValueError("a tool name is 1 to 64 letters, digits, '_' or '-'")

    def spec(self) -> ToolSpec:
        return ToolSpec(self.name, self.description, self.arguments.model_json_schema())


class ToolRegistry:
    def __init__(self, tools: list[Tool[Any]] | None = None) -> None:
        self._tools: dict[str, Tool[Any]] = {}
        for tool in tools or []:
            self.register(tool)

    def register(self, tool: Tool[Any]) -> None:
        if tool.name in self._tools:
            raise ValueError(f"a tool named {tool.name!r} is already registered")
        self._tools[tool.name] = tool

    def names(self) -> list[str]:
        return sorted(self._tools)

    def specs(self) -> list[ToolSpec]:
        return [self._tools[name].spec() for name in self.names()]

    def validate(self, name: str, raw_arguments: str) -> tuple[Tool[Any], BaseModel]:
        """The tool and its validated arguments. Raises UnknownTool or InvalidArguments."""
        tool = self._tools.get(name)
        if tool is None:
            raise UnknownTool(name, self.names())
        try:
            parsed = json.loads(raw_arguments or "{}")
        except json.JSONDecodeError:
            raise InvalidArguments("the arguments are not valid JSON") from None
        if not isinstance(parsed, dict):
            raise InvalidArguments("the arguments must be a JSON object")
        try:
            return tool, tool.arguments.model_validate(parsed)
        except ValidationError as error:
            problems: list[dict[str, object]] = [
                {"loc": list(problem["loc"]), "type": problem["type"], "msg": problem["msg"]}
                for problem in error.errors(include_input=False, include_url=False)
            ]
            raise InvalidArguments(
                "the arguments do not match the tool's schema", problems
            ) from None


def result_json(result: ToolResult) -> dict[str, object]:
    """A handler's result as JSON-ready data. Secret fields stay masked."""
    if isinstance(result, BaseModel):
        dumped: dict[str, object] = result.model_dump(mode="json")
        return dumped
    return dict(result)
