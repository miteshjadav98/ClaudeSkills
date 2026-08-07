# Anti-Patterns

Format: **What it looks like → why it happens → what it costs → the fix.**

Use this as a review sweep on existing code, and as a pre-mortem on new designs.

---

## A. Architecture

### A1. Agent where a chain would do

**Looks like:** a ReAct agent whose traces always show the same three tool calls in the
same order.
**Why:** "agent" is the exciting word; tutorials all build agents.
**Costs:** 3–10× the cost and latency, non-determinism, untestability — for zero
flexibility gained.
**Fix:** read 50 traces. If the path is stable, hard-code it. Keep the agent only for
the genuinely open-ended slice.

### A2. Premature multi-agent

**Looks like:** five "agents" that share the same tools and near-identical prompts,
coordinated by a supervisor.
**Why:** multi-agent is fashionable; role-play feels like decomposition.
**Costs:** handoff calls, context loss between agents, latency multiplication, a
debugging surface spread across five prompts.
**Fix:** one agent until you observe a concrete forcing problem (tool overload,
conflicting instructions, different model requirements, different owning teams). The
test: if two agents' tool lists overlap >70%, they are one agent.

### A3. Subgraph sprawl

**Looks like:** 12 subgraphs, several with two nodes each.
**Why:** treating subgraphs as folders.
**Costs:** state-mapping boilerplate, indirection, harder tracing, no benefit.
**Fix:** subgraph only for state isolation or reuse. Otherwise it's a function.

### A4. God node

**Looks like:** one 300-line node that retrieves, calls the model, parses, validates,
writes to a DB, and decides what's next.
**Why:** it started small.
**Costs:** cannot be retried granularly, cannot be checkpointed usefully, cannot be
tested, traces show one opaque box.
**Fix:** split at I/O boundaries. Each node should have one reason to fail.

### A5. Poor routing

**Looks like:** free-text LLM output parsed with `if "billing" in response.lower()`.
**Why:** structured output felt like extra work.
**Costs:** silent misroutes on phrasing changes; no fallback; unexplainable.
**Fix:** structured output with a `Literal` type, an explicit destination list on the
conditional edge, and **always a fallback branch**.

### A6. LLM calls doing code's job

**Looks like:** a model call to sort a list, format a date, extract a number, or decide
`if x > threshold`.
**Why:** everything looks like a nail.
**Costs:** latency, money, and non-determinism where you could have had certainty.
**Fix:** audit every model call. If the answer is exactly computable, compute it.

---

## B. State

### B1. Missing reducer on a parallel key

**Looks like:** `InvalidUpdateError: At key 'x': Can receive only one value per step.`
**Why:** the graph worked linearly, then a fan-out was added.
**Costs:** hard failure (which is good — the alternative is silent data loss).
**Fix:** `Annotated[list[T], operator.add]` on any key with multiple writers per step.

### B2. State explosion

**Looks like:** full document texts, base64 images, entire API responses, whole
retrieved corpora in state.
**Why:** "the next node needs it".
**Costs:** slow checkpoint writes, storage bloat, unreadable traces, payload-size
failures, expensive replays.
**Fix:** store references (IDs, URIs). Fetch in the node that needs it. If it must be
passed, pass a summary or a bounded excerpt.

### B3. Everything in shared state

**Looks like:** one 30-key `TypedDict` that every node reads and writes.
**Why:** no schema design step.
**Costs:** no isolation, accidental multi-writer conflicts, nobody knows who owns what,
refactoring is impossible.
**Fix:** `input_schema`/`output_schema` for the public contract, private keys for
scratch, per-node `input_schema`, `Send` payloads for workers.

### B4. Mutating state in place

**Looks like:** `state["items"].append(x); return state`
**Why:** normal Python instinct.
**Costs:** the framework can't see the change, replay diverges, parallel branches alias
the same list.
**Fix:** return `{"items": [x]}` and let the reducer merge.

### B5. Returning the whole state from every node

**Looks like:** `return state` or `return {**state, "answer": a}`
**Why:** looks harmless.
**Costs:** turns every key into a multi-writer key under parallelism; masks which node
actually changed what.
**Fix:** return only changed keys.

### B6. Impure or stateful reducers

**Looks like:** a reducer that calls an LLM to merge, or reads the clock, or mutates
`left`.
**Why:** "smart merging" seemed elegant.
**Costs:** non-deterministic replay, unreproducible bugs, side effects on every merge.
**Fix:** reducers are pure functions. Put intelligence in a node.

### B7. Runtime config in state

