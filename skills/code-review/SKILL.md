---
name: code-review
description: Senior code review of a diff, pull request, branch, commit, or set of files — reviews through a senior-developer, tech-lead, and architect lens for correctness, security, performance, architecture, error handling, tests, data/API contracts, observability, and config, with extra checks for LLM, RAG, and multi-agent code. Strictly read-only; reports only evidence-backed findings with P0–P3 severity, a fix, a regression test, and a merge recommendation. Use whenever the user asks to review code, a PR, a diff, a commit, or a branch, asks whether a change is safe to merge, wants a self-review before pushing, or wants to learn how to review code (mentor or quiz mode).
---

# Code Review

A review is worth the bugs it catches **minus the attention it wastes**. Most automated reviewers
fail the second half: twenty style nitpicks bury the one race condition, and the author learns to
skim. This skill reviews like a senior engineer who has been paged at 3 a.m. — it finds what would
break production, proves it with file and line, says how to fix and test it, and stays quiet about
the rest.

The three rules everything else follows from:

1. **Evidence over suspicion.** No finding without a file:line, a traced path, and a concrete
   failing scenario. A plausible-sounding bug that the code already handles is a false positive,
   and false positives are how reviewers lose trust.
2. **Impact over taste.** A missing ownership check outranks every naming opinion in the diff.
   The linter owns formatting; the reviewer owns behaviour.
3. **Context over diff.** The diff shows what changed, not what it broke. The highest-value bugs
   live in callers, consumers, and configuration the diff never touched.

---

## Read-only policy (non-negotiable)

During a review:

- **Never** edit, create, delete, format, or move files; never commit, push, rebase, or check out
  branches that change the user's working tree; never post PR comments or approvals; never run
  migrations, deploys, or anything that writes to a network service.
- **Allowed:** reading files, `grep`/search, `git diff`, `git log`, `git show`, `git blame`,
  `git status`, `gh pr view`, `gh pr diff`, `gh pr checks`, and listing directories.
- **Tests and linters** may be run only when the user asked for it or they are clearly
  side-effect-free (no network, no database writes, no generated files left behind).
- **Secrets:** never reproduce a secret value. Point to its location and redact it:
  "API key hard-coded at `config.py:12` (value redacted)."
- Fixing what was found is a **separate, explicit request** after the review is delivered.

---

## Step 0 — Establish the scope

| User gives | Get the change with |
|---|---|
| PR number or URL | `gh pr view <n>` (title, body, linked issues) and `gh pr diff <n>` |
| A branch | `git diff $(git merge-base <default-branch> HEAD)...HEAD` plus `git log` for the range |
| A commit | `git show <sha>` |
| "my changes" / nothing | `git diff` + `git diff --staged`; if empty, current branch vs the default branch |
| Files or a directory | Review the current state of those files (no diff — say so in the summary) |

State the scope in the first line of the review: what was reviewed, against which base.

**Large changes (over ~800 changed lines):** triage first. Rank files by risk — auth and
permissions, payments and money, data migrations, concurrency, public API contracts, prompts and
agent routing, infrastructure — and review those in depth. Name what was only skimmed. A review
that claims full coverage of 5,000 lines is lying.

**Skip:** generated code, lockfiles (but *do* note added, removed, or major-bumped dependencies),
vendored code, snapshots, and pure formatting changes.

---

## Step 1 — Choose the lens and the level

**Lens** — whose eyes the review uses. Default: all three, weighted by what the change touches.
The user can ask for one ("review this as an architect").

| Lens | Primary question | Looks hardest at |
|---|---|---|
| **Senior developer** | Does this code do what it claims, for every input? | Logic, edge cases, null and empty handling, error paths, concurrency, tests |
| **Tech lead** | Can the team ship, run, and change this safely? | Rollout and rollback, backward compatibility, observability, config, test coverage of risk, consistency with team conventions |
| **Architect** | Does this fit the system and keep it healthy over time? | Boundaries, coupling, dependency direction, data ownership, duplicated logic across services, scaling and failure modes |

