# Long-Term Memory (Cross-Thread)

Long-term memory = **knowledge that outlives a conversation**, held in a **Store**,
addressed by **namespace + key**, not by `thread_id`.

The distinction that matters: a checkpointer remembers *what happened in this
conversation*; a store remembers *what is true about this user/domain*.

---

## 1. The Store

```python
from langgraph.store.memory import InMemoryStore
store = InMemoryStore()

store.put(("memories", "user-1"), "pref-food", {"text": "prefers vegetarian"})
store.get(("memories", "user-1"), "pref-food")     # one item
store.search(("memories", "user-1"))               # all items in namespace
store.search(("memories", "user-1"), query="food") # semantic, if indexing enabled
store.delete(("memories", "user-1"), "pref-food")

graph = builder.compile(checkpointer=cp, store=store)
```

Three coordinates:

| Concept | Analogy | Example |
|---|---|---|
| **namespace** (tuple) | Directory path | `("memories", user_id)` |
| **key** (str) | Filename | `"profile"` or a UUID |
| **value** (dict) | File contents | `{"name": "...", "interests": [...]}` |

Access it in a node via the injected `store` parameter (or `runtime.store`):

```python
def node(state, runtime: Runtime[Context]):
    uid = runtime.context.user_id
    memories = runtime.store.search(("memories", uid), query=last_user_text(state))
    ...
```

### Store backends

| Backend | Persistence | Vector search | Use for |
|---|---|---|---|
| `InMemoryStore` | ❌ | ✅ (in-process) | Tests, dev |
| `PostgresStore` | ✅ | ✅ (pgvector) | **Production default** |
| Custom `BaseStore` | ✅ | Depends | Existing vector DB / infra you must reuse |

**Recommendation:** if you already run Postgres, use `PostgresStore` — one datastore
for checkpoints *and* memories is a large operational simplification. Reach for a
dedicated vector DB only when you have genuine scale (tens of millions of vectors) or
already operate one.

---

## 2. Namespace design

Namespaces are your **isolation and authorization boundary**. Design them before you
write the first memory.

```python
("memories", user_id)                    # per-user semantic memory
("memories", org_id, user_id)            # multi-tenant, org-scoped
("todos", user_id, category)             # per-user, per-category collection
("instructions", user_id)                # procedural memory / learned preferences
("kb", org_id, "policies")               # shared org knowledge
```

**Rules:**

1. **Tenant identifier goes early in the tuple.** `(org_id, ...)` prefix makes
   "list everything for this tenant" and "delete this tenant" trivial.
2. **Never build a namespace from unvalidated user input.** It is a path; treat
   traversal seriously.
3. **The namespace must come from authenticated context, never from state.** If a
   model can influence the namespace, a prompt injection can read another user's
   memories. This is the highest-severity failure mode in this file.
4. **Separate memory *types* into separate namespaces.** Profile, tasks, and
   instructions have different lifecycles, schemas, and update rules — mixing them
   makes every retrieval fuzzy.

---

## 3. Memory types

| Type | Cognitive analogy | Holds | Shape |
|---|---|---|---|
| **Semantic** | Facts | "User is vegetarian", "Acme's SLA is 99.9%" | Profile or collection |
| **Episodic** | Experiences | "Last time we tried X, it failed because Y" | Collection |
| **Procedural** | Skills/rules | "Always ask for a deadline before creating a task" | Single instruction doc |

Most systems need semantic first. Add episodic when past interactions should shape
future ones (few-shot from history). Add procedural when the agent should **learn user
preferences about its own behaviour**.

---

## 4. Profile vs Collection — the core schema decision

### Profile: one document, continuously updated

```python
class UserProfile(BaseModel):
    name: str | None = None
    location: str | None = None
    interests: list[str] = []

store.put(("profile", uid), "main", profile.model_dump())
```

| | |
|---|---|
| **Use when** | Bounded, well-known attributes; you always want *all* of it |
| **Strengths** | One read, no retrieval step, easy to render/debug, easy to let a user edit |
| **Weaknesses** | Updates are read-modify-write (conflict-prone); grows unbounded if the schema has open lists; whole doc goes in the prompt |
| **Scaling limit** | Once the profile exceeds ~1–2k tokens it stops being a profile |

### Collection: many documents, inserted and updated individually

```python
store.put(("memories", uid), str(uuid4()), {"text": "Prefers morning meetings"})
relevant = store.search(("memories", uid), query=user_query, limit=5)
```

| | |
|---|---|
| **Use when** | Open-ended facts, unbounded count, only *relevant* subset needed |
| **Strengths** | Scales; targeted retrieval; individual items expire/delete cleanly |
| **Weaknesses** | Needs a retrieval strategy; **duplicate/contradictory memories accumulate**; recall quality becomes a real problem you must measure |
| **Scaling limit** | Retrieval quality, not storage |

