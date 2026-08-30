# Coppice

**A code-repair agent that searches over execution state instead of guessing at it.**

Coppicing is the practice of cutting a tree back so it throws new shoots from
the stump. That is the architecture: prepare one verified checkpoint, fork it
into many candidate patches, run the real test suite in all of them, cut back
the failures, and grow the survivors.

Built for the Nebius x NVIDIA Global AI Hackathon — **Coding & Agentic
Engineering** track.

---

## The claim, and the evidence for it

A 120B open model fixes a given SWE-bench bug about **14% of the time**. A
single-shot agent therefore fails six times in seven. Coppice does not make the
model better; it changes how compute is allocated.

Measured on 10 SWE-bench Lite instances, 16 independent proposals each,
Nemotron 3 Super on Nebius Token Factory:

| attempts | chance of at least one verified fix |
|---:|---|
| 1  | 14% |
| 2  | 22% |
| 4  | 30% |
| 8  | 39% |
| 16 | **50%** |

5 of 10 instances solved. **$0.30 for the entire sweep** — 160 proposals and
133 sandboxed test runs.

The curve is computed by exact subsampling over the samples actually drawn
(`bench/analyze.py`), not modelled from an assumed independence between
candidates. Reproduce it with `python bench/width_curve.py --samples 16`.

**Green means the repository's own test suite passed** — the tests its
maintainers wrote went from failing to passing with nothing else broken. Not
that a model judged its own work acceptable. Search needs a reward signal it
cannot talk itself into.

---

## Where NVIDIA Nemotron and Nebius are used

**Nemotron 3 Super (`nvidia/nemotron-3-super-120b-a12b`)** generates every
candidate patch, repairs its own rejected ones, and is the only tier in the
pipeline that works — which is itself a finding. We measured all three:

| tier | patches that applied (of 16) | solved | cost |
|---|---|---|---|
| Nemotron 3 Nano | 0 | 0 | $0.0025 |
| **Nemotron 3 Super** | **13** | **3** | $0.0566 |
| Nemotron 3 Ultra | 1 | 0 | $0.4552 |

Nano paraphrases source while transcribing it, so exact-match edits never
apply. Ultra returns prose instead of edit blocks. The binding constraint on an
agent that patches by exact match is **structured-output compliance, not
reasoning** — see `docs/findings-05-tier-selection.md`.

**Nebius Token Factory** serves all inference (`src/coppice/config.py`,
`src/coppice/models.py`). Two Token Factory specifics shaped the design:

- **`n` sampling.** Token Factory bills the prompt once per request regardless
  of `n`. Since ~80% of our spend is input and a width-k expansion sends one
  identical prompt k times, batching cut cost 2.1x and model time 4.9x.
- **Reasoning control.** `chat_template_kwargs: {enable_thinking: false}` cuts
  output tokens ~25x on generation roles, where reasoning traces are billed and
  then discarded (`docs/findings-02-reasoning-cost.md`).

**Token Factory Sandboxes** is implemented in
`src/coppice/executor/contree_exec.py` and is the intended executor: ConTree
versions the filesystem after every command, so forking is `run()` called twice
on the same state. **It is not yet validated** — every Sandboxes call on this
account returns `403 "You do not have permission to perform this action"` while
inference on the same key succeeds. All results above therefore use the Docker
fallback executor. See `docs/nebius-feedback.md` §7.

---

## Install

Requires Python 3.12 and a running Docker daemon.

```bash
git clone <this repo> && cd coppice
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[test]" && pip install contree-sdk datasets

cp .env.example .env      # then add NEBIUS_API_KEY and NEBIUS_PROJECT_ID
```

Confirm the models resolve:

```bash
COPPICE_PROVIDER=nebius python -m coppice.config --check
```

## Run it

**A self-contained demo** (synthetic task, no SWE-bench download):

```bash
COPPICE_PROVIDER=nebius python -m coppice.search --width 6 --beam 2 --depth 3
```

**A real SWE-bench Lite instance** (pulls a ~1.5GB prebuilt image):

```bash
docker pull ghcr.io/epoch-research/swe-bench.eval.x86_64.pylint-dev__pylint-7993
COPPICE_PROVIDER=nebius python -m coppice.search \
  --task pylint-dev__pylint-7993 --width 16 --beam 1 --depth 1 --propose-tier super
```

**The width-curve benchmark** (10 instances, ~$0.30, ~40 min):

```bash
COPPICE_MAX_SPEND=6 COPPICE_PROVIDER=nebius python bench/width_curve.py --samples 16
python bench/analyze.py
```

**Replay any run as the search tree:**

```bash
python viz/build_replay.py runs/demo-pylint7993.jsonl -o viz/replay.html
```

Spend is capped by `COPPICE_MAX_SPEND` (default $3) and raises `BudgetExceeded`
rather than continuing quietly.

---

## How it works

1. **Prepare once.** Clone, install, run the suite, record the baseline. Every
   branch below inherits this state — nothing is rebuilt per attempt.
2. **Propose at width.** Four batched calls at spread temperatures (0.0 greedy,
   then 0.35 / 0.65 / 0.95) rather than k separate calls.
3. **Apply locally.** SEARCH/REPLACE blocks are matched in Python *before*
   forking. A patch that doesn't apply costs a model call and **zero container
   time** — that is what makes width affordable. Rejected proposals get one
   repair attempt with the parse error fed back, recovering ~40% of them.
4. **Execute in parallel.** Each surviving patch runs the gating tests in its
   own forked sandbox.
5. **Score against ground truth.** Newly-passing tests minus regressions
   (weighted 1.5x, because trading a break for a fix is not progress) minus a
   small diff-size penalty. A patch that breaks collection scores -100.
6. **Prune and expand.** Keep the top *b*; discard the rest.

Every backend must pass `tests/test_executor_conformance.py` before it is
trusted. The load-bearing test is `test_fork_isolation`: if two runs from one
state can see each other's writes, branches silently contaminate their siblings
and nothing looks broken.

---

## Limitations, stated plainly

- **10 instances from 4 small repos**, chosen for small target files and short
  regression suites. This is **not a SWE-bench Lite score** and must not be read
  as one.
- **PASS_TO_PASS is sampled at 40 tests** per branch to keep evaluation fast.
  Instances above that cap are scored on a sample, so a "solve" is not yet a
  full-suite guarantee.
- **Single-file patches only.** SWE-bench Lite happens to be single-file
  throughout, so this costs nothing there, but it is a real limit on generality.
- **Sandboxes unvalidated** (403, above). The Docker executor is an honest
  baseline, not a strawman — it uses `docker commit` as a checkpoint, which is
  what a competent engineer would build without ConTree.
- **Width helps in a band.** It does nothing for instances the model already
  solves reliably, and nothing for instances out of reach. See
  `docs/findings-04-width-curve.md`.

## Findings

Written as encountered, including the wrong turns:

| | |
|---|---|
| `findings-01-fork-cost.md` | Docker's per-fork tax; local throughput peaks at width ~12 and *declines* |
| `findings-02-reasoning-cost.md` | Reasoning traces cost ~25x; two corrections to our own measurement |
| `findings-03-width-works.md` | Why 0/3 at width 1 was sampling noise, not a capability ceiling |
| `findings-04-width-curve.md` | The curve, decomposed into three regimes |
| `findings-05-tier-selection.md` | Nano and Ultra both fail, for opposite reasons |
| `nebius-feedback.md` | Nine concrete points of API friction, and what worked |

## License

Apache 2.0 — see [LICENSE](LICENSE).
