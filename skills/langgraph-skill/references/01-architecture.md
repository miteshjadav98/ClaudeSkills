# Graph Architecture

How to shape a graph, compose graphs, and run work concurrently.

---

## 1. The mental model

LangGraph is a **state machine with a shared, reducer-merged store**, executed in
**supersteps** (BSP-style):

1. A superstep runs every node scheduled for that step, **concurrently**.
2. Each node receives the state as of the *start* of the step and returns a
   **partial update**.
3. At the *end* of the step, all updates are merged through the reducers.
4. Edges determine what is scheduled next. Repeat until nothing is scheduled.

Three consequences that explain most confusing behaviour:

- **Nodes in the same step do not see each other's writes.** They see the previous
  step's state.
- **Two nodes writing the same key in one step need a reducer**, or LangGraph raises
  `InvalidUpdateError` — it refuses to guess which write wins.
- **A checkpoint is written per superstep**, which is why resume, replay, and forking
  are step-granular.

---

## 2. Topologies

### 2.1 Chain (linear)

```
START → extract → transform → format → END
```

**Use when:** every step always runs, in a fixed order.
**Strengths:** deterministic, cheapest, trivially unit-testable, no LLM routing cost.
**Weakness:** cannot adapt.
**Anti-pattern:** using an LLM router where a chain suffices — you pay a model call to
decide something you already know.

Real uses: document ingestion, ETL-with-LLM-enrichment, fixed report generation,
scoring pipelines.

### 2.2 Router (conditional edges)

```
START → classify ──cond──→ handler_billing → END
                   ├─────→ handler_tech    → END
                   └─────→ handler_general → END
```

A conditional edge is a **function returning the name(s) of the next node**. It is
plain Python — it does *not* have to call an LLM. The cheapest router is `if/else`
over state.

```python
def route(state) -> Literal["a", "b", END]:
    return "a" if state["score"] > 0.8 else "b"

builder.add_conditional_edges("classify", route, ["a", "b", END])
```

Always pass the **explicit destination list** (third argument) or use
`add_node(..., destinations=...)`. Without it, the rendered graph and static analysis
cannot see where the edge can go, which makes diagrams and Studio misleading.

**Use when:** the set of paths is known; only the choice is dynamic.
**Strengths:** one decision, bounded, observable.
**Weakness:** cannot iterate or revisit.

Real uses: intent classification, triage, tier-1 vs tier-2 support, model selection
(cheap model for easy queries, strong model for hard ones).

### 2.3 ReAct agent (the tool loop)

```
START → assistant ──tools_condition──→ tools ──→ (back to assistant)
                          └──────────→ END
```

The single most important agent pattern: **reason → act → observe → repeat**. The
loop exists because feeding tool results *back to the model* lets it decide whether
it now has enough to answer, or needs another tool.

```python
builder.add_node("assistant", assistant)
builder.add_node("tools", ToolNode(tools))
builder.add_edge(START, "assistant")
builder.add_conditional_edges("assistant", tools_condition, {"tools": "tools", END: END})
builder.add_edge("tools", "assistant")     # ← the loop
```

**Prefer the prebuilt** (`create_agent` from `langchain.agents`, or
`create_react_agent` from `langgraph.prebuilt`) unless you need to modify the loop
itself. Hand-rolling the loop to add one custom step is usually solved better by
middleware.

**Strengths:** handles open-ended tasks; composes with any tool.
**Weaknesses:** unbounded iteration, unbounded cost, non-deterministic. The message
list grows with every observation.
**Mandatory guardrails:** recursion limit, model-call limit, tool-call limit, and a
context strategy. See `10-production.md`.

### 2.4 Parallel fan-out / fan-in

```
START ─┬→ search_web  ─┐
       └→ search_docs ─┴→ synthesize → END
```

**Use when:** independent operations whose results are combined. The classic case is
gathering context from several sources before one generation step.

Two hard requirements:

1. **The shared output key needs a reducer** (`Annotated[list, operator.add]`).
2. **Fan-in ordering is not controllable** by topology. Within a step, LangGraph
   picks a deterministic-but-unspecified order.

If order matters, pick one:
- a **sorting reducer** (simple, but sorts globally — often not what you want);
- **separate keys per branch** plus a join node that assembles them in the order you
  want (recommended — explicit and readable);
- attach an ordering field to each item and sort in the consumer.

**Uneven branch lengths:** `add_edge(["b2", "c"], "d")` makes `d` wait for *both*.
Use `add_node("d", d, defer=True)` when you want a node to run only once everything
else that could feed it has finished.

