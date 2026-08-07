---
name: resume-tailoring
description: Resume-tailoring workflow — produces ATS-optimized, role-specific resumes (AI/GenAI Engineer vs Senior Backend Engineer) as markdown then DOCX/PDF, preserving real work history while reweighting emphasis. Use whenever the user asks to build, tailor, update, or reformat a resume, generate a role-specific version, or optimize a resume for ATS or a specific job description.
---

# Resume Tailoring

Produce ATS-optimized, role-specific resumes. Preserve the candidate's real history; reweight emphasis per target role. Never invent experience, employers, dates, or metrics.

## Fixed facts (do not alter)

Fill this block from the candidate's actual profile before drafting. Treat every value here as immutable once supplied — the rest of the workflow only changes emphasis, never facts.

- **Name:** `<FULL NAME>` — **Location:** `<CITY, COUNTRY>`
- **Contact:** `<EMAIL>` · `<PHONE>` · LinkedIn / GitHub / LeetCode / Portfolio — leave placeholders for URLs unless supplied.
- **Current role:** `<TITLE>` at `<EMPLOYER>`, `<START>`–Present.
- **Education:** `<DEGREE>`, `<INSTITUTION>`, `<YEAR>`.
- **Flagship project:** the single strongest project — name it, state scale (user count, throughput) and the systems it integrates with. Keep headline numbers consistent across the summary and the bullets (pick one figure and reuse it verbatim).
- **Earlier work:** prior projects and the older stack they used, so the timeline reads as progression rather than repetition.

## Two target versions

Ask which version if unspecified. Same history, different weighting (~70/30):

**AI / GenAI Engineer** — lead with LLM, RAG, agentic AI, LangChain, LangGraph, MCP, Azure OpenAI, vector search (FAISS/pgvector), multi-agent orchestration. Backend stays present but secondary.

**Senior Backend Engineer / Chatbot Developer** — lead with Node.js, TypeScript, NestJS, microservices, API design, cloud infra (Azure, Docker, Terraform, GitHub Actions), databases. Mention AI work only where it supports backend framing.

## ATS rules

- **Literal keyword matching:** ATS counts exact strings. Terms like `MCP`, `Azure OpenAI`, `FastAPI`, `LangGraph`, `RAG` must appear verbatim in bullets, not just implied. When tailoring to a JD, mirror its exact terms.
- Strong action verbs; quantify achievements — only reuse metrics the candidate has already used elsewhere. Never invent a number.
- 2 pages max. Single-column, selectable-text formatting (no tables/columns/text boxes that break parsers).
- Separate, role-specific professional summary and technical-skills section per version.
- Skills-section hygiene: no duplicate products listed as separate skills (e.g. "Azure AD SSO" and "Microsoft Entra ID" are the same — pick one); include standalone `Git` and `SQL`; keep granularity consistent (don't mix specific model versions with vague competencies); avoid vague catch-all category names; cap ~8–10 items per line.

## Output workflow

1. Draft in **markdown** first (source of truth); iterate with edits.
2. On request, generate **DOCX** (editable, for the candidate's own URL/profile edits) and/or **PDF** (ATS-friendly, selectable text).
3. Read the `docx` skill before DOCX and the `pdf` skill before PDF. Use US Letter sizing, bullet numbering config, right-aligned tab stops for role/date lines; validate output.
4. End with a short changelog: what was reweighted in each version and why.

## Projects to draw on

Maintain a running list of the candidate's real projects — each with its stack, scale, and one measurable outcome — and select from it per target role. Where a project was delivered for a client under NDA, refer to the client by industry and scale ("a Fortune 500 energy client") rather than by name.
