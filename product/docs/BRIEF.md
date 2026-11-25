# Meeting Prep: product brief

Team 6 (Document Storage vertical): Faizal Rahman, Debasmith Mandal, Vikram Markali,
Darsh Shani, Prateek Saxena. Last updated 2026-11-25.

**Format:** a one-page product requirements document. Our product has several
requirements that depend on each other (three providers, sign-in, approval before any
change), and this format lists goals, users, requirements and success metrics
explicitly, so a reviewer can check each one against the build.

## Problem

It is Thursday night, and the lead of a five-person course project is setting up
Friday's sprint review. They open Trello and copy the open cards into a new document,
decide which ones need discussion, create a calendar event, paste the document's link
into it, and add a card so the review itself is tracked. That takes three tools and a
dozen copy-and-pastes. By Friday two cards have closed and one has been added, so the
agenda is already out of date, and nobody is sure which copy of the document is
current. Next week they do it all again.

The work is not hard, but it is repeated every week by hand, and the pieces drift
apart because nothing connects them.

## What changes

Meeting Prep builds the agenda from the tracker's current state at the moment the
lead asks, and creates the tracker card, the calendar event and the agenda document
together, linked to each other, from one approval. Preparing a review stops being a
copy job across three tools and becomes one decision the lead reviews: what the
meeting is, when it is, and what is on it. The agent proposes; nothing changes until
the lead approves, and asking again never creates a second copy.

## User

Student project leads who run a weekly or sprint review for a team of 3 to 8 people.
They track work in Trello, schedule in Google Calendar, and keep meeting notes in
shared documents. They prepare the review themselves, usually the evening before, and
they want the meeting to start from the real state of the work.

We are **not** building for:

* people who want an assistant to manage their whole calendar, inbox or files;
* teams on GitHub Issues, Jira, Outlook or Microsoft 365: the first version supports
  only Trello and Google Calendar, the implementations our partner teams provide;
* managers who need reports across several teams;
* anyone who wants changes made without reviewing them first.

## Evidence

**To fill (Faizal, from `DISCOVERY.md`):** two or three quotes from the conversations,
each with the person's role, and what we observed versus what we assume.

**Is this only our team's problem?** **To fill**, from the conversations: how many of
the people we spoke to prepare a recurring review, and which tools they use.

## Key scenarios

### 1. Prepare a review meeting (must; uses all three verticals)

1. The lead signs in with Google. The first time, they connect their Trello account
   and choose their team's list, and connect their Google Calendar. Their documents
   are kept in a private space in our storage, so there is nothing to connect for it.
2. They type: "Prepare Friday's sprint review at 3 pm from our open issues."
3. The agent reads the open issues in Trello and the upcoming events in the calendar.
   If something is unclear, such as which Friday, it asks.
4. It shows a **proposed changes** card: the title, the day and time with its time
   zone offset, the agenda items, and what it will create.
5. The lead approves. The service checks that approval against that exact proposal,
   then creates the Trello card, the calendar event and the agenda document, and shows
   each one as done, failed or not sure.
6. If a step failed, approving again finishes only what is missing. Nothing that
   already exists is created twice.

### 2. What's on for my next review? (should; read only)

The lead asks "What's on for Friday's review?" The agent finds the next review in the
calendar, reads its saved agenda, and lists the issues opened or still open since
then. It changes nothing, so no approval is needed.

## Scope

| Priority | First version |
|---|---|
| **Must** | Sign in with Google; sign out on the server. Connect and disconnect Trello and Google Calendar for each user, with no fallback to a shared account. Scenario 1 through the chat, with approval of the exact changes. The same workflow by hand, without the agent. Safe retries: no duplicate card or event. Each user's data kept apart from every other user's. |
| **Should** | Scenario 2. Times read in the user's own time zone. A clear "reconnect" message when a provider connection expires. |
| **Won't** | **Post-meeting follow-ups** (the lead pastes the notes; the agent proposes a card for each action item and saves a summary): we had three days to build the product, and scenario 1 needed all of it. We add it after launch only if launch-week users ask for it. **Other trackers and calendars:** our partner teams provide Trello and Google Calendar, and adding a provider means a new implementation and new tests. **Editing or deleting existing cards and events:** the first version only creates, so a wrong proposal can never destroy a user's data. **Inviting attendees or sending email:** it would act on other people's accounts, which our approval model does not cover. **A background agent that works without the user present:** every change needs the user's approval in the conversation. |

## Success metrics

Measured during launch week (Dec 2 to 6) from the agent's run records and the
execution outcomes the service stores.

| Scenario | Outcome we measure | Target |
|---|---|---|
| 1. Prepare a review | Share of scenario-1 conversations that end in an approved proposal whose three changes all succeed | At least 60% |
| 1. Prepare a review | Median time from the first message to approval | At most 3 minutes |
| 1. Prepare a review | Users who prepare a second review in the same week | At least 3 |
| 2. Next review | Share of questions answered (the run completes with a reply, no tool error) | At least 80% |

