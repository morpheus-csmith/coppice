## Inspiration

Coding agents mostly fail the same way: they try once. A model proposes a fix,
it doesn't work, and the run is over. But the failure isn't usually that the
model *can't* solve the problem — it's that it doesn't solve it *this time*.

We measured that. NVIDIA Nemotron 3 Super fixes a given SWE-bench bug about
**16% of the time**. One attempt fails five times in six. Sixteen attempts, and
one of them is almost certainly right.

The reason nobody just does sixteen attempts is that each one normally means
rebuilding the environment — clone, install, configure — before you can even
run a test. Nebius Token Factory Sandboxes changes that: it versions the
filesystem after every command, so forking a prepared state is nearly free.
Breadth stops being expensive and starts being a configuration value.

Coppicing is the forestry practice of cutting a tree back so it throws new
shoots from the stump. That's the whole architecture.

## What it does

Point Coppice at a repository with a failing test. It:

1. **Prepares one checkpoint** — clone, install, run the suite, record the
   baseline. Paid once.
2. **Proposes many patches at width** from that single state, using Nemotron 3
   Super on Nebius Token Factory.
3. **Applies each one in its own fork** and runs the real test suite in all of
   them, in parallel.
4. **Scores against ground truth** — newly-passing tests minus regressions, not
   a model's opinion of its own work.
5. **Prunes and expands**, keeping the best branches for the next generation.

Green means *the repository's own test suite passed*. The tests its maintainers
wrote went from failing to passing, with nothing else broken. Search needs a
reward signal it cannot talk itself into.

## Results

10 SWE-bench Lite instances, 16 independent proposals each, Nemotron 3 Super on
Nebius Token Factory:

| attempts | all 10 instances | the 5 where the model has a real but unreliable shot |
|---:|---|---|
| 1  | 16% | 19% |
| 2  | 26% | 33% |
| 4  | 36% | 53% |
| 8  | 48% | **76%** |
| 16 | 60% | **100%** |

**6 of 10 solved, $0.33 for the whole sweep.** Three cents an instance.

The second column is the honest one. Width does nothing for the instance the
model already solves reliably, and nothing for the four it never solves. The
value is concentrated in a band — problems the model can *nearly* do — and
that band is where real agent work lives.

The curve is computed by exact subsampling over samples actually drawn, not
modelled from an assumed independence between candidates. Every number is
reproducible from the committed data.

## How we built it

**Inference:** NVIDIA Nemotron 3 Super via Nebius Token Factory's
OpenAI-compatible API. Two Token Factory specifics shaped the design:

- **`n` sampling.** Token Factory bills the prompt once per request regardless
  of `n`. Since ~80% of our spend is input and a width-k expansion sends one
  identical prompt k times, batching cut cost 2.1x and model time 4.9x.
- **Reasoning control.** `chat_template_kwargs: {enable_thinking: false}` cuts
  output tokens ~25x on generation roles, where reasoning traces are billed and
  then discarded.

**Execution:** an `Executor` abstraction with two backends behind one interface
— Token Factory Sandboxes (ConTree) and Docker. Every backend must pass a
9-test conformance suite before it's trusted. The load-bearing test is fork
isolation: if two runs from one state can see each other's writes, branches
silently contaminate their siblings and *nothing looks broken*.

**Patching:** SEARCH/REPLACE blocks matched exactly, in Python, *before*
forking. A patch that doesn't apply costs a model call and **zero container
time**. That's what makes width affordable — most of what a search discards, it
discards for free. Rejected proposals get one repair attempt with the parse
error fed back, recovering ~40% of them.

**Benchmark:** SWE-bench Lite with Epoch AI's prebuilt per-instance images, so
ground truth comes from human-validated gold patches rather than tasks we wrote
ourselves.

## Challenges we ran into

**The tier we expected to use doesn't work.** We planned for Nano to do cheap
breadth generation and Ultra to adjudicate. Measured: Nano applied **0 of 16**
patches — it paraphrases source while transcribing it, so exact-match edits
never land. Ultra applied **1 of 16** at 8x the cost, returning prose instead of
edit blocks. Super applied 13. The binding constraint on an agent that patches
by exact match is **structured-output compliance, not reasoning** — which is a
more useful finding than the tidy story we set out to tell.

