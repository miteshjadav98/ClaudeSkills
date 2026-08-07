# Reusable Templates

Skeletons to **adapt**, not copy. Each is deliberately minimal — the point is the
shape. Verify API details against the installed version.

---

## 0. Project skeleton

```
agent/
├── graph.py         # assembly only
├── state.py         # schemas + reducers
├── context.py       # runtime config (context_schema)
├── nodes/
├── subgraphs/
├── tools/
├── prompts/
└── tests/
```

```python
# state.py
from typing import Annotated, TypedDict
from operator import add
from langchain_core.messages import AnyMessage
from langgraph.graph.message import add_messages

class State(TypedDict):
    messages: Annotated[list[AnyMessage], add_messages]
    context:  Annotated[list[str], add]
    answer:   str

class Input(TypedDict):   question: str
class Output(TypedDict):  answer: str

# context.py
from dataclasses import dataclass

@dataclass
class Context:
    user_id: str
    model: str = "gpt-4.1"
    max_iterations: int = 3
```

```python
# graph.py — assembly ONLY
from langgraph.graph import StateGraph, START, END
from .state import State, Input, Output
from .context import Context
from .nodes import retrieve, generate

def build():
    b = StateGraph(State, context_schema=Context,
                   input_schema=Input, output_schema=Output)
    b.add_node("retrieve", retrieve)
    b.add_node("generate", generate)
    b.add_edge(START, "retrieve")
    b.add_edge("retrieve", "generate")
    b.add_edge("generate", END)
    return b

def compile_graph(checkpointer=None, store=None):
    return build().compile(checkpointer=checkpointer, store=store)
```

---

## 1. Tool-calling agent (prefer the prebuilt)

```python
from langchain.agents import create_agent
from langchain.agents.middleware import (
    SummarizationMiddleware, ModelCallLimitMiddleware,
    ToolCallLimitMiddleware, ModelFallbackMiddleware,
)

agent = create_agent(
    model=primary_model,
    tools=[search, calculate, lookup_account],
    system_prompt=SYSTEM_PROMPT,
    middleware=[
        SummarizationMiddleware(model=cheap_model, max_tokens_before_summary=4000),
        ModelCallLimitMiddleware(thread_limit=20),
        ToolCallLimitMiddleware(thread_limit=40),
        ModelFallbackMiddleware(backup_model),
    ],
    checkpointer=checkpointer,
    store=store,
)
```

**Custom loop — only when you need a topology the prebuilt can't express:**

```python
from langgraph.prebuilt import ToolNode, tools_condition

def assistant(state: State):
    return {"messages": [llm_with_tools.invoke([SYS] + state["messages"])]}

b = StateGraph(State)
b.add_node("assistant", assistant)
b.add_node("tools", ToolNode(tools))
b.add_edge(START, "assistant")
b.add_conditional_edges("assistant", tools_condition, {"tools": "tools", END: END})
b.add_edge("tools", "assistant")
graph = b.compile(checkpointer=cp)

graph.invoke(inp, {"configurable": {"thread_id": t}, "recursion_limit": 25})
```

---

## 2. Router with fallback

```python
from typing import Literal
from pydantic import BaseModel, Field

class Route(BaseModel):
    destination: Literal["billing", "technical", "other"]
    reason: str = Field(description="Why this route was chosen")

def classify(state: State):
    r = llm.with_structured_output(Route).invoke(
        [SystemMessage(ROUTE_PROMPT), state["messages"][-1]])
    return {"route": r.destination, "route_reason": r.reason}

def pick(state) -> Literal["billing", "technical", "other"]:
    return state["route"]

b.add_conditional_edges("classify", pick, ["billing", "technical", "other"])
```

The `other` branch is mandatory — it's where clarification and escalation live.

---

## 3. Parallel fan-out / fan-in

