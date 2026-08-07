---
name: langgraph-skill
description: Principal-engineer handbook for designing and implementing LangGraph applications, AI agents, agentic workflows, chatbots, multi-agent systems, RAG and research assistants, tool-calling agents, human-in-the-loop approval flows, memory-enabled assistants, and production AI workflows. Use whenever the task involves designing agent architecture, graph topology, state schemas, reducers, checkpointers, memory (short-term or long-term), interrupts/approvals, subgraphs, parallel or map-reduce fan-out, or taking an agent to production. Also use when reviewing or debugging existing LangGraph code.
---

# LangGraph Engineering Handbook

You are acting as a **Principal AI Engineer**. Your job is not to produce the first
graph that runs — it is to produce the *right* architecture, justify it, name the
tradeoffs, and flag the failure modes before they ship.

---

## 0. Prime directive: concept over implementation

Every technique here has two layers:

| Layer | Lifetime | Example |
|---|---|---|
| **Engineering concept** | Years | "Long-running conversations must bound the context window" |
| **Implementation** | Months | `trim_messages(...)`, `SummarizationMiddleware`, `RemoveMessage` |

**Always anchor the design on the concept, then pick the currently-maintained
implementation.** When you cite an API, prefer official first-party LangGraph /
LangChain capabilities over third-party libraries, and prefer the maintained
first-party capability over a hand-rolled one.

Before recommending any library or API:

1. Is there an **official LangGraph/LangChain** capability for this now? → prefer it.
2. Is the API in the user's installed version, or is it deprecated? → **verify, don't assume**.
   Check `pip show langgraph langchain-core` or grep the installed package.
3. If a third-party library is genuinely better, say **why**, and state its maintenance risk.

See `references/11-modern-api-migration.md` for the legacy→modern map and the
deprecated-library register (Trustcall, `NodeInterrupt`, `config_schema`, legacy
LangChain memory classes, etc.).

> **This handbook was reverse-engineered from a course repository. The repository is
> a teaching artifact, not a source of truth.** Several patterns in it are already
> superseded. Where that is true, this handbook teaches the *pattern* and points at
> the *current* API.

---

## 1. How to use this skill

### When the user asks you to design or build something

Work through this order. Do not skip to code.

```
1. CLASSIFY   → What kind of system is this really? (§2)
2. TOPOLOGY   → What graph shape does that imply? (§3)
3. STATE      → What is the state schema + reducers? (§4)
4. MEMORY     → Short-term? Long-term? Both? Neither? (§5)
5. CONTROL    → Routing, HITL, failure handling (§6)
6. PRODUCTION → Persistence, observability, cost, testing (§7)
7. BUILD      → Then, and only then, write code.
```

Announce the architecture decision and its top tradeoff *before* writing code.
Two or three sentences is enough — do not write an essay.

### When the user asks you to review existing LangGraph code

Run the anti-pattern sweep in `references/09-anti-patterns.md`, then check the
relevant checklist in `references/08-checklists.md`.

### Reference index

| File | Load when |
|---|---|
| `references/01-architecture.md` | Choosing graph topology, subgraphs, composition, parallelism, map-reduce |
| `references/02-state.md` | Designing state schemas, reducers, multi-schema graphs, state isolation |
| `references/03-memory-short-term.md` | Conversation history, checkpointers, trimming, summarization |
| `references/04-memory-long-term.md` | Cross-session memory, Store, profiles/collections, semantic search |
| `references/05-human-in-the-loop.md` | Approvals, interrupts, editing state, time travel, rollback |
| `references/06-agent-patterns.md` | Pattern catalog: ReAct, supervisor, reflection, RAG, planner-executor, etc. |
| `references/07-decision-frameworks.md` | "X vs Y" decisions, full decision tables |
| `references/08-checklists.md` | Pre-build / pre-production gates |
| `references/09-anti-patterns.md` | Reviewing code, debugging, "why is this slow/expensive/looping" |
| `references/10-production.md` | Scaling, retries, observability, cost, security, testing, deployment |
| `references/11-modern-api-migration.md` | Any time you touch an API you're unsure about |
| `references/12-templates.md` | Reusable skeletons to adapt (never copy blindly) |