**Latency reality check:** parallel branches cut wall-clock time but **not token
cost** — you still pay for every branch. If one branch is usually unnecessary, a
router is cheaper than parallelism.

### 2.5 Map-reduce with `Send`

```
START → plan ──Send × N──→ worker → reduce → END
```

Fan-out where **N is not known until runtime**. This is what `Send` exists for.

```python
from langgraph.types import Send

def fan_out(state):
    return [Send("worker", {"item": x}) for x in state["items"]]

builder.add_conditional_edges("plan", fan_out, ["worker"])
```

Two properties that make `Send` special:

- **The payload does not have to match the parent state schema.** Each worker gets its
  own private input. This is the cleanest way to give workers isolated state.
- **Results merge back through the parent's reducer**, so the collector key must be
  `Annotated[list, operator.add]` (or similar).

**Use when:** same operation over a dynamic collection — N documents, N subtopics,
N candidate answers, N test cases.
**Do not use when:** the operations differ (use parallel branches) or N is huge and
unbounded (add batching/limits, or you will fan out 5,000 LLM calls).

**Scaling:** cap N explicitly. Rate limits and cost both bite here. Batch items into
chunks of k per worker rather than one worker per item when items are small.

### 2.6 Supervisor

```
START → supervisor ──cond──→ researcher ─┐
              │      ├─────→ writer ─────┤
              │      └─────→ END         │
              └──────────────────────────┘
```

One coordinator node decides which specialist runs next; specialists report back.

**Strengths:** routing intelligence centralized and inspectable; specialists stay
small and independently testable; easy to add a specialist.
**Weaknesses:** supervisor is a bottleneck and a single point of prompt failure;
every hop costs a model call; the supervisor's context grows with each report.
**Production advice:** give the supervisor a **structured** output (a typed decision,
not free text), bound the number of hops, and summarize specialist reports before
they enter the supervisor's context.

### 2.7 Network / peer multi-agent

Agents hand off to each other directly (via `Command(goto=...)`) with no coordinator.

**Use only when** handoff logic is genuinely local knowledge and a supervisor would
be a pure bottleneck. Debugging is materially harder — there is no single place that
knows why control moved. **Default to supervisor.**

---

## 3. Subgraphs and composition

### 3.1 What a subgraph buys you

- **State isolation** — the subgraph has its own schema and its own scratch keys.
- **Independent testing** — compile and invoke it standalone.
- **Reuse** — same subgraph in several parents.
- **Cognitive scale** — a 40-node flat graph is unreadable; 4 subgraphs of 10 are fine.

### 3.2 The two composition modes

**(a) Shared-schema subgraph — add the compiled graph directly as a node.**

```python
parent.add_node("analysis", sub_builder.compile())
```

Communication happens through **overlapping state keys**. The parent passes keys the
subgraph declares; the subgraph writes back keys the parent declares. Keys that exist
only in the subgraph stay private to it.

This is the cleanest option **when the schemas genuinely overlap**.

**(b) Different-schema subgraph — wrap it in a function node and translate.**

```python
def analysis_node(state: ParentState) -> dict:
    result = sub_graph.invoke({"docs": state["raw_docs"]})   # map in
    return {"summary": result["report"]}                     # map out
```

This is the option to prefer when the subgraph is a **reusable component**. The
explicit translation layer is a feature: it documents the contract and stops parent
schema changes from silently breaking the child.

### 3.3 Rules and gotchas

- Use `output_schema` on the subgraph to publish only what the parent should see.
  Without it, every internal scratch key leaks into the parent's namespace on merge.
- **Keys written by both the subgraph and other parallel parent nodes need a reducer
  in the parent.**
- Checkpointers propagate to subgraphs automatically — do not compile a child with its
  own checkpointer when it runs inside a parent.
- To stream or inspect inside subgraphs, pass `subgraphs=True` to `stream()` and use
  `xray=True` when drawing the graph.
- **Interrupts inside a subgraph propagate to the parent run.** Resume targets the
  parent thread.

### 3.4 When *not* to use a subgraph

- Fewer than ~4 nodes and no reuse → just inline them. A subgraph adds an indirection
  layer and a state-mapping surface for no benefit.
- You only wanted namespacing → use naming conventions or private-state keys.
- You wanted parallelism → that's `Send` / fan-out, not subgraphs.

---

## 4. Case study: research assistant architecture

This is the reference multi-pattern architecture — worth internalizing because it
composes **five** patterns in one graph.

