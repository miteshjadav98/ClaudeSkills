# Human-in-the-Loop

HITL exists because **autonomous agents are not trustworthy enough for consequential
actions**, and because **debugging a non-deterministic system requires the ability to
stop, inspect, and rewind it**.

Everything here depends on a **checkpointer**. Without persistence there is nothing to
pause into or resume from.

---

## 1. The four motivations

| Motivation | Question it answers | Mechanism |
|---|---|---|
| **Approval** | "Should this action happen?" | `interrupt()` before the action |
| **Editing** | "This is nearly right — fix it" | `interrupt()` returning edited content, or `update_state` |
| **Input** | "I need information only a human has" | `interrupt()` requesting it |
| **Debugging** | "Why did it do that?" | `interrupt_before/after`, `get_state_history`, replay, fork |

Approval and debugging use different tools. Conflating them is the most common
design error in this area.

---

## 2. `interrupt()` — the modern primitive

```python
from langgraph.types import interrupt, Command

def review_email(state):
    decision = interrupt({                    # ← run pauses here, payload surfaced
        "action": "send_email",
        "to": state["recipient"],
        "body": state["draft"],
    })
    if decision["type"] == "reject":
        return {"status": "cancelled"}
    return {"draft": decision.get("body", state["draft"]), "status": "approved"}

# Client side
result = graph.invoke({...}, config)
if "__interrupt__" in result:
    payload = result["__interrupt__"][0].value       # show this to the human
    graph.invoke(Command(resume={"type": "accept"}), config)
```

**Why this is better than the older `NodeInterrupt` exception:**

| | `NodeInterrupt` (deprecated) | `interrupt()` |
|---|---|---|
| Carries a payload to the UI | Only a message string | Arbitrary structured payload |
| Resume with a value | ❌ — you had to `update_state` then resume | ✅ `Command(resume=value)` |
| Re-runs the node on resume | Yes, and re-raises unless state changed | Yes, but the call **returns the value** |
| Status | Deprecated | Current |

> **Migration:** replace `raise NodeInterrupt(msg)` with `interrupt({...})` and resume
> with `Command(resume=...)` instead of `update_state()` + `invoke(None)`.

### 2.1 The resume semantics you MUST understand

**On resume, the node runs again from the top.** `interrupt()` does not resume "in the
middle" of the function — the whole node body re-executes, and the `interrupt()` call
returns the resume value instead of pausing.

Consequences:

```python
# ❌ BROKEN — the charge happens twice
def bad(state):
    charge_card(state["amount"])            # runs on first pass AND on resume
    ok = interrupt({"confirm": True})
    return {...}

# ✅ CORRECT — side effect after the interrupt
def good(state):
    ok = interrupt({"confirm": True, "amount": state["amount"]})
    if ok:
        charge_card(state["amount"])        # runs once, after approval
    return {...}
```

**Rules:**
1. **Put all side effects *after* the `interrupt()` call**, or in a separate downstream
   node.
2. **Keep pre-interrupt work cheap** — it is paid twice.
3. **Multiple `interrupt()` calls in one node** resume positionally; this is fragile.
   Prefer one interrupt per node.
4. Interrupts inside a **subgraph** propagate to the parent run; resume on the parent
   thread.

---

## 3. Static breakpoints

```python
graph = builder.compile(
    checkpointer=cp,
    interrupt_before=["tools"],      # pause before this node
    interrupt_after=["planner"],     # pause after this node
)
graph.invoke(inp, config)            # runs, then pauses
graph.get_state(config).next         # ("tools",) — confirms where it stopped
graph.invoke(None, config)           # resume (None = "continue from checkpoint")
```

**Use static breakpoints for debugging and stepping.** They are set at compile time
by a developer and carry no payload.

**Prefer `interrupt()` for product approval flows**, because:
- the pause point lives next to the logic that needs approving,
- you can send the UI a structured payload describing *what* is being approved,
- you can resume with a decision rather than mutating state and hoping.

