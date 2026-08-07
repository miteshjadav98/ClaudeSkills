# Short-Term Memory (Within-Thread)

Short-term memory = **the state of one conversation/run**, persisted by a
**checkpointer**, keyed by `thread_id`.

Without a checkpointer, graph state is **transient to a single invocation**. Call
`invoke()` twice and the second call knows nothing about the first. That is the entire
problem checkpointers solve.

---

## 1. Checkpointers

### 1.1 What they actually do

On **every superstep**, the checkpointer writes:

- the full channel values (state),
- the next nodes to execute,
- pending writes from nodes that already finished,
- metadata (step number, source, parent checkpoint id).

That single mechanism gives you **five** capabilities at once:

| Capability | Mechanism |
|---|---|
| Multi-turn conversation | Resume from the last checkpoint on the same `thread_id` |
| Human-in-the-loop | Pause mid-run, persist, resume later — even in another process |
| Fault tolerance | Crash mid-run → resume from last good step, not from scratch |
| Time travel | Replay from any historical `checkpoint_id` |
| Forking | Update state at an old checkpoint → new branch |

You cannot have interrupts, time travel, or durable resume **without** a checkpointer.
This is why "add a checkpointer" is step one for almost every real agent.

### 1.2 Choosing one

| Checkpointer | Persistence | Concurrency | Use for |
|---|---|---|---|
| `InMemorySaver` | Process memory | Single process | Tests, notebooks, demos |
| SQLite (`langgraph-checkpoint-sqlite`) | Local file | Single writer | Local dev, single-user desktop apps, prototypes |
| **Postgres** (`langgraph-checkpoint-postgres`) | Durable, networked | Multi-worker | **Production. Default choice.** |
| Custom (`BaseCheckpointSaver`) | Yours | Yours | Existing infra you must reuse |

```python
# Dev
from langgraph.checkpoint.memory import InMemorySaver
graph = builder.compile(checkpointer=InMemorySaver())

# Production
from langgraph.checkpoint.postgres import PostgresSaver
with PostgresSaver.from_conn_string(DB_URL) as cp:
    cp.setup()                       # run once; creates tables
    graph = builder.compile(checkpointer=cp)
```

> `MemorySaver` is the old name for `InMemorySaver`; both appear in older material.
> Use `InMemorySaver`.

**Production notes:**
- Use the **async** saver (`AsyncPostgresSaver`) in async services, or you will block
  the event loop on every step.
- `.setup()` is a migration — run it in deploy, not per-request.
- Connection pooling matters: you write once per superstep per run.

### 1.3 Threads

A `thread_id` groups checkpoints into one conversation.

```python
config = {"configurable": {"thread_id": "conv-123"}}
graph.invoke({"messages": [msg]}, config)   # appends to that thread
```

**Design decisions you must make explicitly:**

- **What is a thread?** One chat session? One ticket? One document? Get this wrong and
  users either lose context or see other contexts bleed in.
- **Thread ids must be unguessable if they carry private data** — a thread id is a
  capability. Use UUIDs, and authorize on the server side anyway.
- **Threads grow forever** unless you bound them. See §2.
- **Retention/deletion policy** — GDPR/CCPA deletion means deleting the thread's
  checkpoints, not just clearing `messages` in current state.

### 1.4 Durability modes

Controls how aggressively state is persisted:

```python
graph.invoke(inp, config, durability="async")   # default
```

| Mode | Behaviour | Trade |
|---|---|---|
| `"exit"` | Persist only at the end of the run | Fastest; a crash loses the whole run |
| `"async"` | Persist each step, don't block on the write | **Default. Right for almost everything.** |
| `"sync"` | Persist each step, block until durable | Slowest; strongest guarantee |

Use `"sync"` when a node has **external side effects you must never repeat** (charging
a card, sending an email) and you need the checkpoint durable before the next step
begins. Use `"exit"` only for short, cheap, side-effect-free runs.

> `checkpoint_during=` is deprecated → use `durability=`.

### 1.5 Common checkpointer mistakes

| Mistake | Consequence |
|---|---|
| `InMemorySaver` in production | All conversations lost on restart/redeploy; breaks with >1 worker |
| No `thread_id` when a checkpointer is compiled | Runtime error |
| Reusing one `thread_id` across users | **Cross-user data leakage.** Treat as a security bug |
| Compiling a checkpointer into a subgraph used by a parent | Double persistence, confused resume |
| Never pruning threads | Storage growth and slow history queries |
| Assuming nodes run exactly once | On resume/replay a node may re-run — make side effects idempotent |

---

## 2. Bounding the conversation

Every long conversation eventually blows the context window, the latency budget, or
the cost budget — usually all three, because **cost grows quadratically** with turns
(each turn resends the whole history).

Four strategies. They compose.

### 2.1 Filter at the call site (state unchanged)

```python
def call_model(state):
    return {"messages": [llm.invoke(state["messages"][-6:])]}
```

- **Keeps:** full history in state for audit/UI.
- **Costs:** nothing.
- **Loses:** the model's access to older context.
- **Use when:** only recency matters (small talk, command-style bots) and you still
  want the full transcript.
- **Watch:** slicing can orphan a `tool_calls` message from its `ToolMessage`. Slice
  at turn boundaries.

### 2.2 Trim by token budget

```python
from langchain_core.messages import trim_messages

trimmed = trim_messages(
    state["messages"],
    max_tokens=4000,
    strategy="last",
    token_counter=llm,
    start_on="human",          # keeps message sequences valid
    include_system=True,
)
```

