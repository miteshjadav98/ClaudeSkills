# System Design Reference

Original quick-reference notes for architecture and design decisions. Use this to pick patterns and sanity-check tradeoffs — not as a script to recite.

## Contents

1. Back-of-envelope estimation
2. Caching
3. Load balancing
4. Database selection
5. API design (REST vs GraphQL vs gRPC)
6. Messaging & event-driven patterns
7. Scalability patterns
8. Resilience & disaster recovery
9. Observability
10. Security checklist

---

## 1. Back-of-envelope estimation

Before designing, size the problem:

- **QPS**: daily active users × actions/user/day ÷ 86,400. Peak ≈ 2–5× average.
- **Storage**: records/day × record size × retention days. Add ~30% overhead for indexes/replication.
- **Bandwidth**: QPS × payload size.
- Useful anchors: 1M requests/day ≈ 12 QPS average. A single Postgres instance comfortably handles low thousands of simple QPS; Redis handles ~100K ops/s per node.

If the numbers fit on one well-provisioned database and a couple of app servers, don't design for planet scale.

## 2. Caching

**Strategies:**
- *Cache-aside* (app reads cache, on miss reads DB and populates) — default choice; simple, tolerates cache failure.
- *Read-through / write-through* — cache library owns the DB interaction; consistent but couples you to the cache layer.
- *Write-behind* — buffer writes in cache, flush async; fast but risks data loss on crash.

**Where things go wrong (design for these):**
- *Stampede / thundering herd*: hot key expires, thousands of requests hit the DB simultaneously. Mitigate with request coalescing (single-flight), jittered TTLs, or serving stale while revalidating.
- *Hot key*: one key takes disproportionate traffic. Mitigate with local (in-process) caching in front of Redis, or key replication with random suffix fan-out.
- *Large key*: multi-MB values block the Redis event loop. Split or compress.
- *Inconsistency*: cache and DB diverge. Prefer "update DB, then delete cache key" over updating both; accept eventual consistency or use short TTLs.
- *Cold start*: fresh deploy with empty cache can take down the DB. Warm critical keys before cutover.

**TTL guidance:** short TTL + cache-aside covers most cases. Explicit invalidation only where staleness is genuinely unacceptable.

## 3. Load balancing

**Algorithms:**
- *Round robin* — default when backends are homogeneous and requests are uniform.
- *Weighted round robin* — heterogeneous instance sizes.
- *Least connections* — long-lived or highly variable request durations (websockets, LLM streaming).
- *IP/consistent hash* — session affinity or cache locality (route same user to same node).
- *Least response time* — latency-sensitive fleets with uneven performance.

**Layers:** L4 (TCP) is faster and protocol-agnostic; L7 (HTTP) enables path routing, header-based routing, TLS termination, and WAF integration. Azure equivalents: Load Balancer (L4), Application Gateway (L7, with WAF).

**Checklist:** health checks with sensible thresholds, connection draining on deploys, timeouts shorter at the edge than at the origin.

## 4. Database selection

- **Relational (PostgreSQL)** — default. Transactions, joins, constraints, mature tooling. Scale reads with replicas; scale writes with partitioning before reaching for sharding.
- **Document (MongoDB)** — flexible/nested schemas, aggregate-oriented access where a document is the unit of work.
- **Key-value (Redis)** — caching, sessions, rate limiting, queues (with care), leaderboards.
- **Wide-column (Cassandra)** — very high write throughput, known query patterns, multi-region.
- **Search (Elasticsearch / Azure AI Search)** — full-text, faceting, vector + hybrid retrieval.
- **Vector (FAISS, pgvector, Azure AI Search)** — embedding similarity for RAG. Prefer pgvector or a managed service when data already lives in Postgres/Azure; standalone FAISS for local/offline pipelines.

**Rules of thumb:** don't introduce a second database to solve a problem an index would fix. Model around query patterns, not entities. Sharding is a last resort — it taxes every future feature.

## 5. API design

