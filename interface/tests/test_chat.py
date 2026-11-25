"""A person asks the agent in plain words and sees its reply and any proposal."""

from markupsafe import escape

from meeting_interface.agent_client import AgentError
from meeting_interface.agent_models import MessageReply
from meeting_interface.fake_agent import proposal
from meeting_interface.messages import STOP_REASONS

FIRST = {"conversation_id": "", "time_zone": "America/New_York", "text": "prep my Friday review"}


def test_chat_page_has_the_message_form(client):
    page = client.get("/chat").text

    assert 'hx-post="/chat/messages"' in page
    assert 'name="text"' in page
    assert 'id="conversation-id"' in page
    assert '<option value="America/New_York" selected>' in page


def test_first_message_starts_a_conversation_in_the_chosen_zone(client, fake_agent):
    page = client.post("/chat/messages", data=FIRST).text

    assert fake_agent.started == ["America/New_York"]
    assert fake_agent.sent == [("c-1", "prep my Friday review")]
    assert 'id="conversation-id"' in page
    assert 'value="c-1"' in page
    assert 'hx-swap-oob="true"' in page


def test_later_messages_reuse_the_conversation(client, fake_agent):
    client.post("/chat/messages", data={**FIRST, "conversation_id": "c-9", "text": "hello"})

    assert fake_agent.started == []
    assert fake_agent.sent == [("c-9", "hello")]


def test_both_sides_of_the_exchange_are_shown(client):
    page = client.post("/chat/messages", data=FIRST).text

    assert "prep my Friday review" in page
    assert "Approve it to go ahead." in page


def test_proposal_card_shows_the_exact_changes(client):
    page = client.post("/chat/messages", data=FIRST).text

    assert "Sprint review" in page
    assert "Open bugs" in page
    assert "Release go or no-go" in page
    assert "Fri 27 Nov 2026" in page
    assert "15:00" in page and "15:30" in page
    assert "POST /v1/review-meetings" in page
    assert 'name="proposal_hash" value="hash-p-1"' in page
    assert 'hx-post="/proposals/p-1/approve"' in page
    assert 'hx-post="/proposals/p-1/reject"' in page


def test_reply_without_a_proposal_has_no_approve_button(client, fake_agent):
    page = client.post("/chat/messages", data={**FIRST, "text": "hello"}).text

    assert "Approve" not in page


def test_a_run_that_stopped_early_says_why(client, fake_agent):
    fake_agent.next_reply = MessageReply(None, "token_limit", "r-1", None, None)

    page = client.post("/chat/messages", data=FIRST).text

    assert str(escape(STOP_REASONS["token_limit"])) in page


def test_busy_agent_says_how_long_to_wait(client, fake_agent):
    fake_agent.next_error = AgentError("busy", "busy", retry_after=42)

    page = client.post("/chat/messages", data=FIRST).text

    assert "about 42 seconds" in page


def test_empty_message_is_not_sent(client, fake_agent):
    page = client.post("/chat/messages", data={**FIRST, "text": "   "}).text

    assert fake_agent.sent == []
    assert "Type a message" in page


def test_superseded_note_names_the_old_proposal(client, fake_agent):
    fake_agent.next_reply = MessageReply(
        "Changed the time.", "completed", "r-2", proposal("p-2", supersedes="p-1"), None
    )

    page = client.post("/chat/messages", data=FIRST).text

    assert "replaces the earlier proposal" in page
