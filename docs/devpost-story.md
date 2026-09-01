## Inspiration

Coding agents mostly fail the same way: they try once. A model proposes a fix,
it doesn't work, and the run is over. But the failure isn't usually that the
model *can't* solve the problem — it's that it doesn't solve it *this time*.

We measured that. On the bugs in our benchmark, NVIDIA Nemotron 3 Super
succeeds on **11–16% of attempts** — and on the six instances where it has a
real shot, **19%**. One try fails four times in five. Sixteen tries, and one of
them is almost certainly right.

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
Nebius Token Factory, executed in Token Factory Sandboxes:

| attempts | all 10 instances | the 6 where the model has a real but unreliable shot |
|---:|---|---|
| 1  | 11% | 19% |
| 2  | 20% | 33% |
| 4  | 32% | 54% |
| 8  | 46% | **77%** |
| 16 | 60% | **100%** |

**6 of 10 solved, $0.29 for the whole sweep.** Three cents an instance —
160 proposals, 139 applied, each verified against the repository's own tests.

**The curve replicates.** We ran the identical benchmark twice on two different
executors, with fresh stochastic draws each time. The sweet-spot row came out
19 / 33 / 53 / 76 / 100 on Docker and 19 / 33 / 54 / 77 / 100 on Sandboxes —
within one point at every width, apply rate 87% on both, 6 of 10 solved on
both. The executor cannot change whether a patch is correct, so agreement was
the prediction; getting it checks the whole measurement chain at once — the
patcher, the scorer, the subsampling estimator, and both backends.

What the executor *does* change is what width costs. Per branch: **66.2s on
Docker, 4.4s on Sandboxes**. Twelve concurrent branches finish within 600
milliseconds of each other on Sandboxes; on Docker all twelve take 66.2s
because they are queueing, not working. Warm, a full 16-proposal instance
completes in about **30 seconds** against Docker's ~240.

The second column is the honest one. Four of the ten instances never solve
once in sixteen tries, and width does nothing for them — no amount of breadth
manufactures a capability the model lacks. The value is concentrated in the
other six: problems the model can *nearly* do. That band is where real agent
work lives, and reporting only the ten-instance average would understate the
effect where it exists while implying one where it doesn't.

The curve is computed by exact subsampling over samples actually drawn, not
modelled from an assumed independence between candidates. Every number is
reproducible from the committed data.

**What this is not.** These are 10 instances from 4 small repositories, chosen
for small target files and short regression suites so a width-16 sweep was
affordable. **This is not a SWE-bench Lite score and must not be read as one.**
A solve means the failing tests pass and 40 sampled regression tests still
pass, not the entire suite. The effect we are claiming — that breadth converts
an unreliable model into a reliable one within a measurable band — is real and
measured twice. The absolute numbers are not comparable to a leaderboard.

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
9-test conformance suite before it's trusted; both pass, 18/18. The
load-bearing test is fork isolation: if two runs from one state can see each other's writes, branches
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

**Sandboxes was blocked, then wasn't.** For most of the build, every Token
Factory Sandboxes call on our account returned `403 "You do not have permission
to perform this action"` while inference on the same key succeeded. We did the
only useful thing available: built the ConTree backend anyway, behind the same
`Executor` interface, and validated the thesis on a Docker fallback that uses
`docker commit` as a checkpoint — an honest baseline, not a strawman, since it
is what a competent engineer would build without ConTree. Then we reported it
with a request ID. Access was enabled, and the conformance suite passed
**18/18 across both backends on first contact** — including `test_fork_isolation
[contree]`, the one test the entire project rests on. The full benchmark
re-ran on Sandboxes the same day.

The lesson we'd keep: an abstraction you write before you can test it is a bet.
Making the conformance suite the thing that settles the bet — nine tests, sixty
seconds, one verdict — is what turned a blocked integration from a schedule
risk into a waiting task.

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

**The winning patches are different from each other — but less different than
we first claimed.** On pylint-7993, three of twelve branches turned the suite
green, and all three are committed as diffs in
`results/contree-pylint7993.jsonl` so this is checkable rather than asserted.
All three rewrote the same regex; they differ in how:

```
re.findall(r"\{\{(.*?)\}\}|\{(.+?)(:.*)?\}", template)
re.findall(r"\{\{(.+?)(:.*)?\}\}|(\{(.+?)(:.*)?\})", template)
re.findall(r"{{|}}|\{([^}]+?)(:.*)?\}", template)   # + a separate filter pass
```

Three implementations, one insight. We had written this up as "genuinely
different reasoning" from an earlier run whose patches we had not committed —
then we made the winners loggable, looked, and found the honest version is
narrower. Width buys *implementation* diversity reliably; whether it buys
*insight* diversity is a separate question we have not measured, and the two
should not be conflated. That distinction is now the top item in what's next.

**$0.29 for the entire benchmark.** Ten instances, 160 proposals, 139 sandboxed
test runs — three cents an instance. Batched `n` sampling on Token Factory and
disabled reasoning traces did most of that work.

**A conformance suite that acts as an oracle.** Nine tests every executor
backend must pass, written against Docker first so they could be trusted, then
pointed at new backends for a sixty-second verdict. The load-bearing one checks
fork isolation — the failure it guards against would corrupt every score in the
project while looking completely normal.

**We published the wrong turns.** Seven findings documents record what we
measured *including* four occasions where a measurement artifact nearly became
a published claim — the fourth being a diversity claim in this very document,
which we caught only by making the winning patches loggable and then looking at
them. The harness now asserts against its own worst failure mode.
That's the part we'd want another engineer to read.

## What we learned

Four times, something we believed nearly became a published claim.

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

Those three share a rule: **a measurement taken under conditions you will not
ship under is not evidence, however clean it looks.** The harness now asserts
that any zero-cost row is missing data rather than a failure to solve.

The fourth was different, and we found it last. "The two winning patches used
different reasoning" had been sitting in three of our documents — this one
included — sourced from a real run whose patches we never committed. Every
other headline number here is recomputable by a reader who distrusts us; that
one was not, so nothing could contradict it and it got copied twice. We made
the winners loggable, re-ran, and found the honest version is narrower.

Its rule is narrower too: **a claim whose evidence is not committed is not a
finding, it is a memory.** The test is mechanical — for every claim in a
document, name the file a hostile reader opens to disprove it. If there is no
such file, produce one or delete the sentence.

All of this is written up as it happened — including the wrong turns — in
`docs/findings-01` through `findings-07`.

## What's next for Coppice

- **Measure insight diversity, not just patch diversity.** Our three winners
  were three implementations of one idea. Whether width ever finds two
  genuinely different *approaches* is the more interesting question and we
  cannot yet answer it.
- **Full-suite verification.** A solve currently means 40 sampled regression
  tests passed. The winning patch should face the whole suite.
- **Attack the remaining 13% patcher tax**, which is width we already paid for.
- **Line-anchor the matcher.** SEARCH strings are matched as substrings, so one
  can match mid-token and apply cleanly while corrupting an identifier. We
  found it writing the unit tests, asserted it rather than quietly fixing it —
  changing the matcher changes the apply rate, and 87% was measured against
  this one.
- **Live streaming UI**, not just replay.
