"""Approving sends the exact proposal the person saw, and the outcome is shown honestly."""

from meeting_interface.agent_client import AgentError
from meeting_interface.agent_models import Outcome, OutcomeStatus
from meeting_interface.fake_agent import REVIEW, proposal


def approve(client, proposal_id: str = "p-1", proposal_hash: str = "hash-p-1"):
    return client.post(f"/proposals/{proposal_id}/approve", data={"proposal_hash": proposal_hash})


def test_approve_sends_the_hash_from_the_card(client, fake_agent):
    approve(client, "p-1", "hash-p-1")

    assert fake_agent.approvals == [("p-1", "hash-p-1")]


def test_executed_proposal_shows_each_outcome(client, fake_agent):
    fake_agent.next_proposal = proposal(
        status="executed",
        outcomes=[Outcome(0, REVIEW.kind, OutcomeStatus.SUCCEEDED, {"run_id": "3f9a1c0d7b2e"})],
    )

    page = approve(client).text

    assert 'data-outcome="succeeded"' in page
    assert ">Done<" in page
    assert "3f9a1c0d7b2e" in page


def test_uncertain_outcome_is_never_shown_as_done(client, fake_agent):
    fake_agent.next_proposal = proposal(
        status="executed", outcomes=[Outcome(0, REVIEW.kind, OutcomeStatus.UNCERTAIN)]
    )

    page = approve(client).text

    assert ">Done<" not in page
    assert "Not sure" in page
    assert "may have happened" in page


def test_failed_outcome_is_shown_as_failed(client, fake_agent):
    fake_agent.next_proposal = proposal(
        status="executed", outcomes=[Outcome(0, REVIEW.kind, OutcomeStatus.FAILED)]
    )

    assert ">Failed<" in approve(client).text


def test_stale_proposal_asks_to_review_the_new_one(client, fake_agent):
    page = approve(client, "p-1", "old-hash").text

    assert "changed" in page
    assert "data-outcome" not in page


def test_superseded_and_rejected_say_so(client, fake_agent):
    fake_agent.next_error = AgentError("proposal_superseded", "x")
    superseded = approve(client).text
    fake_agent.next_error = AgentError("proposal_rejected", "x")
    rejected = approve(client).text

    assert "newer proposal" in superseded
    assert "was rejected" in rejected


def test_execution_failed_offers_approve_again_and_warns(client, fake_agent):
    page = approve(client, "fail-1", "hash-fail-1").text

    assert "Approve again" in page
    assert 'name="proposal_hash" value="hash-fail-1"' in page
    assert "may have been partly applied" in page or "may have happened" in page


def test_reject_marks_the_card_rejected(client, fake_agent):
    page = client.post("/proposals/p-1/reject").text

    assert fake_agent.rejections == ["p-1"]
    assert "Rejected" in page
    assert "Approve" not in page


def test_reject_of_a_proposal_that_is_not_pending(client, fake_agent):
    fake_agent.next_error = AgentError("proposal_not_pending", "x")

    page = client.post("/proposals/p-1/reject").text

    assert "no longer waiting" in page
