# Production Engineering

The gap between a working notebook and a production agent is almost entirely in this
file.

---

## 1. Reliability

### 1.1 Retries

```python
from langgraph.types import RetryPolicy

builder.add_node(
    "search", search_node,
    retry_policy=RetryPolicy(
        max_attempts=3,
        initial_interval=0.5,
        backoff_factor=2.0,
        jitter=True,
        retry_on=(ConnectionError, TimeoutError),   # be specific
    ),
)
```

**Retry:** network calls, rate limits (429), 5xx, transient timeouts.
**Never retry:** non-idempotent side effects (charges, sends, writes without an
idempotency key), auth failures, validation errors, 4xx other than 429.

**Retry on the narrowest node possible.** A retry policy on a node that does three
things repeats all three.

You can pass a **sequence** of policies to handle different exception classes with
different backoffs.

### 1.2 Timeouts

Every external call needs one. An agent without timeouts converts a slow dependency
into a hung run holding a checkpoint open.

```python
llm = ChatModel(..., timeout=30, max_retries=2)
```

### 1.3 Loop bounds — defense in depth

Three independent layers, because each catches a different failure:

```python
graph.invoke(inp, {"recursion_limit": 25, **config})        # 1. framework backstop
```
```python
def route(state):                                            # 2. explicit counter
    if state["iterations"] >= 3: return "finalize"
    ...
```
```python
create_agent(..., middleware=[                               # 3. call budgets
    ModelCallLimitMiddleware(thread_limit=20),
    ToolCallLimitMiddleware(thread_limit=40),
])
```

**All three.** The recursion limit stops catastrophe; the counter encodes intent; the
call limits cap spend.

### 1.4 Model fallback

```python
create_agent(model=primary, middleware=[ModelFallbackMiddleware(secondary, tertiary)])
```

Cross-**provider** fallback is what actually survives an outage; a fallback to another
model at the same provider fails together. Note that behaviour differs between models
— test the fallback path, don't just configure it.

### 1.5 Graceful degradation

For every dependency, decide in advance:

| Dependency down | Behaviour |
|---|---|
| Vector store | Answer without retrieval + say so, or fail loudly? |
| One of N parallel sources | Continue with partial context (usually correct) |
| Store (long-term memory) | Continue without personalization |
| Checkpointer | **Fail** — you cannot safely run without persistence |
| Model provider | Fallback provider, then fail |

Encode the choice; don't let it be decided by whichever exception escapes first.

### 1.6 Idempotency

Nodes re-run on resume, replay, and retry. Any node with an external side effect must
tolerate it:

- idempotency keys on API calls;
- upserts instead of inserts;
- check-before-act against the external system;
- record completion in state and short-circuit on re-entry.

---

## 2. Observability

### 2.1 Tracing

Non-negotiable. A multi-step non-deterministic system cannot be debugged from logs.

```bash
LANGSMITH_TRACING=true
LANGSMITH_API_KEY=...
LANGSMITH_PROJECT=my-agent-prod
```

Traces give you the full input/output of every node and model call, token counts,
latency per step, and the exact prompt that produced a bad answer. OpenTelemetry
export is the vendor-neutral alternative.

**Tag runs** with user/tenant/version so you can slice: `config={"tags": [...],
"metadata": {"app_version": "1.4.2", "tenant": org_id}}`.

### 2.2 What to measure

| Category | Metrics |
|---|---|
| Latency | p50/p95/p99 end-to-end; per-node; time-to-first-token |
| Cost | Tokens in/out per run; **cost p95**; cost per successful outcome |
| Reliability | Error rate by node; retry rate; timeout rate; fallback activations |
| Behaviour | Steps per run; tool-call distribution; loop-limit hits; recursion aborts |
| Quality | Eval score over time; human-feedback rate; escalation rate |
| HITL | Approval latency; approval/rejection rate; **count of paused threads** |
| Memory | Memories written/user; retrieval hit rate; store size |

**Average cost is a misleading metric.** A small fraction of runs that loop will
dominate your bill. Alert on p99 and on absolute daily spend.

### 2.3 Logging

Structured, correlated by `thread_id` and `run_id`. Log **decisions**, not just events:
which branch was taken and why, which tool was chosen, why a loop terminated.

**Scrub PII from logs and traces.** Traces contain full prompts, which contain
everything the user said.

---

## 3. Performance and latency

### 3.1 Where latency actually goes

| Source | Typical share | Lever |
|---|---|---|
| Model inference | 60–90% | Smaller model, shorter prompts, fewer sequential calls |
| Retrieval | 5–20% | Index tuning, caching, parallelism |
| Sequential model calls | Multiplies | Parallelize independent calls |
| Checkpoint writes | 1–5% | Smaller state; `durability="async"` |
| Tool I/O | Varies | Parallel tool calls, timeouts |