**Looks like:** `user_id`, `model_name`, `api_key` as state keys.
**Why:** it was convenient.
**Costs:** checkpointed redundantly every step; mutable identity (a node can change
`user_id` mid-run — a security bug); pollutes the state contract.
**Fix:** `context_schema` + `runtime.context`.

---

## C. Memory

### C1. Memory for its own sake

**Looks like:** a memory layer on a stateless Q&A bot.
**Why:** memory is a checkbox on the roadmap.
**Costs:** extraction cost every turn, privacy surface, stale/wrong recalls that make
answers worse.
**Fix:** answer "would this be meaningfully worse without memory?" concretely, or skip it.

### C2. Wrong memory type

**Looks like:** conversation history in the Store; user facts only in `messages`.
**Why:** the checkpointer/store distinction wasn't internalized.
**Costs:** history-in-Store loses replay and ordering; facts-in-messages vanish when
the thread ends or gets summarized.
**Fix:** history → checkpointer. Durable facts → Store. Both, usually.

### C3. Duplicating the system of record into memory

**Looks like:** "user's subscription tier" extracted into semantic memory.
**Why:** it appeared in conversation.
**Costs:** it goes stale immediately and then confidently contradicts your database.
**Fix:** query the system of record. Memory is for things you have no other source for.

### C4. Memory duplication and contradiction

**Looks like:** six variants of "likes coffee"; "lives in SF" alongside "lives in NYC".
**Why:** insert-only collection with no dedup or reconciliation.
**Costs:** retrieval returns the wrong one; the model gets confused; storage grows.
**Fix:** search-before-insert, timestamps + recency preference, periodic consolidation,
and let users delete.

### C5. Regenerating structured memory (silent field loss)

**Looks like:** "here's the profile, update it" → the model returns a profile missing
three fields it wasn't reminded of.
**Why:** trusting the model to preserve what wasn't discussed.
**Costs:** silent, cumulative data loss — the worst kind, because nothing errors.
**Fix:** optional fields + `None` defaults, **drop nulls, then merge explicitly in your
code**. Or switch to a collection where each item is independent.

### C6. Namespace from untrusted input

**Looks like:** `namespace = ("memories", state["user_id"])` where `user_id` came from
the conversation or a tool result.
**Why:** state was assumed trustworthy.
**Costs:** **cross-tenant data leakage via prompt injection.** Highest-severity bug in
this document.
**Fix:** namespace from authenticated context only. Never from state or model output.

### C7. Unbounded memory growth

**Looks like:** thousands of memories per user, all retrieved or all in the prompt.
**Why:** no TTL, no cap, no retrieval limit.
**Costs:** cost per turn grows forever; recall quality collapses.
**Fix:** TTL with `refresh_on_read`, retrieval limits, consolidation.

---

## D. Control flow

### D1. Unbounded loops

**Looks like:** an agent hitting the recursion limit, or a critique→revise cycle
running 15 times, or two agents handing off forever.
**Why:** the stop condition was semantic ("until it's good") and the model never agrees.
**Costs:** runaway cost, hung runs, angry finance team.
**Fix:** **a counter in state, checked in the conditional edge.** Always. Plus
`recursion_limit` and call-limit middleware as a backstop. Semantic stop conditions are
an optimization on top of a hard cap, never a replacement.

### D2. No fallback branch

**Looks like:** a router with exactly the three expected categories.
**Why:** the happy path was designed; the unhappy path wasn't.
**Costs:** unroutable input either errors or gets forced into a wrong branch.
**Fix:** always add `other`/`clarify`/`escalate`.

### D3. Blocking nodes in an async graph

**Looks like:** `requests.get()` or `time.sleep()` in a node in an async service.
**Why:** copied from a sync example.
**Costs:** blocks the event loop; throughput collapses under concurrency; one slow
call stalls unrelated runs.
**Fix:** async all the way — async nodes, async client, async checkpointer/store. Or
offload blocking work to a thread pool.

### D4. Swallowing tool errors

**Looks like:** `try: ... except: return {"result": None}`
**Why:** defensive coding.
**Costs:** the model can't see what went wrong, so it retries the same broken call, or
answers confidently from nothing.
**Fix:** return the error text as a `ToolMessage` so the model can adapt. Raise only
for genuinely unrecoverable conditions.

### D5. Retries on non-idempotent nodes

**Looks like:** `retry_policy` on the node that charges the card.
**Why:** retries were applied uniformly.
**Costs:** duplicate side effects.
**Fix:** retry only idempotent operations; use idempotency keys for the rest.

### D6. Side effects before `interrupt()`