`invoke(None, config)` is the universal "continue from where you stopped" call.

---

## 4. Editing state

```python
graph.update_state(config, {"messages": [HumanMessage("Actually, use 3 not 2")]})
graph.invoke(None, config)
```

`update_state` writes **through the reducers**, which is why message semantics apply:

| Goal | How |
|---|---|
| Append a correction | Pass a message **without** an id |
| Rewrite an existing message | Pass a message **with the existing id** |
| Overwrite a scalar key | Just pass the new value (overwrite reducer) |
| Attribute the update to a node | `update_state(config, values, as_node="planner")` |

`as_node` matters: it determines which edges fire next. Without it, the graph resumes
from the interrupted node's position; with it, the graph behaves as though that node
had just produced the update.

**Editing a tool call before it runs** is the highest-value variant of this pattern —
the model proposed `delete_records(filter="*")`, the human narrows it to
`filter="status=test"`, then execution proceeds.

---

## 5. Time travel: replay, fork, rollback

```python
history = list(graph.get_state_history(config))   # newest first
target  = history[2]

# REPLAY — re-run from that point with the same state
graph.invoke(None, {"configurable": {"thread_id": tid,
                                     "checkpoint_id": target.config["configurable"]["checkpoint_id"]}})

# FORK — change state at that point, creating a new branch
forked = graph.update_state(
    {"configurable": {"thread_id": tid,
                      "checkpoint_id": target.config["configurable"]["checkpoint_id"]}},
    {"messages": [HumanMessage(content="Multiply 3 and 3", id=original_msg_id)]},  # same id ⇒ rewrite
)
graph.invoke(None, forked)
```

| Operation | What it does | Use for |
|---|---|---|
| **Replay** | Re-execute from a checkpoint, unchanged state | Reproducing a bug; re-running after fixing a tool |
| **Fork** | Modify state at a checkpoint → new branch | "What if the model had chosen differently?"; A/B prompts |
| **Rollback** | Resume from an earlier checkpoint, abandoning later ones | Undo; recover from a bad turn |

**Critical caveat: replay re-executes side effects.** Replaying a run that sends
emails sends the emails again. Before enabling replay in production:
- make external calls idempotent (idempotency keys), **or**
- gate side-effecting nodes on a "replay mode" flag, **or**
- restrict replay to non-side-effecting prefixes of the graph.

**Forking with message ids is the trick that makes "edit and regenerate" work** — pass
the *same id* and `add_messages` rewrites in place instead of appending, so the
alternate timeline starts from a modified past rather than a contradictory one.

---

## 6. Streaming and interruption

HITL is unusable without streaming — a human cannot approve what they cannot see.

```python
for chunk in graph.stream(inp, config, stream_mode="updates"):
    ...
```

| `stream_mode` | Emits | Use for |
|---|---|---|
| `"values"` | Full state after each step | Debugging, simple UIs |
| `"updates"` | Only the delta per node | Progress UI, logging — **default choice** |
| `"messages"` | LLM tokens + metadata | Token-by-token chat UX |
| `"custom"` | Whatever you `writer()` | Node-level progress ("searching 3 of 12…") |
| `"debug"` / `"tasks"` / `"checkpoints"` | Execution internals | Deep debugging |

Combine: `stream_mode=["updates", "messages"]`. Add `subgraphs=True` to see inside
nested graphs.

**Emitting custom progress from a node:**

```python
def slow_node(state, runtime):
    runtime.stream_writer({"status": "searching", "progress": 0.4})
    ...
```

**Interruption vs interrupt:** stopping a *stream* client-side does not stop the run.
To actually halt a run you either cancel it at the server/task level or design an
interrupt point. If a user "stops generation", decide explicitly whether the partial
work is kept (see the run-concurrency table in `01-architecture.md`).

---

## 7. Designing approval flows

### 7.1 What to gate

Gate on **consequence**, not on model confidence.

