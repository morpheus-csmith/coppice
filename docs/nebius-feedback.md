# Feedback log — Nebius Token Factory / ConTree SDK

Written as encountered, not reconstructed afterwards. Submitted with the
project per the hackathon's feedback requirement.

---

## 1. `disposable=True` is the wrong default for agent workloads

`ImageLike.run()` defaults to `disposable=True`, which discards the produced
image after execution. A discarded image has no `uuid`, so calling `run()` on
it raises `DisposableImageRunError`.

**Why this hurts:** the headline use case for Sandboxes is agents that branch
and roll back. That use case *requires* keeping states. So the default is
inverted relative to the product's own positioning — the documented "fork
execution state at any checkpoint" workflow does not work with default
arguments.

**How it fails:** not at the fork. The first `run()` succeeds and returns a
result, so the code looks correct. It fails one level deeper, when you try to
branch from that result, with an exception that reads like an API fault rather
than a caller mistake. We only avoided this by reading the installed source.

**Suggested fixes**, in order of preference:
1. Default `disposable=False`, or
2. Raise a specific error at fork time naming `disposable`, or
3. At minimum, say so in the Sandboxes overview page — the branching example
   there does not mention `disposable` at all.

## 2. `run()` is a lazy builder, and the name does not say so

`run()` returns a *prepared* image; execution happens when the returned object
is awaited. The docstring ("Prepare image for command execution") is accurate,
but the method name says otherwise, and the overloads returning `_T` rather
than a result type make it easy to assume the object in hand is finished.
`prepare()` / `build()` would read truer, or the docs could lead with the
await.

## 3. Docs quality vs. discoverability

The Sandboxes overview describes the model well conceptually — checkpoints,
branching, rollback — but has no API reference. We recovered the actual
contract by grepping site-packages. Publishing the `run()` signature and the
`ContreeResult` fields would have saved roughly an hour.

## 4. Good: per-run `cost` on `ContreeResult`

Genuinely excellent and rare. `ContreeResult` exposes `exit_code`,
`elapsed_time` and `cost` together, so cost accounting needs no estimation
layer. This let us report real spend per branch instead of inferring it from
token counts. More providers should do this.

## 5. Good: exception taxonomy

`OperationTimedOutError`, `FailedOperationError`, `CancelledOperationError`
and the `ApiStatusCodeError` hierarchy are well separated, which made mapping
backend failures onto our own result type straightforward. Timeouts being
distinguishable from failures matters for us — a timed-out branch and a failed
branch are scored differently.

## 6. `contree-sdk` is not installable everywhere

`pip install contree-sdk` resolved on the dev machine but returned
"no matching distribution" from another environment on a different index
mirror. Worth checking propagation, since a hackathon participant hitting that
would likely assume the package does not exist.

## 7. Sandboxes returns 403 with no route to enablement

A fresh Token Factory account with a valid API key and project can call
inference successfully, but every Sandboxes call returns:

```
403 "You do not have permission to perform this action"
```

The Sandboxes overview documents a six-step quick start and says nothing about
requesting access, joining a waitlist, or enabling the service on a project.
So the failure gives a developer nowhere to go: the credentials are right, the
docs imply it should work, and the error names no missing permission, no
console setting, and no next step.

Reaching the right error took three tries, each one more specific than the
last -- 401-shaped, then `400 Missing "Project" header`, then this. That
progression is good API design. The last step should continue it: a 403 on a
beta service ought to say *how* to get access, or the overview should state
that access is granted separately.

**Suggested fix:** either enable Sandboxes by default for accounts that have
completed billing, or have the 403 body name the enablement path. As it
stands, a hackathon participant whose project depends on Sandboxes hits a wall
with no documented way past it.

## 8. Nemotron 3 model ids use three naming conventions in one catalogue

`GET /v1/models` on Token Factory returns the Nemotron 3 family as:

```
nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B     doubled vendor prefix, TitleCase
nvidia/nemotron-3-super-120b-a12b          all lowercase
nvidia/Nemotron-3-Ultra-550b-a55b          mixed: TitleCase name, lowercase size
```

Three sibling models, three conventions. Ids cannot be derived from the model
name, from each other, or from the ids the same models carry on NVIDIA Build
(which uses all-lowercase for all three). Anyone porting between the two
providers must hand-map every tier and will get a 404 on two of three.

**Suggested fix:** normalise to one convention, or publish aliases so a single
lowercase id resolves everywhere. This is a small thing that costs every
integrator the same twenty minutes.

## 9. Model pricing is hard to find from the API side

Building a cost ledger meant estimating Nano and Super prices for most of a
day because there is no programmatic way to get them: `/v1/models` returns
ids and nothing else, and the pricing page is not machine-readable. Our Nano
estimate was 40% too high, so every cost figure carried an asterisk until we
found a third-party listing.

**Suggested fix:** include price-per-token in the `/v1/models` response, the
way some providers do. Any agent that routes across tiers by cost needs this
at runtime, and a secondary source is a poor substitute when the numbers end
up in a published benchmark.

Related: `ContreeResult.cost` on the Sandboxes side is exactly right — real
spend, per operation, no estimation. The inference API should do the same.

## 10. Timeouts are reported through the result, not the documented exception

`ImageLike.run(timeout=...)` is honoured correctly — a `sleep 30` with
`timeout=3` returns at ~3.5s. But it comes back as a normal result carrying
`exit_code = -1`, rather than raising `OperationTimedOutError`, which the SDK
defines and which the exception taxonomy strongly implies is the timeout
signal.

Our conformance suite caught this immediately (17/18 on first contact with the
real API), but only because we were testing for it. A caller who handles
`OperationTimedOutError` and trusts `exit_code` otherwise will silently treat a
timed-out branch as a legitimate failure — which, for a search that scores
branches, means a runaway operation is scored as evidence rather than discarded.

A negative exit code is also ambiguous on its own: any signal kill looks the
same. We disambiguate by requiring `exit_code < 0` *and* elapsed >= 90% of the
requested timeout, which works but is a heuristic over something the API knows
exactly.

**Suggested fix:** raise `OperationTimedOutError`, or add an explicit
`timed_out` boolean to `ContreeResult` alongside `exit_code` and `cost`.

---

## Correction to §7

Nebius replied within hours: Sandboxes beta **can** be activated from the
Sandboxes page in Token Factory, and they enabled it for our account directly.
So the path exists and we failed to find it. The feedback stands in narrower
form: the 403 response names no remedy, and the Sandboxes overview page
documents a six-step quick start without mentioning that activation is a
prerequisite. A developer hitting that error has no way to learn either fact
from the error or the docs.
