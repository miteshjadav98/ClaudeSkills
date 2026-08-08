# Trade-offs and Checklists

> If you don't know trade-offs, you don't know system design.
> Everything is a trade-off. Everything is a compromise. There is no right or wrong design.

Every design choice loses something. A recommendation with no named downside has not been thought
about.

---

## 1. The ten trade-offs you cannot ignore

### 1. Vertical vs horizontal scaling

**Vertical** — add resources (CPU, RAM) to an existing server.
*Gains:* simplicity, no code change, no distribution, immediate.
*Loses:* a hard ceiling, a single point of failure, a very expensive top end.

**Horizontal** — add more servers to the pool.
*Gains:* elasticity, fault tolerance, no ceiling.
*Loses:* requires statelessness, adds coordination and network failure modes.

**In practice:** scale vertically until it stops being cheap, then horizontally. Vertical scaling is
not defeat; at L2 it is usually the highest-leverage move available.

### 2. SQL vs NoSQL

**SQL** organises data into tables of rows and columns.
*Gains:* transactions, joins, constraints, mature tooling, ad-hoc queries.
*Loses:* rigid schema, harder write scaling.

**NoSQL** is ideal for applications needing a flexible schema.
*Gains:* flexible schema, write throughput, easy partitioning.
*Loses:* no joins, weak transactions, **query patterns locked in at design time**.

**The decisive question:** do you know all your queries now? If not, SQL, because it forgives being
wrong.

### 3. Batch vs stream processing

**Batch** — collect data and process it all at once (daily billing).
*Gains:* throughput, simplicity, trivial retry, easy reasoning.
*Loses:* latency measured in hours.

**Stream** — process in real time (fraud detection).
*Gains:* freshness.
*Loses:* operational complexity, late and out-of-order events, harder correctness.

### 4. Normalization vs denormalization

**Normalization** splits data into related tables so each fact is stored once.
*Gains:* one source of truth, cheap writes, no update anomalies.
*Loses:* expensive joins on read.

**Denormalization** combines data into fewer tables for query performance.
*Gains:* fast reads.
*Loses:* write amplification, update anomalies, more storage.

### 5. Consistency vs availability

**Consistency** — the assurance of getting the most recent data every time.
**Availability** — the system is always up and running, even when parts are having problems.

Under a network partition you get one. Decide **per operation**, not per system: a bank balance
needs consistency, a like count does not.

### 6. Strong vs eventual consistency

**Strong** — updates are immediately reflected everywhere.
*Loses:* latency, and availability under partition.

**Eventual** — updates are delayed before being available across nodes.
*Loses:* the application must handle stale reads, and the UI must be designed for it.

### 7. REST vs GraphQL

**REST** — gather data by accessing multiple endpoints.
*Gains:* simple, cacheable, universal tooling.
*Loses:* over/under-fetching, multiple round trips.

**GraphQL** — more efficient data fetching with specific queries, **but the design cost is higher**.
*Gains:* exact payloads, one round trip, strong schema.
*Loses:* caching complexity, N+1 resolvers, query-cost abuse if unguarded.

### 8. Stateful vs stateless

**Stateful** — remembers past interactions.
*Gains:* locality, lower latency, simpler protocols.
*Loses:* sticky routing, hard failover, hard rebalancing.

**Stateless** — keeps no track of past interactions.
*Gains:* trivial horizontal scaling and failover.
*Loses:* state must live somewhere else — and that somewhere becomes the bottleneck.

### 9. Read-through vs write-through cache

**Read-through** — loads from the database on a cache miss.
*Loses:* cold-start penalty; the first request always pays.

**Write-through** — writes to cache and storage simultaneously.
*Gains:* the cache is never stale.
*Loses:* every write pays cache latency.

### 10. Sync vs async processing

**Synchronous** — tasks performed one after another.
*Gains:* simple reasoning, immediate errors, easy debugging.
*Loses:* coupling, latency accumulates, cascading failure.

**Asynchronous** — tasks run in the background; new tasks start without waiting.
*Gains:* decoupling, absorbs spikes, better resource use.
*Loses:* eventual consistency, harder debugging, requires idempotency.