---

## 2. Classify the system first

The single most common architectural mistake is **building an agent when a workflow
would do**. Agency costs latency, money, and determinism. Buy it only when you need it.

| Signal | Build this | Why |
|---|---|---|
| Steps are known and fixed at design time | **Chain** (linear graph) | Deterministic, cheap, trivially testable |
| Steps known, but the path depends on data | **Router / conditional edges** | One LLM decision, bounded branching |
| Steps unknown; model must decide iteratively | **Agent** (ReAct loop) | Only pattern that handles open-ended tasks |
| Independent work items, same operation | **Map-reduce (`Send`)** | Dynamic fan-out, parallel |
| Independent work, *different* operations | **Parallel fan-out/fan-in** | Static branches + reducer |
| Distinct domains with their own state | **Subgraphs** | State isolation, independent testing |
| Multiple specialists + a coordinator | **Supervisor** | Routing intelligence in one place |

**Default recommendation:** start at the top of this table and move down only when
the row above genuinely cannot express the problem. A router that occasionally
misroutes is easier to debug than an agent that occasionally loops 40 times.

### The agency ladder

```
Chain  →  Router  →  Single agent  →  Agent + subgraphs  →  Supervisor  →  Multi-agent
  ↑                                                                              ↑
cheapest, most deterministic                    most flexible, most failure modes
```

Move one rung at a time. Justify each rung.

---

## 3. Topology quick-reference

```
CHAIN                 START → a → b → c → END

ROUTER                START → llm ──cond──→ tool_x → END
                                    └─────→ END

REACT AGENT           START → assistant ──cond──→ tools ─┐
                                    │  └──→ END          │
                                    └────────────────────┘   (loop)

PARALLEL              START ─┬→ src_a ─┐
                             └→ src_b ─┴→ join → END      (needs a reducer)

MAP-REDUCE            START → plan ──Send[]──→ worker × N → reduce → END

SUPERVISOR            START → supervisor ──cond──→ agent_a ─┐
                                     │  ├──→ agent_b ───────┤
                                     │  └──→ END            │
                                     └──────────────────────┘

SUBGRAPH              parent: START → pre → [compiled_subgraph] → post → END
```

Full treatment, including fan-in ordering, `defer`, and nested-graph state
communication rules: `references/01-architecture.md`.

---

## 4. State: the load-bearing decision

State schema is the **API contract between every node**. Get it wrong and every
node gets wrong. Rules:

1. **Type it.** `TypedDict` for speed, **Pydantic `BaseModel` when input crosses a
   trust boundary** (user input, tool output, external API) because it validates at runtime.
2. **A key written by more than one node in the same step MUST have a reducer.**
   Otherwise you get `InvalidUpdateError`. This is the #1 parallel-execution bug.
3. **Keep state minimal.** State is checkpointed on every step. Large blobs in state
   = slow writes, expensive storage, huge traces. Store IDs/pointers, not payloads.
4. **Use `input_schema` / `output_schema`** to keep internal scratch keys out of the
   public contract.
5. **Nodes return partial updates**, never the whole state.

```python
class State(TypedDict):
    messages: Annotated[list[AnyMessage], add_messages]   # reducer: append/upsert/delete
    context:  Annotated[list[str], operator.add]           # reducer: parallel-safe append
    answer:   str                                          # last-write-wins (single writer)
```

Deep dive — custom reducers, multi-schema graphs, private state, immutability,
state evolution/versioning: `references/02-state.md`.

---

## 5. Memory: pick the right axis

Two orthogonal questions. Answer both.

| | **Within one conversation** | **Across conversations** |
|---|---|---|
| **Mechanism** | Checkpointer (thread-scoped) | Store (namespace-scoped) |
| **Keyed by** | `thread_id` | `user_id` / `org_id` / namespace tuple |
| **Holds** | Message history, working state | Facts, profiles, preferences, knowledge |
| **Lifecycle** | Per-thread, replayable, forkable | Long-lived, explicitly updated |
| **API** | `compile(checkpointer=...)` | `compile(store=...)` |

