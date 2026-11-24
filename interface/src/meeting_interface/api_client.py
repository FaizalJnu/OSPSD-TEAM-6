"""The interface's only way out: calls to our API service.

The interface never talks to a provider, another team's service, or the
database. Every failure, including an API that cannot be reached, arrives as
ApiError so pages handle one error type. The API key stays on the server; it
never reaches a page.
"""

from typing import Any, Protocol

import httpx2 as httpx

from meeting_interface.models import Run, RunRequest, RunResult

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
        retryable: bool = False,
        may_have_applied: bool = False,
        run: Run | None = None,
        retry_after: int | None = None,
    ) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message
        self.step = step
        self.retryable = retryable
        self.may_have_applied = may_have_applied
        self.run = run
        self.retry_after = retry_after


class ApiClient(Protocol):
    def run_review_meeting(self, request: RunRequest) -> RunResult: ...


class HttpApiClient:
    def __init__(self, http: httpx.Client, api_key: str) -> None:
        self._http = http
        self._api_key = api_key

    @classmethod
    def for_url(
        cls, base_url: str, api_key: str, timeout_seconds: float = 120.0
    ) -> "HttpApiClient":
        return cls(httpx.Client(base_url=base_url, timeout=timeout_seconds), api_key)

    def run_review_meeting(self, request: RunRequest) -> RunResult:
        try:
            response = self._http.post(
                "/v1/review-meetings",
                json=request.to_json(),
                headers={"Authorization": f"Bearer {self._api_key}"},
            )
        except httpx.HTTPError as error:
            raise ApiError(API_UNREACHABLE, "the service could not be reached") from error
        try:
            payload = response.json()
        except ValueError:
            payload = None
        if not isinstance(payload, dict):
            raise _bad_response(response.status_code)
        try:
            if response.is_success:
                return RunResult.from_json(payload)
            failure = _error_from(payload, response)
        except (KeyError, TypeError) as broken:
            raise _bad_response(response.status_code) from broken
        raise failure


def _error_from(payload: dict[str, Any], response: httpx.Response) -> ApiError:
    error = payload.get("error")
    if not isinstance(error, dict) or "code" not in error:
        return _bad_response(response.status_code)
    run = payload.get("run")
    step = error.get("step")
    return ApiError(
        str(error["code"]),
        str(error.get("message", "")),
        step=None if step is None else str(step),
        retryable=error.get("retryable") is True,
        may_have_applied=error.get("may_have_applied") is True,
        run=Run.from_json(run) if isinstance(run, dict) else None,
        retry_after=_seconds(response.headers.get("retry-after")),
    )


def _seconds(value: str | None) -> int | None:
    return int(value) if value is not None and value.isdigit() else None


def _bad_response(status: int) -> ApiError:
    return ApiError(BAD_RESPONSE, f"the service sent an unexpected reply ({status})")