### Decision table

| Signal | Choose |
|---|---|
| Fixed set of attributes | Profile |
| Unbounded facts over time | Collection |
| Need all of it every turn | Profile |
| Need the relevant 3 of 300 | Collection |
| User should be able to review/edit it directly | Profile |
| Facts arrive incrementally and independently | Collection |
| Both are true | **Both** — profile for identity, collection for observations |

The "both" answer is common and correct: a small structured profile for stable
identity, plus a collection for accumulated observations.

---

## 5. Writing memories: hot path vs background

| | **Hot path** (during the turn) | **Background** (after / batched) |
|---|---|---|
| Latency impact | Adds an LLM call to every turn | None for the user |
| Freshness | Immediate | Delayed |
| Complexity | Low | Needs a queue/scheduler |
| Cost | Every turn | Can debounce/batch |
| Best for | Short conversations; memory needed next turn | High-volume chat; expensive extraction |

**Recommendation:** start hot-path (simpler, and you'll learn what's worth storing);
move to background once you see the latency. Do not build the background pipeline
before you know what you're extracting.

**Two hot-path shapes:**

```
(a) Always extract:   call_model → write_memory → END        # simple, costs every turn
(b) Model-decides:    call_model ──cond──→ update_profile ─┐  # cheaper, model gates it
                             │    ├──→ update_todos ───────┤
                             │    └──→ END                 │
                             └───────────────────────────── (loop back)
```

(b) is the better production pattern: give the model an `UpdateMemory` tool with a
typed `update_type`, and route on it. You only pay extraction cost when there is
something to extract, and the model's decision is visible in the trace.

---

## 6. Updating structured memory — the hard part

**The problem:** regenerating a whole structured document from a conversation makes the
model **silently drop fields it didn't see mentioned**. Ask an LLM to "update this
profile" and it will happily return a profile missing the three fields the latest
messages didn't discuss.

### Option A — Native structured output + explicit merge (recommended default)

```python
existing = store.get(("profile", uid), "main")
result = llm.with_structured_output(UserProfile).invoke([
    SystemMessage(f"Update this profile. Preserve every existing value unless "
                  f"the conversation explicitly contradicts it.\n{existing.value if existing else '{}'}"),
    *state["messages"],
])
merged = {**(existing.value if existing else {}), **drop_nulls(result.model_dump())}
store.put(("profile", uid), "main", merged)
```

- **You control the merge**, so nothing is silently lost.
- No third-party dependency; uses first-party `with_structured_output`.
- Make fields `Optional` with `None` defaults and **drop nulls before merging** — that
  is what turns "model didn't mention it" into "leave it alone".

### Option B — Collection with per-item writes

Sidesteps the merge problem entirely: each memory is its own document. Updating means
writing one item; it can't clobber the others. **If the merge problem is hurting you,
switching to a collection is often the better fix than a better merger.**

### Option C — JSON-patch extraction libraries (e.g. Trustcall)

Instead of regenerating the document, the model emits **patches** to it.

**What problem it solved:** at the time the course was written, models were unreliable
at regenerating large/nested schemas, and patching was materially more accurate and
cheaper (you emit a diff, not the whole doc). It also validates and retries on schema
failure, and supports inserting new items into collections.

**Current status and recommendation:**
- Trustcall is **pre-1.0, single-maintainer**, and primarily survives as a transitive
  dependency of LangMem. Do **not** make it your default.
- Modern models are far better at structured output than they were, and
  `with_structured_output` is first-party and maintained.
- **Recommend it only when:** you have a genuinely large/deeply-nested schema, you have
  measured that full regeneration loses data, and Option A's explicit merge is
  insufficient.
- **Migration path if you already use it:** replace `create_extractor(...)` with
  `with_structured_output(Schema)` + explicit merge (Option A) for profiles; for
  collections, replace `enable_inserts=True` with "model proposes new items → you
  `put()` each with its own key". Keep the schema; drop the library.

**The durable lesson, independent of library:** *decide explicitly whether a memory
write is a merge or a replace, and make the merge deterministic in your code rather
than hoping the model preserves fields.*

### Option D — LangMem

LangChain's memory SDK, built on the Store. Provides prebuilt memory managers
(extraction, consolidation) and prompt optimization.

- **Status:** actively developed but **pre-1.0**; API can move.
- **Latency:** its managers are slow enough that they are best used **in background**,
  not in an interactive hot path.
- **Use when:** you want batteries-included semantic/episodic/procedural memory and
  can absorb pre-1.0 churn. **Don't** use it as a thin wrapper over one `store.put()`.

