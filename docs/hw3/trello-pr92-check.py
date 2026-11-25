"""Live check of Team 4 PR #92 (constructor arguments) against our Trello test account.

One-off helper, not part of the repository. Run from the repo root:

    uv run --isolated --no-project --python 3.14 --env-file product/.env \
      --with "team-4-issue-tracker-trello @ git+https://github.com/Tyler-Arciniaga/OSPSD-Team-4.git@<commit>#subdirectory=team-4-trello-impl" \
      python -I docs/hw3/trello-pr92-check.py

It reads the key, token and list from the environment, then REMOVES the TRELLO_*
variables, so the provider can only get them through its constructor. Two
providers (lists To Do and Doing on the same board) create cards with interleaved
calls; each card must land in its own provider's list. Every card is deleted.
Prints IDs and error codes only, never the key or token.
"""

import hashlib
import json
import os
import sys
from urllib.request import Request, urlopen

from issue_tracker_contract.errors import ServiceError
from team_4_issue_tracker_trello import TrelloIssueProvider


def other_list(key: str, token: str, list_id: str, name: str) -> str:
    """ID of the list called `name` on the same board as `list_id`."""
    auth = {"Authorization": f'OAuth oauth_consumer_key="{key}", oauth_token="{token}"'}
    url = f"https://api.trello.com/1/lists/{list_id}?fields=idBoard"
    with urlopen(Request(url, headers=auth), timeout=10) as response:
        board_id = json.load(response)["idBoard"]
    url = f"https://api.trello.com/1/boards/{board_id}/lists?filter=open&fields=name"
    with urlopen(Request(url, headers=auth), timeout=10) as response:
        lists = json.load(response)
    found = [item["id"] for item in lists if item["name"] == name]
    if not found:
        sys.exit(f"no open list named {name!r}; lists: {[item['name'] for item in lists]}")
    return found[0]


def main() -> None:
    key = os.environ.pop("TRELLO_API_KEY")
    token = os.environ.pop("TRELLO_TOKEN")
    todo = os.environ.pop("TRELLO_LIST_ID")
    for name in [n for n in os.environ if n.startswith("TRELLO_")]:
        del os.environ[name]
    doing = other_list(key, token, todo, "Doing")

    print("no args, no environment -> constructs:", TrelloIssueProvider() is not None)
    try:
        TrelloIssueProvider().list_issues(limit=1)
    except ServiceError as error:
        print("no args, no environment -> call fails with:", error.code, error.cause)

    a = TrelloIssueProvider(api_key=key, token=token, list_id=todo)
    b = TrelloIssueProvider(api_key=key, token=token, list_id=doing)
    print("ping a (To Do):", a.ping(), " ping b (Doing):", b.ping())

    made: list[tuple[TrelloIssueProvider, str]] = []
    try:
        tok_a = hashlib.sha256(b"pr92-check-a").hexdigest()
        tok_b = hashlib.sha256(b"pr92-check-b").hexdigest()
        title_a = f"PR 92 check  A [{tok_a[:12]}]"
        card_a = a.create_tagged_issue(title_a, tok_a)
        made.append((a, card_a.id))
        card_b = b.create_issue(f"PR 92 check B [{tok_b[:12]}]")
        made.append((b, card_b.id))
        print("created", card_a.id, "via a and", card_b.id, "via b")

        ids_a = {i.id for i in a.list_issues(limit=100)}
        ids_b = {i.id for i in b.list_issues(limit=100)}
        print("a's card only in To Do:", card_a.id in ids_a and card_a.id not in ids_b)
        print("b's card only in Doing:", card_b.id in ids_b and card_b.id not in ids_a)
        print("a finds its tagged card:", (f := a.find_tagged_issue(tok_a)) is not None and f.id == card_a.id)
        print("b does not see a's tagged card:", b.find_tagged_issue(tok_a) is None)
        print("title kept exactly:", a.get_issue(card_a.id, fresh=True).title == title_a)
        print("card calls work across lists (b reads a's card):", b.get_issue(card_a.id).id == card_a.id)

        bad = TrelloIssueProvider(api_key=key, token="0" * 64, list_id=todo)
        try:
            bad.list_issues(limit=1)
            print("wrong token: no error (unexpected)")
        except ServiceError as error:
            leaked = token in str(error) or key in str(error) or "0" * 64 in str(error)
            print("wrong token ->", error.code, "cause", error.cause, "| credentials in error:", leaked)
        print("a still works after bad provider:", a.ping())
    finally:
        for provider, card_id in made:
            provider.delete_issue(card_id)
            print("deleted", card_id)


if __name__ == "__main__":
    try:
        main()
    except ServiceError as error:
        sys.exit(f"failed: {error.code} (cause {error.cause}, may_have_applied {error.may_have_applied})")
