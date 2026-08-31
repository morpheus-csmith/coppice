# Finding 06 — Sandboxes validated: 15x faster per branch, no concurrency penalty

**Date:** 2026-08-31 · pylint-dev__pylint-7993 · width 16 · Nemotron 3 Super
**Status:** the week-one gate, finally executed.

## The gate

`tests/test_executor_conformance.py` — 9 tests every executor must pass — run
against both backends:

```
18 passed
```

`test_fork_isolation[contree]` passing is the result the entire project rested
on. Two runs from the same ConTree state cannot observe each other's writes.
Beam search over forked execution state is sound. Until this ran, every branch
score we had was conditional on an assumption we could not check.

One test failed on first contact and was our bug, not theirs: ConTree honours
`timeout=` correctly but reports it through the *result* (`exit_code = -1` at
the deadline) rather than raising `OperationTimedOutError`. Fixed; logged as
feedback §10.

## Same instance, same width, same model, two executors

| | Docker (local) | Token Factory Sandboxes |
|---|---|---|
| setup command | 17.2s | **1.7s** |
| per-branch execution | 66.2s | **4.0–4.6s** |
| 12 branches, wall-clock | ~53s | **4.6s** |
| branches solved | 2 of 13 | **3 of 12** |
| stability | two crashes today | clean |

**~15x faster per branch.** And the important half: the spread across twelve
concurrent branches was **600 milliseconds** (4.0s to 4.6s). Docker's twelve
branches all took 66.2s — identical, because they were queueing, not working.

## This is finding-01, measured

Finding-01 predicted this from local throughput alone: on this machine,
throughput peaks near width 12 and *declines* at 16 — 1.94 forks/s at 12, 1.19
at 16. We argued the ceiling, not the unit cost, was the defensible thesis.

The measurement confirms it. Docker's 66.2s per branch is not the cost of
running pylint's tests; it is the cost of twelve containers contending for 7.8
GB of RAM and 12 cores. Sandboxes removes the contention, and the same work
takes 4.4s.

**Width beyond ~12 was never expensive on a laptop. It was unavailable.**

Two independent crashes today make the same point less politely: the Docker
executor segfaulted twice under width-16 concurrency (`double free or
corruption`, then `Segmentation fault`). The Sandboxes run completed clean.
Local execution became the least reliable component in the system.

## Honest accounting

- **First-run image import cost ~122s.** `setup.done` reads 1.7s but the
  timestamp is 123.8s: ConTree imported the SWE-bench OCI image from ghcr.io on
  first use. That is a one-time per-image cost, amortised across every
  subsequent run, and it is why end-to-end wall clock (148s vs Docker's 321s)
  understates the per-branch advantage.
- **Docker is not a strawman.** It uses `docker commit` as a checkpoint — what
  a competent engineer would build without ConTree. The comparison is against a
  real implementation, not a naive one.
- One instance, one run per backend. The per-branch timings are unambiguous;
  the solve counts (3 vs 2) are within noise for a ~19% per-shot rate.

## What this changes

Every result in `findings-04` was measured on Docker. The width curve should be
re-run on Sandboxes — not because we expect the *solve* numbers to move (the
model is identical) but because the wall-clock and concurrency story is
materially different, and the benchmark should be measured on the executor the
project is actually about.