**Looks like:** the email sends, *then* the approval prompt appears.
**Why:** not knowing that resume re-runs the whole node.
**Costs:** the approval gate is decorative; the action already happened — twice.
**Fix:** all side effects **after** the `interrupt()` call, or in a downstream node.

---

## E. Human-in-the-loop

### E1. Approval fatigue

**Looks like:** approve every tool call, including searches.
**Why:** "safety".
**Costs:** humans rubber-stamp; the gate provides the *appearance* of oversight while
providing none.
**Fix:** tiered approval — auto-approve reads, gate consequences.

### E2. Approval placed too late

**Looks like:** approving the final report after 40 minutes and $12 of generation.
**Why:** gating the output rather than the decision.
**Costs:** rejection wastes everything.
**Fix:** gate the plan, before the fan-out.

### E3. Paused threads nobody knows about

**Looks like:** interrupts fire; no notification exists; work silently stalls.
**Why:** HITL was built as a graph feature, not a product feature.
**Costs:** dropped tasks, invisible backlog.
**Fix:** notification on interrupt + a timeout/escalation policy + a dashboard of
paused threads.

### E4. Unauthorized resume

**Looks like:** anyone with a `thread_id` can approve.
**Why:** the thread id was treated as an identifier, not a capability.
**Costs:** privilege escalation.
**Fix:** authorize resume server-side against the actual approver identity.

---

## F. Production

### F1. `InMemorySaver` in production

**Looks like:** it worked in the notebook.
**Costs:** every conversation lost on restart; breaks entirely with >1 worker (each
worker has a different memory).
**Fix:** Postgres.

### F2. No tracing

**Looks like:** debugging a non-deterministic multi-step system from print statements.
**Costs:** every incident is an archaeology project.
**Fix:** enable tracing before the first real user. It is the highest-leverage 10
minutes in the whole project.

### F3. No evaluation

**Looks like:** prompt changes shipped because they "seem better".
**Costs:** silent regressions; no way to know whether a change helped.
**Fix:** 30–50 labelled cases and assertions in CI. Small and real beats large and
aspirational.

### F4. One model everywhere

**Looks like:** the frontier model doing routing, classification, and formatting.
**Costs:** typically 5–20× the necessary spend, and slower.
**Fix:** cheap models for routing/classification/extraction; strong models for
reasoning and generation. Measure quality per node before downgrading.

### F5. Ignoring context growth

**Looks like:** cost per turn rising steadily; latency creeping; eventual context-limit
errors.
**Why:** it was fine in testing (5 turns) and dies in production (80 turns).
**Costs:** quadratic cost growth, then hard failure.
**Fix:** a context strategy from day one — trim, summarize, or offload.

### F6. Trusting tool/retrieval output as instructions

**Looks like:** retrieved documents, tool results, or stored memories concatenated
straight into the prompt.
**Why:** it's all "just context".
**Costs:** **prompt injection**. A malicious document can redirect the agent, exfiltrate
data through a tool call, or corrupt memory.
**Fix:** delimit and label untrusted content; instruct the model that it is data, not
instructions; gate consequential tools behind approval regardless; enforce
authorization at the data layer so a hijacked agent still can't read what the user can't.

### F7. Agent holds broader permissions than the user

**Looks like:** the agent uses a service account with full DB access, filtering results
by prompt.
**Why:** simpler to implement.
**Costs:** any injection or routing bug becomes a data breach.
**Fix:** scope credentials to the requesting user; enforce authorization at the data
layer, never in the prompt.

### F8. Renaming nodes/keys without migration

**Looks like:** a rename ships; in-flight threads break on resume.
**Why:** node names look like implementation detail.
**Costs:** stuck threads, corrupted resumes.
**Fix:** treat node names and state keys as a public API. Version the graph and drain
old threads.

---

## Rapid triage table

| Symptom | Look at |
|---|---|
| `InvalidUpdateError` | B1 — missing reducer |
| Hits recursion limit | D1 — unbounded loop |
| Cost 10× the estimate | A1, A6, F4, F5 |
| Slow steps | B2 — state size; D3 — blocking I/O |
| Forgets between sessions | C2 — needs a Store |
| Forgets mid-session | Missing/misconfigured checkpointer |
| Loses profile fields | C5 — regeneration without merge |
| Wrong tool chosen | A5, or tool descriptions (see `06`) |
| Provider 400 on messages | Orphaned tool_calls after trimming (`02` §3) |
| Works locally, breaks deployed | F1 — InMemorySaver + multi-worker |
| Approval gate doesn't prevent the action | D6 — side effect before interrupt |
| Cross-user data appears | C6 / F7 — namespace or permission scoping |
| Can't reproduce a bug | F2 — no tracing; also check reducer purity (B6) |