```
START → create_analysts → human_feedback (interrupt)
                               │
                     ┌─────────┴──────── "revise" ──→ back to create_analysts
                     │
                 Send × N (one per analyst)
                     │
                     ▼
        ┌─────── conduct_interview (SUBGRAPH) ────────┐
        │  ask_question ─┬→ search_web    ─┐          │
        │                └→ search_wiki    ─┴→ answer │
        │  answer ──cond──→ ask_question (loop, capped)│
        │           └────→ save → write_section       │
        └─────────────────────────────────────────────┘
                     │  (sections accumulate via reducer)
        ┌────────────┼────────────┐
        ▼            ▼            ▼          (parallel)
   write_intro  write_body  write_conclusion
        └────────────┼────────────┘
                     ▼
              finalize_report → END
```

**Patterns composed:**

| Layer | Pattern | Why it's there |
|---|---|---|
| Analyst generation | Structured output | Forces a typed list of personas, not prose |
| Human feedback | Interrupt + loop-back | Cheap to fix personas *before* N expensive interviews |
| Interview dispatch | `Send` map | N unknown until analysts are generated |
| Interview internals | Subgraph | Own message state per analyst; isolated and testable |
| Source gathering | Parallel fan-out | Web + wiki concurrently, merged via `operator.add` |
| Interview turn-taking | Conditional loop + **turn cap** | Bounded iteration |
| Report assembly | Parallel + fan-in | Intro/body/conclusion are independent |

**Engineering lessons worth stealing:**

1. **Put the human gate before the expensive fan-out.** Approving 4 personas costs
   nothing; regenerating 4 full interviews costs a lot.
2. **Cap every conversational loop with a counter**, not only with a "the model said
   thanks" heuristic. Semantic stop conditions fail; counters don't.
3. **Duplicate the collector key in both the subgraph and parent schema** so `Send`
   results have somewhere to land.
4. **A failing source must not kill the run.** Wrap each retrieval branch so one dead
   API returns empty context instead of aborting N parallel interviews.
5. **Sub-results are strings by the time they reach the reducer.** Serializing early
   (interview → transcript → section) keeps parent state small and checkpoints fast.

**Real-world analogues:** competitive-intelligence briefs, due-diligence memos,
literature reviews, incident post-mortems, multi-source compliance reports.

---

## 5. Organizing large graphs

Once you pass ~15 nodes:

```
agent/
├── graph.py              # assembly ONLY: nodes, edges, compile. No logic.
├── state.py              # schemas + reducers (single source of truth)
├── context.py            # context_schema (runtime config: user_id, model, flags)
├── nodes/
│   ├── retrieve.py       # one file per node/node-group; pure-ish functions
│   └── generate.py
├── subgraphs/
│   └── interview/        # each subgraph is its own mini-package with the same layout
├── tools/
├── prompts/              # prompts as data, versioned, not inline f-strings
└── tests/
```

Rules that keep this maintainable:

- **`graph.py` contains no business logic.** If you can't see the whole topology on
  one screen, extract a subgraph.
- **Nodes are functions of `(state) -> dict`.** Keep I/O at the edges; keep the
  transformation testable without a graph.
- **Prompts live in files, not f-strings scattered across nodes.** They change more
  often than code and need review.
- **One schema module.** Two definitions of "the state" is how drift starts.
- **Node names are a public API** — they appear in checkpoints, traces, `interrupt_before`
  lists, and stored state. Renaming a node invalidates in-flight threads. Treat renames
  as migrations.

---

## 6. Deployment shape (kept deliberately brief)

LangGraph graphs are plain Python objects; you can serve them from anything.

- **Embedded:** import the compiled graph into your existing FastAPI/Django service.
  You own persistence, queuing, and streaming. Most control, most work.
- **Self-hosted LangGraph Server:** `langgraph.json` declares graphs, deps, env.
  Gives you a task queue, thread persistence, streaming, and run-concurrency handling
  out of the box.
- **Managed platform:** same, hosted.

The one concept worth carrying regardless of host: **run concurrency policy** — what
happens when a second request arrives on a thread that is still running.

| Policy | Behaviour | Fits |
|---|---|---|
| Reject | Refuse the new run | Transactional flows where interleaving is unsafe |
| Enqueue | Finish current, then run new | Task/queue assistants; preserves all work |
| Interrupt | Stop current (keep partial state), run new | Chat UIs — user changed their mind |
| Rollback | Discard current, run new | Chat where the superseded run's output is noise |

If you build embedded, **you must decide this yourself** — it does not solve itself,
and "both runs write to the same thread" is a real corruption bug.
