# Finding 01 — What a fork actually costs

**Date:** 2026-08-29 · **Gate:** week one · **Status:** Docker arm complete, ConTree arm blocked on API key

## Setup

12-core / 7.8 GB WSL2 host, Docker 29.7.2. Workload shaped like a migration:
expensive prepare (`pip install pytest requests flask sqlalchemy`, ~9.5s),
cheap attempt (write a test file, run `pytest -q`).

## Results

Per-fork tax, measured with a no-op command so the number is workload-independent:

| metric | value |
|---|---|
| Docker per-fork tax (median, serial, zero workload) | **2.17s** |
| Setup cost paid once instead of per-attempt | 9.5s |

Scaling, `prepared` arm, width == concurrency:

| width | wall | median attempt | throughput | failures |
|---|---|---|---|---|
| 4  | 3.2s  | 3.12s  | 1.25 /s | 0 |
| 8  | 4.3s  | 4.12s  | 1.86 /s | 0 |
| 12 | 6.2s  | 6.01s  | **1.94 /s** | 0 |
| 16 | 13.4s | 13.24s | 1.19 /s | 0 |

## What we got wrong

We predicted OOM kills at width 12–16 given 7.8 GB and a 900 MB per-container
limit. **No container was ever killed.** The constraint is CPU and I/O
contention, not memory, and it manifests as latency inflation rather than
failure. Throughput peaks near width 12 and *declines* after — width 16 does
more work and delivers less than width 8.

## What this changes about the thesis

The per-fork tax alone does not carry the argument. A real migration attempt
runs a test suite for 10–60s; 2.17s of overhead against that is 4–20%. A judge
will do that arithmetic.

The defensible claim is the **ceiling**, not the unit cost:

> Search width beyond ~12 is not expensive on a developer machine — it is
> unavailable, and degrades if attempted. Sandboxes makes width a
> configuration value, at 50.

Reframes the pitch from *cheaper* to *possible*. Stronger, and supported by
the data we actually have.

## Known limitation of this benchmark

Setup here is 9.5s. Real migrations clone real repositories and install real
dependency trees: 60–300s. **This benchmark understates the checkpoint
advantage.** Replace the synthetic workload with real repos before any of
these numbers appear in the submission.

## Next

1. Realistic workload — real clone, real dependency install.
2. ConTree arm — blocked on `NEBIUS_API_KEY`.
3. Compare on throughput at width, not on per-fork latency.
