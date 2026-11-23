"""The interface's only way out: calls to our API service.

The interface never talks to a provider, another team's service, or the
database. Every failure, including an API that cannot be reached, arrives as
ApiError so pages handle one error type.
"""

from typing import Any, Protocol

import httpx2 as httpx

from meeting_interface.models import RunRequest, RunResult, StepOutcome

# Codes the interface itself produces when the API gives no documented error.
API_UNREACHABLE = "api_unreachable"
BAD_RESPONSE = "bad_response"


class ApiError(Exception):
    def __init__(
        self,
        code: str,
        message: str,
        *,
        step: str | None = None,
        steps: list[StepOutcome] | None = None,
    ) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message
        self.step = step
        self.steps = steps or []


class ApiClient(Protocol):
    def run_review_meeting(self, request: RunRequest) -> RunResult: ...

    def get_run(self, run_id: str) -> RunResult: ...


class HttpApiClient:
    def __init__(self, http: httpx.Client) -> None:
        self._http = http

    @classmethod
    def for_url(cls, base_url: str, timeout_seconds: float = 60.0) -> "HttpApiClient":
        return cls(httpx.Client(base_url=base_url, timeout=timeout_seconds))

    def run_review_meeting(self, request: RunRequest) -> RunResult:
        return RunResult.from_json(self._call("POST", "/v1/review-meetings", request.to_json()))

    def get_run(self, run_id: str) -> RunResult:
        return RunResult.from_json(self._call("GET", f"/v1/runs/{run_id}"))

    def _call(self, method: str, path: str, body: dict[str, Any] | None = None) -> dict[str, Any]:
        try:
            response = self._http.request(method, path, json=body)
        except httpx.HTTPError as error:
            raise ApiError(API_UNREACHABLE, "the service could not be reached") from error
        try:
            payload = response.json()
        except ValueError:
            payload = None
        if not isinstance(payload, dict):
            raise ApiError(
                BAD_RESPONSE, f"the service sent an unexpected reply ({response.status_code})"
            )
        if response.is_success:
            return payload
        raise _error_from(payload, response.status_code)


def _error_from(payload: dict[str, Any], status: int) -> ApiError:
    error = payload.get("error")
    if not isinstance(error, dict) or "code" not in error:
        return ApiError(BAD_RESPONSE, f"the service sent an unexpected reply ({status})")
    step = error.get("step")
    return ApiError(
        str(error["code"]),
        str(error.get("message", "")),
        step=None if step is None else str(step),
        steps=[StepOutcome.from_json(s) for s in error.get("steps", [])],
    )
