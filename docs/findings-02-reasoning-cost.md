# Finding 02 — Reasoning traces cost 25x and did not help

**Date:** 2026-08-29 · **Provider:** NVIDIA Build (free tier) · **Samples: n=1 per cell**

## Mechanism

Nemotron 3 returns reasoning inside `content`, billed as output tokens.
Two documented controls exist and the docs disagree across model generations,
so we send both and let the unused one be ignored:

```python
extra_body={"chat_template_kwargs": {"enable_thinking": False}}   # Nemotron 3
system="/no_think"                                                 # Llama-Nemotron
```

Both are honoured through the NVIDIA Build endpoint.

## Measurement

One migration question (`requests.packages.urllib3` removal), each tier twice,
`max_tokens=1200` so nothing truncates mid-thought.

| tier | output tokens (on → off) | reduction | latency (on → off) |
|---|---|---|---|
| nano  | 274 → 11 | **24.9x** | 2.9s → 0.3s |
| super | 290 → 11 | **26.4x** | 3.1s → 1.6s |
| ultra | 190 → 11 | **17.3x** | 21.3s → 15.6s |

## Accuracy

With reasoning **off**, all three tiers returned the correct answer
(`import urllib3; urllib3.disable_warnings()`).

With reasoning **on**, `super` returned `requests.urllib3.disable_warnings()`
— also wrong; that path does not exist. It spent 26x the tokens to be less
correct.

**This is n=1 at temperature 0.2 and may be sampling noise.** Do not quote the
accuracy claim without more samples. The cost reduction reproduces across all
three tiers and is too large to be chance.

## Decisions taken

1. Reasoning **off** for breadth roles (`propose`, `triage`, `repair`).
   Width-8 expansion drops from ~2,200 output tokens to ~88.
2. Reasoning **on** for judgement roles (`plan`, `adjudicate`, `explain`) —
   a handful of calls per run where token cost is irrelevant.
3. Policy encoded in `models.ROLES` so it is one readable table, and callable
   via `Router.act(role, prompt)`.

## Also observed

**Ultra's latency floor is not reasoning.** Even with thinking off it takes
15.6s versus Super's 1.6s. Ultra cannot sit in any inner loop regardless of
token settings; it must be called rarely and, where possible, concurrently
with other work.

## Open

- Re-run at n>=10 on harder, multi-step migration decisions. The hypothesis
  worth testing is that reasoning helps on genuine judgement calls and hurts
  on mechanical transformations — which, if true, is exactly the split the
  ROLES table already encodes.
- Confirm this holds on Nebius Token Factory, not just NVIDIA Build.

---

## Addendum (same day) — Ultra's latency floor was the free tier, not the model

The conclusion above ("Ultra cannot sit in any inner loop; 15.6s even with
reasoning off") was measured on NVIDIA Build's free tier. On Nebius Token
Factory the same model, same prompt:

| tier | NVIDIA Build (free) | Nebius Token Factory |
|---|---|---|
| Nano | 2.9s | 2.1s |
| Super | 1.5s | **0.7s** |
| Ultra | 31.0s | **1.0s** |

Ultra is roughly **30x faster** on Token Factory -- faster than Super was on
the free tier. The 15.6s floor was queueing on shared free capacity, not a
property of a 550B model.

**This reopens the routing question.** The ROLES table keeps Ultra to a
handful of judgement calls per run because it was assumed unaffordable in
latency. At 1.0s that assumption is void: Ultra may be viable for candidate
generation itself, which would raise per-proposal quality in exactly the band
finding-04 shows width paying off.

Do not rewrite ROLES on this measurement alone -- it is one prompt, one
sample, and token cost still differs by tier. But re-run the width curve with
`--propose-tier ultra` before settling the architecture; if Ultra's per-shot
solve rate is meaningfully above Super's, the cost calculus changes.

**Methodological note:** two findings in this project have now come from
measuring an artefact of the environment rather than the thing under study
(the width-1 sampling error in finding-03, and this). Benchmark the
configuration you intend to ship on.

### Correction to the addendum above

The "30x faster" figure came from a 68-token prompt. Under a realistic ~8,300
token prompt, Ultra on Token Factory takes **17s per call** (538s across 31
calls), not 1.0s. Latency scales with prompt size and the smoke test used the
smallest possible input.

The addendum's own closing advice -- benchmark the configuration you intend to
ship on -- was violated in the act of writing it. Third instance of this class
of error in one session. The rule to internalise: **a measurement taken under
conditions you will not ship under is not evidence, however clean it looks.**
