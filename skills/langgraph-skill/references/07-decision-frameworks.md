# Decision Frameworks

Answer these before writing code. Each includes the *signal that should change your mind*.

---

## 1. Chain vs Router vs Agent

```
Are the steps known at design time?
├─ YES ─ Does the path vary by input?
│        ├─ NO  → CHAIN
│        └─ YES → ROUTER (conditional edges)
└─ NO  ─ Must the system iterate based on results?
         ├─ NO  → ROUTER with a fallback branch
         └─ YES → AGENT (ReAct loop)
```

| | Chain | Router | Agent |
|---|---|---|---|
| Determinism | Total | High | Low |
| Cost | 1× | 1× + routing call | Unbounded |
| Latency | Predictable | Predictable | Unpredictable |
| Testability | Unit tests | Unit + routing tests | Requires eval sets |
| Failure mode | Wrong output | Wrong branch | Loops, cost blowout |

**Default to the least agentic option that works.** Agency is a cost you pay for
flexibility you must actually need.

**Changes my mind:** if the router's category list keeps growing and each category
needs multi-step work → promote to agent. If the agent's traces show it always takes
the same 3 steps → demote to chain.

---

## 2. Router vs Conditional Edge

Not actually a dichotomy — a router *is* a conditional edge. The real question:

| Question | Answer |
|---|---|
| Does the routing decision need an LLM? | Only if it requires semantic understanding |
| Can I decide from state alone? | Then use plain Python in the conditional edge — free and deterministic |
| Do I need explainable routing? | Structured LLM output with a `reason` field |

**Rule:** never spend a model call on a decision `if state["score"] > 0.8` can make.

---

## 3. Sequential vs Parallel

```
Do the steps depend on each other's output?
├─ YES → SEQUENTIAL (you have no choice)
└─ NO  ─ Are all branches usually needed?
         ├─ YES → PARALLEL (fan-out/fan-in + reducer)
         └─ NO  → ROUTER (only run what's needed — cheaper than parallel)
```

| | Sequential | Parallel |
|---|---|---|
| Wall-clock | Sum of steps | Max of steps |
| Token cost | Only what's needed | **All branches, always** |
| Complexity | Low | Needs reducers; ordering is not controllable |
| Debugging | Easy | Interleaved traces |

**The trap:** parallelism reduces latency but never cost. If one of three sources is
rarely useful, a router beats parallel fan-out on both cost *and* quality (less noise
in context).

---

## 4. Parallel branches vs Map-Reduce (`Send`)

| | Static parallel | `Send` map-reduce |
|---|---|---|
| N known at build time | ✅ | ❌ |
| Branches do *different* work | ✅ | ❌ (same node) |
| Branches do the *same* work over data | ❌ | ✅ |
| Per-branch private input | Awkward | ✅ native |

```
Is N known when you write the graph?
├─ YES ─ Do branches do different things? ─ YES → PARALLEL EDGES
│                                          └ NO  → Send (still cleaner)
└─ NO  → Send
```

**Changes my mind:** if N can be large and unbounded, neither is right without a
batching/limit layer.

---

## 5. Subgraph vs Separate Node vs Separate Service

```
Is it >3 nodes AND has its own state concerns?
├─ NO → plain node (or a few nodes)
└─ YES ─ Reused across graphs, or independently deployable/scalable?
         ├─ NO  → SUBGRAPH
         └─ YES → separate SERVICE (call it from a node)
```

| | Node | Subgraph | Service |
|---|---|---|---|
| State isolation | ❌ | ✅ | ✅ total |
| Independent test | Function-level | Graph-level | Full |
| Independent deploy/scale | ❌ | ❌ | ✅ |
| Overhead | None | State mapping | Network, auth, versioning |
| Unified tracing | ✅ | ✅ | ⚠️ needs propagation |

**Trap:** creating subgraphs for organization alone. If it doesn't have its own state,
it's a function, not a subgraph.

---

## 6. Single Agent vs Multiple Agents

