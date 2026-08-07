# Modern APIs, Deprecations, and Migration

**How to use this file:** before recommending any API, check it here. If it isn't
listed, **verify against the installed version** rather than trusting memory —
this ecosystem moves fast and this file will age.

```bash
pip show langgraph langchain-core langchain
python -c "import langgraph; print(langgraph.__version__)"
```

Grep the installed package for `@deprecated` when unsure:
```bash
grep -rn "deprecated" .venv/Lib/site-packages/langgraph/errors.py
```

*Baseline for this document: LangGraph 1.2.x, LangChain 1.5.x, langgraph-prebuilt 1.1.x.*

---

## 1. Deprecation register

| Legacy | Status | Modern replacement | Notes |
|---|---|---|---|
| `NodeInterrupt` | **Deprecated** | `interrupt()` from `langgraph.types` | Payload + `Command(resume=...)` |
| `StateGraph(config_schema=...)` | **Deprecated** | `context_schema=` | Since v1.0 |
| `StateGraph(input=..., output=...)` | **Deprecated** | `input_schema=`, `output_schema=` | Since v0.5 |
| `invoke(..., checkpoint_during=...)` | **Deprecated** | `durability="async"\|"sync"\|"exit"` | |
| `AgentState` / `AgentStatePydantic` from `langgraph.prebuilt` | **Deprecated** | `from langchain.agents import AgentState` | Moved to LangChain |
| `AgentStateWithStructuredResponse` | **Deprecated** | `AgentState` in `langchain.agents` | |
| `MemorySaver` | Alias, still works | `InMemorySaver` | Same class, newer name |
| `langgraph.constants.Send` | Works | `langgraph.types.Send` | Prefer `types` |
| LangChain `ConversationBufferMemory` etc. | **Deprecated (v0.3.1+)**, removed in 1.0 | LangGraph checkpointer | Entire legacy memory family |
| LangChain `AgentExecutor`, `initialize_agent` | **Legacy** | `create_agent` / LangGraph | |
| `LLMChain`, `SequentialChain` | **Legacy** | LCEL or a LangGraph chain | |
| `astream_events(version="v2")` | Works | Native `stream_mode="messages"` | Simpler for token streaming |
| `TavilySearchResults` (langchain-community) | Superseded | `TavilySearch` (`langchain-tavily`) | Returns a dict with `results` |
| `create_react_agent` (langgraph.prebuilt) | Supported | `create_agent` (`langchain.agents`) | `create_agent` is the forward path |

---

## 2. Migration recipes

### 2.1 `NodeInterrupt` → `interrupt()`

```python
# LEGACY
from langgraph.errors import NodeInterrupt
def step(state):
    if len(state["input"]) > 5:
        raise NodeInterrupt(f"Too long: {state['input']}")
    return state
# resume: graph.update_state(cfg, {"input": "hi"}); graph.invoke(None, cfg)

# MODERN
from langgraph.types import interrupt, Command
def step(state):
    if len(state["input"]) > 5:
        corrected = interrupt({"reason": "too_long", "value": state["input"]})
        return {"input": corrected}
    return state
# resume: graph.invoke(Command(resume="hi"), cfg)
```

**What you gain:** a structured payload for your UI, and resume-with-a-value instead of
mutate-then-resume.
**What to watch:** the node re-runs from the top on resume — move side effects after
the `interrupt()` call.

### 2.2 `config_schema` → `context_schema`

```python
# LEGACY
builder = StateGraph(State, config_schema=Configuration)
def node(state, config: RunnableConfig):
    user_id = config["configurable"]["user_id"]

# MODERN
from langgraph.runtime import Runtime

@dataclass
class Context:
    user_id: str
    model: str = "gpt-4.1"

builder = StateGraph(State, context_schema=Context)
def node(state, runtime: Runtime[Context]):
    user_id = runtime.context.user_id
    store    = runtime.store            # also available here

graph.invoke(inp, config={"configurable": {"thread_id": t}}, context={"user_id": "u1"})
```