- **REST** — default for CRUD-ish resources and public APIs. Nouns for resources, verbs via methods, plural collection names, versioning in the path (`/v1/`), pagination via cursor for large sets, idempotency keys for unsafe retries.
- **GraphQL** — many client shapes over the same data (mobile + web + partners), read-heavy aggregation. Costs: N+1 resolution (needs dataloaders), caching complexity, query cost control.
- **gRPC** — service-to-service, low latency, streaming, strongly typed contracts. Costs: browser support requires a proxy; harder debugging.
- **Webhooks** — push events to consumers; sign payloads, retry with backoff, make handlers idempotent.

**Every API:** authentication, authorization per resource, input validation at the boundary (Pydantic / class-validator), rate limiting, consistent error envelope, request IDs propagated in headers.

## 6. Messaging & event-driven patterns

- **Queue (point-to-point)** — work distribution: one consumer processes each message. Azure Service Bus queue, BullMQ.
- **Pub/sub (fan-out)** — multiple independent consumers per event. Service Bus topics, Redis pub/sub (ephemeral only), Event Grid.
- **Log (Kafka / Event Hubs)** — replayable ordered stream; use for event sourcing, analytics pipelines, high-throughput ingestion.

**Non-negotiables:** consumers must be idempotent (at-least-once delivery is the norm); dead-letter queues with alerting; poison-message handling; outbox pattern when a DB write and an event publish must succeed together.

**Event sourcing** — store state changes as an append-only event log; derive current state by replay or projections. Powerful for audit and temporal queries; expensive in complexity. Use only when the audit/replay requirement is real.

## 7. Scalability patterns

- Stateless app tier first — state lives in DB/cache, enabling horizontal scaling.
- Async everything that isn't user-facing: queues for email, indexing, embeddings generation.
- Read replicas before caching complex query results; caching before sharding.
- CDN for static assets and cacheable GETs.
- Backpressure: rate limits at the edge, bounded queues, load shedding beats cascading failure.
- For LLM workloads specifically: token streaming to cut perceived latency, semantic caching of frequent queries, batch embedding jobs, model tiering (small model for routing/classification, large model only where needed).

## 8. Resilience & disaster recovery

**In-process resilience:** timeouts on every outbound call, retries with exponential backoff + jitter (only on idempotent operations), circuit breakers around flaky dependencies, bulkheads to isolate resource pools.

**DR strategies, cheapest to most expensive:**
1. *Backup & restore* — hours of RTO; fine for internal tools.
2. *Pilot light* — core data replicated, minimal infra idle in second region.
3. *Warm standby* — scaled-down full copy running; minutes of RTO.
4. *Active-active* — full traffic in multiple regions; near-zero RTO, highest cost and complexity (conflict resolution).

Decide from stated RTO/RPO requirements — don't buy more DR than the business needs. Test restores; an untested backup is a hope, not a plan.

## 9. Observability

Three pillars, in order of importance for debugging production:

1. **Structured logs** — JSON, request ID on every line, no secrets/PII. Log decisions and errors, not noise.
2. **Metrics** — RED for services (Rate, Errors, Duration) and USE for resources (Utilization, Saturation, Errors). Alert on symptoms (error rate, p99 latency), not causes (CPU).
3. **Traces** — distributed tracing (OpenTelemetry) when more than two services participate in a request.

For LLM systems add: token usage per request, cost per conversation, tool-call success rates, retrieval hit quality, and eval scores tracked over time.

## 10. Security checklist

- Secrets in a vault (Azure Key Vault), never in code or env files committed to git.
- AuthN via a managed identity provider (Entra ID); short-lived tokens; validate JWTs server-side.
- AuthZ enforced per resource in the service layer, not just the gateway.
- Input validation at every boundary; parameterized queries only.
- TLS everywhere; WAF (Azure App Gateway) in front of public endpoints.
- Least-privilege service identities (managed identities over connection strings).
- Dependency scanning in CI; pin versions.
- For LLM apps: prompt injection defenses (tool allow-lists, output validation, never execute model output blindly), PII scrubbing before sending to model APIs, per-user rate/cost limits.
