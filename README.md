# ClaudeSkills

A personal collection of [Claude Code](https://claude.com/claude-code) skills for backend, AI, and frontend engineering work.

Skills are reusable instruction packages that Claude loads on demand when a task matches their description — so a workflow you've refined once gets applied consistently every time, without re-explaining it.

## Skills

| Skill | What it does |
|---|---|
| **[langgraph-skill](skills/langgraph-skill/)** | Principal-engineer handbook for designing and building LangGraph applications — graph topology, state schemas and reducers, checkpointers, short- and long-term memory, interrupts and human-in-the-loop approvals, subgraphs, map-reduce fan-out, and production hardening. 12 reference documents including agent patterns, anti-patterns, decision frameworks, and templates. |
| **[engineering-buddy](skills/engineering-buddy/)** | An engineering-partner persona for system design, backend development, cloud/infra, and AI engineering. Enforces a Understanding → Analysis → Solution → Tradeoffs → Implementation spine, plus a system-design pattern reference. Explicitly invoked only. |
| **[frontend-design](skills/frontend-design/)** | Guidance for distinctive, intentional visual design when building or reshaping UI — aesthetic direction, type systems, and making choices that don't read as templated defaults. |
| **[resume-tailoring](skills/resume-tailoring/)** | ATS-optimized, role-specific resume generation. Reweights emphasis between an AI/GenAI Engineer and a Senior Backend Engineer framing over the same real history, then outputs markdown → DOCX/PDF. |
| **[job-match-scoring](skills/job-match-scoring/)** | Scores and ranks scraped job listings with a blended weighted model that favours differentiator skills over raw keyword counts, then emits a ranked JSON report and an Excel tracker. |

## Usage

Clone into your Claude Code skills directory:

```bash
git clone https://github.com/miteshjadav98/ClaudeSkills.git
cp -r ClaudeSkills/skills/* ~/.claude/skills/
```

Claude picks up each skill automatically from its `SKILL.md` frontmatter and invokes it when a task matches. To scope a skill to a single project instead, copy it into that project's `.claude/skills/` directory.

## Notes

The `resume-tailoring` and `job-match-scoring` skills use placeholders (`<FULL NAME>`, `<EMAIL>`, `<PHONE>`) in place of personal details — fill them in locally after cloning. No credentials, personal data, or client-specific information is committed to this repository.

## Author

**Mitesh Jadav** — miteshjadav.ict17@gmail.com

## License

MIT
