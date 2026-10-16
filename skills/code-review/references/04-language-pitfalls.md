# Language and Framework Pitfalls

Traps that recur in review, grouped by stack. Each is a *signal to look closer*, not an automatic
finding — it still has to pass the evidence gate.

---

## Python

| Pitfall | Why it bites |
|---|---|
| Mutable default arguments on plain functions (`def f(x=[])`) | Shared across calls. (Not a bug on Pydantic models or `default_factory`.) |
| `except Exception: pass` / bare `except:` | Hides real failures; bare `except` also catches `KeyboardInterrupt` and `SystemExit` |
| f-strings or `%` in SQL | Injection; use bound parameters |
| `requests`, `time.sleep`, sync DB drivers inside `async def` | Blocks the event loop for every request |
| Fire-and-forget `asyncio.create_task(...)` with no reference kept | Task can be garbage-collected mid-flight; exceptions are lost |
| `asyncio.gather` without `return_exceptions` or handling | One failure cancels the rest's results silently from the caller's view |
| Naive vs aware `datetime` comparisons; `datetime.utcnow()` | `TypeError` at runtime or silent off-by-timezone bugs |
| `yaml.load`, `pickle.loads` on untrusted input | Arbitrary code execution |
| Module-level clients / globals holding per-request state | Leaks data between requests and users |
| Pydantic v1 vs v2 APIs mixed (`.dict()` vs `.model_dump()`) | Deprecation warnings today, breakage on upgrade |

### FastAPI

- `async def` endpoint doing blocking work → blocks the loop. A plain `def` endpoint runs in a
  thread pool and is fine for blocking calls.
- Dependencies (`Depends`) are the codebase's injection mechanism — clients built inline in a
  handler bypass it and are hard to test.
- `BackgroundTasks` run in-process after the response — not durable; lost on restart or crash.
- Response models: returning ORM objects without a response model can leak fields.

## TypeScript / Node.js

| Pitfall | Why it bites |
|---|---|
| Missing `await` | The promise is never awaited; errors become unhandled rejections; tests pass falsely |
| `array.forEach(async …)` | Does not wait; use `for…of` or `Promise.all` |
| Async errors in Express 4 handlers without `next(err)` or a wrapper | Request hangs or process crashes |
| `any`, non-null assertions (`!`), unchecked `as` casts at boundaries | Type safety ends exactly where untrusted data enters |
| `==` vs `===`; truthiness checks on `0` and `""` | Valid values treated as missing |
| CPU-heavy work (big JSON, sync crypto, regex on large input) on the main thread | Blocks every request |
| `JSON.parse` on external input without try/catch and validation | Crash or prototype pollution with unsafe merges |
| Environment read at import time vs runtime | Config set after import is ignored |

## Java / Spring

| Pitfall | Why it bites |
|---|---|
| `@Transactional` on a method called from the same class | Self-invocation bypasses the proxy — no transaction |
| `@Transactional` on private methods | Ignored |
| Lazy JPA relations accessed in a loop or in serialisation | N+1 queries; `LazyInitializationException` outside the session |
| `Optional.get()` without `isPresent` | `NoSuchElementException` |
| `equals` without `hashCode` (or JPA entities using generated IDs in either) | Broken sets and maps |
| Field injection (`@Autowired` on fields) in new code where the codebase uses constructor injection | Inconsistent DI, harder tests |
| `@Async` without a configured executor | Unbounded default executor or same-thread surprises |
| Catching `Exception` and wrapping without the cause | Lost stack traces |
| Mutating a collection while iterating | `ConcurrentModificationException` |
| Shared `SimpleDateFormat` | Not thread-safe |

## SQL and migrations

- Adding a `NOT NULL` column without a default to a large table — long lock or failure.
- Creating an index without `CONCURRENTLY` (Postgres) on a hot table — blocks writes.
- Dropping or renaming a column the currently deployed code still reads — deploy-order outage.
  Safe pattern: expand (add new) → migrate code → contract (remove old) across releases.
- Data migrations without batching; no rollback script.
- `SELECT *` in application queries that then break when columns are added.
- Missing index for a new query's `WHERE` / `JOIN` / `ORDER BY` on a large table.

## Containers, config, and CI

- Secrets baked into images, build args, or committed `.env` files.
- Containers running as root without need; `latest` tags in production manifests.
- New environment variables missing from deploy manifests, `.env.example`, or Terraform.
- CI steps that skip tests or swallow failures (`|| true`).
- Health checks that only test that the process is up, not that dependencies are reachable —
  or the reverse, readiness checks that fail the whole fleet when one dependency blips.
