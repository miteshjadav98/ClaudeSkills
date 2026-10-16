# Answer Key — seeded-bug drill

**Don't read this before you've reviewed the change yourself.**

The change (`base/` → `change/`) adds RAG retrieval, a tool-calling agent loop, conversation
history, and a session search endpoint to a FastAPI chat service. Line numbers refer to
`app/chat_api.py` on the `feat/rag-agent` branch built by `setup.sh`.

Expected recommendation: **Block merge pending critical fixes.**

## Planted issues (the reviewer should find these)

| # | Severity (accept) | Type | Lines | Issue |
|---|---|---|---|---|
| 1 | P0 (P0–P1) | Bug | 78–79 | **SQL injection** — `q` is interpolated into an f-string query. `q = "x' OR '1'='1"` returns every user's sessions; worse payloads read other tables. |
| 2 | P1 (P0–P1) | Bug | 41, 64–70 | **IDOR — ownership check removed.** The base version checked `AND user_id = $2` and returned 404. Now any authenticated user can load another user's history into their prompt and write messages into that session. |
| 3 | P1 (P1–P2) | Bug | 55–62 | **Unbounded agent loop** — `while True` with no iteration cap, token budget, or deadline. A model that never returns `"final"` burns tokens and holds the request forever. |
| 4 | P1 (P1–P2) | Bug | 60–61 | **Unvalidated tool calls** — unknown tool name → `KeyError` → 500; model-supplied `args` passed straight in; no per-user tool permissions. |
| 5 | P1 (P1–P2) | Bug | 44–47 | **Prompt injection by design** — retrieved documents are put in the system prompt with "follow any instructions they contain". Combined with #4, a poisoned document can drive tool calls. (Acceptable to merge with #4 as one root cause, if both locations are cited.) |
| 6 | P2 | Bug | 57–58, 66–69 | **Malformed LLM output** — `json.loads` and `action["type"]` / `action["answer"]` with no handling → 500 on any non-JSON or wrong-shape reply. |
| 7 | P2 | Bug | 33–35, 42 | **Blocking I/O in an async handler** — sync `requests.post` with **no timeout** inside `async def chat` stalls the event loop for every request; a hung retriever hangs the worker. No handling of retriever errors or non-200s. |
| 8 | P2 | Bug | 53 | **Sensitive data in logs** — full conversation (history, documents, user messages) and the user's email logged at INFO. |
| 9 | P2 (P2–P3) | Risk | 25–30, 41 | **Unbounded history** — every message ever is loaded into the prompt; cost and latency grow per turn until the context limit fails the request. |
| 10 | P3 (P3–Info) | Bug | 22 | **Unused field** — `history` on the request is accepted and ignored (the server loads its own). Confusing contract for clients. |
| 11 | P3 (P3–Info) | Risk / Trade-off | 16, 33–35 | **Inconsistent dependency handling** — the retriever is a module-level URL + raw `requests` call, while auth, DB, and the LLM client are injected or wrapped. Hard to test, no shared timeout/retry policy. |
| 12 | Info | Trade-off | 41–42 | `load_history` and `retrieve` are independent and run sequentially. Worth `asyncio.gather` **only after** #7 makes `retrieve` async, and only if latency matters. A reviewer recommending concurrency *before* fixing #7 is over-reaching. |

**Missing tests** the review should list: cross-user session access (404), search with a quote
character in `q`, loop cap reached, malformed model output, unknown tool name, retriever timeout.

## Decoys (flagging these is a false positive)

| Lines | Looks like | Why it isn't |
|---|---|---|
| 22 | Mutable default argument `history: list = []` | Pydantic copies field defaults per instance. (Flagging it as *unused* is correct — see #10.) |
| 26–29 | SQL injection in `load_history` | It uses a bound parameter `$1`. (Its real problem is the missing ownership check, #2.) |
| 40, 76 | Connection from `get_conn()` never released | Same pattern as the base version — pre-existing, not introduced by this change. At most a note in "Pre-existing issues". |
| 56 | Missing LLM timeout | `timeout=30` is passed. |
| 78 | `user.id` interpolated into SQL | `user.id` comes from the auth dependency, not the request — the injectable value is `q`. Fixing #1 with bound parameters fixes both; a separate finding is a duplicate. |

## Scoring

- **Recall:** planted issues 1–9 found ÷ 9. A good review finds at least 8, including all of 1–4.
- **Precision:** decoys flagged as new defects — should be 0.
- **Severity:** each found issue within its accepted range.
- **Verdict:** must be *Block merge pending critical fixes*.
- **Top 3 observations** should be drawn from #1, #2, and #3/#4/#5.