**The dominant lever is almost always "make fewer sequential model calls".** A
5-node chain with 5 model calls has 5× the latency floor of a 1-call design.

### 3.2 Techniques

- **Parallelize** independent model calls and retrievals (fan-out).
- **Stream** — time-to-first-token is what users perceive. A 20s streamed response
  feels faster than an 8s silent one.
- **Emit progress** from slow nodes via `stream_writer` so the UI is never silent.
- **Cache** deterministic nodes:
  ```python
  builder.add_node("embed", embed_node, cache_policy=CachePolicy(ttl=3600))
  graph = builder.compile(cache=InMemoryCache())
  ```
- **Prompt caching** at the provider level for long stable prefixes (system prompt +
  tool definitions). Often the single largest cost reduction available.
- **Right-size models per node.** Routing and classification rarely need a frontier model.
- **Trim context** — shorter prompts are both faster and cheaper.

### 3.3 Throughput

- Async end-to-end, or concurrency collapses (see anti-pattern D3).
- Connection pooling for checkpointer and store.
- Cap parallel fan-out against provider rate limits; a `Send` over 500 items will hit
  429s before it hits compute limits.
- Use a queue for long runs; don't hold HTTP connections open for minutes.

---

## 4. Cost

### 4.1 The cost model

Cost per run ≈ **Σ over calls of (prompt tokens + output tokens × output multiplier)**.

The dangerous property: in a conversation, **prompt tokens grow with every turn**, so
cost per turn grows linearly and cost per conversation grows **quadratically**. This is
why context strategy is a cost control, not a nicety.

### 4.2 Levers, ranked by typical impact

1. **Fewer model calls.** Delete a node, don't optimize it.
2. **Right-size the model per node.** Routing/classification/extraction on a cheap model.
3. **Prompt caching** for stable prefixes.
4. **Bound context** — trim/summarize.
5. **Cache deterministic sub-results.**
6. **Cap loops** — one runaway agent can cost more than a thousand normal runs.
7. **Trim tool definitions** — every tool schema is in every prompt of the loop.

### 4.3 Controls

- Per-run token budget enforced in state, not just monitored.
- Call-limit middleware.
- Alerts on daily spend and on p99 cost per run.
- Cost attribution by tenant/feature via trace metadata.

---

## 5. Testing

### 5.1 The test pyramid for agents

```
        ┌─────────────────┐
        │  Eval sets      │  slow, non-deterministic, quality
        ├─────────────────┤
        │  Graph tests    │  topology, routing, interrupts — mock the model
        ├─────────────────┤
        │  Node tests     │  fast, deterministic, most of your tests
        └─────────────────┘
```

**Node tests** — a node is `(state) -> dict`. Test it as a function. No graph, no model.

```python
def test_route_escalates_on_low_confidence():
    assert route({"confidence": 0.2}) == "escalate"
```

**Graph tests** — mock the model, assert the *path*.

```python
def test_tool_failure_routes_to_fallback():
    graph = build(model=FakeModel([...]))
    result = graph.invoke({"messages": [...]}, cfg)
    assert result["status"] == "fallback"
```

Use `InMemorySaver` here; test interrupts by asserting `get_state(cfg).next`.

**Eval sets** — 30–50 real cases with expected outcomes. Run in CI on prompt/model
changes. Assert on: correctness where checkable, required tool calls, absence of
forbidden behaviour, cost and step-count ceilings.

### 5.2 What to assert on non-deterministic output

Ranked by reliability:
1. **Deterministic checks** — schema validity, required fields, citations present,
   tests pass, no forbidden tool called.
2. **Constraint checks** — length, format, language, no PII leaked.
3. **Reference comparison** — semantic similarity to a known-good answer.
4. **LLM-as-judge** — last resort. Validate the judge against human labels before
   trusting it, or you're optimizing against noise.

### 5.3 Test the failure paths

The paths nobody tests and everybody needs: tool timeout, model refusal, empty
retrieval, malformed structured output, interrupt→resume, recursion-limit hit, replay
after a crash.

---

## 6. Versioning and deployment

### 6.1 What has a version

| Artifact | Why it matters |
|---|---|
| Graph topology | Node names live in checkpoints; renames break in-flight threads |
| State schema | Old checkpoints deserialize into new code |
| Prompts | The most frequently changed, least version-controlled artifact |
| Model + params | Provider model updates change behaviour under you |
| Tool schemas | Changing args breaks pending tool calls |

