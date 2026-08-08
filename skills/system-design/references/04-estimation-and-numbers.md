# Estimation and Numbers

Estimation is what selects the level. Do it before drawing anything, and write it down — a design
without numbers is an opinion.

---

## 1. The estimation procedure

### Step 1 — Traffic

```
average QPS = DAU × actions per user per day ÷ 86,400
peak QPS    = average QPS × peak factor
```

**Peak factor** — 2× for a smooth global service, 3–5× for a consumer product with a daily rhythm,
10×+ for event-driven spikes (ticket sales, launches, sports).

Also compute the **read:write ratio**. It determines almost everything downstream: a 100:1 read-heavy
system is solved with caching and replicas; a write-heavy system is not.

### Step 2 — Storage

```
storage/day   = records per day × average record size
total storage = storage/day × retention days × (1 + overhead)
```

**Overhead ≈ 30%** for indexes, then multiply by the replication factor. A 1 TB dataset with indexes
and three replicas needs roughly 4 TB provisioned.

Estimate the **largest single object** separately — it decides whether you need object storage,
chunked upload, and the claim-check pattern.

### Step 3 — Bandwidth

```
ingress = write QPS × average request size
egress  = read QPS × average response size
```

Egress is usually the expensive one, and cross-region egress is the expensive-expensive one. This
number, not compute, drives cloud bills at scale.

### Step 4 — Memory (for cache sizing)

Apply the 80/20 rule: roughly 20% of the data serves 80% of requests.

```
cache size ≈ daily active dataset × 0.2
```

Then check it against the cost of a Redis instance that size. If the working set does not fit
affordably, the caching strategy needs rethinking, not more memory.

---

## 2. Anchors worth memorising

| Anchor | Value |
|---|---|
| Seconds in a day | 86,400 (~100K) |
| Seconds in a month | ~2.6M |
| **1M requests/day** | **≈ 12 QPS average** |
| 1B requests/day | ≈ 12K QPS average |
| A well-provisioned Postgres | low thousands of simple QPS |
| Redis | ~100K ops/sec per node |
| A modern app server | thousands of concurrent connections; hundreds to low thousands of RPS depending on work per request |
| Kafka broker | hundreds of MB/s sequential write |
| 1 TB | ~1M records at 1 KB each × 1000 |

**The single most useful one is "1M requests/day ≈ 12 QPS".** It deflates most claims that a system
needs to scale. A million requests a day sounds enormous and is twelve requests a second.

---

## 3. Latency numbers every engineer should know

Based on Jeff Dean's numbers, rounded:

| Operation | Latency | Practical meaning |
|---|---|---|
| L1 cache reference | **1 ns** | Built onto the microprocessor. Only matters if you work with hardware |
| L2 cache reference | **10 ns** | Same |
| Main memory reference | **100 ns** | Reading from RAM. **Redis is in-memory, so a Redis read is ~this plus network** |
| Send 1 KB over 1 Gbps network | **10 µs** | Sending 1 KB from Memcached over the network |
| Read from SSD | **100 µs** | RocksDB is a disk-based KV store; read latency ~100 µs on SSD |
| Database insert | **1 ms** | A Postgres commit — store the data, create the index, flush logs |
| Send packet CA → Netherlands → CA | **100 ms** | A long-distance video call's round trip |
| Retry / refresh interval | **1–10 s** | Monitoring systems typically refresh every 5–10 s |

**Unit reference:** 1 ns = 10⁻⁹ s · 1 µs = 10⁻⁶ s = 1,000 ns · 1 ms = 10⁻³ s = 1,000 µs = 1,000,000 ns

### The three consequences

1. **Memory is ~1,000× faster than SSD.** This is the entire justification for caching.
2. **A cross-continent round trip is ~1,000× slower than a local disk read.** This is the entire
   justification for CDNs and multi-region deployment.
3. **A database insert is ~10,000× slower than a memory read.** This is why write paths get queues
   and read paths get caches.

Almost every performance decision is an argument about which of those tiers a piece of data lives in.

### The business anchor

Amazon measured that **every 100 ms of latency cost them 1% in sales** — roughly $5.7 billion in
today's terms. Latency is revenue. Quote this when performance work needs justification.

**Six strategies to reduce latency:** database indexing · caching · load balancing · CDN ·
async processing · data compression.

---

## 4. Availability math

| Target | Downtime/day | Downtime/month | Downtime/year |
|---|---|---|---|
| 99% ("2 nines") | 14.4 min | 7.2 h | 3.65 days |
| 99.9% ("3 nines") | 86 s | 43 min | 8.76 h |
| 99.99% ("4 nines") | **8.64 s** | 4.3 min | 52.6 min |
| 99.999% ("5 nines") | **864 ms** | 26 s | 5.26 min |

