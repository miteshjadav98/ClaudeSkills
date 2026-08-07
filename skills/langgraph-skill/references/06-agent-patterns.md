# Agent Pattern Catalog

Each entry: purpose → architecture → strengths → weaknesses → production notes → real uses.

Patterns compose. Most real systems are 2–4 of these layered.

---

## 1. Simple Chatbot

**Purpose:** conversational interface with no tools; possibly memory.

```
START → call_model → END          (+ checkpointer for multi-turn)
```

**Strengths:** trivial, fast, cheap, predictable.
**Weaknesses:** cannot act or look anything up; hallucinates on anything outside
training data.
**Production notes:** the entire engineering problem is **context management** — trim
or summarize, and pick a `thread_id` granularity that matches how users think about
"a conversation".
**Real uses:** writing assistants, brainstorming, tutoring, internal Q&A over a system
prompt.

**When to upgrade:** the moment users ask about current or private data → RAG or tools.

---

## 2. Router Agent

**Purpose:** classify input and dispatch to a specialized handler.

```
START → classify ──cond──→ handler_a / handler_b / handler_c → END
```

**Strengths:** one decision, bounded cost, each handler independently testable and
independently promptable; easy to add a category.
**Weaknesses:** misclassification is unrecoverable (no loop back); doesn't handle
requests that span categories.
**Production notes:**
- Use **structured output** for the classification, not free text parsing.
- **Always include an `other`/fallback branch.** Forcing a hard classification is how
  you get confidently wrong routing.
- Log the classification with confidence; it's your best signal for prompt tuning.
- A cheap model is usually enough for routing — this is the highest-ROI place to
  downshift models.

**Real uses:** support triage, intent detection, cheap-vs-strong model selection,
content moderation pre-filter.

---

## 3. Tool-Calling Agent (ReAct)

**Purpose:** open-ended tasks requiring external actions.

```
START → assistant ──cond──→ tools ──→ assistant (loop) 
                     └────→ END
```

**Strengths:** the general-purpose pattern; handles multi-step tasks; adding a tool
adds a capability with no graph change.
**Weaknesses:** unbounded loops; cost grows with every observation; tool-selection
accuracy degrades sharply past ~10–15 tools; the message list grows monotonically.

**Production notes — the ones that actually matter:**
- **Tool descriptions are prompts.** Most "the agent picked the wrong tool" bugs are
  description bugs, not model bugs. Write them for a reader who has no other context.
- **Cap the loop**: recursion limit + `ModelCallLimitMiddleware` / `ToolCallLimitMiddleware`.
- **Return errors as `ToolMessage`s, not exceptions** — the model can often recover
  from "invalid date format" if you let it see the error.
- **Disable parallel tool calls when the operations are order-dependent**
  (`bind_tools(tools, parallel_tool_calls=False)`); leave it on when they're independent
  and you want the latency win.
- Past ~15 tools, use tool-selection middleware (retrieve relevant tools per turn) or
  split into sub-agents by domain.
- **Prefer `create_agent`** over hand-rolling the loop.

**Real uses:** coding agents, data analysis, ops automation, API orchestration, personal
assistants.

---

## 4. RAG Agent

**Purpose:** ground answers in a corpus the model wasn't trained on.

```
Static:   START → retrieve → generate → END
Agentic:  START → agent ──cond──→ retrieve_tool ──→ agent → END
Corrective: retrieve → grade ──cond──→ generate
                          └──→ rewrite_query → retrieve  (loop, capped)
```

**Strengths:** grounded, citable, updatable without retraining.
**Weaknesses:** answer quality is capped by retrieval quality — and **retrieval is
usually the bug**, not generation. Chunking strategy silently determines your ceiling.

**Production notes:**
- **Static retrieval (always retrieve) is the right default.** Agentic retrieval costs
  an extra model call to decide something that's usually "yes".
- **Hybrid retrieval** (dense + sparse) — dense-only fails on exact identifiers,
  error codes, and product names.
- **Rerank** the top ~50 down to ~5. Usually the single largest quality win per unit
  of effort.
- **Grade relevance before generating** (corrective RAG) when wrong answers are
  costly — and **cap the rewrite loop**, it's a classic infinite loop.
