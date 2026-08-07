---
name: job-match-scoring
description: LinkedIn job-scrape scoring workflow — recomputes a blended weighted match score over scraped job data (weighting differentiator skills, title-fit, and seniority), filters and ranks, and produces a ranked JSON report plus an Excel tracker. Use whenever the user wants to score, rank, filter, or triage scraped job listings, run a job search over LinkedIn, or build a job-match report or tracker.
---

# Job Match Scoring

Score and rank scraped job listings against the candidate's profile, then produce a ranked report and tracker. The scraper's own keyword score is a raw signal only — it counts literal string presence, so a strong-fit role loses points when the JD omits terms like "MCP" or "FastAPI", or uses synonyms ("AOAI" for Azure OpenAI). Always recompute a blended weighted score in post-processing.

## Candidate profile

Fill this from the candidate before scoring: target titles, years of experience, and locations of interest (including remote). The example weighting below is tuned for an **AI/GenAI Engineer** track — target titles such as AI/GenAI Engineer, LLM Engineer, Conversational AI Engineer, or Backend Engineer. Retune the skill universe and weights for a different track.

## Blended score

Example skill universe (18): Python, FastAPI, Node.js, TypeScript, Azure OpenAI, LangChain, LangGraph, RAG, Vector Database, LLM, Agentic AI, MongoDB, PostgreSQL, Redis, Docker, Azure, MCP, Prompt Engineering.

**Differentiator weights** (the candidate's high-signal skills weigh most):

| Skill | Weight |
|---|---|
| LangGraph | 3.0 |
| RAG | 3.0 |
| Agentic AI | 3.0 |
| Azure OpenAI | 2.5 |
| FastAPI | 2.5 |
| MCP | 2.5 |
| all other skills | 1.0 |

Score = (sum of weights of matched skills ÷ sum of weights of all skills) × 100, then apply:

- **Title-fit bonus** for core AI roles (title contains AI / GenAI / LLM / Machine Learning / Agentic).
- **Penalty** for architect / QA / support / non-IC titles that don't match an IC engineering track.
- Optionally a small seniority-fit adjustment (senior/lead roles fit; junior roles down-weight).

**Filter** to ≥55%. **Sort** by blended score → AI relevance → recency (most recent first).

## Apify scraper gotchas (actor: cheap_scraper/linkedin-job-scraper)

Enum values are hyphenated — underscores are silently ignored:
- `jobType`: `"full-time"` (not `full_time`)
- `experienceLevel`: `"associate"`, `"mid-senior"` (not underscore forms)
- `workType`: `"remote"`, `"hybrid"`, `"on-site"`

`resumeKeywords` takes objects with `keyword` + optional `aliases`; returns `keywordMatchScorePercentage` per job — treat as raw signal only. Paginate `get-dataset-items` with `offset`/`limit`; dedupe across pages by jobUrl.

## Outputs

1. **Ranked JSON** — full structured array, one object per job with all requested fields (title, company, location, workType, experienceLevel, postedTime, blendedScore, rawScore, matchedKeywords, unmatchedKeywords, salaryInfo, applicationsCount, jobUrl).
2. **Excel tracker** — top N rows with matched/missing skills, salary, applicant counts, clickable apply links, plus working columns: Status, Applied Date, Notes. Read the `xlsx` skill first.
3. A short in-chat summary table (rank, blended %, title, company, location) with a color cue (🟢 for ≥80%) and a one-line note on recurring resume gaps to close (which high-weight terms are frequently unmatched).