- **Keeps:** a hard, predictable context budget.
- **Costs:** nothing (token counting is cheap).
- **Loses:** old content, irrecoverably from the model's view.
- **Use when:** you need a guaranteed ceiling on prompt size.
- **Prefer over naive slicing** — it counts tokens rather than messages, and
  `start_on`/`include_system` protect message-sequence validity.

### 2.3 Summarize and prune

The high-value pattern for long assistants: compress old turns into a running summary,
delete the raw messages, inject the summary as a system message.

```
conversation ──cond(len > N)──→ summarize ──→ END
        └──────────────────────────────────→ END
```

```python
class State(MessagesState):
    summary: str

def call_model(state):
    msgs = state["messages"]
    if summary := state.get("summary"):
        msgs = [SystemMessage(f"Conversation so far: {summary}")] + msgs
    return {"messages": llm.invoke(msgs)}

def summarize(state):
    prior = state.get("summary", "")
    prompt = (f"Extend this summary with the new messages:\n{prior}"
              if prior else "Summarize the conversation above:")
    new = llm.invoke(state["messages"] + [HumanMessage(prompt)])
    keep = state["messages"][-2:]                       # keep recent turns verbatim
    drop = [RemoveMessage(id=m.id) for m in state["messages"][:-2]]
    return {"summary": new.content, "messages": drop}
```

- **Keeps:** semantic content of the whole conversation, compressed.
- **Costs:** one extra LLM call per compaction.
- **Risks:** **lossy and irreversible in current state.** Summaries drift; recursive
  re-summarization compounds error; specifics (names, numbers, IDs) get dropped first.
- **Use when:** sessions run long and early context genuinely matters.
- **Production advice:**
  - Trigger on **token count**, not message count. Six messages could be 200 tokens
    or 200k.
  - Prompt the summarizer for the things that actually matter — "preserve names,
    dates, numbers, decisions, and open questions" — otherwise it writes prose.
  - Keep the last 2–4 messages verbatim so the immediate turn isn't paraphrased.
  - Add hysteresis: summarize at 80% of budget down to 40%, so you don't summarize
    on every single turn.
  - The raw messages remain in **checkpoint history** — summarization is a context
    strategy, not a deletion mechanism.

**Modern shortcut:** `SummarizationMiddleware` from `langchain.agents.middleware`
implements this for prebuilt agents. Prefer it over hand-rolling when using
`create_agent`. Hand-roll when you need custom trigger logic or a domain-specific
summary schema.

### 2.4 Offload to long-term memory

Extract durable facts into the Store, then let them be *retrieved* rather than carried.
This is the only strategy that survives the session ending. See `04-memory-long-term.md`.

### 2.5 Choosing

| Situation | Strategy |
|---|---|
| Short sessions, small context | Nothing. Don't pre-optimize |
| Only recent turns matter | Filter or trim |
| Hard prompt-size ceiling required | Trim by tokens |
| Long sessions, early context matters | Summarize + prune |
| Facts must survive across sessions | Store (long-term) |
| High-volume production assistant | Trim **and** summarize **and** Store |

---

## 3. External / self-managed conversation memory

Sometimes you keep conversation history in **your own** database (existing chat
product, compliance requirements, an ORM you already own).

**Two valid designs:**

1. **Custom checkpointer** — implement `BaseCheckpointSaver` over your store. You keep
   interrupts, replay, and forking. More work, full feature parity.
2. **Load-and-inject** — a node reads history from your DB and puts it in state;
   another writes it back. Simple, but you **lose** time travel and durable resume
   unless you also have a checkpointer.

**Do not** do (2) and then expect interrupts to work. Interrupts require a checkpointer.

**Anti-pattern:** two sources of truth — history in both your DB and the checkpointer,
drifting apart. Pick one owner and treat the other as a projection.

---

## 4. Checkpoint lifecycle

```
invoke ──► step 1 ──► checkpoint ──► step 2 ──► checkpoint ──► ... ──► END
                          │                        │
                     replayable               forkable via
                     via checkpoint_id        update_state(...)
```

```python
graph.get_state(config)                  # latest StateSnapshot: .values, .next, .tasks
graph.get_state_history(config)          # all checkpoints, newest first
graph.update_state(config, {...})        # write an update (goes through reducers)
graph.invoke(None, config)               # resume from the last checkpoint
```

**Understanding `.next` is the key debugging skill.** It tells you what the graph is
*about to* run — which is how you confirm an interrupt landed where you expected.

**Retention:** checkpoints accumulate per thread per step. A 100-turn conversation
with a 5-node graph is ~500 checkpoints. Have a deletion policy:
- delete threads after N days of inactivity;
- delete on user account deletion (compliance);
- consider `durability="exit"` for high-volume, low-value runs.

---

## 5. Reference decision table

| Question | Answer |
|---|---|
| Do I need a checkpointer? | Yes if: multi-turn, HITL, resumable, or debuggable. Effectively: yes |
| Which checkpointer? | Postgres in prod, SQLite locally, InMemory in tests |
| Where does conversation history live? | `messages` in state, persisted by the checkpointer |
| How do I stop it growing forever? | Trim (hard cap) + summarize (semantic) + Store (durable facts) |
| Trim or summarize? | Trim if recency-dominant; summarize if early context matters; both at scale |
| Where do user facts live? | **Not here.** Store, keyed by user — see `04-memory-long-term.md` |
| How do I reset a conversation? | New `thread_id` (preferred) or `RemoveMessage(REMOVE_ALL_MESSAGES)` |
| Does deleting messages delete history? | **No.** Old checkpoints retain them. Delete the thread |
