# Review Checklist — the eleven passes

Each pass lists what to look for and the one question a senior asks. Do not tick every box on
every change — the level (L1/L2/L3) and what the diff touches decide which passes get depth.
A box ticked is not a finding; a finding still has to pass the evidence gate in `SKILL.md`.

---

## 1. Correctness

**Senior question:** *What input, timing, or state makes this produce the wrong answer?*

- **Boundaries:** empty collections, zero, negative numbers, max values, single element,
  off-by-one in ranges, slices, and pagination.
- **Null / None / undefined:** optional fields, missing dictionary keys, lookups that return
  nothing, `Optional.get()` without a check.
- **Wrong assumptions:** "this list is always sorted", "this ID always exists", "this runs once",
  "this string is ASCII", "this timestamp is UTC".
- **Changed semantics:** a function that used to return `None` now raises (or the reverse); a
  default flipped; a boolean inverted; a filter widened.
- **Concurrency:** check-then-act races (read, decide, write without a lock or a conditional
  update); shared mutable state across requests; non-atomic counters; two requests creating the
  same row.
- **Time:** time zones, daylight saving, clock skew between services, comparing naive and aware
  datetimes, using wall-clock time for durations.
- **Money and numbers:** floats for currency, integer overflow, rounding direction, unit mismatches
  (ms vs s, paise vs rupees).
- **Removed guards:** a deleted `if`, ownership check, transaction, or lock. Read every red line in
  the diff as carefully as the green ones.

## 2. Security

**Senior question:** *Who can reach this code, with what input, and what can they make it do?*

- **Injection:** SQL, NoSQL, shell, LDAP, template, path traversal, and **prompt injection** — any
  place untrusted input is concatenated into something that gets interpreted.
- **Authentication:** new endpoints, handlers, or queues without the auth dependency the rest of
  the codebase uses.
- **Authorization / IDOR:** the user is logged in, but is this *their* record? Every lookup by an ID
  from the request needs an ownership or tenant check.
- **Secrets:** keys, tokens, or passwords in code, config, tests, logs, error messages, or client
  bundles. Never print the value in the review.
- **Unsafe input handling:** unvalidated file uploads, unbounded sizes, deserialising untrusted data
  (`pickle`, Java serialisation, `yaml.load`), SSRF via user-supplied URLs, open redirects.
- **Sensitive data exposure:** PII, tokens, or full prompts in logs or analytics; verbose errors
  returned to clients; stack traces in responses.
- **Crypto and sessions:** home-made crypto, weak hashing for passwords, missing CSRF protection on
  cookie-authenticated mutations, overly broad CORS.
- **Dependencies:** new packages — maintained? necessary? from the expected publisher?

## 3. Data and API contracts

**Senior question:** *What breaks for whoever consumes this — clients, other services, old data?*

- **Breaking changes:** renamed or removed fields, changed types, new required fields, changed
  status codes or error shapes. Old mobile clients and other services do not upgrade in lockstep.
- **Validation:** at the boundary, once — types, ranges, lengths, formats, enums.
- **Migrations:** paired with the code; safe on a large table (no long locks, no `NOT NULL` column
  without a default on a hot table); reversible; deploy order (migrate before or after code?).
- **Transactions:** multi-step writes that must succeed or fail together; external calls inside a
  database transaction (holds locks while waiting on the network).
- **Pagination:** unbounded list endpoints; offset pagination on large, changing tables.
- **Idempotency:** retried requests, duplicated messages, and double-clicks — will they create
  duplicates or double-charge?

## 4. Error handling and resilience

**Senior question:** *When the dependency is slow, down, or returns garbage, what happens?*

- **Swallowed errors:** `except: pass`, empty `catch`, errors logged and then ignored where the
  caller needed to know.
- **Timeouts:** every network call (HTTP, database, LLM, queue) has one, and it is shorter than the
  caller's.
- **Retries:** bounded, with backoff and jitter, and only on idempotent operations and retryable
  errors. Retrying a 400 is a bug; retrying a non-idempotent POST can duplicate side effects.
- **Cleanup:** connections, files, locks, and temporary resources released on the error path
  (`with`, `try/finally`, `using`, try-with-resources).
- **Partial failure:** step two of three fails — is the system left consistent?
- **Error messages:** accurate, actionable, and free of internals and secrets.

## 5. Performance

**Senior question:** *What happens to this code at ten times today's data or traffic?*