---

## 2. The five higher-order tensions

Name these explicitly in a design document — they are the ones stakeholders actually care about:

- **Cost vs performance**
- **Reliability vs scalability**
- **Performance vs consistency**
- **Security vs flexibility**
- **Development speed vs quality**

---

## 3. Additional trade-offs worth naming

| Choice | Gains | Loses |
|---|---|---|
| **Monolith** | Transactions, refactoring, one deploy | Coupled releases, one scaling profile |
| **Microservices** | Independent deploy and scale, fault isolation | Distributed everything; nine platform components to own |
| **Sharding** | Write scale, unbounded growth | No cross-shard joins or transactions; shard key is permanent |
| **Multi-region active-active** | Near-zero RTO, low global latency | Conflict resolution, doubled cost, hardest ops |
| **Write-behind cache** | Fast writes | Data loss window on crash |
| **Serverless** | No ops, scale to zero, spiky-workload economics | Cold starts, time limits, lock-in, cost at sustained load |
| **Orchestration** | The process is readable in one place | The coordinator is coupled to everyone |
| **Choreography** | Minimal coupling; teams add reactions freely | The process exists nowhere readable |
| **Event sourcing** | Perfect audit, temporal queries, replay | Permanent event schema, slow replays, cognitive load |
| **CQRS** | Independent read/write scaling | Two models, a projection pipeline, eventually consistent reads |

---

## 4. Fifteen-point design checklist

For a full design or design review:

1. **Requirement gathering** — functional and non-functional; what is explicitly out of scope
2. **System architecture** — components and the request path
3. **Data design** — schema, access patterns, store selection
4. **Domain design** — boundaries, ownership, ubiquitous language
5. **Scalability** — where the first bottleneck is and what you do about it
6. **Reliability** — does it consistently produce correct results
7. **Availability** — target, redundancy topology, failover
8. **Performance** — latency budget for the critical path
9. **Security** — authn, authz, encryption, secrets, data protection
10. **Maintainability** — can another team change this in a year
11. **Testing** — unit, integration, load, error, automation
12. **User experience design** — including degraded-mode behaviour
13. **Cost estimation** — infrastructure and operational
14. **Documentation** — the design record and the runbooks
15. **Migration plan** — how you get from today to this design

**Migration plan is the most commonly missing item**, and the one that determines whether a design
ever actually ships.

---

## 5. System Design Blueprint — the discussion checklist

The topics a complete design should have an answer for, even if the answer is "not needed":

**Edge** — DNS resolution · CDN and edge caching · load balancing · API gateway (input validation,
authn/authz, rate limiting and throttling, TLS termination, request deduplication, metering)

**Communication protocols** — REST · GraphQL · gRPC · WebSocket · SSE · webhooks · HTTP long polling ·
RTMP/WebRTC for media

**Services to scale the system** — distributed ID generation (UUID, auto-increment, Twitter
Snowflake, offline generation, Redis UID generator) · distributed resource locking (Redis Redlock,
Google Chubby, Apache Zookeeper)

**Cache** — eviction policy · write policy · hit/miss metrics · memory sizing · invalidation strategy

**Database** — engine type · sharding strategy · replication and quorum · consistent hashing ·
bloom filters · RBAC, encryption, audit trail

**Async paths** — message queues · job workers · fan-out services (log processing, search indexing,
analytics, notifications, recommendations, payment charging **with an idempotency key**)

**Cross-cutting** — scalability · availability · performance · security · fault tolerance and
resilience · observability · cost

---

## 6. High availability, throughput, and scalability — the three asks decoded

When someone says "design for high availability, high scalability, and high throughput", these are
the three distinct things they mean:

### High availability

*Ensure a high agreed level of uptime.* Targets are described as "3 nines" or "4 nines" —
99.99% means the service can be down only **8.64 seconds per day**; 99.999% means **864 milliseconds**.

*Principles:* redundancy, no single point of failure.
*Solutions:* hot-hot · hot-warm · single-leader cluster · leaderless cluster.
*Measurements:* uptime percentage, RTO, RPO.

