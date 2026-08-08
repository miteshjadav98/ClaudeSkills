---
name: system-design
description: Tiered system-design handbook that first sizes a problem into one of three levels — L1 mini POC/prototype, L2 mid-size production (modular monolith or microservices), L3 hyperscale (millions to billions of requests, Amazon/Netflix-class) — then applies only the patterns that level earns. Use whenever the task is designing a system or service, choosing an architecture or architectural style, estimating capacity, picking a database/cache/queue/API style, deciding monolith vs microservices, planning how to scale, sharding or partitioning data, hardening for failure, or preparing/reviewing a system design or design document. Also use when reviewing an existing architecture for over- or under-engineering.
---

# System Design

Most bad architecture is not wrong — it is **the right design for the wrong level**. A sharded,
event-sourced, multi-region microservice fleet is excellent engineering and a catastrophic choice
for a product with 400 users. A single Postgres box is excellent engineering and a catastrophic
choice at a million writes a second.

So the first move in any design task is never "what pattern?" It is **"what level is this?"**

Stack Overflow serves its entire global traffic from a monolith on nine on-premise web servers. If a
design cannot justify itself against that benchmark, it is over-built.

---

## Step 0 — Size the problem before designing it

Ask, or infer and then state the assumption:

1. **Users / requests** — DAU, peak QPS, read:write ratio
2. **Data** — total volume, growth rate, largest single object
3. **Latency budget** — p99 target for the critical path
4. **Availability target** — and what an hour of downtime actually costs
5. **Team** — how many engineers, how many teams
6. **Horizon** — is this alive in 3 months or 3 years?

Run the arithmetic (`references/04-estimation-and-numbers.md`), then place it:

| | **L1 — Prototype / POC** | **L2 — Production, mid-size** | **L3 — Hyperscale** |
|---|---|---|---|
| Users | < ~1K | ~1K – 1M | > ~10M |
| Peak QPS | < ~10 | ~10 – 5,000 | > ~10,000 sustained |
| Data | fits on one disk | ~GB – low TB | TB – PB |
| Availability | best effort | 99.9% (~43 min/mo) | 99.99%+ (8.64 s/day) |
| Team | 1–3 engineers | 3–50, a few teams | 50+, many teams |
| Downtime costs | an apology | money | headlines |
| Optimise for | **learning speed** | **reliability + team velocity** | **scale + org scale** |
| Default shape | one deployable, one DB | modular monolith + managed services | sharded, partitioned, multi-region |

Then design from the matching reference:
`references/01-level-1-poc.md` · `references/02-level-2-production.md` ·
`references/03-level-3-hyperscale.md`

### Judgement calls that matter more than the table

- **Mixed levels are normal and correct.** A company can be L3 on read traffic and L1 on its admin
  panel. Level the *component*, not the company — and say so explicitly when it happens.
- **Round down, not up.** If a system sits between two levels, design for the lower one and write
  down the specific trigger that promotes it. Under-engineering is a bug you fix in a sprint;
  over-engineering is a tax you pay every sprint forever.
- **Non-functional requirements can promote a level on their own.** A payments ledger at 5 QPS is not
  L1 — regulatory audit, exactly-once semantics, and RPO≈0 pull it up. Correctness and compliance
  outrank traffic.

---

## The design spine (all levels; depth varies)

Run this order every time. What changes by level is how much each step gets, never whether it happens.

1. **Requirements** — functional, then non-functional (latency, availability, consistency,
   durability, compliance). Name what is explicitly *out* of scope.
2. **Estimation** — back-of-envelope QPS, storage, bandwidth. One line each. This selects the level,
   so do it before drawing anything. → `04-estimation-and-numbers.md`
3. **API / contract** — entry points, shapes, idempotency, pagination, versioning, errors.
   → `08-api-design.md`
4. **Data model** — entities, **access patterns first**, then the store choice. Model around
   queries, not entities. → `06-data-layer.md`
5. **Architecture** — components and the request path. Draw it in Mermaid. Keep the happy path on one
   screen. → `05-architecture-patterns.md`
6. **Scale plan** — where the first bottleneck appears, what you do when it does, and the metric that
   tells you. → `06-data-layer.md` §12, `07-caching.md`
7. **Failure plan** — what breaks, blast radius, degradation behaviour, recovery.
   → `10-reliability-and-failure.md`
8. **Operations** — deploy, rollback, observability, cost, on-call surface.
   → `12-operations-and-delivery.md`

Collapse steps that add nothing for the task at hand, but **never silently skip 6 and 7** — an
unexamined bottleneck and an unexamined failure are the two things that actually hurt in production.

