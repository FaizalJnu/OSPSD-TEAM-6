"""One-off check of the Trello test account. Not part of the repository; delete when done.

Run from product/ with the settings loaded:

    cd product && uv run --env-file .env python ../trello-check.py

With TRELLO_LIST_ID empty, it prints the test account's boards and lists, so you can
copy the list's ID. With it set, it runs the calls the review-meeting workflow relies on
against that list and deletes the card it made. It prints IDs and error codes only,
never the key or token.
"""

import hashlib
import json
import os
import sys
from urllib.request import Request, urlopen

from issue_tracker_contract.errors import ServiceError
from team_4_issue_tracker_trello import TrelloIssueProvider


def show_lists() -> None:
    key, token = os.environ["TRELLO_API_KEY"], os.environ["TRELLO_TOKEN"]
    request = Request(
        "https://api.trello.com/1/members/me/boards?fields=name&lists=open&list_fields=name",
        headers={"Authorization": f'OAuth oauth_consumer_key="{key}", oauth_token="{token}"'},
    )
    with urlopen(request, timeout=10) as response:
        boards = json.load(response)
    for board in boards:
        print(f"board {board['name']!r}")
        for trello_list in board.get("lists", []):
            print(f"  list {trello_list['name']!r}: TRELLO_LIST_ID={trello_list['id']}")


def check(provider: TrelloIssueProvider) -> None:
    print("ping:", provider.ping())

    token = hashlib.sha256(b"trello-check").hexdigest()
    title = f"Review: trello check  double  spaces [{token[:12]}]"
    created = provider.create_tagged_issue(title, token)
    print("created card", created.id)
    try:
        fetched = provider.get_issue(created.id, fresh=True)
        print("title kept exactly:", fetched.title == title)
        found = provider.find_tagged_issue(token)
        print("find_tagged_issue finds it:", found is not None and found.id == created.id)
        newest = provider.list_issues(limit=1)
        print("newest in list_issues:", bool(newest) and newest[0].id == created.id)
    finally:
        provider.delete_issue(created.id)
        print("deleted card", created.id)


def main() -> None:
    for name in ("TRELLO_API_KEY", "TRELLO_TOKEN"):
        if not os.environ.get(name):
            sys.exit(f"{name} is not set in product/.env")
    try:
        if not os.environ.get("TRELLO_LIST_ID"):
            show_lists()
            print("\nCopy the list's ID into TRELLO_LIST_ID in product/.env and run again.")
            return
        check(TrelloIssueProvider())
    except ServiceError as error:
        sys.exit(f"failed: {error.code} (cause {error.cause}, may_have_applied {error.may_have_applied})")


if __name__ == "__main__":
    main()
