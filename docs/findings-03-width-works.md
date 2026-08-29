# Finding 03 — Width converts a 12% model into an 88% agent

**Date:** 2026-08-29 · **Instance:** pylint-dev__pylint-7993 · **Model:** Nemotron 3 Super, reasoning off

## Result

One instance, 16 independent proposals, one generation, no beam:

| metric | value |
|---|---|
| proposals asked | 16 |
| applied (parsed + matched) | 11 |
| rejected before forking | 5 (zero container cost) |
| branches executed | 11 |
| **branches that turned the suite green** | **2** |
| per-proposal success rate | **12.5%** |
| cost | $0.0563 |
| wall clock | 76s |

Assuming independence, p = 0.125 implies:

| width | P(at least one solve) |
|---|---|
| 1  | 12.5% |
| 4  | 41% |
| 8  | 66% |
| 16 | **88%** |

## Why the earlier measurements said 0/3

Three instances at width 1, twice, both 0/3. That looked like a capability
ceiling. It was not. At p = 0.125, P(zero solves in three attempts) = **67%** —
the most likely single outcome. Width-1 sampling cannot detect an effect of
this size, and we spent an hour drawing conclusions from an instrument with no
resolution.

**The lesson is methodological and worth keeping.** A low single-shot rate is
not evidence against search. It is the regime in which search is worth doing.
The synthetic demo task failed the opposite way: 6/6 at width 1 meant width
bought nothing. The interesting band is exactly here, and we nearly abandoned
the benchmark for landing in it.

## Why this is the argument for Sandboxes

Finding-01 measured local throughput peaking near width 12 and *declining* at
16 — 1.94 forks/s at 12, 1.19 at 16. This workload wants width 16+, which is
past the cliff. On a developer machine that width is not expensive, it is
unavailable.

The SEARCH/REPLACE patcher matters here too: 5 of 16 proposals were rejected
in Python before forking, so a third of the width cost nothing at all.

## Caveats — do not quote this as a headline yet

- **n = 1 instance, one sample of the width.** 2/16 gives a 95% interval of
  roughly 2%-38%. The point estimate is encouraging; the interval is wide.
- Independence across candidates is assumed, not shown. Samples from one model
  at spread temperatures are correlated to an unknown degree, so the predicted
  curve is an upper bound on what width will actually deliver.
- One instance from one repo. pylint-7993 has a small target file and 10
  regression tests; harder instances will have lower p.

## Next

Measure the curve rather than infer it: width in {1, 2, 4, 8, 16} across
8-10 instances, solve rate per width. That plot -- measured, not modelled --
is the headline result of the submission.