Note the split: `thread_id`/`checkpoint_id` stay in `config`; **application** config
moves to `context`. This also removes the boilerplate `Configuration.from_runnable_config()`
dataclass pattern seen in older course code.

### 2.3 Legacy LangChain memory → checkpointer

```python
# LEGACY (removed)
memory = ConversationBufferMemory(return_messages=True)
chain  = ConversationChain(llm=llm, memory=memory)

# MODERN
graph = builder.compile(checkpointer=PostgresSaver(...))
graph.invoke({"messages": [msg]}, {"configurable": {"thread_id": "conv-1"}})
```

The conceptual shift: memory is **persistence of graph state per thread**, not an
object bolted onto a chain. This is why you get replay, forking, and HITL for free.

### 2.4 Hand-rolled ReAct loop → `create_agent` + middleware

```python
# LEGACY-ISH (still valid, but usually unnecessary)
builder = StateGraph(MessagesState)
builder.add_node("assistant", assistant)
builder.add_node("tools", ToolNode(tools))
builder.add_conditional_edges("assistant", tools_condition)
builder.add_edge("tools", "assistant")

# MODERN
from langchain.agents import create_agent
from langchain.agents.middleware import (
    SummarizationMiddleware, HumanInTheLoopMiddleware, ModelCallLimitMiddleware,
)

agent = create_agent(
    model=model,
    tools=tools,
    system_prompt="...",
    middleware=[
        SummarizationMiddleware(model=model, max_tokens_before_summary=4000),
        HumanInTheLoopMiddleware(interrupt_on={"delete_records": True}),
        ModelCallLimitMiddleware(thread_limit=20),
    ],
    checkpointer=checkpointer,
    store=store,
)
```

**Keep the `StateGraph` version** when you need a topology the loop can't express
(parallel branches, map-reduce, supervisor, multi-stage pipelines) — that is the
legitimate reason, and it remains fully supported. Don't hand-roll just to insert one
cross-cutting behaviour; that's what middleware is for.

### 2.5 `astream_events` → native stream modes

```python
# LEGACY
async for ev in graph.astream_events(inp, cfg, version="v2"):
    if ev["event"] == "on_chat_model_stream" and ev["metadata"]["langgraph_node"] == "chat":
        print(ev["data"]["chunk"].content, end="")

# MODERN
async for token, meta in graph.astream(inp, cfg, stream_mode="messages"):
    if meta["langgraph_node"] == "chat":
        print(token.content, end="")
```

`astream_events` still works and remains useful for deep introspection, but
`stream_mode="messages"` is the direct path for token streaming. Combine modes with a
list: `stream_mode=["updates", "messages"]`.

---

## 3. Third-party library register

### 3.1 Trustcall

- **What it does:** LLM-driven **JSON-patch** updates to structured documents, with
  schema validation/retry and collection inserts.
- **Problem it solved:** models regenerating a whole structured doc would silently drop
  fields they weren't reminded of; patching avoided that and was cheaper on large schemas.
- **Current status:** pre-1.0, single-maintainer, low release cadence. Survives largely
  as a transitive dependency of LangMem.
- **Recommendation:** **not the default.** Use `with_structured_output` + an explicit
  merge you control (see `04-memory-long-term.md` §6 Option A), or restructure to a
  collection so per-item writes can't clobber each other.
- **Keep it only if:** you have a large/deeply-nested schema and have *measured* that
  regeneration loses data.
- **Migration:**
  ```python
  # FROM
  extractor = create_extractor(model, tools=[Profile], tool_choice="Profile")
  result = extractor.invoke({"messages": msgs, "existing": {"Profile": current}})
  new = result["responses"][0].model_dump()

  # TO
  result = model.with_structured_output(Profile).invoke([
      SystemMessage(f"Update this profile; preserve existing values unless "
                    f"explicitly contradicted:\n{current}"), *msgs])
  new = {**current, **{k: v for k, v in result.model_dump().items() if v is not None}}
  ```
  For collections (`enable_inserts=True`): have the model propose new items, then
  `store.put()` each under its own key. Same behaviour, no dependency.
