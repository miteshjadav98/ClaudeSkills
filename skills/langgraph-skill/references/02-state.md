# State Management

State is the contract every node in the graph depends on. It is also what gets
serialized to the checkpointer on every superstep — so it is simultaneously your
API design *and* your performance budget.

---

## 1. Choosing a schema type

| Type | Runtime validation | Cost | Access | Use when |
|---|---|---|---|---|
| `TypedDict` | ❌ hints only | Lowest | `state["k"]` | Default. Internal state, trusted writers |
| `dataclass` | ❌ hints only | Low | `state.k` | You prefer attribute access; internal only |
| Pydantic `BaseModel` | ✅ on input | Higher | `state.k` | **Input crosses a trust boundary** |

**Recommendation:** `TypedDict` for the internal working state, **Pydantic for the
input schema** when input comes from users, webhooks, or other services. This gives
you validation exactly where bad data enters and no per-step validation tax
everywhere else.

```python
class GraphInput(BaseModel):                # validated at the boundary
    question: str = Field(min_length=1, max_length=4000)
    user_id: str

class State(TypedDict):                     # cheap internally
    question: str
    user_id: str
    context: Annotated[list[str], operator.add]
    answer: str

builder = StateGraph(State, input_schema=GraphInput, output_schema=GraphOutput)
```

**Pydantic caveats worth knowing before you commit:**
- Validation runs on the state passed *into* nodes, not on every partial update.
- Default values can mask "the node never wrote this" — prefer `Optional[...] = None`
  over a misleading default when absence is meaningful.
- Nested models are more expensive to serialize per checkpoint.

**Note:** nodes return **plain dicts of updates** regardless of schema type. Even with
a `dataclass` or Pydantic state, you return `{"key": value}`. LangGraph stores each
key as an independent channel.

---

## 2. Reducers — the concurrency contract

A reducer is `(existing_value, update) -> new_value`. It defines **how writes merge**.

**Default reducer is last-write-wins (overwrite).** That is safe for a key written by
exactly one node per step, and a bug for anything else.

```python
class State(TypedDict):
    answer:   str                                        # overwrite (single writer)
    context:  Annotated[list[str], operator.add]         # append (parallel writers)
    messages: Annotated[list[AnyMessage], add_messages]  # append + upsert-by-id + delete
    scores:   Annotated[dict, merge_dicts]               # custom
```

### The rule that prevents most parallel bugs

> **If two nodes can write the same key in the same superstep, that key must have a
> reducer.** Otherwise: `InvalidUpdateError: At key 'x': Can receive only one value
> per step.`

This bites the moment you add a fan-out. It is not a bug in your graph — it is
LangGraph refusing to silently discard one of your writes.

### Custom reducers

Write one when `operator.add` is wrong. Common needs:

```python
def safe_extend(left: list | None, right: list | None) -> list:
    """None-tolerant concat. operator.add crashes on None."""
    return (left or []) + (right or [])

def keep_best(left: dict | None, right: dict | None) -> dict:
    """Domain merge: highest-confidence value per field wins."""
    left, right = left or {}, right or {}
    out = dict(left)
    for k, v in right.items():
        if k not in out or v["confidence"] > out[k]["confidence"]:
            out[k] = v
    return out

def bounded_append(left: list | None, right: list | None, cap: int = 100) -> list:
    """Self-limiting channel — prevents unbounded state growth."""
    return ((left or []) + (right or []))[-cap:]
```

**Reducer requirements** — a reducer that violates these produces
non-deterministic replays:

1. **Pure.** No I/O, no clock, no randomness, no mutation of inputs.
2. **Total.** Must handle `None` on either side (initial state, skipped branches).
3. **Order-tolerant.** Within a step you do not control the order updates arrive.
   If your reducer is order-sensitive, your results are order-sensitive.
4. **Fast.** It runs on every merge of that channel.
5. **Serializable output.** It goes straight into the checkpoint.

**Anti-pattern:** a reducer that calls an LLM to "intelligently merge" values. Reducers
must be deterministic; put merge intelligence in a node.

---

## 3. Messages state

`add_messages` is the reducer that makes chat work. It does three things:

| Operation | Trigger |
|---|---|
| **Append** | New message with no matching id |
| **Replace** | Message whose `id` already exists → overwritten in place |
| **Delete** | `RemoveMessage(id=...)` → removes that message |

```python
class State(MessagesState):     # == {"messages": Annotated[list[AnyMessage], add_messages]}
    summary: str                # extend it with whatever else you need
    user_id: str
```

**Replace-by-id is the mechanism behind editing and forking.** Passing a message with
an existing id rewrites history rather than appending to it — that is exactly what
"edit my last message and re-run" needs.

**Message hygiene rules:**

- **Never leave an `AIMessage` with `tool_calls` without matching `ToolMessage`s.**
  Most providers reject the request. This is the #1 cause of "it worked, then I
  trimmed the history and it 400s". Any trim/filter must cut at a **turn boundary**.
- `RemoveMessage(id=REMOVE_ALL_MESSAGES)` clears the list when you need a hard reset.
- Deleting from state is not the same as deleting from the checkpoint history — old
  checkpoints still contain the messages. For true deletion you must delete the thread.

