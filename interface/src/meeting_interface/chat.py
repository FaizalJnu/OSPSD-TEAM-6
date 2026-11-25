"""Chat with the agent and approve or reject its proposals.

The routes collect what the person typed or chose and pass it to the agent
service. Approving sends back the proposal hash the person saw, so an approval
never covers changes they did not see; the agent service and the API check it.
"""

from collections.abc import Callable
from datetime import datetime
from typing import Annotated

from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from meeting_interface.agent_client import AgentClient, AgentError
from meeting_interface.agent_models import Proposal
from meeting_interface.form import DEFAULT_TIME_ZONE, TIME_ZONES
from meeting_interface.messages import agent_help, stop_reason_text


def meeting_time(start: object, end: object) -> str:
    """'Fri 27 Nov 2026, 15:00 to 15:30 (UTC-05:00)', in the offset the agent proposed."""
    try:
        begin = datetime.fromisoformat(str(start))
        finish = datetime.fromisoformat(str(end))
    except ValueError:
        return f"{start} to {end}"
    offset = begin.strftime("%z")
    zone = f"UTC{offset[:3]}:{offset[3:]}" if offset else "no time zone"
    day = begin.strftime("%a %d %b %Y")
    if finish.date() != begin.date():
        return f"{day}, {begin:%H:%M} to {finish:%a %d %b} {finish:%H:%M} ({zone})"
    return f"{day}, {begin:%H:%M} to {finish:%H:%M} ({zone})"


def add_chat_routes(app: FastAPI, templates: Jinja2Templates, agent: AgentClient) -> None:
    templates.env.globals.update(meeting_time=meeting_time, stop_reason_text=stop_reason_text)

    def fragment(request: Request, name: str, **context: object) -> HTMLResponse:
        return templates.TemplateResponse(request, f"partials/{name}.html", context)

    @app.get("/chat", response_class=HTMLResponse)
    def chat(request: Request) -> HTMLResponse:
        return templates.TemplateResponse(
            request, "chat.html", {"time_zones": TIME_ZONES, "default_zone": DEFAULT_TIME_ZONE}
        )

    @app.post("/chat/messages", response_class=HTMLResponse)
    def send(
        request: Request,
        text: Annotated[str, Form()] = "",
        conversation_id: Annotated[str, Form()] = "",
        time_zone: Annotated[str, Form()] = DEFAULT_TIME_ZONE,
    ) -> HTMLResponse:
        if not text.strip():
            return fragment(request, "exchange", problem="Type a message first.")
        try:
            if not conversation_id:
                zone = time_zone if time_zone in TIME_ZONES else DEFAULT_TIME_ZONE
                conversation_id = agent.start_conversation(zone).id
            reply = agent.send_message(conversation_id, text)
        except AgentError as error:
            return fragment(
                request,
                "exchange",
                text=text,
                conversation_id=conversation_id,
                error=error,
                help=agent_help(error.code),
            )
        return fragment(
            request, "exchange", text=text, conversation_id=conversation_id, reply=reply
        )

    @app.post("/proposals/{proposal_id}/approve", response_class=HTMLResponse)
    def approve(
        request: Request, proposal_id: str, proposal_hash: Annotated[str, Form()]
    ) -> HTMLResponse:
        return decide(
            request, proposal_id, proposal_hash, lambda: agent.approve(proposal_id, proposal_hash)
        )

    @app.post("/proposals/{proposal_id}/reject", response_class=HTMLResponse)
    def reject(request: Request, proposal_id: str) -> HTMLResponse:
        return decide(request, proposal_id, "", lambda: agent.reject(proposal_id))

    def decide(
        request: Request, proposal_id: str, proposal_hash: str, call: Callable[[], Proposal]
    ) -> HTMLResponse:
        try:
            proposal = call()
        except AgentError as error:
            return fragment(
                request,
                "decision",
                proposal_id=proposal_id,
                proposal_hash=proposal_hash,
                error=error,
                help=agent_help(error.code),
            )
        return fragment(request, "proposal", proposal=proposal)