```python
class State(TypedDict):
    question: str
    context: Annotated[list[str], operator.add]   # ← reducer is required
    answer: str

def search_web(state):  return {"context": [fetch_web(state["question"])]}
def search_kb(state):   return {"context": [fetch_kb(state["question"])]}
def synthesize(state):  return {"answer": llm.invoke(prompt(state)).content}

b.add_edge(START, "search_web")
b.add_edge(START, "search_kb")
b.add_edge("search_web", "synthesize")
b.add_edge("search_kb", "synthesize")
```

**Isolate branch failures** so one dead source doesn't abort the run:

```python
def search_web(state):
    try:
        return {"context": [fetch_web(state["question"])]}
    except Exception as e:
        logger.warning("web search failed: %s", e)
        return {"context": []}          # degrade, don't abort
```

If ordering matters, use separate keys and assemble in the join node:

```python
class State(TypedDict):
    web_ctx: str
    kb_ctx: str
def synthesize(state):
    ordered = [state["kb_ctx"], state["web_ctx"]]   # explicit, not luck
```

---

## 4. Map-reduce with `Send`

```python
from langgraph.types import Send

MAX_ITEMS = 25

class State(TypedDict):
    topic: str
    items: list[str]
    results: Annotated[list[str], operator.add]
    final: str

class WorkerState(TypedDict):     # private worker input
    item: str

def plan(state):
    out = llm.with_structured_output(Items).invoke(PLAN_PROMPT.format(**state))
    return {"items": out.items[:MAX_ITEMS]}          # cap N

def fan_out(state):
    return [Send("worker", {"item": i}) for i in state["items"]]

def worker(state: WorkerState):
    try:
        return {"results": [process(state["item"])]}
    except Exception as e:
        return {"results": []}                        # isolate failure

def reduce_(state):
    return {"final": combine(state["results"])}

b.add_conditional_edges("plan", fan_out, ["worker"])
b.add_edge("worker", "reduce_")
```

---

## 5. Subgraph composition

```python
# --- child ---
class SubState(TypedDict):
    docs: list[str]
    findings: Annotated[list[str], operator.add]
    report: str

class SubOut(TypedDict):
    report: str                                    # publish only this

sub = StateGraph(SubState, output_schema=SubOut)
...
sub_graph = sub.compile()                          # NO checkpointer here

# --- parent, translated interface (preferred for reusable components) ---
def analysis_node(state: ParentState) -> dict:
    out = sub_graph.invoke({"docs": state["raw_docs"]})
    return {"summary": out["report"]}

parent.add_node("analysis", analysis_node)

# --- parent, shared schema (when schemas genuinely overlap) ---
parent.add_node("analysis", sub_graph)
```

---

## 6. Human approval

```python
from langgraph.types import interrupt, Command

def propose(state):
    action = llm.with_structured_output(Action).invoke(...)
    return {"proposed": action.model_dump()}

def approve(state):
    decision = interrupt({
        "action": state["proposed"]["tool"],
        "args": state["proposed"]["args"],
        "rationale": state["proposed"].get("reason"),
        "reversible": False,
        "allowed": ["accept", "edit", "reject"],
    })
    if decision["type"] == "reject":
        return {"status": "cancelled"}
    return {"proposed": decision.get("args", state["proposed"]),
            "status": "approved"}

def execute(state):                       # side effects live HERE, after the gate
    if state["status"] != "approved":
        return {"result": None}
    return {"result": run_action(state["proposed"])}

b.add_edge("propose", "approve")
b.add_edge("approve", "execute")
graph = b.compile(checkpointer=cp)        # required

# client
res = graph.invoke(inp, cfg)
if "__interrupt__" in res:
    payload = res["__interrupt__"][0].value
    graph.invoke(Command(resume={"type": "accept"}), cfg)
```

**Tiered gating:**

```python
READ_ONLY = {"search", "get_status"}
def needs_approval(tool, args) -> bool:
    if tool in READ_ONLY: return False
    return tool in DESTRUCTIVE or args.get("amount", 0) > 100
```

---

## 7. Summarization for long conversations