---

## 4. Multiple schemas

Four distinct mechanisms. They solve different problems.

### 4.1 Input / output filtering

```python
builder = StateGraph(State, input_schema=InputState, output_schema=OutputState)
```

- `input_schema` — what callers are allowed to supply. Everything else starts empty.
- `output_schema` — what `invoke()` returns. Internal scratch keys are hidden.

**Always do this for anything with an external caller.** Without it, your entire
internal state is your public API and you can never refactor it.

### 4.2 Private inter-node state

```python
class Overall(TypedDict):  result: str
class Scratch(TypedDict):  intermediate: list

def a(state: Overall) -> Scratch:  return {"intermediate": [...]}
def b(state: Scratch) -> Overall:  return {"result": summarize(state["intermediate"])}
```

Keys not present in the overall schema are invisible to the graph's input and output.
Use for genuinely intermediate working data.

### 4.3 Per-node input schema

```python
builder.add_node("worker", worker, input_schema=WorkerState)
```

The node declares exactly what it reads. Best documentation you can give a node, and
it makes the node independently testable.

### 4.4 `Send` payloads

`Send("worker", {...})` passes an **arbitrary payload** that need not match any schema.
This is the strongest isolation available: the worker sees only what you handed it.

---

## 5. Runtime context vs state

A distinction people get wrong constantly.

| | **State** | **Context** |
|---|---|---|
| Changes during the run | ✅ | ❌ immutable for the run |
| Checkpointed | ✅ | ❌ |
| Merged via reducers | ✅ | ❌ |
| Examples | messages, retrieved docs, draft | `user_id`, `model_name`, tenant, feature flags |

```python
@dataclass
class Context:
    user_id: str
    model: str = "gpt-4.1"

builder = StateGraph(State, context_schema=Context)

def node(state: State, runtime: Runtime[Context]):
    uid = runtime.context.user_id
    ...

graph.invoke({"messages": [...]}, context={"user_id": "u1"})
```

> **Deprecation:** `config_schema=` is deprecated in favour of `context_schema=`.
> The old `config["configurable"]["user_id"]` access pattern still works, but new code
> should use `Runtime`/`get_runtime()`. See `11-modern-api-migration.md`.

**Putting `user_id` in state is a bug**, not a style choice: it becomes mutable,
gets checkpointed redundantly on every step, and a node can accidentally change
identity mid-run.

---

## 6. State design principles

### 6.1 Keep it small

State is serialized on **every** superstep. Consequences of a fat state:

| Symptom | Cause |
|---|---|
| Slow steps | Serializing MBs per checkpoint |
| Expensive storage | Every checkpoint stores a full copy of changed channels |
| Unreadable traces | LangSmith payloads dominated by blobs |
| Resume failures | Oversized rows / payload limits |

**Store references, not payloads.** Document IDs not document text; S3 keys not file
bytes; a summary not the full transcript.

### 6.2 One purpose per key

Do not overload `data: dict` to mean five different things at five points in the
graph. Named keys are self-documenting and let you attach the right reducer to each.

### 6.3 Treat updates as immutable

```python
# WRONG — mutating state directly. Breaks checkpointing and replay.
def bad(state):
    state["items"].append(x)
    return state

# RIGHT — return a partial update; let the reducer merge.
def good(state):
    return {"items": [x]}
```

Mutating the state object in place produces updates the framework cannot see,
corrupts replay, and creates aliasing bugs across parallel branches.

### 6.4 Return only what changed

Returning the whole state on every node makes every key look like it was written by
that node — which turns single-writer keys into multi-writer keys and triggers
`InvalidUpdateError` under parallelism.

### 6.5 Plan for schema evolution

Old checkpoints were written with the old schema. When you add a key:

- **Adding an optional key** is safe — reads must use `state.get("k")` with a default.
- **Removing a key** is safe for new runs; old threads still carry it.
- **Changing a key's type or reducer is a breaking change.** A thread mid-flight will
  deserialize old data into new semantics.
- **Renaming a node or key is a migration**, not a refactor.

Practical policy for anything with live threads:
1. Add new keys as optional, never required.
2. Read defensively: `state.get("new_field", default)`.
3. To make a breaking change, version the graph and route new threads to the new
   version; let old threads drain.

---

## 7. Quick diagnostics

| Symptom | Likely cause | Fix |
|---|---|---|
| `InvalidUpdateError: can receive only one value per step` | Two nodes write one key in a step | Add a reducer, or serialize the writes |
| Parallel results silently lost | Overwrite reducer where you wanted append | `Annotated[list, operator.add]` |
| `TypeError: unsupported operand ... NoneType` in a reducer | `operator.add` got `None` | None-tolerant custom reducer |
| Node sees stale data from a sibling | Same-step nodes don't see each other's writes | Put the reader in a later step |
| Output contains internal junk | No `output_schema` | Add one |
| Checkpoint writes are slow | Large blobs in state | Store references |
| State key mysteriously resets | A node returned the full state and clobbered it | Return partial updates only |
| Provider 400 on message history | Orphaned `tool_calls` after trimming | Cut at turn boundaries |
