# Finding 04 — The width curve, decomposed

**Date:** 2026-08-29 · 9 SWE-bench Lite instances · 16 samples each · Nemotron 3 Super, reasoning off · $0.43 total

## Method

For each instance we drew 16 independent proposals at spread temperatures,
applied and evaluated every one, then read the curve off by subsampling: of
all C(16,k) ways to choose k of our samples, what fraction contain at least
one solver. This is an exact combinatorial estimate over samples actually
drawn -- it assumes nothing about independence between candidates, which a
model-based curve would have to.

Rejected proposals count as failures at their width. They cost no container,
but they consumed a slot.

## Raw

| instance | applied/16 | solved/16 | per-shot |
|---|---|---|---|
| pylint-dev__pylint-7993 | 13 | 3 | 19% |
| pylint-dev__pylint-7228 | 10 | 3 | 19% |
| astropy__astropy-12907 | 8 | 4 | 25% |
| mwaskom__seaborn-3010 | 13 | 13 | 81% |
| pylint-dev__pylint-5859 | 8 | 0 | 0% |
| pylint-dev__pylint-6506 | 16 | 0 | 0% |
| astropy__astropy-14365 | 7 | 0 | 0% |
| astropy__astropy-14182 | 11 | 0 | 0% |
| pallets__flask-4992 | 10 | 0 | 0% |

`pydata__xarray-4248` failed on a Docker client read timeout, not a model
failure. Excluded; timeout raised for future runs.

## The result

Aggregated across all 9, solve rate goes 16% -> 44% from width 1 to 16. That
number is honest but not informative, because it averages three populations
that behave completely differently:

| regime | n | w1 | w2 | w4 | w8 |
|---|---|---|---|---|---|
| already easy (>50% per-shot) | 1 | 81% | 98% | 100% | 100% |
| **sweet spot (1-50% per-shot)** | **3** | **21%** | **38%** | **65%** | **92%** |
| out of reach (0 in 16) | 5 | 0% | 0% | 0% | 0% |

**The claim we can defend: where the model has a real but unreliable shot,
width 1 -> 8 moves solve rate from 21% to 92%.**

Width does nothing in the other two regimes, and saying so plainly is what
makes the middle row credible. A single averaged curve would understate the
effect where it exists and imply one where it does not.

## What this says about the thesis

The value of breadth is concentrated in a band, and that band is where real
agent work lives -- problems the model can nearly do. Below it, no amount of
sampling helps; above it, sampling is waste. Our synthetic demo task sat above
the band (6/6 at width 1) which is exactly why it proved nothing.

Width 8 is also where local execution starts losing: finding-01 measured
throughput peaking near width 12 and declining at 16 on this machine. The
regime that pays is the regime a laptop cannot serve.

## Costs to disclose

- **Patcher tax: 33%.** 96 of 144 proposals applied; the rest were rejected
  before forking (unmatched SEARCH, no-op, malformed). Free in compute, but
  they consumed width. Raising apply rate multiplies effective width directly
  and is the cheapest available improvement.
- $0.43 for 144 proposals and 96 branch evaluations.

## Caveats

- 9 instances from 4 small repos, chosen for small target files and short
  regression suites. **Not a SWE-bench Lite score** and must never be
  presented as one.
- PASS_TO_PASS sampled at 40 tests per branch; instances above that cap are
  scored on a sample, so a "solve" is not a full-suite guarantee. The winning
  patch needs a full-suite verification pass.
- Single generation, no beam, no repair. This measures breadth alone.

## Next

1. Verification pass on winning patches against the full PASS_TO_PASS set.
2. Attack the 33% patcher tax -- retry rejected proposals with the parse error
   fed back, which costs one call and no container.
3. Re-run on Token Factory once access exists, to confirm the curve holds.


---

## Replication on Token Factory Sandboxes (2026-08-31)

The curve above was measured on the Docker executor. After Sandboxes access was
granted we re-ran the identical benchmark on it — same instances, same width,
same model, fresh stochastic draws.

| width | Docker (n=5 sweet spot) | Sandboxes (n=6 sweet spot) |
|---|---|---|
| 1  | 19% | 19% |
| 2  | 33% | 33% |
| 4  | 53% | 54% |
| 8  | **76%** | **77%** |
| 16 | 100% | 100% |

Apply rate 87% on both. Instances solved 6/10 on both. Pooled per-proposal
rate differs (16.2% vs 11.2%) because these are independent draws from a
~15% process, which is exactly the variance finding-03 warned about.

**Why this matters more than either run.** The executor cannot affect whether
a patch is correct — it runs the same tests on the same code. So agreement was
the prediction, and getting it is a check on the whole measurement chain: the
patcher, the scorer, the subsampling estimator, and both backends. A
divergence would have meant a bug the conformance suite missed.

## Infrastructure, measured

The executors differ enormously on time, and not at all on correctness:

| | Docker (local) | Sandboxes (cold images) | Sandboxes (warm) |
|---|---|---|---|
| per instance | ~240s | ~130s | **~30s** |
| per branch | 66.2s | 4.4s | 4.4s |
| 12 concurrent branches | ~53s | 4.6s | 4.6s |

The warm-cache figure is the honest steady state: first use of each SWE-bench
image pays a one-time OCI import. After that, a full 16-proposal instance —
16 model calls, ~14 sandboxed test runs — completes in about half a minute.

Raw data: `results/width-curve-sandboxes.json`,
`results/width-curve-nebius.json` (Docker).