**Level** — how much rigor the change earns. Mirrors the `system-design` skill's tiers. Infer it
from the repository and the files touched, and state the assumption.

| Level | Example | Review depth |
|---|---|---|
| **L1 — prototype / script / POC** | Hackathon code, a one-off script, a notebook | Correctness and security only; skip observability and architecture unless something is dangerous |
| **L2 — production service** | A normal feature in a deployed app | The full checklist |
| **L3 — critical path** | Auth, payments, multi-tenant isolation, data migrations, the hot path at scale | Full checklist **plus** failure-mode analysis, rollback plan, and data-integrity checks |

Level the **component**, not the repo: an L2 app can have an L3 auth module.

---

## Step 2 — Understand the intent before judging

1. Read the PR description, commit messages, and any linked issue.
2. Read project instructions: `README`, `CLAUDE.md`, `AGENTS.md`, `CONTRIBUTING`, lint and
   formatter configs, and the test layout.
3. Write the intended behaviour down in one or two sentences. Every finding is measured against it.
4. Note the languages, frameworks, and conventions — **from the neighbouring code**. The
   codebase's existing conventions beat your preferences; inconsistency with them is a finding,
   disagreement with them is not.

If you cannot tell what the code is supposed to do, say so as a question. Do not invent intent and
then report the code for failing it.

---

## Step 3 — Gather context beyond the diff

For every changed function, class, schema, endpoint, prompt, config key, or environment variable:

- **Callers and consumers** — grep for every use. Did a signature, return shape, error type, or
  default change under them?
- **Removed or renamed things** — is anything still referencing them (code, config, docs, other
  services, dashboards)?
- **Pairs that must move together** — schema change with its migration; new env var with the
  deploy config and `.env.example`; new endpoint with its auth middleware; new tool with its
  permission rules; prompt change with its output parser.
- **What used to protect this path** — a check, a lock, a transaction, a validation that the diff
  removed or bypassed. Removed guards are the most-missed class of bug in review.
- **Existing tests** — what the change is already covered by, and what it silently broke.

---

## Step 3b — Trace the paths, then ask the six design questions

Before judging any single line, trace each changed path end to end: entry point → validation →
business logic → data access and external calls → response, events, or side effects. Note where
data is created, transformed, and stored, and which component owns each step. Then ask these
questions of the change as a whole. They catch what line-by-line reading misses.

| # | Question | What it catches |
|---|---|---|
| 1 | **Is each component doing the right job?** | Business rules in controllers or prompts, persistence in agents, a router that also executes, a "utils" module that became the domain |
| 2 | **Is unnecessary work being performed?** | Repeated queries or LLM calls, data fetched and discarded, work done before checking whether it is needed, recomputation that a parameter could pass along |
| 3 | **Are independent operations blocking each other?** | Sequential `await`s on unrelated calls, sync I/O on an event loop, a lock or transaction held across a network call, one slow tool stalling an agent step that did not need it |
| 4 | **Are dependencies and runtime contracts designed consistently?** | Clients constructed inline instead of injected the way the rest of the codebase does; config read in three different ways; a function returning `None` on one path and raising on another; an agent state key one node writes as a string and another reads as a list |
| 5 | **Will this design stay maintainable as the application grows?** | The second tool, tenant, model, or agent requiring a copy-paste; a switch statement every new feature must edit; hidden coupling through shared globals |
| 6 | **Could the change break another service, agent, or existing workflow?** | Changed payloads, event schemas, state shapes, prompt outputs that a parser depends on, shared config keys, cron jobs and background workers nobody grepped for |

Each question either produces evidence-backed findings or is answered "no issue" silently.
A question you **cannot** answer from the code goes into the final *Questions before approval*.

