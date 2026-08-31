# Devpost feedback questionnaire — answers

## Which model(s) did you use, and why that size/variant?

**NVIDIA Nemotron 3 Super (120B A12B)** for everything in the final pipeline.
We evaluated all three tiers on the same instance, 16 proposals each, and chose
by measurement rather than assumption:

| tier | patches that applied (of 16) | solved | cost |
|---|---|---|---|
| Nemotron 3 Nano 30B A3B | 0 | 0 | $0.0025 |
| **Nemotron 3 Super 120B A12B** | **13** | **3** | $0.0566 |
| Nemotron 3 Ultra 550B A55B | 1 | 0 | $0.4552 |

Our agent edits code by exact-match SEARCH/REPLACE blocks, so a patch only
lands if the model copies source *character for character*. Nano paraphrases
while transcribing — it collapsed a four-line function signature onto one line,
and the block matched nothing. Ultra mostly returned prose about what it would
change instead of blocks. Super sits in the band where the model is large enough
to hold a strict output format and small enough not to editorialise.

We had planned the opposite: Nano doing cheap breadth, Ultra adjudicating. The
data killed that architecture in an afternoon.

## Rate Nemotron's output quality for your use case (1–10)

**7.**

What worked: on real SWE-bench bugs, Super produced *correct* fixes — verified
by the repository's own test suite, not self-assessment. On one instance it
found two genuinely different valid patches (one escaping brace literals before
template parsing, one routing through a defaulting dictionary). That diversity
is exactly what a breadth-first search needs and it's not guaranteed.

What fell short: **structured-output compliance, and its variance across
sizes.** This was the binding constraint on our entire system — not reasoning,
not domain knowledge. Format adherence also degraded sharply with temperature:
at 0.9 our apply rate collapsed from 67% to 11%, with 113 of 126 rejections
being "no output block found at all."

Instruction-following on the *task* was good. Instruction-following on the
*output contract* was the problem.

## Fine-tune, prompt-engineer, or out of the box?

**Out of the box, with deliberate prompt engineering. No fine-tuning.**

Four things moved the numbers:

1. **A system prompt that is only about the output contract**, separate from
   the task prompt — with the rule "copy character for character, never retype
   from memory" stated explicitly.
2. **One worked example** of a correct edit block, drawn from the same kind of
   edit the model kept getting wrong.
3. **Reasoning disabled** for generation roles via
   `chat_template_kwargs: {enable_thinking: false}` — ~25x fewer output tokens
   with no accuracy loss on transformation-shaped work.
4. **Error-fed repair.** A rejected patch already carries a precise diagnosis
   ("SEARCH not found", "ambiguous", "no-op"). Feeding that back for one retry
   recovers ~40% of rejections, for one model call and zero sandbox time.

## How did Nemotron compare to other models for similar tasks?

Honestly: **we did not run a head-to-head against other vendors' models**, so we
won't invent one. Our comparisons were between Nemotron tiers, and between
Nemotron on Nebius Token Factory versus the same models on NVIDIA Build's free
tier.

What we can say: the **explicit reasoning toggle is a real differentiator.**
Most hosted models either always reason or never do. Being able to switch it
off per-call — cheaply, without a different endpoint — let us put reasoning
where judgement matters and remove it where we were paying for prose we then
discarded. That single control was worth ~25x on output tokens.

The size-to-format-compliance relationship surprised us and we haven't seen it
documented elsewhere: the largest model in the family was *worse* at emitting a
strict format than the mid-size one.

## Which Nebius platform capabilities were most valuable?

**Token Factory serverless inference.** We provisioned no GPUs, chose no
instance types, and managed no deployment — which for a solo build against a
deadline is the entire value proposition. All access was through the
OpenAI-compatible endpoint at
`https://api.tokenfactory.us-central1.nebius.com/v1`.

Two Token Factory specifics measurably shaped the architecture:

- **`n` sampling with the prompt billed once.** Our workload is ~80% input
  tokens, and a width-16 expansion sends one identical prompt sixteen times.
  Batching via `n` cut cost **2.1x** and model time **4.9x** on the same
  instance. This is the single largest optimisation in the project.
- **Reasoning control** via `chat_template_kwargs`, as above.

Because inference was OpenAI-compatible, switching providers was **one
environment variable** — we prototyped on NVIDIA Build and moved to Token
Factory without touching a line of application code.