- **Always return citations.** Ungrounded RAG is worse than no RAG because it looks
  authoritative.
- Measure retrieval separately from generation. If you only measure the final answer
  you cannot tell which half is broken.

**Real uses:** documentation Q&A, policy/compliance lookup, customer support over a
knowledge base, contract search.

---

## 5. Research Assistant (multi-perspective)

**Purpose:** deep research producing a structured report from many sources.

```
plan → [HUMAN APPROVAL] → Send × N → interview subgraph → parallel writers → assemble
```

**Strengths:** parallel coverage of a topic; diverse perspectives surface more than a
single query; the human gate is cheap and high-leverage.
**Weaknesses:** expensive (N × interview turns × sources); latency in minutes; failure
of one branch can strand the reduce step.

**Production notes:**
- **Human gate before fan-out** — the defining design decision. Approve the plan, not
  the output.
- **Cap N** and cap turns per interview.
- **Isolate branch failures** — a dead source returns empty context, never an exception.
- Serialize sub-results (transcript → section string) before they hit the parent
  reducer, to keep checkpoints small.
- Budget the run explicitly; report cost per report.

**Real uses:** market/competitive analysis, due diligence, literature review, incident
post-mortems, RFP responses.

Full walkthrough in `01-architecture.md` §4.

---

## 6. Supervisor / Multi-Agent

**Purpose:** coordinate specialists that each have their own tools and prompt.

```
START → supervisor ──cond──→ specialist_a / specialist_b → supervisor → ... → END
```

**Strengths:** each specialist stays small and testable; separate tool sets avoid
tool-overload; routing logic centralized and inspectable.
**Weaknesses:** every hop is a model call; supervisor context grows with each report;
a single supervisor prompt becomes a bottleneck of complexity; hardest pattern to debug.

**Production notes:**
- **Structured handoffs.** The supervisor should emit a typed decision
  (`{"next": "researcher", "task": "..."}`), never free text you parse.
- **Bound the hops.** Supervisor ping-pong is a real and expensive failure mode.
- **Summarize specialist output before it enters supervisor context**, or the
  supervisor's prompt grows without limit.
- **Justify it.** Two agents that share all their tools and context are one agent with
  a confused prompt. The test: *do the specialists have genuinely different tools or
  genuinely different instructions?* If no → single agent.

**Real uses:** software teams (planner/coder/reviewer), customer service tiers,
document pipelines (extract/validate/route).

---

## 7. Planner–Executor

**Purpose:** decompose a complex goal into a plan, then execute steps.

```
START → plan → execute_step ──cond──→ execute_step (next)
                      │                    
                      └──→ replan (on failure/new info) → execute_step
                      └──→ END (plan complete)
```

**Strengths:** the plan is inspectable and approvable *before* execution; better on
long-horizon tasks than pure ReAct; natural HITL insertion point.
**Weaknesses:** plans go stale as reality diverges; replanning loops; over-planning
simple tasks wastes a model call.