**No speculative engineering.** Do not recommend an abstraction, concurrency, caching, a queue, or a
refactor unless you can name the concrete benefit in this codebase — the bug it prevents, the
latency it removes, the duplicate it collapses. "Might be useful later" is not a benefit; write the
trigger that would make it one instead.

---

## Step 4 — Review in priority order

Run the passes from highest value to lowest. Detail for each lives in
`references/01-review-checklist.md`; language-specific traps in `references/04-language-pitfalls.md`.

1. **Correctness** — logic, edge cases, null/empty, off-by-one, race conditions, wrong assumptions
2. **Security** — injection, authn/authz gaps, IDOR, secrets, unsafe input, sensitive data in logs
3. **Data & API contracts** — schema compatibility, validation, migrations, transactions, pagination,
   breaking changes for clients
4. **Error handling & resilience** — swallowed errors, missing timeouts, unsafe retries, cleanup,
   misleading messages
5. **Performance** — N+1 queries, blocking I/O on async paths, unbounded loads, avoidable network
   or LLM calls, leaks
6. **AI / LLM / agents** — only when the change touches them → `references/02-ai-agent-review.md`
7. **Testing** — critical behaviour and edge cases untested, tests that cannot fail, over-mocking
8. **Architecture** — separation of concerns, coupling, dependency direction, duplicated logic,
   service boundaries
9. **Observability** — can someone on call tell what happened, without leaking data?
10. **Configuration & deployment** — env vars, defaults, dependency changes, deploy ordering,
    rollback safety
11. **Maintainability** — readability, naming, types, complexity, needless abstraction

---

## Step 5 — Verify every finding (the evidence gate)

A candidate finding is reported only if it passes all of these:

1. **Location** — it points to a specific file and line (or line range).
2. **Not already handled** — you read the surrounding code and callers, and nothing upstream
   (middleware, a validator, framework escaping, a wrapper, a database constraint) already
   prevents it. See the false-positive table in `references/03-severity-and-evidence.md`.
3. **Reachable** — you can describe a concrete input, sequence, or condition that triggers it.
   "An attacker could theoretically…" with no reachable input is not a finding.
4. **In scope** — the change introduced it or made it worse. Pre-existing problems go in a short
   separate section, and only if they are P0 or P1.