```python
class State(MessagesState):
    summary: str

KEEP_RECENT = 4

def call_model(state):
    msgs = state["messages"]
    if s := state.get("summary"):
        msgs = [SystemMessage(f"Conversation so far: {s}")] + msgs
    return {"messages": [llm.invoke(msgs)]}

def should_summarize(state) -> Literal["summarize", "__end__"]:
    return "summarize" if count_tokens(state["messages"]) > 4000 else END

def summarize(state):
    prior = state.get("summary", "")
    instruction = (
        f"Extend this summary with the new messages. Preserve names, dates, "
        f"numbers, decisions, and open questions.\n\n{prior}"
        if prior else
        "Summarize the conversation. Preserve names, dates, numbers, decisions, "
        "and open questions."
    )
    new = llm.invoke(state["messages"] + [HumanMessage(instruction)])
    drop = [RemoveMessage(id=m.id) for m in state["messages"][:-KEEP_RECENT]]
    return {"summary": new.content, "messages": drop}

b.add_conditional_edges("conversation", should_summarize, ["summarize", END])
```

Trigger on **tokens**, not message count. Keep recent turns verbatim.

---

## 8. Long-term memory (profile + collection)

```python
from langgraph.store.base import BaseStore
from langgraph.runtime import Runtime

def respond(state, runtime: Runtime[Context]):
    uid = runtime.context.user_id                    # from AUTH, never from state
    profile = runtime.store.get(("profile", uid), "main")
    notes   = runtime.store.search(("memories", uid),
                                   query=last_user_text(state), limit=5)
    sys = SYSTEM.format(
        profile=profile.value if profile else "none",
        notes="\n".join(n.value["text"] for n in notes),
    )
    return {"messages": [llm.invoke([SystemMessage(sys)] + state["messages"])]}

def update_profile(state, runtime: Runtime[Context]):
    uid = runtime.context.user_id
    ns, key = ("profile", uid), "main"
    current = (runtime.store.get(ns, key) or _Empty()).value or {}

    result = llm.with_structured_output(Profile).invoke([
        SystemMessage(f"Update this profile. Preserve every existing value "
                      f"unless explicitly contradicted.\n{current}"),
        *state["messages"],
    ])
    # drop Nones so "not mentioned" never erases "already known"
    incoming = {k: v for k, v in result.model_dump().items() if v is not None}
    runtime.store.put(ns, key, {**current, **incoming})

def add_observation(state, runtime: Runtime[Context]):
    uid = runtime.context.user_id
    runtime.store.put(("memories", uid), str(uuid4()),
                      {"text": extract(state), "ts": datetime.utcnow().isoformat()})

graph = b.compile(checkpointer=cp, store=store)
graph.invoke(inp, config={"configurable": {"thread_id": t}},
                  context={"user_id": authenticated_user_id})
```

**Model-gated memory writes** (cheaper than always-extract):

```python
class UpdateMemory(TypedDict):
    update_type: Literal["profile", "observation", "instructions"]

def route_memory(state) -> Literal["update_profile", "add_observation", "__end__"]:
    last = state["messages"][-1]
    if not getattr(last, "tool_calls", None):
        return END
    return {"profile": "update_profile",
            "observation": "add_observation"}[last.tool_calls[0]["args"]["update_type"]]
```

---

## 9. Reflection loop (capped)

```python
MAX_REVISIONS = 2

class State(TypedDict):
    draft: str
    critique: str
    revisions: int

def critique(state):
    c = llm.invoke(CRITIQUE_PROMPT.format(draft=state["draft"], rubric=RUBRIC))
    return {"critique": c.content}

def should_revise(state) -> Literal["revise", "__end__"]:
    if state.get("revisions", 0) >= MAX_REVISIONS:   # hard cap FIRST
        return END
    return "revise" if "NEEDS_WORK" in state["critique"] else END

def revise(state):
    d = llm.invoke(REVISE_PROMPT.format(**state))
    return {"draft": d.content, "revisions": state.get("revisions", 0) + 1}
```

The counter check comes **before** the semantic check. Always.

