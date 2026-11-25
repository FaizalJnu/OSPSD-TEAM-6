# Getting started with Meeting Prep

Meeting Prep gets your weekly or sprint review ready. You ask for the meeting in your
own words. The agent reads your open issues, your calendar and your documents, then
proposes exactly what it will create: a tracker issue, a calendar event, and an agenda
document that links them. **Nothing is created until you approve it.**

It is for student project leads who run a regular review meeting.

## 1. Sign in

1. Open the link the team shared with you.
2. Select **Sign in with Google** at the top right, and choose your Google account.

The app is still in Google's testing mode, so only accounts the team has added can sign
in. If Google says the app is not verified or you are not allowed, send the email
address you use with Google to the team and ask to be added.

Your sign-in lasts 8 hours. If the page shows **Sign in with Google** again, your
session ended: sign in again. Nothing you prepared is lost.

## 2. Ask the agent

1. Select **Ask the agent**.
2. Check the **Time zone** box. Times you mention are read in that zone.
3. Type what you need and select **Send**. For example:
   * "Prepare Friday's sprint review at 3 pm from our open issues."
   * "Set up the review meeting for next Tuesday, 30 minutes, with the release on the agenda."

While it works, the page says **Working**. This can take up to a minute.

If the agent needs something, such as which day you mean, it asks. Answer in the same box.

## 3. Check the proposal, then approve or reject it

When the agent is ready, it shows a **Proposed changes** card with:

* the meeting title,
* the day and time, with its time offset,
* the agenda items,
* the operation it will run.

Read it. Then:

* **Approve** creates exactly what the card shows: the tracker issue, the calendar
  event and the agenda document.
* **Reject** creates nothing.
* To change something, don't approve. Tell the agent what to change; it shows a new
  card, and the old one can no longer be approved.

## 4. See what happened

After you approve, the card shows each change:

| You see | It means |
|---|---|
| **Done** | It was created. |
| **Failed** | It was not created. |
| **Not sure** | It may have been created. Check your tracker and calendar before asking again. |

## 5. If something goes wrong

The page always says what happened and what to do next. The common cases:

| The page says | What to do |
|---|---|
| This proposal changed since you saw it | Review the newest card in the chat and approve that one. |
| A newer proposal replaced this one | Approve the newer card instead. |
| The approved changes could not be made | Select **Approve again**. Nothing that already exists is created twice. If it says part of it may have happened, check your tracker and calendar first. |
| The agent is busy, or you sent several messages quickly | Wait the time it shows, then send again. |
| The agent stopped without an answer | Send the request again, or ask for less at once. |
| Your session has ended | Sign in with Google and send it again. |

## Prepare a meeting by hand

**Prepare by hand** runs the same workflow without the agent: fill in the title, date,
start and end time, time zone and agenda items (one per line), then select
**Prepare meeting**. The page shows each step: start the run, open the tracker issue,
book the calendar event, save the agenda, finish. Sending the same form again never
creates a second issue or event: it finishes whatever did not finish, or says the
meeting was already prepared.

## Sign out

Select **Sign out** at the top right. This ends your session on the server, not only in
this browser.

## Report a problem

Open an issue in our repository (during launch week, with the `launch-feedback` label). Say what you tried,
what happened, what you expected, and the run ID if the page showed one. Don't include
passwords or tokens.