5. **Labelled honestly** — **Confirmed** means you traced the path end to end. **Potential** means
   it depends on something you could not verify — and you name exactly what (e.g. "depends on
   whether `session_id` is a guessable integer; the schema is not in this repo").

6. **Typed** — every finding is exactly one of:

   | Type | Meaning | How it is reported |
   |---|---|---|
   | **Bug** | The code produces wrong behaviour, a vulnerability, data loss, or an outage under a stated scenario | P0–P3, with fix and regression test |
   | **Risk** | Not wrong today, but a concrete, likely condition (scale, a second caller, a config change) makes it fail | P1–P3, with the triggering condition named |
   | **Trade-off** | A defensible design choice with a real cost worth knowing — coupling, latency, operability | Usually P3 or Info; states both sides, and when the other choice would win |
   | **Preference** | Taste: a different but equally valid style or structure | **Not reported** — or one Info line at most if the user asked for style feedback |

   Never dress a preference up as a trade-off, or a trade-off as a bug.

Then cut the noise:

- Drop anything a linter or formatter already enforces, and pure preference.
- Merge duplicates: one root cause reported once, with every affected location listed.
- At most three individual P3 findings; fold the rest into a single "minor nits" line.

---

## Step 6 — Assign severity honestly

| Level | Meaning | Typical example |
|---|---|---|
| **P0 — Critical** | Immediate severe security hole or production failure | SQL injection on an authenticated endpoint; deleting all tenants' data |
| **P1 — High** | Significant defect, exploitable vulnerability, data loss, or major functional failure | Missing ownership check (IDOR); unbounded agent loop burning tokens |
| **P2 — Medium** | Real bug, performance problem, or reliability risk with bounded impact | Blocking I/O in an async handler; PII in logs; unhandled malformed LLM output |
| **P3 — Low** | Minor issue, limited impact | Unused parameter; misleading name; small missing validation on an internal tool |
| **Info** | Optional improvement, not a defect | A simpler approach; a future-proofing note |

**Do not inflate.** Severity is impact × likelihood, given the conditions you state. Every finding
says what must be true for it to happen. Calibration examples: `references/03-severity-and-evidence.md`.

---

## Step 7 — Write the review

Use the exact structure in `references/05-output-template.md`:

1. **Summary** — scope, intent in one line, lens and level, finding counts by severity, main risks,
   and whether it looks safe to merge.
2. **Findings** — ordered by severity. Each has: severity, type (Bug / Risk / Trade-off),
   confidence (Confirmed / Potential), title, `file:line`, what is wrong, a realistic failing
   scenario, impact, a practical fix, a regression test, and a one-line **How it was spotted** (the
   signal that made a senior look twice — this is how the reader learns to find the next one).
3. **Positive observations** — only specific, genuine ones ("the retry wraps an idempotent call
   with jittered backoff"), never filler.
4. **Missing tests** — the most important untested behaviours, not repeating findings.
5. **Top 3 observations** — the three things that matter most about this change, in plain
   language, even if one of them is not a defect (e.g. "the agent loop has no exit condition";
   "this introduces a second way to load config"). If the author reads nothing else, they read this.
6. **Questions before approval** — what must be answered before this can merge: missing context,
   unverifiable assumptions behind *Potential* findings, rollout or ownership questions. Each
   question says why the answer changes the verdict. Write "None" if there are none.
7. **Final recommendation** — exactly one of the four below.

| Recommendation | When |
|---|---|
| **Block merge pending critical fixes** | Any confirmed P0 |
| **Request changes** | Any confirmed P1, or P2s on an L3 path, or several P2s that compound |
| **Approve with minor follow-ups** | Isolated P2s on an L1/L2 path, or only P3s worth tracking |
| **Approve** | Nothing above P3 |

The recommendation follows the evidence, not the count: one confirmed P0 blocks; fifteen P3s do not.
Give a one-sentence reason.

---

## Modes

**Review (default)** — everything above.

**Mentor mode** — triggered by "teach me", "mentor mode", "I'm learning", or "explain your
reasoning". Every finding gains a **🧠 How a senior finds this** block: the signal in the code, the
question the reviewer asked, and the general rule worth remembering. The review ends with two or
three **Habits to practise** drawn from this specific change.
→ `references/06-learning-to-review.md`

**Quiz mode** — triggered by "quiz me" or "let me review first". Do the full review silently, then
show the user only the scope, the intent, and a hint per risky area ("look closely at how
`session_id` reaches the query"). Wait for their findings. Then reveal the review, mark which they
caught, which they missed, and which of theirs were false positives — with why.

**Self-review** — the user is the author and wants to check before pushing. Same review, plus a
short pre-push checklist: tests run, migrations paired, env vars documented, nothing debug left in.

**Posting to a PR** — only on explicit request *after* the review is delivered, and only after the
user confirms the exact comments. Use Conventional Comments labels (format in
`references/05-output-template.md`).

---

## Reference index

| File | Use it for |
|---|---|
| `references/01-review-checklist.md` | What to look for in each of the eleven passes, with the senior question for each |
| `references/02-ai-agent-review.md` | LLM, RAG, tool-calling, multi-agent, and LangGraph-specific review |
| `references/03-severity-and-evidence.md` | Severity calibration, confirmed vs potential, and the false-positive table |
| `references/04-language-pitfalls.md` | Python/FastAPI, TypeScript/Node, Java/Spring, SQL and migration traps |
| `references/05-output-template.md` | The exact review template, a worked finding, and PR-comment format |
| `references/06-learning-to-review.md` | How seniors read a PR, how to write comments, a practice plan |
| `evals/` | A seeded-bug change with an answer key, to validate the reviewer (and yourself) |