**Token Factory Sandboxes** is the executor and the reason we chose this track.
ConTree versions the filesystem after every command, which makes forking a
prepared checkpoint nearly free — exactly the primitive our thesis needs. Our
headline benchmark runs on it.

Measured against a local Docker executor doing the same work with
`docker commit` as its checkpoint: **66.2s per branch on Docker, 4.4s on
Sandboxes**, and twelve concurrent branches finish within 600ms of each other
where Docker's twelve all take 66.2s because they are queueing. Warm, a
16-proposal instance completes in ~30s against Docker's ~240s. Docker also
segfaulted twice under width-16 concurrency; Sandboxes ran clean.

Access was initially blocked — every call returned
`403 "You do not have permission to perform this action"` while inference on the
same key succeeded (request id `58bb1d784337cba8f8b3258ff36990bb`). Support
enabled it and the conformance suite passed **18/18 across both backends on
first contact**. We kept the Docker backend, and the two executors produce the
same solve curve within one point at every width — an unusually clean
cross-check on both.

We did not use AI Cloud GPU instances, Serverless Endpoints, or Serverless Jobs.

## How likely are you to recommend running Nemotron on Nebius? (1–10)

**8.**

Serverless removes GPU operations entirely, the OpenAI-compatible API means
zero integration cost, latency was good (Super at 0.7s on short prompts), and
our entire 10-instance benchmark — 160 proposals, 139 sandboxed test runs —
cost **$0.29**.

Two points off for friction that is all fixable: model IDs that follow three
different naming conventions inside one catalogue, no pricing available through
the API, and a Sandboxes 403 whose body named no route to enablement (support
resolved it quickly once we asked — the gap was discoverability, not
willingness).

## Rate the inference experience vs. previous environments (1–10)

**8.**

We ran the identical workload on NVIDIA Build's free tier first, so this is a
measured comparison rather than an impression:

| tier | NVIDIA Build (free) | Nebius Token Factory |
|---|---|---|
| Nano | 2.9s | 2.1s |
| Super | 1.5s | **0.7s** |
| Ultra | 31.0s | **1.0s** |

(Short-prompt measurements. Under realistic ~8,300-token prompts Ultra is 17s —
latency scales with input, which is worth documenting.)

Local comparison isn't meaningful: we cannot run a 120B model on the hardware
this was built on. That's the point of serverless.

## What additional features would have made this more effective?

1. **Prompt caching.** Our largest remaining cost is resending an identical
   prompt across a search generation. Currently an open feature request on your
   own ideas board — for agentic search workloads it would be transformative.
2. **Pricing in `/v1/models`.** We estimated Nano and Super prices for most of a
   day because there's no programmatic source; our Nano estimate was 40% too
   high. Any agent that routes by cost needs this at runtime.
3. **Consistent model IDs.** `nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B`,
   `nvidia/nemotron-3-super-120b-a12b`, and `nvidia/Nemotron-3-Ultra-550b-a55b`
   use three conventions in one catalogue. Ids can't be derived, and they differ
   from the same models' ids on NVIDIA Build.
4. **A 403 that names its remedy.** Sandboxes rejected with no indication of
   whether access is granted separately, requested, or already enabled. Support
   enabled it within a day of us asking — but we lost build time to not knowing
   asking was the answer. One sentence in the response body fixes this.
5. **Grammar-constrained or schema-constrained decoding.** See below — this
   would have removed the single biggest source of waste in our project.

## What do you most hope to see from the Nemotron team next?

**Guaranteed structured output.** JSON-schema or grammar-constrained decoding,
at every size.

Our entire project is bottlenecked on it. 13% of proposals are still discarded
because the model didn't produce a parseable edit block — that's search width we
paid for and threw away. The smallest model in the family is unusable for us not
because it reasons badly but because it cannot reliably reproduce a string
verbatim, and the largest is unusable because it prefers prose. A constrained
decoding mode would make Nano viable for breadth generation, which would cut our
costs by roughly an order of magnitude.

Second: **document the reasoning toggle prominently.** It's one of the most
useful controls in the family and we found it by grepping a NIM reference page.

## Did you use Tavily?

**No.** We considered it for retrieving upstream changelogs when a branch
stalls, but our final benchmark is SWE-bench bug-fixing rather than dependency
migration, and the fix information is in the repository itself. Adding a Tavily
call that our solution didn't functionally need would not have qualified, and
would have been dishonest.