```
Does one agent have >~15 tools OR conflicting instructions?
├─ NO → SINGLE AGENT
└─ YES ─ Do sub-tasks need genuinely different tools/prompts?
         ├─ NO  → single agent + tool-selection middleware
         └─ YES ─ Is there a clear coordination point?
                  ├─ YES → SUPERVISOR
                  └─ NO  → network/handoff (last resort)
```

**Honest cost of multi-agent:**
- every handoff is a model call and a context copy;
- context does not transfer perfectly — agents re-derive things;
- debugging spans multiple prompt surfaces;
- latency multiplies.

**Test for "do I really need multiple agents?":** write down each agent's tool list and
system prompt. If they overlap >70%, you have one agent.

**Start with one agent.** Split when a specific, observed problem forces it (tool
overload, prompt conflict, different model requirements, different owners/teams).

---

## 7. Short-term vs Long-term Memory

```
Must it survive the conversation ending?
├─ NO  → SHORT-TERM (checkpointer)
└─ YES ─ Is it a fact about the user/domain?
         ├─ YES → LONG-TERM (store)
         └─ NO  ─ Is it already in your database?
                  ├─ YES → query the system of record; don't duplicate
                  └─ NO  → long-term store
```

| Data | Where |
|---|---|
| Message history | Checkpointer |
| Working state for this run | Checkpointer |
| "User is vegetarian" | Store |
| "User's plan is Enterprise" | **Your database** — it's a system of record |
| "Last time we tried X it failed" | Store (episodic) |
| "Always ask for a deadline" | Store (procedural) |

**Most systems need both.** They are not alternatives.

**The most common mistake:** duplicating authoritative business data into fuzzy memory,
where it goes stale and contradicts the source of truth.

---

## 8. Trim vs Filter vs Summarize

| | Filter | Trim | Summarize |
|---|---|---|---|
| Cost | Free | Free | 1 LLM call |
| Info retained (in state) | All | All | All until pruned |
| Info retained (to model) | Recent only | Within budget | Compressed all |
| Reversible | ✅ | ✅ | ❌ (in current state) |
| Latency added | None | None | Yes |

```
Is the context window/cost actually a problem yet?
├─ NO → do nothing
└─ YES ─ Does early context matter for quality?
         ├─ NO  → TRIM by tokens
         └─ YES ─ Can you afford one extra call per compaction?
                  ├─ YES → SUMMARIZE + prune
                  └─ NO  → TRIM + push key facts to the STORE
```

**At scale, do all three:** trim for a hard ceiling, summarize for continuity, store for
durable facts.

---

## 9. Profile vs Collection Memory

```
Is the set of attributes bounded and known?
├─ YES ─ Do you need all of it every turn?
│        ├─ YES → PROFILE
│        └─ NO  → PROFILE (it's small; just load it)
└─ NO  → COLLECTION + retrieval
```

| | Profile | Collection |
|---|---|---|
| Item count | 1 | Many |
| Retrieval | Load it | Search it |
| Update risk | Clobbering fields on merge | Duplicates/contradictions |
| Prompt cost | Whole doc, every turn | Top-k only |
| User-editable | Easy | Harder |

**Both is a valid and common answer:** profile for stable identity, collection for
accumulating observations.

---

## 10. Checkpointer vs Store

| | Checkpointer | Store |
|---|---|---|
| Scope | One thread | Cross-thread namespace |
| Contains | Graph state per step | Arbitrary documents |
| Written by | The framework, every step | Your code, explicitly |
| Enables | Resume, HITL, time travel | Personalization, knowledge |
| Query | By `thread_id`/`checkpoint_id` | By namespace/key/semantic search |

**Never a choice between them.** The question is only "do I need the Store *as well*?"
Answer: yes if anything must survive the thread.

---

## 11. Static Breakpoint vs `interrupt()`

```
Is this for a developer or an end user?
├─ DEVELOPER (debugging/stepping) → interrupt_before/after at compile
└─ END USER (approval/input) → interrupt() in the node
```

| | `interrupt_before/after` | `interrupt()` |
|---|---|---|
| Set at | Compile time, by dev | Runtime, in logic |
| Conditional | ❌ | ✅ |
| Payload to UI | ❌ | ✅ structured |
| Resume with a value | ❌ (`update_state` first) | ✅ `Command(resume=...)` |
| Right for products | ❌ | ✅ |