### Two consequences

**1. Above 3 nines, no human is in the recovery path.** 8.64 seconds a day does not permit paging
someone, opening a laptop, or reading a runbook. Everything must fail over automatically, and the
failover must be tested continuously.

**2. Dependencies multiply.** For services in series:

```
availability = A₁ × A₂ × ... × Aₙ
```

Five dependencies at 99.9% each → 99.5% overall (3.65 hours/month of downtime). **Every service
added to the critical path lowers availability** unless it is made optional through graceful
degradation.

For redundant components in parallel:

```
availability = 1 − (1 − A)ⁿ
```

Two 99% components in parallel → 99.99%. This is why redundancy is the primary availability lever.

### Error budgets

A 99.99% target is a budget of **8.64 seconds per day, 4.3 minutes per month**. Spend it
deliberately on releases and risky changes; when it is exhausted, feature work stops until
reliability is restored. This is what makes an availability target a real constraint rather than a
slogan.

---

## 5. Percentiles, not averages

Always specify latency as a percentile. An average hides everything that matters.

- **p50 (median)** — the typical experience
- **p95** — the experience of your least lucky 1 in 20 requests
- **p99** — the standard SLA target; the tail that generates support tickets
- **p99.9** — matters when a single page makes many requests, because a user hitting 100 resources
  will almost certainly hit the p99

**Fan-out amplifies tails.** If rendering one screen requires 20 backend calls, and each has a 1%
chance of being slow, roughly **18% of screen renders hit at least one slow call**. This is why
Netflix's LOLOMO screen — fetching from tens of microservices — became a performance problem, and
why hedged requests exist.

Set a latency budget for the critical path and divide it between components before designing them.

---

## 6. A worked example

**"Design a URL shortener."**

*Assumptions stated up front:* 100M new URLs/month, 10:1 read:write ratio, 5-year retention,
500-byte records.

**Traffic**
```
writes/day     = 100M ÷ 30 ≈ 3.3M
write QPS      = 3.3M ÷ 86,400 ≈ 40 QPS
read QPS       = 40 × 10 = 400 QPS
peak read QPS  = 400 × 3 ≈ 1,200 QPS
```

**Storage**
```
records over 5 years = 100M × 12 × 5 = 6B
raw storage          = 6B × 500 bytes = 3 TB
with 30% index overhead ≈ 4 TB
with 3× replication  ≈ 12 TB provisioned
```

**Bandwidth**
```
egress = 400 QPS × 500 bytes ≈ 200 KB/s
```

**Cache**
```
hot set ≈ 20% of daily reads = 0.2 × (400 × 86,400) × 500 bytes ≈ 3.5 GB
```

**Conclusion:** 1,200 peak QPS with a 3.5 GB working set. This fits comfortably on **one Postgres
instance with a read replica and a small Redis**. It is a **Level 2** system, and any design
involving sharding, Kafka, or microservices is over-built.

That conclusion — reached in five lines of arithmetic — is the entire value of doing estimation
first. Note also that 3 TB over five years is the number that would eventually promote this to L3,
and that is a problem for year four.

---

## 7. When the numbers are unknown

You will often be asked to design something with no numbers available. Do not skip estimation —
**state assumptions and proceed**:

> "Assuming ~50K daily active users each performing ~20 actions, that's roughly 12 QPS average and
> 40 QPS peak. At that volume a single database handles this comfortably, so I'm designing for L2.
> If the real number is 100× that, the design changes at the data layer — I'll note where."

This is strictly better than either guessing silently or refusing to proceed. It makes the
assumption reviewable, and it tells the reader exactly which part of the design is sensitive to it.

---

## 8. Sanity checks before you commit to a design

- Does the whole dataset fit on one machine? → you probably do not need sharding
- Is peak QPS under ~1,000? → one database plus a cache is almost certainly enough
- Is the read:write ratio above 10:1? → caching and replicas solve this; sharding does not
- Is the read:write ratio near 1:1 with high volume? → the write path is the hard problem
- Is the latency budget under 100 ms with users on another continent? → you need edge presence,
  regardless of traffic volume
- Is the availability target above 99.9%? → automated failover is mandatory; budget for it
- Does the largest object exceed a few MB? → object storage plus the claim-check pattern

If a design's numbers do not force a component to exist, the component should not exist. See
`15-tradeoffs-and-checklists.md` for the trade-off catalogue that governs the choices these numbers
open up.
