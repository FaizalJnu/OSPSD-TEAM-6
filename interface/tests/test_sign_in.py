"""Sign-in and sign-out screens over the API's /v1/auth routes.

The browser holds the session cookie the API set after Google sign-in. The
interface reads it, asks the API who it belongs to, and forwards it as a Bearer
token to the agent service. It never shows or logs the token.
"""

from tests.conftest import ORIGIN, SESSION_COOKIE, TOKEN


def test_signed_out_page_offers_sign_in(anon):
    page = anon.get("/chat").text

    assert 'href="/v1/auth/sign-in"' in page
    assert "Sign out" not in page


def test_signed_out_chat_asks_to_sign_in_and_has_no_message_box(anon):
    page = anon.get("/chat").text

    assert "Sign in to ask the agent" in page
    assert 'name="text"' not in page


def test_signed_in_page_shows_the_email_and_sign_out(client, fake_auth):
    page = client.get("/chat").text

    assert "a@example.com" in page
    assert 'action="/sign-out"' in page
    assert fake_auth.looked_up == [TOKEN]


def test_the_session_token_never_reaches_the_page(client):
    page = client.get("/chat").text

    assert TOKEN not in page


def test_an_expired_or_revoked_session_is_signed_out(client, fake_auth):
    fake_auth.users.clear()

    page = client.get("/chat").text

    assert 'href="/v1/auth/sign-in"' in page
    assert "a@example.com" not in page


def test_the_email_is_escaped(client, fake_auth):
    fake_auth.users[TOKEN] = "<b>x</b>@example.com"

    page = client.get("/chat").text

    assert "<b>x</b>" not in page


def test_sign_out_revokes_the_session_and_clears_the_cookie(client, fake_auth):
    response = client.post("/sign-out", headers={"Origin": ORIGIN}, follow_redirects=False)

    assert response.status_code == 303
    assert response.headers["location"] == "/"
    assert fake_auth.revoked == [TOKEN]
    cookie = response.headers["set-cookie"]
    assert cookie.startswith(f"{SESSION_COOKIE}=")
    assert "Max-Age=0" in cookie


def test_sign_out_from_another_site_is_refused(client, fake_auth):
    response = client.post(
        "/sign-out", headers={"Origin": "https://evil.example"}, follow_redirects=False
    )

    assert response.status_code == 403
    assert fake_auth.revoked == []


def test_sign_out_without_an_origin_is_refused(client, fake_auth):
    response = client.post("/sign-out", follow_redirects=False)

    assert response.status_code == 403
    assert fake_auth.revoked == []


def test_sign_out_when_already_signed_out_just_goes_home(anon, fake_auth):
    response = anon.post("/sign-out", headers={"Origin": ORIGIN}, follow_redirects=False)

    assert response.status_code == 303
    assert fake_auth.revoked == []


def test_signed_out_message_is_not_sent_to_the_agent(anon, fake_agent):
    page = anon.post(
        "/chat/messages", data={"conversation_id": "", "time_zone": "UTC", "text": "prep"}
    ).text

    assert fake_agent.sent == []
    assert "Sign in" in page


def test_signed_out_approval_is_not_sent(anon, fake_agent):
    anon.post("/proposals/p-1/approve", data={"proposal_hash": "hash-p-1"})

    assert fake_agent.approvals == []


def test_the_agent_is_called_as_the_signed_in_user(client, fake_agent):
    client.post("/chat/messages", data={"conversation_id": "", "time_zone": "UTC", "text": "hi"})
    client.post("/proposals/p-1/approve", data={"proposal_hash": "hash-p-1"})

    assert fake_agent.tokens == [TOKEN, TOKEN]