### High throughput

*Handle a high number of requests in a given period.* Measured as **QPS** (queries per second) or
**TPS** (transactions per second).

*Principles:* caching · identify bottlenecks · more threads and instances · spike management.
*Solutions:* add caches and a CDN so requests return without hitting slower I/O; increase threads for
computation-intensive tasks — **but too many threads deteriorates performance**; use asynchronous
processing to isolate heavy-lifting components.

### High scalability

*Quickly and easily extend to accommodate more volume (horizontal) or more functionality (vertical).*
Normally you watch **response time** to decide whether to scale.

*Principles:* segregation of service responsibilities · load balancing and service discovery ·
capacity planning.
*Solutions:* microservices with an API gateway and service registry.

---

## 7. Design review questions

Ask these of any design, including your own:

**On sizing**
- What level is this, and what numbers say so?
- What breaks first if traffic goes 10×? How would we know?
- Which components exist only for a scale we do not have?

**On data**
- What are the access patterns, and were they written down before the store was chosen?
- Where is the source of truth for each entity?
- What is the acceptable staleness for each cached or replicated read?

**On failure**
- What happens when each dependency is down? Is that behaviour designed or accidental?
- Which operations are retried, and are they idempotent?
- What is the blast radius of the worst single failure?

**On operations**
- How is this deployed and rolled back? Has the rollback been rehearsed?
- What is the alert that fires first when this breaks, and who owns it?
- What does this cost per month, and what drives that number?

**On the future**
- What are we deliberately not doing yet, and what triggers each decision?
- What is the hardest thing to change later, and are we sure about it?

That last question is the shard key, the API contract, and the data model — the three decisions that
outlive everything else.

---

## 8. Anti-patterns

| Anti-pattern | What it looks like | The fix |
|---|---|---|
| **Resume-driven design** | Kafka, K8s, and microservices for 400 users | Size the problem first |
| **Distributed monolith** | Microservices sharing one database, deployed together | Merge them back, or give each its own data |
| **Premature sharding** | Sharding before indexes, caching, or replicas | Climb the ladder in order |
| **The abstraction that awaits a second implementation** | An interface with one implementor "for flexibility" | Delete it; add it when the second arrives |
| **Alert on causes** | Paging on CPU, memory, disk | Alert on error rate and p99 latency |
| **Retry without jitter or breaker** | Exponential backoff, synchronised across all clients | Add jitter; add a circuit breaker |
| **Untested backups** | A backup job that has never been restored | Restore one, on a schedule |
| **The unversioned public API** | Breaking changes shipped to live clients | Version before launch |
| **Cache without a stampede plan** | Uniform TTLs, no single-flight, no null caching | See `07-caching.md` §4 |
| **Auth at the gateway only** | Service-layer code assumes the caller is authorised | Enforce per-resource in the service |
| **Design without a migration plan** | A beautiful target architecture nobody can reach | Write the steps from today to there |

---

## 9. Recommended reading

**Software architecture** — *Designing Data-Intensive Applications* (Martin Kleppmann) ·
*System Design Interview* Vols 1–2 (Alex Xu, Sahn Lam)

**General practice** — *The Pragmatic Programmer* · *Code Complete* (McConnell)

**Coding** — *Clean Code* (Robert Martin) · *Refactoring* (Martin Fowler)

**Design patterns** — *Design Patterns* (Gamma et al.) · *Domain-Driven Design* (Eric Evans)

**Foundational papers** — Dynamo (Amazon's highly available key-value store) · Google File System ·
Scaling Memcached at Facebook · BigTable · Borg · Cassandra · Kafka · Amazon Aurora · Spanner ·
MapReduce · Shard Manager · Dapper (distributed tracing) · Flink · Zanzibar (global ACLs) ·
Monarch · Raft · *Time, Clocks, and the Ordering of Events in a Distributed System* (Lamport) ·
*Attention Is All You Need*

**Engineering blogs** — Netflix TechBlog · Uber · Cloudflare · Engineering at Meta ·
LinkedIn Engineering · Discord · AWS Architecture · Slack Engineering · Stripe