**Pin model versions explicitly.** "Latest" silently changing under you is an outage
you cannot diagnose.

### 6.2 Safe change classes

| Change | Safe for in-flight threads? |
|---|---|
| Prompt wording | ✅ |
| Adding an optional state key | ✅ |
| Adding a node not on existing paths | ✅ |
| Adding a tool | ⚠️ pending tool calls unaffected; behaviour changes |
| Renaming a node | ❌ migration |
| Changing a reducer | ❌ migration |
| Removing a node on an active path | ❌ migration |

**Migration procedure:** deploy the new version alongside; route new threads to it;
let old threads drain or explicitly migrate/terminate them.

### 6.3 Rollout

Canary → monitor cost/error/eval → ramp. Keep the previous version deployable. Have a
documented rollback that accounts for in-flight threads.

### 6.4 Configuration-as-variant

A powerful pattern regardless of hosting: **the same graph, parameterized by
`context_schema`, is a different assistant.**

```python
@dataclass
class Context:
    user_id: str
    role_prompt: str = DEFAULT
    category: str = "general"
    model: str = "gpt-4.1"
```

One deployment serves a "personal" and a "work" assistant, or per-tenant behaviour,
with no code duplication. Version these configurations like code — a prompt change is
a behaviour change.

### 6.5 Deployment shapes (brief)

- **Embedded** in your own service — most control, you own queue/persistence/streaming.
- **LangGraph Server** (self-hosted or managed) — declared by `langgraph.json`; gives
  you thread persistence, a task queue, streaming, and run-concurrency policy.

Whatever you choose, you must answer: **what happens when a second request arrives on
a busy thread?** (reject / enqueue / interrupt / rollback — see `01-architecture.md` §6).

---

## 7. Security

### 7.1 Threat model

| Threat | Vector | Mitigation |
|---|---|---|
| Prompt injection | Retrieved docs, tool output, **stored memories**, user input | Delimit+label untrusted content; never let it choose namespaces or tools without a gate; **enforce authz at the data layer** |
| Data exfiltration | Agent calls a tool with sensitive data | Restrict outbound tools; approval gate; egress allowlists |
| Excessive agency | Agent has more permission than the user | Per-user credentials; least privilege |
| Cross-tenant leakage | Namespace/thread built from untrusted input | Identity from authenticated context only |
| Secret leakage | Secrets in prompts, state, logs, traces | Secret manager; never in state; scrub traces |
| Resource exhaustion | Adversarial input triggers loops/fan-out | Call limits, rate limits, cost ceilings |
| Unauthorized resume | `thread_id` treated as an identifier | Authorize resume server-side |

### 7.2 The rule that carries the most weight

> **Authorization must be enforced at the data layer, for the end user — never by the
> agent's prompt.**

If the agent uses a service account and filters results by instruction, then any
injection, routing bug, or hallucination becomes a data breach. If the agent uses the
*user's* credentials, the worst case of a hijacked agent is that it does something the
user could already do.

### 7.3 Practical controls

- Secrets from a secret manager; never in `langgraph.json`, code, or state.
- Tool allowlists per assistant/role.
- Validate and bound all tool inputs (Pydantic).
- Bound tool *outputs* too — a tool returning 200KB is both a cost and an injection surface.
- Scrub PII from logs and traces.
- Rate limit per user, not just globally.
- Audit log for consequential actions: who, what, when, approved-by.

---

## 8. Governance

- **Accountability:** a named owner for the agent's behaviour.
- **Disclosure:** users know they're talking to an AI, and know when memory is stored.
- **Human override:** a documented path to stop or reverse an agent action.
- **Data rights:** view, export, delete — including memories and thread history.
- **Change control:** prompt changes reviewed like code, because they are.
- **Incident procedure:** how to disable a tool, pause a graph, or drain threads fast.

---

## 9. Production readiness — one-page summary

| Area | Minimum bar |
|---|---|
| Persistence | Postgres checkpointer; async if the service is async |
| Loop safety | recursion limit + explicit counter + call limits |
| Retries | Narrow policies on idempotent network nodes only |
| Fallback | Cross-provider model fallback, tested |
| Tracing | Enabled, tagged with version + tenant |
| Metrics | Latency p95, cost p95, error rate, paused-thread count |
| Alerts | Cost spike, error rate, stuck threads |
| Context | A concrete strategy; measured under long conversations |
| Eval | 30+ cases in CI; regression-gated prompt changes |
| Security | Per-user authz at the data layer; secrets managed; injection surfaces enumerated |
| HITL | Notification + timeout + authorized resume + audit trail |
| Ops | Runbook incl. "resume the stuck thread"; rollback tested |