**Production notes:**
- Store the plan **in state** so it's visible, editable, and resumable.
- **Cap replans** — 2–3. Unbounded replanning is a very expensive infinite loop.
- Approve the plan, not each step (that's approval fatigue).
- `TodoListMiddleware` provides a maintained implementation of plan-tracking for
  prebuilt agents.

**Real uses:** multi-file code changes, migration scripts, complex data pipelines,
travel/event planning.

---

## 8. Reflection / Self-Critique

**Purpose:** improve output quality by having the model (or another model) critique
and revise.

```
generate → critique ──cond──→ revise → critique (loop, capped)
                       └────→ END (good enough)
```

**Strengths:** measurably better output on writing, code, and reasoning tasks; catches
format and constraint violations reliably.
**Weaknesses:** 2–3× cost and latency; models are poor judges of their own factual
accuracy; diminishing returns after ~2 iterations; can talk itself out of a correct answer.

**Production notes:**
- **Cap iterations at 2–3.** Always. Non-negotiable.
- **Critique against explicit criteria**, not "is this good?" — a rubric produces
  actionable critique; a vague prompt produces vague praise.
- **A separate critic model/prompt beats self-critique.** Self-critique has a strong
  bias toward "yes, that's fine".
- **Prefer deterministic validation where it exists.** Running the tests, the linter,
  or a schema validator beats asking an LLM whether the code is correct. Use reflection
  for what you cannot check mechanically.

**Real uses:** content generation with style rules, code review, structured extraction
QA, translation refinement.

---

## 9. Memory Agent

**Purpose:** personalization that persists across sessions.

```
START → respond ──cond──→ update_profile / update_collection / update_instructions → respond
                    └──→ END
```

**Strengths:** genuine continuity; the model decides *when* memory is worth writing,
so you don't pay extraction cost every turn.
**Weaknesses:** memory quality decays (duplicates, contradictions); privacy surface;
extraction latency; users can be unsettled by unexpected recall.

**Production notes:**
- **Separate namespaces per memory type** (profile / observations / instructions).
- **Model-gated writes** (an `UpdateMemory` tool) beat always-extract.
- Make memory **visible and deletable** by the user.
- Namespace from **authenticated identity**, never from model output.
- Treat retrieved memories as **untrusted input** — they can carry injected instructions.

**Real uses:** personal assistants, tutoring, long-running project companions,
CRM-augmented sales agents.

See `04-memory-long-term.md` for the full treatment.

---

## 10. Approval Workflow Agent

**Purpose:** agent proposes, human disposes, then execution proceeds.

```
START → propose → interrupt(payload) → [human] → execute / cancel → END
```

**Strengths:** makes consequential automation shippable; full audit trail; the fastest
path to trust with a skeptical stakeholder.
**Weaknesses:** human latency becomes system latency; approval fatigue; needs
notification and timeout infrastructure.

**Production notes:** covered in depth in `05-human-in-the-loop.md` §7–8. The two things
people forget: **notify the human**, and **decide what happens if nobody answers.**

**Real uses:** refunds, financial transactions, outbound comms, infra changes,
content publishing, HR actions.

---

## 11. Document Processing Agent

**Purpose:** extract structure from unstructured documents at volume.

```
START → split → Send × N (chunk) → extract → merge → validate ──cond──→ END
                                                          └──→ human review
```

**Strengths:** parallel throughput; typed output; validation gate catches the tail.
**Weaknesses:** chunk boundaries split entities; merge conflicts across chunks; cost
scales linearly with pages.

**Production notes:**
- **Overlap chunks** so entities aren't cut in half.
- **Structured output with a strict schema**, plus a confidence field.
- **Route low-confidence extractions to human review** — this is where HITL pays for
  itself in document work.
- Cap concurrency; you will hit provider rate limits before you hit compute limits.
- Deterministic post-validation (regex, checksums, cross-field consistency) is cheaper
  and more reliable than a second LLM pass.

**Real uses:** invoice/receipt processing, contract analysis, resume parsing, medical
records, KYC.

---

## 12. Customer Support Agent

**Purpose:** resolve customer issues with access to real systems.

```
START → classify ──→ retrieve_context (KB + account) → respond ──cond──→ action(interrupt) 
                                                            ├──→ escalate_to_human
                                                            └──→ END
```

**Strengths:** deflects routine volume; consistent policy application; 24/7.
**Weaknesses:** confidently wrong answers damage trust; escalation detection is hard;
policy changes require prompt+KB updates.

**Production notes:**
- **Escalation is a first-class path**, not an error case. Detect frustration, repeated
  failures, and out-of-policy requests; hand off *with the transcript*.
- **Gate every account-modifying action** behind approval or strict policy checks.
- **Ground every factual claim in the KB** and cite it.
- Track deflection rate **and** post-deflection contact rate — deflection alone is a
  vanity metric if customers just come back angrier.

**Real uses:** tier-1 support, order status, returns, account management, onboarding.

---

## 13. Coding Agent

**Purpose:** read, write, and modify code with verification.

```
START → understand → plan → edit ──→ run_tests ──cond──→ fix (loop, capped) 
                                                   └──→ END
```

**Strengths:** the test suite is a **ground-truth verifier** — this pattern has a real
oracle, which most agent patterns lack.
**Weaknesses:** large repos overflow context; tests can be missing or wrong; edits can
be destructive.

**Production notes:**
- **Verification loop is the whole pattern.** An agent that writes code without running
  it is a code *suggester*.
- Work in an isolated worktree/branch/sandbox; never edit the user's working tree
  directly without consent.
- Retrieve code by symbol/grep, don't stuff the repo into context.
- Cap the fix loop — thrashing on a failing test is a common and expensive failure.
- Approval gate before commit/push/deploy.

**Real uses:** refactoring, test generation, bug fixing, migrations, code review.

---

## 14. Knowledge Assistant (hybrid)

**Purpose:** answer over an organization's combined structured + unstructured knowledge.

```
START → route ──cond──→ sql_agent      ─┐
                 ├────→ rag_retriever  ─┼→ synthesize → END
                 └────→ api_lookup     ─┘
```

**Strengths:** one interface over heterogeneous back ends; each retriever is optimized
for its data type.
**Weaknesses:** routing errors; conflicting answers across sources; permissions must be
enforced per source, not at the agent.

**Production notes:**
- **Enforce authorization at the data layer**, per source, for the *end user* — never
  rely on the agent to respect access rules.
- Have an explicit conflict-resolution policy (source precedence) when sources disagree.
- Attribute every claim to its source.

**Real uses:** internal "ask anything" bots, BI assistants, ops copilots.

---

## 15. Map-Reduce Worker Pattern

**Purpose:** the same operation over N items, N known only at runtime.

```
START → plan ──Send × N──→ worker → reduce → END
```

Covered in `01-architecture.md` §2.5.

**Production notes:** cap N; batch small items; isolate worker failures so one bad item
doesn't fail the reduce; consider partial results ("42 of 50 succeeded") as a valid outcome.

**Real uses:** bulk classification, multi-document summarization, test generation,
per-customer report generation, candidate-answer generation for ranking.

---

## 16. Evaluator–Optimizer

**Purpose:** generate candidates, score them, pick or improve.

```
START → generate × k ──→ evaluate ──cond──→ return_best
                              └──→ regenerate with feedback (capped)
```

**Strengths:** quality via selection rather than via a better single generation; works
well when evaluation is easier than generation.
**Weaknesses:** k× generation cost; the evaluator becomes the quality ceiling.

**Production notes:** use a **deterministic** evaluator whenever one exists (tests,
schema validation, constraint checks). LLM judges need their own validation against
human labels, or you are optimizing against noise.

**Real uses:** copy variants, code solution selection, query rewriting, prompt search.

---

## 17. Hybrid Search Agent

**Purpose:** maximize recall+precision over a corpus with mixed query types.

```
query → ┬→ dense_search  ─┐
        ├→ sparse_search  ─┼→ fuse (RRF) → rerank → generate
        └→ metadata_filter ┘
```

**Production notes:** Reciprocal Rank Fusion is a strong, tuning-free default for
combining rankings. Filters before search beat filters after. Measure recall@k on a
labelled set — you cannot tune what you don't measure.

---

## 18. Streaming Conversational Agent

**Purpose:** low perceived latency in chat.

**Production notes:**
- `stream_mode="messages"` for tokens; `"updates"` for step progress; combine both.
- Emit custom progress events from slow nodes so the UI isn't silent during a 20-second
  retrieval.
- Decide the **double-text policy** (reject/enqueue/interrupt/rollback) — see
  `01-architecture.md` §6. Chat UIs usually want interrupt or rollback.

---

## Pattern selection matrix

| If the task… | Pattern |
|---|---|
| Has fixed steps | Chain |
| Needs one classification | Router |
| Needs open-ended tool use | ReAct |
| Needs private/current knowledge | RAG |
| Needs multi-source depth | Research assistant |
| Needs distinct specialist skills | Supervisor |
| Has a long horizon | Planner–executor |
| Has quality bar > single-shot | Reflection / evaluator-optimizer |
| Should remember the user | Memory agent |
| Has irreversible consequences | Approval workflow |
| Processes many items | Map-reduce |
| Has a mechanical correctness oracle | Coding agent / evaluator |

**Composition is normal.** A production support agent is commonly:
Router → RAG → ReAct → Approval → Memory. Build it one layer at a time, and measure
after each.
