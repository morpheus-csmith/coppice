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
