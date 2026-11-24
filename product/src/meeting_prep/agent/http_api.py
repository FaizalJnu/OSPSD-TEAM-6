"""The agent's HTTP client for the user API. It forwards the current user's session."""

from collections.abc import Callable, Mapping

import httpx2
from pydantic import TypeAdapter, ValidationError

from meeting_prep.agent.api_client import (
    ActionOutcome,
    ApiError,
    Document,
    OpenIssue,
    UpcomingEvent,
)
from meeting_prep.agent.proposals import Approval, Proposal

_ISSUES = TypeAdapter(list[OpenIssue])
_EVENTS = TypeAdapter(list[UpcomingEvent])
_DOCUMENT = TypeAdapter(Document)
_OUTCOMES = TypeAdapter(list[ActionOutcome])


class HttpApiClient:
    def __init__(self, base_url: str, session_for: Callable[[str], str | None]) -> None:
        self.base_url, self.session_for = base_url, session_for

    async def list_open_issues(self, user: str, limit: int) -> list[OpenIssue]:
        payload = await self._request(user, "GET", "/v1/issues/open", params={"limit": limit})
        return _parse(_ISSUES, payload.get("issues"))

    async def list_upcoming_events(self, user: str, days: int) -> list[UpcomingEvent]:
        payload = await self._request(user, "GET", "/v1/calendar/upcoming", params={"days": days})
        return _parse(_EVENTS, payload.get("events"))

    async def read_document(self, user: str, path: str) -> Document:
        payload = await self._request(user, "GET", "/v1/documents", params={"path": path})
        return _parse(_DOCUMENT, payload)

    async def execute(
        self, user: str, proposal: Proposal, approval: Approval
    ) -> list[ActionOutcome]:
        payload = await self._request(
            user,
            "POST",
            f"/v1/proposals/{proposal.id}/execute",
            body={"approval_id": approval.id, "proposal_hash": proposal.hash},
        )
        return _parse(_OUTCOMES, payload.get("outcomes"), write=True)

    async def _request(
        self,
        user: str,
        method: str,
        path: str,
        *,
        params: Mapping[str, str | int] | None = None,
        body: dict[str, str] | None = None,
    ) -> dict[str, object]:
        token = self.session_for(user)
        if token is None:
            raise ApiError("unauthorized", "A verified session is required.")
        write = method == "POST"
        try:
            async with httpx2.AsyncClient(
                base_url=self.base_url,
                headers={"Authorization": f"Bearer {token}"},
                follow_redirects=False,
                timeout=httpx2.Timeout(180, connect=5),
            ) as client:
                response = await client.request(method, path, params=params, json=body)
        except httpx2.HTTPError:
            raise ApiError(
                "api_unavailable", "The meeting API could not be reached.", may_have_applied=write
            ) from None
        try:
            payload = response.json()
        except ValueError:
            payload = None
        if not isinstance(payload, dict):
            raise ApiError(
                "api_error", "The meeting API returned an invalid response.", may_have_applied=write
            )
        if response.is_success:
            return payload
        error = payload.get("error")
        code = error.get("code") if isinstance(error, dict) else None
        raise ApiError(
            code if isinstance(code, str) else "api_error",
            "The meeting API could not complete this operation.",
            may_have_applied=write
            and (
                payload.get("may_have_applied") is True
                or (response.status_code >= 500 and "may_have_applied" not in payload)
            ),
        )


def _parse[T](adapter: TypeAdapter[T], value: object, *, write: bool = False) -> T:
    try:
        return adapter.validate_python(value)
    except ValidationError:
        raise ApiError(
            "api_error", "The meeting API returned an invalid response.", may_have_applied=write
        ) from None