| Gate | Don't gate |
|---|---|
| Irreversible actions (delete, send, pay, deploy) | Reads and searches |
| Actions affecting other people | Internal reasoning steps |
| Spend above a threshold | Formatting/summarizing |
| Anything with legal/compliance weight | Every single tool call |

**Approval fatigue is a real failure mode.** If a human approves 40 things per session,
they stop reading. Approve few things, and make each one meaningful.

### 7.2 Tiered approval

```python
def needs_approval(action) -> bool:
    if action.tool in READ_ONLY:            return False
    if action.tool in ALWAYS_APPROVE:       return True
    return action.estimated_impact > THRESHOLD
```

Auto-approve the safe majority; escalate the consequential minority. This is what
makes HITL survivable at volume.

### 7.3 Placement matters more than mechanism

Put the gate **before the expensive or irreversible step, and as early as the
information allows**. The research-assistant pattern is the model: approve 4 generated
personas (cheap to redo) rather than 4 completed interviews (expensive to redo).

### 7.4 The interrupt payload is a UI contract

Send the human what they need to decide:

```python
interrupt({
    "action": "send_refund",
    "args": {"customer": cid, "amount": 240.00},
    "rationale": state["reasoning"],       # why the agent wants this
    "reversible": False,
    "allowed": ["accept", "edit", "reject"],
})
```

Design this payload deliberately — it is the contract between your graph and your
front end, and changing it breaks in-flight threads.

### 7.5 Standard HITL types

`langgraph.prebuilt.interrupt` provides `HumanInterrupt`, `ActionRequest`,
`HumanResponse`, and `HumanInterruptConfig` — a conventional payload shape
(accept / edit / respond / ignore) understood by generic inbox UIs. Prefer it over an
ad-hoc dict if you want tooling compatibility.

For prebuilt agents, `HumanInTheLoopMiddleware` (from `langchain.agents.middleware`)
wires tool-call approval without hand-writing interrupt nodes. Prefer it when you're
already using `create_agent`.

---

## 8. Production considerations

| Concern | Guidance |
|---|---|
| **Interrupts are unbounded in time** | A paused run can sit for days. Add TTLs and a timeout/escalation policy — decide what happens to an unanswered approval |
| **Who is allowed to resume?** | Authorize the resume call. A `thread_id` is a capability; anyone holding it can approve |
| **Notification** | The human must *learn* that approval is pending — email/Slack/queue. A paused thread nobody sees is a dropped task |
| **Audit trail** | Record who approved what, when, and what payload they saw. Checkpoint history gives you the state; you must record the identity |
| **Concurrency** | Two approvers acting on one thread → conflicting resumes. Lock or make last-writer-wins explicit |
| **Idempotency** | Resume re-runs the node. Non-idempotent pre-interrupt work runs twice |
| **Cost of the pause** | Nothing runs while paused, but the thread's state is held. Long-lived paused threads accumulate |
| **Graceful degradation** | If no human is available, what happens? Auto-reject, auto-approve, or queue — pick one and make it explicit |

---

## 9. Failure modes and recovery

| Failure | Detection | Recovery |
|---|---|---|
| Agent stuck in a loop | Step count / recursion limit | Interrupt, inspect `.next`, edit state, resume |
| Model produced a bad tool call | Approval gate | Edit the args in the interrupt response |
| Tool failed transiently | Exception in node | `retry_policy` on the node |
| Tool failed permanently | Repeated failure | Route to a fallback node or interrupt for human input |
| Run crashed mid-way | Missing terminal state | Resume from last checkpoint (`invoke(None, config)`) |
| Wrong answer at step 3 of 9 | Human review | Fork from checkpoint 3, correct, re-run |
| Poisoned state (bad data written) | Anomaly/eval | Roll back to a clean checkpoint |
| Approval never answered | Age of paused threads | Timeout policy → escalate or auto-resolve |

**The recovery capability you get for free with a checkpointer is enormous** — most
non-LangGraph agent systems have to re-run from the beginning. Make sure your ops
runbook actually uses it: "resume the thread" should be a documented operation, not a
rediscovery every incident.