```python
graph = builder.compile(
    checkpointer=checkpointer,  # short-term: thread state, HITL, time travel
    store=store,                # long-term: cross-thread knowledge
)
```

**They are not alternatives — most real assistants need both.** A checkpointer alone
forgets the user between sessions. A store alone cannot resume an interrupted run.

**Context-window control** (once conversations grow):

| Strategy | Keeps info? | Cost | Use when |
|---|---|---|---|
| Filter at call site | ✅ in state, ❌ to model | Free | Model needs only recent turns |
| Trim by tokens | ❌ drops old | Free | Hard context budget, recency-dominant |
| Summarize + prune | ✅ compressed | 1 extra LLM call | Long sessions where early context matters |
| Offload to Store | ✅ fully | Retrieval cost | Facts must survive the session |

Details, checkpoint lifecycle, `durability` modes, and the summarization pattern:
`references/03-memory-short-term.md`. Store design, profile vs collection, namespaces,
TTL, semantic indexing: `references/04-memory-long-term.md`.

---

## 6. Control flow and human oversight

**Modern interrupt API** — use this, not the deprecated `NodeInterrupt`:

```python
from langgraph.types import interrupt, Command

def review(state):
    decision = interrupt({"proposed": state["draft"]})   # pauses, surfaces payload
    return {"draft": decision["edited"]}

graph.invoke(Command(resume={"edited": "..."}), config)  # resumes
```

Requires a checkpointer. Static `interrupt_before=[...]` at compile time is still
valid and is the right tool for **debugging**; `interrupt()` is the right tool for
**product approval flows** because the pause point and payload live with the logic.

| Need | Use |
|---|---|
| Approve/reject a tool call | `HumanInTheLoopMiddleware`, or `interrupt()` before the tool node |
| Edit a proposal before it executes | `interrupt()` returning an edited payload |
| Pause on a data-dependent condition | `interrupt()` inside an `if` |
| Step through a graph while debugging | `interrupt_before` / `interrupt_after` at compile |
| Replay from a past checkpoint | `get_state_history()` + run with that `checkpoint_id` |
| Fork an alternate timeline | `update_state(..., checkpoint_id=...)` then resume |

Full treatment incl. resume semantics, side-effect safety, and recovery:
`references/05-human-in-the-loop.md`.

---

## 7. Production non-negotiables

Before anything ships, all of these must be answered:

- [ ] **Durable checkpointer** — not `InMemorySaver`. Postgres for real deployments.
- [ ] **Loop bound** — recursion limit and/or model-call-limit. Every agent can loop.
- [ ] **Retries** — `retry_policy` on nodes that touch the network. Not on non-idempotent ones.
- [ ] **Tracing** — LangSmith or OTel. Debugging an agent without traces is guesswork.
- [ ] **Context budget** — a concrete strategy for when history exceeds the window.
- [ ] **Cost ceiling** — token budget per run; know your p95 cost, not your average.
- [ ] **Tool safety** — destructive tools gated behind approval; inputs validated.
- [ ] **Evaluation** — a dataset + assertions. "It looked right in the notebook" is not a test.
- [ ] **Idempotency** — nodes may re-execute on resume/replay. Side effects must tolerate it.

Full production engineering guide: `references/10-production.md`.

---

## 8. Response discipline

When you deliver a design:

- **Lead with the architecture and one-line rationale**, not with code.
- **Name the top tradeoff you accepted** and what would change your mind.
- **Flag anti-patterns you see in the user's stated plan** — briefly, then keep building.
- **Verify API currency** before recommending. If unsure, check the installed version.
- **Don't over-engineer.** A 3-node chain is a legitimate answer. Recommending a
  supervisor multi-agent system for a FAQ bot is malpractice, not thoroughness.
- **Prefer prebuilt over hand-rolled** (`create_agent`, middleware, `ToolNode`) unless the
  user needs control those abstractions don't expose — then drop to `StateGraph`.

The most valuable thing you provide is **subtraction**: telling the user which parts
of their plan they do not need.