---

## 7. Retrieval

### 7.1 Semantic search

```python
store = InMemoryStore(index={
    "dims": 1536,
    "embed": init_embeddings("openai:text-embedding-3-small"),
    "fields": ["text"],          # which fields get embedded; ["$"] = whole doc
})
hits = store.search(("memories", uid), query="what food do they like", limit=5)
```

**`fields` is the underrated knob.** Embedding the entire JSON document mixes
identifiers and metadata into the vector and degrades recall. Embed the natural-language
field(s) only.

### 7.2 Choosing a retrieval strategy

| Volume per namespace | Strategy |
|---|---|
| < ~20 items | **Load them all.** No search, no embeddings, no ranking bugs |
| 20 – a few hundred | Semantic search with a limit, or filter-then-load |
| Thousands+ | Semantic search + metadata filters + recency weighting; measure recall |

**Do not add embeddings before you need them.** Below ~20 memories, retrieval adds a
failure mode (missed recall) and cost, and solves nothing.

### 7.3 Hybrid retrieval

For knowledge bases (as opposed to user memories), combine:
- **dense** (embeddings) — semantic similarity;
- **sparse** (BM25/keyword) — exact terms, IDs, error codes, product names;
- **metadata filters** — tenant, date, doc type (a filter is cheaper and more reliable
  than hoping the embedding respects it);
- **reranking** — a cross-encoder over the top ~50 to produce the top ~5.

Dense-only retrieval reliably fails on exact identifiers. If your users search for
`ERR-4021` or `SKU-88213`, you need the sparse leg.

---

## 8. Lifecycle, expiry, and hygiene

### TTL

```python
store = PostgresStore(..., ttl={
    "default_ttl": 60 * 24 * 30,     # minutes → 30 days
    "refresh_on_read": True,          # accessed memories stay alive
    "sweep_interval_minutes": 60,
})
```

`refresh_on_read=True` gives you **use-based decay**: memories that keep being
retrieved survive; ones nobody needs age out. That is usually the behaviour you want
for observational memories, and *not* what you want for a profile.

### Contradiction and duplication

Collections accumulate junk. Without maintenance you get:
- near-duplicates ("likes coffee" × 6),
- stale contradictions ("lives in SF" + "lives in NYC"),
- retrieval that surfaces the wrong one.

Mitigations, cheapest first:
1. **Prompt the extractor to update an existing memory when one matches**, rather than
   always inserting.
2. **Deduplicate on write** — search for similar memories before inserting.
3. **Store timestamps and prefer recency** on conflict.
4. **Periodic consolidation job** — merge/prune in background.
5. **Let users see and delete their memories.** Cheapest, most trustworthy correction
   mechanism you can ship, and increasingly a compliance expectation.

### Governance checklist

- [ ] Namespace derived from **authenticated** identity, never from model output
- [ ] User can list, edit, and delete their memories
- [ ] Deletion is real (store + any vector index), not a soft flag
- [ ] PII is classified; sensitive categories are excluded from extraction
- [ ] Memory content is **untrusted input** when it re-enters a prompt — a stored
      memory containing "ignore previous instructions" is a stored prompt injection
- [ ] Retention policy documented and enforced by TTL or a job

---

## 9. When NOT to use long-term memory

Genuinely important — memory is the most over-applied feature in agent design.

| Situation | Why not |
|---|---|
| Single-turn or stateless tasks | Nothing to remember; pure overhead |
| Facts already in your database | Query the system of record; don't duplicate it into fuzzy memory |
| Compliance forbids retention | Don't build a retention system |
| You haven't shipped v1 yet | Memory is a personalization feature, not a correctness feature |
| Users would be unsettled by it | "How do you know that?" is a real product risk |

**Ask:** *would this system be meaningfully worse without memory?* If you cannot
answer concretely, skip it.

---

## 10. Combined short + long memory: the canonical shape

```python
graph = builder.compile(
    checkpointer=PostgresSaver(...),   # thread_id → this conversation
    store=PostgresStore(...),          # user_id  → durable knowledge
)

graph.invoke(
    {"messages": [msg]},
    config={"configurable": {"thread_id": "conv-9"}},
    context={"user_id": "u-1"},
)
```

```
       ┌───────────── thread: conv-9 ─────────────┐
       │  messages, summary, working state        │  ← checkpointer
       └──────────────────────────────────────────┘
                       ▲          │
                  retrieve      extract
                       │          ▼
       ┌───────────── namespace: ("memories", u-1) ┐
       │  profile, observations, instructions      │  ← store
       └───────────────────────────────────────────┘
              (shared across conv-1, conv-9, conv-42…)
```

This is the shape of essentially every production personal assistant.