---

## Rules that override pattern enthusiasm

- **Every component must justify its existence in one sentence.** If the sentence is "we might need
  it later", delete the component and write down the trigger instead.
- **Prefer boring.** Postgres, a cache, a queue, and one well-run deployment target solve a startling
  share of problems. Postgres now covers time-series, vector, geospatial, search, and OLAP — reach
  for a second datastore only when a real access pattern demands it.
- **The escalation order is fixed.** Index → fix N+1 → materialised view → denormalise → vertical
  scale → cache → read replicas → pooling → partition → **only then** shard. Skipping to sharding
  taxes every future feature.
- **Cache before shard, async before scale-up, replicate before partition.**
- **Distribution is a cost, not a feature.** Every network hop adds a failure mode, a timeout, a
  retry, and an idempotency requirement. Microservices solve a *team* problem far more often than a
  *scale* problem.
- **State the trade-off out loud.** Every design choice loses something. A recommendation with no
  named downside has not been thought about. → `15-tradeoffs-and-checklists.md`
- **Measure before you architect.** Pinterest cut clone times 99% — 40 minutes to 30 seconds — with
  one missing git refspec flag. That is the most common shape of a real performance problem.

---

## Output format

Structure a design as:

1. **Level & sizing** — the level, the numbers behind it, assumptions made
2. **Requirements** — functional / non-functional / out of scope
3. **Estimation** — QPS, storage, bandwidth
4. **Design** — API, data model, architecture diagram (Mermaid), request walkthrough
5. **Trade-offs** — what was chosen over what, and what it costs
6. **Scale & failure plan** — first bottleneck, degradation behaviour, recovery
7. **Operations** — deploy, observe, roll back, cost
8. **What we are deliberately not doing yet** — and the trigger that changes each answer

Section 8 is the one people skip and the one that ages best. It is what stops the next engineer from
adding Kafka in month two.

**For a design review** rather than a new design, keep the same spine but lead with the level
assessment, and flag every component that belongs to a different level than the system is at — in
both directions. Over-engineering and under-engineering are both findings.

---

## References

| File | Use it for |
|---|---|
| `references/01-level-1-poc.md` | Prototypes, POCs, internal tools, demos, MVPs; the L1→L2 migration |
| `references/02-level-2-production.md` | Real production systems; monolith vs microservices; the scaling ladder |
| `references/03-level-3-hyperscale.md` | Sharding, CQRS, multi-region, cells, federated graphs, org architecture |
| `references/04-estimation-and-numbers.md` | Back-of-envelope method, latency numbers, availability math, a worked example |
| `references/05-architecture-patterns.md` | The full style catalogue — layered, hexagonal, microkernel, microservices, space-based, event-driven, orchestration vs choreography, CQRS, event sourcing, MVC family |
| `references/06-data-layer.md` | Database selection, data models, storage engines, ACID/CAP, locks and deadlocks, replication, sharding, CDC, the scaling ladder |
| `references/07-caching.md` | Where caches live, strategies, eviction policies, **the four ways caches go wrong**, semantic caching |
| `references/08-api-design.md` | REST/GraphQL/gRPC/WebSocket/webhooks, pagination, idempotency, auth, JWT vs session, OAuth flows, HTTP/2, API testing |
| `references/09-messaging-and-events.md` | Queues vs pub/sub vs log, the six cloud messaging patterns, saga, outbox, Kafka internals and message loss, retry strategies, data pipelines |
| `references/10-reliability-and-failure.md` | The Fantastic Four, availability math, fault tolerance, circuit breakers, heartbeats, DR, observability, diagnosing production |
| `references/11-security.md` | The 12-domain checklist, sensitive data, encoding vs encryption vs tokenization, passwords, XSS, TLS, DevSecOps, LLM security |
| `references/12-operations-and-delivery.md` | 12-Factor, CI/CD, GitOps, Docker, Kubernetes and its 10 patterns, cost reduction, SDLC models, diagramming |
| `references/13-worked-designs.md` | Full walkthroughs: YouTube, live streaming, push notifications, search, ChatGPT, payments, URL-to-render, OSI |
| `references/14-case-studies.md` | How Discord, Figma, Reddit, Netflix, Stack Overflow, Pinterest, and Redis actually scaled |
| `references/15-tradeoffs-and-checklists.md` | The ten trade-offs, design checklists, review questions, anti-patterns, reading list |

Source material distilled from the ByteByteGo / Alex Xu system-design collection, re-organised by
scale tier and annotated with the escalation triggers between tiers.
