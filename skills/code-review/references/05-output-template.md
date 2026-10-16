# Output Template

Use this structure exactly. Omit a section only where noted. Keep it concise — the reader is busy,
and every extra sentence competes with the finding that matters.

---

```markdown
# Code Review — <PR title / branch / files>

## Summary
**Scope:** <what was reviewed, against which base; anything only skimmed>
**Intent:** <one or two sentences — what this change is meant to do>
**Lens / level:** <senior dev · tech lead · architect> / <L1 · L2 · L3, and why>
**Findings:** P0: n · P1: n · P2: n · P3: n · Info: n
**Main risks:** <one or two lines>
**Safe to merge?** <yes / yes after follow-ups / no — one-line reason>

## Findings

### [P1 · Bug · Confirmed] <Short title>
**Where:** `path/to/file.py:42-58`
**What's wrong:** <the defect, in one or two sentences>
**Scenario:** <concrete inputs or sequence → what happens>
**Impact:** <who is affected and how badly>
**Fix:** <a practical change — a short snippet if it is clearer than prose>
**Regression test:** <the test that would fail today and pass after the fix>
**How it was spotted:** <the signal in the code that made it worth a second look>

### [P2 · Trade-off] <Short title>
**Where:** …
**Choice made:** <what the code does>
**Cost:** <what it gives up, concretely>
**When to revisit:** <the trigger that would make the other choice better>

## Pre-existing issues (not introduced by this change)
<Only P0/P1. Omit the section if none.>

## Positive observations
- <specific and genuine; omit the section rather than pad it>

## Missing tests
- <the most important untested behaviours — not repeating findings>

## Top 3 observations
1. <the single most important thing about this change>
2. …
3. …

## Questions before approval
1. <question> — *why it matters:* <how the answer changes the verdict>
<or "None.">

## Recommendation
**<Approve | Approve with minor follow-ups | Request changes | Block merge pending critical fixes>**
— <one-sentence reason grounded in the findings>
```

---

## A worked finding

### [P1 · Bug · Confirmed] Session ownership check removed — any user can read another user's chat

**Where:** `app/chat_api.py:31` (`load_history(conn, req.session_id)`)
**What's wrong:** The previous version selected the session `WHERE id = $1 AND user_id = $2` and
returned 404 when it did not match. This change loads history by `session_id` alone.
**Scenario:** User A sends `POST /chat` with User B's `session_id`. B's full history is loaded
into the prompt, the model answers from it, and A's message and the reply are written into B's
session.
**Impact:** Cross-user data disclosure and corruption of another user's conversation. Severity
depends on how guessable session IDs are — a UUID makes it hard to exploit blindly but not safe
(IDs appear in URLs, logs, and shared links).
**Fix:** Restore the ownership check before any read or write:
```python
session = await sessions.get_owned(conn, req.session_id, user.id)
if session is None:
    raise HTTPException(status_code=404, detail="session not found")
```
**Regression test:** As user A, `POST /chat` with user B's session ID → expect 404 and no rows
written to B's session.
**How it was spotted:** A red line in the diff — the `AND user_id = $2` query was deleted, and
nothing new took its place. Every lookup by a request-supplied ID needs an ownership answer.

---

## Posting to a PR (only on explicit request, after the review)

Use **Conventional Comments** so the author knows what blocks and what does not:

```
<label> [decorations]: <subject>

<discussion>
```

| Label | Use for |
|---|---|
| `issue (blocking):` | P0/P1 bugs |
| `issue (non-blocking):` | P2/P3 bugs the author can fix in a follow-up |
| `suggestion:` | A concrete improvement with a stated benefit |
| `question:` | Missing context — often the *Questions before approval* |
| `thought:` | A trade-off worth considering, no action required |
| `praise:` | A genuinely good decision — be specific |

Avoid `nitpick:` comments unless the author asked for them. Show the user the exact comments and
get confirmation before posting with `gh pr review` or `gh api`.
