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
