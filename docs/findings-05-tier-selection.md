# Finding 05 — Super is the proposer. Both neighbours fail, for opposite reasons.

**Date:** 2026-08-29 · pylint-dev__pylint-7993 · 16 proposals per tier · Token Factory

## Result

| tier | applied/16 | solved | cost | model time |
|---|---|---|---|---|
| Nano  | 0  | 0 | $0.0025 | 32s |
| **Super** | **13** | **3** | **$0.0566** | 203s |
| Ultra | 1  | 0 | $0.4552 | 538s |

## Why both neighbours fail

Not capability at the task -- **format compliance**.

Exact-match patching needs SEARCH text copied from the file character for
character. Nano paraphrases as it transcribes: it reformats a multi-line
signature onto one line, and the block no longer matches anything. Ultra
mostly declines to emit blocks at all, returning prose about what it would
change. Neither failure is about understanding the bug; both are about
producing a machine-checkable artefact.

Super sits in the band where the model is large enough to hold the format and
small enough not to editorialise.

## Cost consequence

At width 16 per instance: Super $0.057, Ultra $0.455. Against ~$50 of
hackathon credits that is roughly **880 instance-runs on Super versus 110 on
Ultra** -- and Ultra's runs solve nothing.

## The routing table was wrong

`models.ROLES` assumed Nano would carry ~80% of calls as the cheap breadth
tier, and reserved Ultra for judgement. Both halves are now unsupported:

- Nano cannot produce an applicable patch. 0 of 16.
- Ultra is slower, 8x dearer, and worse at the one thing breadth needs.

Breadth roles move to Super. Ultra is retained only for free-text roles where
no format is enforced (planning, final rationale) -- and even there its value
is **unmeasured**, so it is used sparingly and flagged as unvalidated.

## What this costs the pitch

The original plan's "Nano does the volume, Ultra adjudicates" story is
tidier than the truth. The truth is that one tier does nearly everything,
because structured-output compliance -- not reasoning -- is the binding
constraint on an agent that edits code by exact match.

That is a more useful finding for anyone building on Nemotron than the tidy
version would have been, and it goes in the submission as measured.

## Caveat

One instance, one sample per tier, reasoning off throughout. Enough to reject
Nano and Ultra as proposers; not enough to characterise the gap. Re-run across
the width-curve instance set before quoting the solve numbers.
