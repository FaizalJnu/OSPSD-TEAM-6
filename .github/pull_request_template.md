## Which issue does this PR close?
Closes #

## Problem and resulting behavior
What was missing or wrong, and what the service does now. For a change to existing
behavior, show before and after: request, status, body.

## Approach and why
Why this approach. Alternatives you considered. Assumptions you made. Compatibility
consequences (if this breaks the API, add the `breaking change` label).

## What changed
One line per changed file, naming the responsibility that required the change. If you
extended a teammate's code, say which module or interface changed and why the change
spread to other files.

## How it was verified
- Fast checks: commands run and results (for example, `uv run pytest`: 41 passed).
- Tests added or changed, and what each one asserts.
- Real-provider check: provider, request, expected result, observed result (paste the
  output, with no keys in it).
- Bug fixes: the failing test output before the fix, and the passing output after it.

## Status
- What works:
- What remains / known gaps:
- Who owns the next steps:
- Blocked on:

## AI assistance
Which tool you used and what it produced. "I reviewed every line and can explain it."

## Checklist
- [ ] Linked to an issue, one purpose
- [ ] ruff check, ruff format --check, mypy, and pytest pass locally; CI is green
- [ ] Tests cover the new behavior; a bug fix starts with a failing test
- [ ] docs/API.md, TESTING.md, and README updated where behavior or setup changed
- [ ] No .env, keys, or other secrets committed
- [ ] I reviewed my own diff