- **N+1 queries:** a query inside a loop; lazy-loaded relations in serialisation.
- **Unbounded work:** loading a whole table, an unbounded history, or every file into memory.
- **Blocking I/O on async paths:** synchronous HTTP, file, or database calls inside `async`
  handlers stall every request on that event loop.
- **Independent work run serially:** `await a(); await b()` where `b` does not need `a`'s result
  (use `asyncio.gather` / `Promise.all` / `CompletableFuture.allOf` — *only* if latency matters on
  this path and the calls are safe to run together, e.g. not sharing one DB session or connection).
- **Locks and transactions held across slow calls:** a database transaction or mutex held while
  waiting on HTTP or an LLM blocks every other request that needs it.
- **Avoidable calls:** repeated identical network or LLM calls that could be batched or cached;
  calls made before checking whether they are needed.
- **Hot-path cost:** regex compiled per call, serialisation in tight loops, logging large objects.
- **Leaks:** caches without eviction, listeners never removed, growing global lists.

Do not flag micro-optimisations without evidence the code is on a hot path.

## 6. AI / LLM / agents

Only when the change touches them. → `02-ai-agent-review.md`

## 7. Testing

**Senior question:** *If someone breaks this behaviour next month, which test goes red?*

- The change's core behaviour and its riskiest edge case are both tested.
- Bug fixes include a test that fails without the fix.
- Tests assert behaviour, not implementation details (no asserting that a private helper was
  called three times).
- Mocks do not mock away the thing under test; mocked responses match the real shape.
- No tests that cannot fail (asserting on the mock's own return value; missing `await`; exceptions
  caught inside the test).
- Flakiness sources: real time, randomness, ordering, shared state, network.

## 8. Architecture

**Senior question:** *Does this make the next change easier or harder?*

- **Separation of concerns:** business logic in controllers, SQL in templates, HTTP details deep in
  the domain.
- **Dependency direction:** core modules importing from edges; circular imports; a shared library
  that now knows about one consumer.
- **Duplicated logic:** a second implementation of a rule that already exists — they will drift.
- **Boundaries:** one service reaching into another's database; a module bypassing the public API
  of another.
- **Consistency:** the change solves a problem differently from how the codebase already solves it,
  without a stated reason.
- **Dependency injection:** clients (DB, HTTP, LLM, cache) constructed inline or as module globals
  where the codebase injects them (FastAPI `Depends`, Spring beans, constructor injection). Inline
  construction hides the dependency, defeats test doubles, and often creates a new connection pool
  per call.
- **Runtime contracts:** the same concept returned, raised, or shaped differently on different
  paths — `None` here, an exception there; a timestamp as string in one event and epoch in another;
  an agent state key written as one type and read as another. Check both producer and every consumer.
- **Responsibility creep:** a component that now does two jobs — a router that also executes tools,
  a repository that also calls an external API, a prompt that also encodes business rules.
- **Over-engineering:** an abstraction, interface, or framework with exactly one user and no
  stated trigger for a second. (See the `system-design` skill: round down, not up.)

## 9. Observability

**Senior question:** *At 3 a.m., can on-call tell what went wrong from the logs and metrics alone?*

- Errors logged once, at the boundary, with context (request ID, entity ID) — not at every layer.
- Structured logs, not string concatenation, where the codebase uses structured logging.
- New failure modes have a metric or an alertable log.
- Trace or correlation IDs propagate across service and agent hops.
- **Nothing sensitive** — no tokens, passwords, full prompts with user data, or PII.

## 10. Configuration and deployment

**Senior question:** *Will this deploy cleanly, and can we roll it back?*

- New environment variables documented (`.env.example`, deploy config, README) with safe defaults —
  or failing fast at startup when missing, not at first use.
- Defaults are safe for production (debug off, permissive CORS off, test keys never default).
- Dependency changes: pinned, necessary, licence-compatible.
- Deploy ordering: does the code need the migration, the new queue, or the new secret to exist
  first?
- Rollback: can the previous version run against the new schema and data?
- Feature flags for risky behaviour changes on L3 paths.

## 11. Maintainability

**Senior question:** *Will the next engineer understand this without asking the author?*

- Names say what things are and do; no misleading names.
- Functions do one thing; deep nesting and long parameter lists are signals, not automatic findings.
- Types are present and honest where the codebase uses them (no `any` or `Any` escape hatches on
  new public interfaces).
- Comments explain *why*, not *what*; no stale comments contradicting the code.
- Dead code, debug prints, and commented-out blocks removed.

Most maintainability observations are P3 or Info. Raise one higher only when it is genuinely likely
to cause a bug (a name that will make the next caller misuse the function).
