# Finding 07 — A claim survived three documents because nothing could check it

**Date:** 2026-08-31 · pylint-dev__pylint-7993 · width 16 · Sandboxes
**Status:** correction. The fourth time a measurement artifact nearly shipped.

## The claim

Three documents — the Devpost story, the Nebius questionnaire, and the demo
video script — said some version of this:

> The two winning patches were different from each other. One escaped brace
> literals before parsing the template; the other routed the format call
> through a defaulting dictionary. Different reasoning, both correct.

It was the emotional centre of the pitch. If width buys sixteen copies of one
guess, the whole thesis is a cost story with no upside. "Genuinely different
reasoning" is what makes breadth a *search* rather than a retry loop.

## Why it stood for days

It came from a real run. Somebody read two winning patches, saw they differed,
and wrote it down. That is normal engineering.

The problem is what happened next: **the patches were never committed.** The
event log recorded scores, verdicts, timings and test counts — everything
needed to compute the width curve — and threw away the artifact the claim was
about. Nothing in the repository could contradict the sentence, so nothing did.
It got copied into a second document, then a third.

Every other headline number in this project is recomputable from
`results/*.json` by a reader who distrusts us. This one was not, and that is
exactly the property that let it drift.

## The fix, then the correction

`search.py` now logs a unified diff for every solved branch, and the replay
page renders it. One re-run later, the winners were on disk:

```
re.findall(r"\{\{(.*?)\}\}|\{(.+?)(:.*)?\}", template)
re.findall(r"\{\{(.+?)(:.*)?\}\}|(\{(.+?)(:.*)?\})", template)
re.findall(r"{{|}}|\{([^}]+?)(:.*)?\}", template)   # + a separate filter pass
```

Three of twelve branches green. All three rewrote the **same** regex on the
**same** line. They differ in capture-group layout, and the third restructures
the loop with a filtering pass rather than tuple indexing — real differences a
reviewer would argue about, but not different *ideas*.

No defaulting dictionary appears anywhere in the run.

## What is actually true

**Width reliably buys implementation diversity.** Twelve applied patches were
not twelve copies; three independently reached a working fix by different
routes through the same insight. That is enough for search to function — the
scorer does not care why a branch is different, only that a fresh sample is a
fresh draw.

**Whether width buys *insight* diversity is unmeasured.** On this bug there was
plausibly only one insight available: the regex mishandles `{{`. A single-idea
bug cannot demonstrate multi-idea search. Answering the real question needs
instances with genuinely distinct valid approaches, and a way to classify a
patch's approach that is not one of us eyeballing three diffs.

Conflating those two is the error. We made it.

## The rule this adds

Findings 03, 04 and 06 all produced a version of *a measurement taken under
conditions you will not ship under is not evidence.* This one is different, and
narrower:

> **A claim whose evidence is not committed is not a finding. It is a memory.**

Memories are fine in conversation and fatal in a README. The test is
mechanical: for every claim in a document, name the file a hostile reader opens
to disprove it. If there is no such file, either produce one or delete the
sentence.

Applying that test to the rest of the repository is how this was caught, and it
is worth re-running before any future publication.

## Cost of the correction

$0.0484 and thirty-four seconds — one width-16 run on Sandboxes. On Docker the
same check would have taken about five minutes and, at width 16, had a
meaningful chance of segfaulting (see findings-06). Cheap verification is not a
nicety; it is what determines whether a claim gets checked at all.
