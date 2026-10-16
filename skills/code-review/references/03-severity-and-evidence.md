# Severity, Evidence, and False Positives

## Severity = impact × likelihood, under stated conditions

Every finding names the conditions it needs. The same line can be P0 in one codebase and P3 in
another: SQL built from a string is P0 when the string comes from a public request parameter and
P3 when it comes from a hard-coded enum.

| Level | Impact | Likelihood | Calibration examples |
|---|---|---|---|
| **P0** | Security breach, data loss or corruption at scale, full outage | Reachable now by ordinary users or the internet | SQL injection on an authenticated endpoint; auth middleware removed from a router; a migration that drops a column still read in production; secrets committed to a public repo |
| **P1** | Major functional failure, exploitable vulnerability, limited data loss, runaway cost | Reachable under realistic conditions | IDOR — any user reads another's records by ID; unbounded agent loop; double-charge on retry; a breaking API change for existing clients; tools callable with unvalidated model arguments |
| **P2** | Real bug or reliability/performance risk with bounded blast radius | Plausible | Blocking I/O in an async handler; malformed LLM output causes a 500; PII in INFO logs; N+1 on a list endpoint; missing timeout on an external call |
| **P3** | Minor defect, small impact | Any | Unused field; misleading error message; missing validation on an internal admin tool; small inconsistency with conventions |
| **Info** | No defect | — | A simpler alternative; a future trigger worth writing down |

**Promote** one level when: the path is L3 (auth, money, tenant isolation, migrations), the failure
is silent (corrupts data instead of erroring), or it is hard to roll back.
**Demote** one level when: it is behind a feature flag that is off, only reachable by trusted
operators, or an L1 prototype.

## Confirmed vs potential

| | Confirmed | Potential |
|---|---|---|
| Meaning | You traced input → vulnerable line → impact end to end | One link depends on something you could not see |
| Required | The scenario, step by step | The scenario **and** the exact unknown ("depends on whether the gateway strips this header") |
| Recommendation weight | Full | Counts toward the verdict only through *Questions before approval* |

Never present a potential finding as confirmed to make the review look stronger.

## Types: bug, risk, trade-off, preference

| Ask | If yes |
|---|---|
| Does it produce wrong behaviour under a scenario I can describe today? | **Bug** |
| Does it fail under a specific, likely future condition I can name? | **Risk** |
| Is it a reasonable choice whose cost the author should knowingly accept? | **Trade-off** — state both sides |
| Would another senior reasonably write it the author's way? | **Preference** — do not report |

## The false-positive table

Check these before writing a finding. Each is a common way reviewers — human and AI — report bugs
that are not there.

| Looks like | Why it may not be | How to check |
|---|---|---|
| Missing input validation | A schema, framework, or middleware validates earlier | Trace the request from the router; check Pydantic/Zod/Bean Validation models |
| SQL injection | The value is a bound parameter, or comes from a constant/enum | Read the actual query call and where the value originates |
| XSS | The template engine auto-escapes | Check for `|safe`, `dangerouslySetInnerHTML`, `v-html`, `th:utext` |
| Missing auth check | A router-level dependency, decorator, or gateway enforces it | Check router/app-level dependencies and middleware registration |
| Mutable default argument | Pydantic and dataclass `field(default_factory)` copy defaults | Check whether the class is a Pydantic model or uses `default_factory` |
| Unhandled exception | A global exception handler maps it deliberately | Look for exception handlers / `@ControllerAdvice` / error middleware |
| Race condition | A unique constraint, row lock, or single-worker design prevents it | Check the schema, `SELECT … FOR UPDATE`, and the deployment model |
| N+1 query | Relations are eager-loaded or batched by the ORM | Check `selectinload`, `@EntityGraph`, `include`, DataLoader |
| Missing timeout | The client is constructed with a default timeout elsewhere | Find where the client is created |
| Unused code | Used by reflection, a decorator registry, a CLI, or another service | Grep the whole repo and config, not just the module |
| "Should be async" | It runs in a worker thread already (e.g. FastAPI sync `def` endpoints) | Check how the framework executes it |
| Pre-existing pattern | The issue existed before this change | `git blame` / compare with the base version |

When a check is inconclusive, report it as **Potential** with the unknown named, or as a question.