We chose 60% because launch week is the first use by people outside the team, and in
our own pre-launch runs the agent sometimes answered with text instead of a proposal.
The evaluation results set the baseline we compare against.

**Guardrails** (target: zero, every week):

* a provider change made without a stored approval of that exact proposal;
* one user seeing or changing another user's data;
* a second card or event created by a retry;
* a credential in a log, a prompt or a run record;
* a request that uses another user's or the team's own provider account.

## Assumptions and risks

Ranked by the damage if the assumption is wrong.

| # | Assumption | If it is wrong | Status |
|---|---|---|---|
| 1 | Leads want to approve a proposal rather than have the agent act directly | The approval step is friction, and users drop off at the proposal card | Product assumption test below |
| 2 | Each user can connect their own Trello and Google Calendar through our partner teams' packages | We cannot serve anyone beyond our own test account | Team 4's Trello package takes a key and token as arguments since its v1.1.0 tag. Team 5's calendar package needs a credentials argument: our pull request adds it; until it is released we install from our pull request's commit |
| 3 | Our users use Trello and Google Calendar | The product does not fit their tools | **To fill** from discovery |
| 4 | A retried run never creates a duplicate card or event | Users find two cards or events after a failure | Passes on fakes for every failure point; the live resume test runs once the test accounts are configured |
| 5 | Groq's free tier is enough for launch week | Users wait or are refused | Technical assumption test below: partly holds |
| 6 | The model reads dates and times correctly | Meetings land on the wrong day | Measured: correct dates went from 1 of 4 proposals to 5 of 5 after we gave the model today's date and the user's time zone |
| 7 | Users reconnect Google Calendar weekly | Connections silently stop working | Google issues 7-day refresh tokens while our app is in testing mode; the getting-started page explains how to reconnect |

## Assumption tests

### Technical: one review run fits Groq's free-tier token limit (Vikram, 2026-11-23)

* **Belief:** one scenario-1 run fits inside Groq's limit of 8,000 tokens per minute,
  with room for more than one user per minute.
* **Test:** five runs of the real agent with the live model, the same request
  ("Prepare our sprint review for next Tuesday 3 to 3:30 pm Eastern from the open
  issues"), each in a new conversation, one minute apart.
* **Observed:** runs that reached a proposal used 4,212 to 4,486 tokens and took about
  3 seconds. No run hit a limit. Two of five answered with text instead of a proposal.
* **Decision:** the assumption partly holds. One run fits in a minute; two do not. We
  plan launch capacity at one scenario-1 run per minute, share one token budget across
  all users, and answer "busy, try again in N seconds" beyond it. Details:
  [assumption-groq-budget.md](assumption-groq-budget.md).

### Product: leads want proposals, not automatic actions (Faizal)

* **Belief:** leads would rather approve the exact changes than have the agent create
  them directly, even though approving takes one more step.
* **Why it matters:** the whole product is built around approval. If leads find it a
  burden, the drop-off at the proposal card decides our main success metric.
* **Test:** show five project leads the same request handled two ways: (A) the agent
  creates the card, event and document and reports what it did; (B) the agent shows
  the proposed changes and waits for approval. Ask which they would use for their next
  review and why, then watch one of them approve a real proposal on staging.
* **What would change our mind:** if most choose (A), we would offer "approve
  automatically next time" for proposals that only create.
* **Observed:** **To fill.**
* **Decision:** **To fill.**

## Open questions

| Question | Owner | Decide by |
|---|---|---|
| Will Team 5 release the credentials and upcoming-events change, or do we launch on our pull request's commit? | Faizal | Dec 1 |
| Do launch-week users already have Trello accounts and a board, or does the getting-started page need a "create a board" step? | Faizal | Dec 1 |
| Is one agent run per minute enough for launch week, or do we need shorter prompts or a paid model tier? Decided from the load test | Prateek, Vikram | Dec 1 |
| Which two teams use our product in launch week, and are all their members on the Google test-user list? | Faizal | Dec 2 |
| Do we build post-meeting follow-ups after launch? Decided from launch feedback | Faizal | Dec 8 |

## Plan and tracker

GitHub project board with the Milestone 2 (Dec 2) and Milestone 3 (Dec 9) milestones:
**To fill: link.** Each issue names an owner, the scenario it supports, and how we
check it is done. Scenario 1 is built first, end to end, and is never cut. If time runs
short, scenario 2 is cut first.

## Links

* Design document: **To fill: shared link to the team's design document**
* Getting started: [interface/GETTING_STARTED.md](../../interface/GETTING_STARTED.md)
* Discovery notes: [DISCOVERY.md](DISCOVERY.md)
* Launch readiness record: [READINESS.md](READINESS.md)
* Agent tools and their contracts: [agent.md](agent.md)
