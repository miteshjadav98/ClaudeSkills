# ClaudeSkills

A personal collection of [Claude Code](https://claude.com/claude-code) skills for backend, AI, and frontend engineering work.

Skills are reusable instruction packages that Claude loads on demand when a task matches their description — so a workflow you've refined once gets applied consistently every time, without re-explaining it.

## Skills

| Skill | What it does |
|---|---|
| **[langgraph-skill](skills/langgraph-skill/)** | Principal-engineer handbook for designing and building LangGraph applications — graph topology, state schemas and reducers, checkpointers, short- and long-term memory, interrupts and human-in-the-loop approvals, subgraphs, map-reduce fan-out, and production hardening. 12 reference documents including agent patterns, anti-patterns, decision frameworks, and templates. |
| **[code-review](skills/code-review/)** | Read-only senior code review through a senior-developer, tech-lead, and architect lens. Traces paths and asks six design questions before judging lines, gates every finding on evidence (file:line, reachable scenario, not already handled), types it as bug, risk, or trade-off, and ends with P0–P3 findings, the top 3 observations, questions before approval, and a merge verdict. Includes LLM/RAG/multi-agent checks, mentor and quiz modes for learning to review, and a seeded-bug drill with an answer key. |
| **[system-design](skills/system-design/)** | Tiered system-design handbook. Sizes a problem into one of three levels — L1 mini POC, L2 mid-size production (modular monolith or microservices), L3 hyperscale — then applies only the patterns that level earns, with the escalation triggers between tiers written down. 15 reference documents covering architecture styles, the data layer, caching failure modes, API design, messaging, reliability, security, operations, worked designs (YouTube, live streaming, notifications, payments), and case studies of how Netflix, Reddit, Discord, and Figma actually scaled. |
| **[engineering-buddy](skills/engineering-buddy/)** | An engineering-partner persona for system design, backend development, cloud/infra, and AI engineering. Enforces a Understanding → Analysis → Solution → Tradeoffs → Implementation spine, plus a system-design pattern reference. Explicitly invoked only. |
| **[frontend-design](skills/frontend-design/)** | Guidance for distinctive, intentional visual design when building or reshaping UI — aesthetic direction, type systems, and making choices that don't read as templated defaults. |
| **[resume-tailoring](skills/resume-tailoring/)** | ATS-optimized, role-specific resume generation. Reweights emphasis between an AI/GenAI Engineer and a Senior Backend Engineer framing over the same real history, then outputs markdown → DOCX/PDF. |
| **[job-match-scoring](skills/job-match-scoring/)** | Scores and ranks scraped job listings with a blended weighted model that favours differentiator skills over raw keyword counts, then emits a ranked JSON report and an Excel tracker. |

## Agents

| Agent | What it does |
|---|---|
| **[code-reviewer](agents/code-reviewer.md)** | A read-only Claude Code subagent (no edit or write tools) that loads the `code-review` skill and reviews a PR, branch, commit, or uncommitted changes in its own context. Claude can call it proactively after a significant change. |

## Usage

Clone into your Claude Code skills directory:

```bash
git clone https://github.com/miteshjadav98/ClaudeSkills.git
cp -r ClaudeSkills/skills/* ~/.claude/skills/
mkdir -p ~/.claude/agents && cp ClaudeSkills/agents/*.md ~/.claude/agents/
```

Claude picks up each skill automatically from its `SKILL.md` frontmatter and invokes it when a task matches. To review code, ask in natural language — "review my changes", "review PR 42", "is this branch safe to merge?", "review this as an architect", or "review it in mentor mode" — or call the agent directly: "use the code-reviewer agent on feat/x". To scope a skill to a single project instead, copy it into that project's `.claude/skills/` directory.

## Notes

The `resume-tailoring` and `job-match-scoring` skills use placeholders (`<FULL NAME>`, `<EMAIL>`, `<PHONE>`) in place of personal details — fill them in locally after cloning. No credentials, personal data, or client-specific information is committed to this repository.

## Author

**Mitesh Jadav** — miteshjadav.ict17@gmail.com

## License

MIT
