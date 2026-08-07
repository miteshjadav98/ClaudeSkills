# Design Checklists

Gates, not suggestions. Use the relevant one before building and again before shipping.

---

## Before building anything

- [ ] **What is the actual task?** One sentence, no jargon.
- [ ] **Would a chain do?** If yes, build the chain.
- [ ] **What does "correct" mean?** If you cannot define it, you cannot evaluate it.
- [ ] **What's the cost budget per run?** p95, not average.
- [ ] **What's the latency budget?** What does the user see while waiting?
- [ ] **What happens when it's wrong?** Annoying, expensive, or dangerous?
- [ ] **Who is accountable for its output?**
- [ ] **What's the simplest version that delivers value?** Build that first.

**If the answer to "what does correct mean" is fuzzy, stop.** You are about to build
something you cannot improve.

---

## Before building a chatbot

- [ ] Is it stateless, single-session, or cross-session? (Determines checkpointer/store)
- [ ] What is a "thread" — a session, a ticket, a day, forever?
- [ ] Context strategy for long conversations chosen (trim / summarize / both)?
- [ ] System prompt versioned and reviewable, not inline in a node?
- [ ] Does it need tools, or is it purely conversational?
- [ ] Streaming for perceived latency?
- [ ] What happens on double-texting (user sends while it's still generating)?
- [ ] Out-of-scope handling — what does it say when asked something it shouldn't answer?
- [ ] Conversation reset path for the user?

---

## Before building an agent

- [ ] **Loop bound set** — `recursion_limit` and/or model/tool call limits?
- [ ] Tool count under ~15? If not, plan tool selection or sub-agents.
- [ ] Every tool has a description written for someone with no context?
- [ ] Tool errors returned as `ToolMessage`, not raised?
- [ ] Parallel tool calls: enabled (independent ops) or disabled (order-dependent)?
- [ ] What stops it when it's confused rather than looping?
- [ ] Cost ceiling per run enforced, not just monitored?
- [ ] Traces enabled before first real use?
- [ ] Which actions need human approval?
- [ ] Could `create_agent` + middleware do this instead of a hand-rolled graph?

---

## Before adding tools

- [ ] **Does this tool need to exist,** or can the model already do it?
- [ ] Name and description unambiguous vs every other tool?
- [ ] Args typed and validated (Pydantic), with sane defaults?
- [ ] **Is it destructive?** → approval gate + confirmation in the description
- [ ] Idempotent? If not, what happens on replay/resume?
- [ ] Timeout set? (An agent hanging on a tool is a hung run)
- [ ] Failure returns a *useful* message the model can act on?
- [ ] Output size bounded? (A tool returning 200KB destroys the context window)
- [ ] Rate limits / quotas understood, especially under fan-out?
- [ ] **Does it need the caller's permissions, not the agent's?**
- [ ] Is tool output treated as untrusted input? (It can carry prompt injection)

---

## Before adding memory

- [ ] **Would the system be meaningfully worse without it?** Be specific.
- [ ] Short-term, long-term, or both?
- [ ] Namespace design fixed, tenant-prefixed, and derived from **authenticated** identity?
- [ ] Profile, collection, or both?
- [ ] What triggers a write — every turn, model decision, or background?
- [ ] Update semantics: merge or replace? Who guarantees fields aren't lost?
- [ ] Retrieval strategy: load-all (<20 items) or search?
- [ ] Duplicate/contradiction handling?
- [ ] TTL / expiry policy?
- [ ] **Can users see and delete their memories?**
- [ ] PII policy — what must never be stored?
- [ ] Retrieved memories treated as untrusted input in prompts?
- [ ] Deletion path tested (store + vector index)?

---

## Before using checkpoints

- [ ] Durable backend for production (not `InMemorySaver`)?
- [ ] `thread_id` scheme defined and **unguessable** where data is private?
- [ ] Authorization on thread access — a `thread_id` is a capability?
- [ ] `durability` mode chosen deliberately (`async` default; `sync` for side effects)?
- [ ] Async saver if the service is async?
- [ ] `.setup()` run in deploy, not per-request?
- [ ] Retention/deletion policy for old threads?
- [ ] State small enough to serialize cheaply per step?
- [ ] **Nodes idempotent** — safe to re-run on resume/replay?

---

## Before introducing subgraphs

- [ ] More than ~4 nodes, or genuinely reused?
- [ ] Does it have its own state concerns, or is it just organization?
- [ ] Shared-schema or translated-interface composition — chosen deliberately?
- [ ] `output_schema` set so internals don't leak into the parent?
- [ ] Keys shared with parallel parent nodes have reducers?
- [ ] Child compiled **without** its own checkpointer?
- [ ] Testable standalone?
- [ ] Interrupt behaviour understood (propagates to parent)?

---

## Before parallel execution

- [ ] **Every key written by >1 node in a step has a reducer?**
- [ ] Reducer handles `None` and is order-tolerant?
- [ ] Do you actually need all branches, or would a router be cheaper?
- [ ] Fan-in point correct — do you need `defer=True` or a multi-source edge?
- [ ] Ordering requirements handled (separate keys + join, not luck)?
- [ ] **One branch failing doesn't abort the others?**
- [ ] Concurrency capped vs provider rate limits?
- [ ] Cost understood: parallel saves time, not money.

---

## Before map-reduce / `Send`

- [ ] Is N bounded? What's the max?
- [ ] Cost at max N acceptable?
- [ ] Rate limits at max N acceptable?
- [ ] Collector key has an append reducer?
- [ ] Worker failures isolated — partial results acceptable?
- [ ] Should small items be batched per worker instead of one-per-worker?
- [ ] Is per-item state genuinely private (via the `Send` payload)?

---

## Before human approval

- [ ] Gating on **consequence**, not model confidence?
- [ ] Approval placed before the expensive/irreversible step, as early as possible?
- [ ] Interrupt payload contains everything needed to decide?
- [ ] **All side effects come after the `interrupt()` call?**
- [ ] Pre-interrupt work is cheap (it runs twice)?
- [ ] How is the human **notified** that approval is pending?
- [ ] **What happens if nobody responds?** Timeout, escalate, auto-reject?
- [ ] Who is authorized to resume — and is that enforced?
- [ ] Audit trail: who approved what, when, seeing what?
- [ ] Approval volume low enough to avoid fatigue?
- [ ] Concurrent-approver conflict handled?

---

## Before production release

**Correctness**
- [ ] Evaluation dataset exists with expected outcomes
- [ ] Regression suite runs in CI
- [ ] Known failure modes documented
- [ ] Nodes unit-tested independently of the graph

**Reliability**
- [ ] Durable checkpointer, correctly configured
- [ ] `retry_policy` on network-touching nodes (and *not* on non-idempotent ones)
- [ ] Model fallback for provider outages
- [ ] Recursion / call limits enforced
- [ ] Timeouts on every external call
- [ ] Graceful degradation defined for each dependency

**Observability**
- [ ] Tracing enabled (LangSmith / OTel)
- [ ] Structured logs with `thread_id` + `run_id` correlation
- [ ] Metrics: latency p50/p95/p99, error rate, cost/run, token usage, loop depth
- [ ] Alerts on cost spikes, error rate, and stuck/paused threads

**Cost**
- [ ] p95 cost per run measured, not estimated
- [ ] Model choice per node justified (cheap models for routing/classification)
- [ ] Prompt caching used where the provider supports it
- [ ] Context growth bounded
- [ ] Budget alerts configured

**Security**
- [ ] Secrets from a secret manager, never in code or `langgraph.json`
- [ ] **Authorization checked per-user at the data layer, not by the agent**
- [ ] Tool permissions scoped to the *end user*, not to a service account
- [ ] Prompt injection surfaces enumerated (tool output, retrieved docs, stored memories)
- [ ] Destructive operations gated
- [ ] PII handling documented; logs/traces scrubbed
- [ ] Thread and namespace access authorized server-side

**Operations**
- [ ] Deployment and rollback procedure documented
- [ ] Graph version tracked; in-flight-thread compatibility considered
- [ ] Runbook exists — including "resume the stuck thread"
- [ ] On-call knows how to inspect a thread's state history
- [ ] Load tested at expected concurrency

---

## Code review checklist (LangGraph-specific)

- [ ] Nodes return **partial** updates, never the full state
- [ ] No state mutation in place
- [ ] Multi-writer keys have reducers; reducers are pure and None-tolerant
- [ ] Conditional edges declare their destination list
- [ ] `output_schema` set on anything with an external caller
- [ ] Runtime config (`user_id`, model, flags) in `context_schema`, not in state
- [ ] No large blobs in state
- [ ] No deprecated APIs (`config_schema`, `NodeInterrupt`, `input=`/`output=`, `checkpoint_during`)
- [ ] Side effects after `interrupt()`, and idempotent
- [ ] Loops bounded
- [ ] Errors surfaced to the model where recoverable, raised where not
- [ ] Prompts in files, not scattered f-strings
- [ ] `graph.py` is assembly only