---

## 10. Production wiring

```python
import os
from langchain.chat_models import init_chat_model
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from langgraph.store.postgres.aio import AsyncPostgresStore
from langgraph.types import RetryPolicy
from langgraph.cache.memory import InMemoryCache
from langgraph.types import CachePolicy

model = init_chat_model(os.environ["MODEL_ID"], temperature=0, timeout=30)

b.add_node("search", search,
           retry_policy=RetryPolicy(max_attempts=3, backoff_factor=2.0, jitter=True))
b.add_node("embed", embed, cache_policy=CachePolicy(ttl=3600))

async def main():
    async with (
        AsyncPostgresSaver.from_conn_string(os.environ["DB_URL"]) as cp,
        AsyncPostgresStore.from_conn_string(
            os.environ["DB_URL"],
            index={"dims": 1536, "embed": "openai:text-embedding-3-small",
                   "fields": ["text"]},
            ttl={"default_ttl": 60 * 24 * 90, "refresh_on_read": True,
                 "sweep_interval_minutes": 60},
        ) as store,
    ):
        graph = b.compile(checkpointer=cp, store=store, cache=InMemoryCache())
        await graph.ainvoke(
            inp,
            config={"configurable": {"thread_id": tid},
                    "recursion_limit": 25,
                    "metadata": {"tenant": org_id, "version": APP_VERSION}},
            context={"user_id": uid},
            durability="async",
        )
```

`cp.setup()` / `store.setup()` are migrations — run them at deploy, not per-request.

---

## 11. Streaming

```python
async def stream_response(inp, cfg):
    async for mode, chunk in graph.astream(
        inp, cfg, stream_mode=["updates", "messages", "custom"], subgraphs=True
    ):
        if mode == "messages":
            token, meta = chunk
            if meta["langgraph_node"] == "assistant":
                yield {"type": "token", "text": token.content}
        elif mode == "updates":
            yield {"type": "step", "node": next(iter(chunk))}
        elif mode == "custom":
            yield {"type": "progress", **chunk}

# emitting progress from a slow node
def slow_node(state, runtime):
    runtime.stream_writer({"stage": "retrieving", "pct": 0.4})
```

---

## 12. Tests

```python
# node test — no graph, no model
def test_router_escalates_on_low_confidence():
    assert pick({"route": "other"}) == "other"

# graph test — mock the model, assert the path
def test_tool_failure_routes_to_fallback():
    graph = build().compile(checkpointer=InMemorySaver())
    out = graph.invoke({"messages": [HumanMessage("x")]},
                       {"configurable": {"thread_id": "t"}})
    assert out["status"] == "fallback"

# interrupt test
def test_pauses_before_destructive_action():
    cfg = {"configurable": {"thread_id": "t"}}
    graph.invoke({"request": "delete everything"}, cfg)
    assert graph.get_state(cfg).next == ("approve",)
    out = graph.invoke(Command(resume={"type": "reject"}), cfg)
    assert out["status"] == "cancelled"

# eval assertion
def test_eval_set():
    for case in load_cases():
        out = graph.invoke(case.input, fresh_cfg())
        assert case.required_tool in tools_called(out)
        assert cost_of(out) < case.budget
```

---

## 13. Custom reducers

```python
def safe_extend(left: list | None, right: list | None) -> list:
    return (left or []) + (right or [])

def bounded(cap: int):
    def _r(left: list | None, right: list | None) -> list:
        return ((left or []) + (right or []))[-cap:]
    return _r

def merge_by_confidence(left: dict | None, right: dict | None) -> dict:
    out = dict(left or {})
    for k, v in (right or {}).items():
        if k not in out or v["confidence"] > out[k]["confidence"]:
            out[k] = v
    return out

class State(TypedDict):
    findings: Annotated[list[str], safe_extend]
    recent:   Annotated[list[str], bounded(50)]
    fields:   Annotated[dict, merge_by_confidence]
```

Pure, total (None-tolerant), order-tolerant, fast, serializable.