- **Durable lesson:** decide explicitly whether a memory write is a *merge* or a
  *replace*, and make the merge deterministic in your code.

### 3.2 LangMem

- **What it does:** memory managers over the LangGraph Store — semantic/episodic/
  procedural extraction, consolidation, and prompt optimization.
- **Status:** actively developed, **pre-1.0**; API can move between releases.
- **Latency:** its managers are slow; use them in **background/batch**, not in an
  interactive hot path.
- **Recommendation:** the Store plus ~50 lines covers most memory needs. Adopt LangMem
  when you specifically want its consolidation or prompt-optimization machinery and can
  absorb pre-1.0 churn. Don't adopt it as a wrapper over one `store.put()`.

### 3.3 Search / retrieval tools

| Legacy | Modern |
|---|---|
| `TavilySearchResults` (langchain-community) | `TavilySearch` from `langchain-tavily` |
| `WikipediaLoader` (community) | Fine for demos. In production, prefer an API you control, add retries/backoff (it rate-limits hard under parallel fan-out), and never let it raise into a fan-out branch |

**Principle:** anything in `langchain-community` is community-maintained with variable
quality. For production paths, prefer a dedicated partner package (`langchain-*`) or
your own thin wrapper with explicit error handling and timeouts.

### 3.4 Vector stores / embeddings

Rapidly changing. Do not hard-code a specific vector DB into your architecture — put it
behind the `BaseStore` interface or a small retrieval interface of your own so it can
be swapped.

Use `init_embeddings("provider:model")` rather than provider-specific classes where
possible; it keeps the swap cheap.

---

## 4. Model-provider portability

Notebook code often hard-codes a provider (e.g. `AzureChatOpenAI` with an Azure
*deployment name*, which is not a model name). In production:

```python
from langchain.chat_models import init_chat_model
model = init_chat_model(os.environ["MODEL_ID"], temperature=0)   # provider-agnostic
```

Portability caveats that bite in practice:

- **Azure addresses models by deployment name**, so token counters that infer an
  encoding from the model name need `model=` passed explicitly.
- Structured-output support and quality vary by provider.
- Parallel-tool-call behaviour and defaults differ.
- Reasoning-model params (`temperature`, etc.) are often ignored or rejected.

**Keep model configuration in `context_schema`**, not hard-coded in nodes. It makes
A/B testing, per-tenant model choice, and provider fallback trivial.

---

## 5. Evaluating any new dependency

Before adding a library to an agent stack:

1. **Is there a first-party capability?** (LangGraph core, `langgraph-prebuilt`,
   `langchain` middleware.) Prefer it — it will be maintained alongside the framework.
2. **Release cadence and version.** Pre-1.0 with no release in 6+ months is a risk you
   are taking on deliberately.
3. **Maintainer count.** One person is a bus factor.
4. **Is it a thin wrapper?** If you can replicate it in ~50 lines you control, do that.
5. **Can you swap it out?** Put it behind an interface at the boundary.
6. **Does it own your data?** Anything that owns storage is expensive to leave.

**Bias:** first-party > well-maintained third-party > thin wrapper you write >
unmaintained third-party.

---

## 6. Future-proofing rules

These outlive any specific API:

1. **Depend on concepts, not signatures.** "Bound the context window" survives; the
   function that does it may not.
2. **Isolate the edges.** Model calls, retrieval, and storage behind thin interfaces
   means a deprecation is a one-file change.
3. **Config over code.** Model, prompts, limits in `context_schema` — swapping a model
   should not require a deploy of new logic.
4. **Pin versions; upgrade deliberately.** Read the changelog; run your eval set; then
   upgrade.
5. **Run with deprecation warnings visible in CI.** They are your early-warning system:
   `python -W error::DeprecationWarning` in a canary test.
6. **Prefer boring, stable primitives.** `StateGraph`, `TypedDict`, reducers, and
   checkpointers have been stable through multiple major versions. Novel abstractions
   churn.
7. **When this file and reality disagree, reality wins.** Verify against the installed
   version.