`NodeInterrupt` is deprecated — use `interrupt()`.

---

## 12. Reducer vs Custom State Design

```
Do multiple nodes write this key in one step?
├─ NO → default (overwrite) is fine
└─ YES ─ Is list-append the correct merge?
         ├─ YES → operator.add  (or add_messages for messages)
         └─ NO  → CUSTOM REDUCER
```

Write a custom reducer when you need: None-tolerance, deduplication, bounded growth,
domain merge rules (highest confidence wins), or dict merging.

**Never** put I/O, randomness, clocks, or LLM calls in a reducer — replays must be
deterministic.

**Alternative to a complex reducer:** give each writer its own key and merge explicitly
in a join node. Usually more readable and always easier to debug.

---

## 13. Prebuilt Agent vs Custom `StateGraph`

```
Is it a standard tool-calling loop?
├─ YES ─ Do you need to modify the loop itself?
│        ├─ NO  → create_agent (+ middleware for cross-cutting concerns)
│        └─ YES → is there middleware for it? ── YES → create_agent + middleware
│                                              └─ NO  → StateGraph
└─ NO → StateGraph
```

| | Prebuilt (`create_agent`) | Custom `StateGraph` |
|---|---|---|
| Time to working | Minutes | Hours |
| Maintained by | LangChain | You |
| Custom topology | ❌ | ✅ |
| Extension model | Middleware hooks | Anything |

**Prefer prebuilt + middleware.** Middleware covers most reasons people hand-roll:
summarization, HITL, retries, fallbacks, call limits, PII redaction, tool selection,
dynamic prompts. Drop to `StateGraph` when you need a topology the loop can't express
(parallel branches, map-reduce, supervisor, multi-stage pipelines).

---

## 14. LLM Call vs Deterministic Code

The most under-asked question in agent design.

| Use code | Use an LLM |
|---|---|
| Parsing structured formats | Understanding intent |
| Arithmetic, dates, IDs | Summarizing, rewriting |
| Filtering, sorting, joining | Classifying ambiguous text |
| Validation with known rules | Generating natural language |
| Anything with an exact answer | Anything requiring judgement |

Every LLM call you can replace with code makes the system faster, cheaper, more
reliable, and testable. **Audit your graph for model calls that are really just
`if` statements.**

---

## 15. Sync vs Async

| Use sync | Use async |
|---|---|
| Scripts, notebooks, CLIs | Web services |
| Low concurrency | Many concurrent runs |
| Simplicity matters most | Parallel I/O matters |

**Do not mix.** A sync node inside an async graph blocks the event loop and destroys
throughput under load. If you go async, go async all the way: async nodes, async
checkpointer, async store, async model calls.

---

## 16. Build vs Buy for memory

| Situation | Choice |
|---|---|
| Simple facts, <100 per user | LangGraph Store + `with_structured_output`. Build it — it's ~50 lines |
| Need semantic/episodic/procedural managers | Consider LangMem (pre-1.0; run in background) |
| Large nested schemas that regenerate badly | Patch-based extraction; measure first |
| Millions of vectors, existing vector DB | Custom `BaseStore` over your DB |
| Temporal/graph relationships | Dedicated graph-memory system |

**Default: build on the Store.** It's first-party, it's already in your dependency
tree, and most memory needs are genuinely simple. Buy when you've measured a specific
shortfall.

---

## 17. When to add each capability (sequencing)

Build in this order. Each step should be measured before the next.

```
1. Working graph with the right topology       ← get this right first
2. Durable checkpointer                        ← unlocks everything else
3. Tracing / observability                     ← before you need it
4. Loop bounds + retries                       ← before real traffic
5. Context strategy (trim/summarize)           ← when conversations get long
6. Evaluation set                              ← before optimizing anything
7. HITL on consequential actions               ← before granting real permissions
8. Long-term memory                            ← last; it's a feature, not a foundation
```

**People do this backwards** — they build memory before evaluation and HITL before
tracing. The result is an unmeasurable system with a personalization layer nobody can
debug.
