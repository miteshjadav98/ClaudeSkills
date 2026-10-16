# Learning to Review — How Seniors Actually Do It

Reviewing is a separate skill from writing code. Juniors read a diff top to bottom and comment on
what they notice. Seniors read it in a deliberate order, ask a fixed set of questions, and comment
only on what changes the outcome. This file is the method, so it can be practised.

---

## 1. Why reviews matter (and what they are not)

A review exists to catch **defects the author cannot see**, spread knowledge of the codebase, and
keep the design coherent. It is not a style audit (the linter does that), not a rewrite in the
reviewer's taste, and not a gate to prove the reviewer is smart.

What the industry has learned from AI review tools is the same lesson humans learned earlier:
**precision beats recall**. A reviewer that leaves thirty comments trains authors to ignore all
thirty. The good tools — and the good seniors — leave a handful of high-confidence comments with
evidence, and stay silent otherwise. That is why this skill has an evidence gate and a noise cap.

## 2. The reading order

Read in this order, not file order:

1. **The description and linked issue** — what is this supposed to do? If you cannot say it in
   one sentence, ask before reviewing.
2. **The tests** — they tell you what the author thinks the behaviour is, and what they forgot.
   Missing tests for the risky part is often the first finding.
3. **The public surface** — new or changed endpoints, function signatures, schemas, events,
   prompts, config. This is where other people's code breaks.
4. **The core logic** — now read the implementation with the intent and contracts in mind.
5. **The red lines** — re-read every deleted line. Removed checks, locks, and transactions are the
   most-missed bugs in review.
6. **The edges** — config, migrations, dependency changes, deploy files.
7. **Outside the diff** — grep the callers of anything whose behaviour changed.

## 3. The three lenses

The same diff, three different questions:

- **Senior developer:** "What input breaks this?" Trace one happy path and two unhappy paths by hand.
  Empty, null, huge, duplicate, concurrent, slow dependency.
- **Tech lead:** "Can we ship and operate this?" How is it deployed, rolled back, observed, and
  tested? Does it follow how the team does things? Who gets paged when it fails?
- **Architect:** "Is this the right place for this logic?" Does each component keep one job? Did a
  dependency arrow point the wrong way? Is this the second implementation of something that
  already exists? Will the tenth feature like this be as easy as the first?

## 4. The signals that make seniors look twice

These patterns are not bugs on their own. They are where bugs live.

| Signal | Look for |
|---|---|
| An ID comes from the request | Ownership / tenant check |
| A string is built and then executed or interpreted | Injection (SQL, shell, prompt, template) |
| `while True`, recursion, retries | The exit condition and the bound |
| A network call | Timeout, retry policy, error handling, is it on an async path |
| A query inside a loop | N+1 |
| `await` after `await` on unrelated things | Independent work serialised |
| A deleted line | What it used to protect |
| A new env var or config key | Is it in the deploy config, with a safe default? |
| A changed return shape, field, or state key | Every consumer |
| `except` / `catch` | What is swallowed, and does the caller need to know? |
| Model output used as data | Validation, malformed-output handling |
| Untrusted text placed in a prompt | Which tools can it trigger? |
| "Temporary", "TODO", "hack" | Whether temporary has a ticket and an owner |

## 5. Writing the comment

A good review comment has four parts: **where**, **what happens**, **why it matters**, **what to do**.

- ❌ "This is wrong."
- ❌ "Consider adding validation here."
- ✅ "`chat_api.py:31` — the ownership check was removed, so a user can pass another user's
  `session_id` and read their history. Can we restore the `user_id` filter (or `get_owned`)
  before loading? A test with two users would lock it in."

Habits that keep reviews kind and effective:

- **Comment on the code, not the person.** "This query" not "your query".
- **Ask when you are unsure.** "Is this already validated upstream?" is better than a wrong claim.
- **Say what blocks.** Label comments blocking or non-blocking so the author can prioritise.
- **Praise specifically, when it is real.** It tells the author what to keep doing.
- **One root cause, one comment.** List the other locations in it instead of repeating yourself.
- **Do not redesign in review.** If the approach is wrong, talk early — before the code is written.

## 6. What not to comment on

- Anything the formatter or linter enforces.
- Taste: a different but equally good name, structure, or pattern.
- Hypothetical future requirements with no trigger.
- Abstractions, caching, concurrency, or refactors without a concrete benefit in this codebase.
- Pre-existing issues — unless P0/P1, and then in a separate section.

## 7. A practice plan

**Week 1 — read, don't write.** Review three PRs with this skill in **mentor mode**. For each
finding, read the *How a senior finds this* block and add the signal to your own list.

**Week 2 — quiz yourself.** Run **quiz mode** on the seeded-bug change in `evals/seeded-bugs/`.
Write your findings before revealing the answer key. Score yourself: how many did you catch, how
many of yours were false positives, how far off was your severity?

**Week 3 — review first, compare second.** On real PRs at work, write your own review, then run the
skill. Compare: what did it catch that you missed, and what did you catch that it missed? The
second list is where your context beats the tool's.

**Week 4 onwards — specialise.** Pick one lens (architect is the hardest) and deliberately review
only through it for a week. Then rotate.

Track one number over time: **findings you would stand behind ÷ comments you left**. Seniors keep
it high.

## 8. Common reviewer mistakes

- Reviewing only the green lines.
- Approving because the tests pass — without checking the tests can fail.
- Reporting a vulnerability without tracing whether the input is reachable.
- Inflating severity to win an argument.
- Leaving twenty nits and missing the one design problem.
- Reviewing a 3,000-line PR in one pass instead of asking for it to be split.