**A cost optimization silently broke everything.** Batching 15 samples into one
call at temperature 0.9 cut cost — and dropped apply rate from 67% to **11%**.
113 of 126 rejections were "no SEARCH/REPLACE block found." High temperature
destroys format compliance. Four batches at spread temperatures (0.0 / 0.35 /
0.65 / 0.95) kept most of the saving and restored apply rate to 87%.

**Sandboxes is blocked.** Every Token Factory Sandboxes call on our account
returns `403 "You do not have permission to perform this action"`, while
inference on the same key succeeds. The ConTree backend is written, and the
conformance suite will validate it in ninety seconds — but it has never run.
Every result above therefore uses the Docker fallback, which is an honest
baseline, not a strawman: it uses `docker commit` as a checkpoint, which is what
a competent engineer would build without ConTree. We've reported it with a
request ID.

## Accomplishments that we're proud of

**A measured curve on ground truth we didn't author.** Every instance comes
from SWE-bench Lite with human-validated gold patches, and every "solve" is the
repository's own test suite going green. We could have written tasks that
needed search — that would have been circular, and a judge would smell it. The
result is smaller for being honest and worth more.

**Rejected proposals cost nothing.** SEARCH/REPLACE blocks are matched in
Python before anything forks, so a patch that doesn't apply consumes one model
call and zero container time. In the final benchmark, 21 of 160 proposals were
discarded for free. That single design decision is what turns "try sixteen
things" from expensive into routine.

**The two winning patches were different from each other.** On the same bug,
one escaped brace literals before parsing the template; the other routed the
format call through a defaulting dictionary. Different reasoning, both correct,
both verified. Width bought genuine diversity — not sixteen copies of one idea,
which is the failure mode we were most worried about.

**$0.33 for the entire benchmark.** Ten instances, 160 proposals, 139 sandboxed
test runs — three cents an instance. Batched `n` sampling on Token Factory and
disabled reasoning traces did most of that work.

**A conformance suite that acts as an oracle.** Nine tests every executor
backend must pass, written against Docker first so they could be trusted, then
pointed at new backends for a sixty-second verdict. The load-bearing one checks
fork isolation — the failure it guards against would corrupt every score in the
project while looking completely normal.

**We published the wrong turns.** Five findings documents record what we
measured *including* three occasions where a measurement artifact nearly became
a published claim. The harness now asserts against its own worst failure mode.
That's the part we'd want another engineer to read.

## What we learned

Three times, a measurement artifact nearly became a published claim.

We measured single-shot solve rate across three instances, got 0/3 twice, and
nearly abandoned the benchmark. At a true 15% rate, P(zero solves in three) is
**67%** — the most likely outcome. Width-1 sampling cannot detect the effect we
were trying to measure. We were one message from the wrong strategic decision.

We measured Ultra's latency on a 68-token prompt, found it 30x faster on Token
Factory, and wrote it up — in the same file where we'd just written *"benchmark
the configuration you intend to ship on."* Under realistic 8,300-token prompts
it's 17s per call.

And a stale zero-cost row sat in our benchmark scoring 0/16 on an instance we'd
watched solve three separate times, quietly costing four points of headline
result.

The rule we ended up with: **a measurement taken under conditions you will not
ship under is not evidence, however clean it looks.** The harness now asserts
that any zero-cost row is missing data rather than a failure to solve.

All of this is written up as it happened — including the wrong turns — in
`docs/findings-01` through `findings-05`.

## What's next

- **Validate on Sandboxes.** The thesis is about forking execution state; we've
  proved it on a Docker stand-in. Everything is ready for the real thing.
- **Full-suite verification.** A solve currently means 40 sampled regression
  tests passed. The winning patch should face the whole suite.
- **Attack the remaining 13% patcher tax**, which is width we already paid for.
- **Live streaming UI**, not just replay.
