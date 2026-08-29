"""Beam search over execution state.

The loop: from a verified checkpoint, generate k candidate rewrites of
the target file, apply each in its own fork, run the suite in all of
them, score against the baseline, keep the best b, repeat.

Two choices worth defending:

**Full-file rewrites, not diffs.** Models produce unreliable unified
diffs -- wrong line numbers, drifting context -- and a failed `git apply`
wastes a whole branch on a formatting error rather than a reasoning one.
Rewriting one small file is far more robust. This will not scale to
large files and we will revisit it with SEARCH/REPLACE blocks; for now
correctness of the *search* matters more than generality of the patcher.

**Temperature is spread across candidates.** Candidate 0 runs greedy --
the model's best single guess. The rest climb toward 1.0. k identical
samples is not a search, and diversity is the only thing width buys.
"""

from __future__ import annotations

import argparse
import asyncio
import difflib
import uuid
from dataclasses import dataclass, field
from pathlib import Path

from .events import EventLog
from .models import Router
from .patcher import PatchError, apply_text
from .scoring import Score, TestOutcome, parse_pytest, score_branch
from .tasks import TASKS, Task

SYSTEM = """You are a code-editing tool. You reply ONLY with edit blocks
in this exact format, and nothing else:

<<<<<<< SEARCH
lines copied verbatim from the file
=======
replacement lines
>>>>>>> REPLACE

Rules that are not negotiable:
- Copy SEARCH text character-for-character from the file shown to you.
  Never retype it from memory, never reformat it, never join wrapped
  lines. If the file wraps a signature across four lines, your SEARCH
  block wraps it across the same four lines.
- SEARCH must appear exactly once in the file. Add adjacent lines for
  uniqueness if needed.
- No prose, no explanation, no markdown fences. Blocks only.
"""

PROMPT = """You are fixing a bug in one file of a real codebase.

GOAL
{goal}

CURRENT SOURCE
{context}

TEST OUTPUT (what is failing now)
{failures}

Edit {target} so the failing tests pass without breaking the others.

Reply with one or more edit blocks in exactly this format:

<<<<<<< SEARCH
lines copied exactly from the current source
=======
what they should become
>>>>>>> REPLACE

The SEARCH text must match the file character for character, including
indentation, and must appear exactly once. Include a few surrounding
lines if needed to make it unique. Change only what the fix requires.
Output blocks only -- no explanation.

Worked example. Given this source:

    class Config(dict):
        def from_file(
            self,
            filename: str,
            load: t.Callable[[t.IO[t.Any]], t.Mapping],
        ) -> bool:
            with open(filename) as f:
                obj = load(f)

a correct reply adding a parameter looks like:

<<<<<<< SEARCH
        load: t.Callable[[t.IO[t.Any]], t.Mapping],
    ) -> bool:
        with open(filename) as f:
=======
        load: t.Callable[[t.IO[t.Any]], t.Mapping],
        text: bool = True,
    ) -> bool:
        with open(filename, "r" if text else "rb") as f:
>>>>>>> REPLACE

Note the SEARCH block keeps the original line breaks and indentation exactly.
"""

def _strip_fences(text: str) -> str:
    t = text.strip()
    if t.startswith("```"):
        lines = t.splitlines()[1:]
        if lines and lines[-1].strip().startswith("```"):
            lines = lines[:-1]
        t = "\n".join(lines)
    return t.strip() + "\n"


def _changed_lines(before: str, after: str) -> int:
    diff = difflib.unified_diff(before.splitlines(), after.splitlines(), n=0)
    return sum(1 for l in diff if l.startswith(("+", "-")) and not l.startswith(("+++", "---")))


def _budget_for(source: str) -> int:
    """Output budget for a whole-file rewrite.

    A rewrite must emit the entire file, so the budget has to scale with
    it. Too small and every candidate is truncated -- which produces a
    syntax error, scores -100, and looks exactly like a model that cannot
    code. Roughly 3 chars per token for source, plus headroom.
    """
    return max(1500, min(12000, len(source) // 3 + 800))


def _temperatures(k: int) -> list[float]:
    """Candidate 0 greedy, the rest spread toward 1.0."""
    if k <= 1:
        return [0.0]
    return [0.0] + [0.4 + 0.6 * i / (k - 1) for i in range(1, k)]


@dataclass
class Node:
    state: object
    content: str
    outcome: TestOutcome
    failures: str = ""      # test output FOR THIS node, not the run
    score: float = 0.0
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:8])
    parent: str | None = None
    depth: int = 0


@dataclass
class SearchResult:
    solved: bool
    best: Node
    generations: int
    branches_run: int
    cost_usd: float


async def search(
    task: Task,
    executor,
    router: Router,
    log: EventLog,
    *,
    width: int = 6,
    beam: int = 2,
    depth: int = 3,
    propose_tier: str | None = None,
    propose_think: bool | None = None,
) -> SearchResult:
    log.emit("run.start", task=task.name, width=width, beam=beam, depth=depth,
             backend=executor.name, provider=router.p.name)

    # ---- prepare once; every branch below inherits this for free ----
    base = await executor.base(task.image)
    prep = await base.run(task.setup, stdin=task.setup_stdin, timeout_s=900)
    if not prep.ok:
        log.emit("setup.failed", stderr=prep.tail(12))
        raise RuntimeError("task setup failed")
    root_state = prep.state
    log.emit("setup.done", seconds=round(prep.duration_s, 1))

    original = (await root_state.run(f"cat {task.target}")).stdout
    # Static context -- test sources do not change as we patch, so this is
    # fetched once. The TARGET file is per-node and must never come from here.
    extra_context = (await root_state.run(task.context_cmd)).stdout
    baseline_run = await root_state.run(task.test_cmd, timeout_s=300)
    baseline = parse_pytest(baseline_run.stdout + baseline_run.stderr)
    log.emit("baseline", outcome=str(baseline), green=baseline.green)

    baseline_out = baseline_run.stdout + baseline_run.stderr
    if baseline.green:
        return SearchResult(
            True, Node(root_state, original, baseline, baseline_out), 0, 0, 0.0
        )

    frontier = [Node(root_state, original, baseline, baseline_out)]
    branches_run = 0
    lenient_used = 0

    for gen in range(1, depth + 1):
        log.emit("gen.start", gen=gen, frontier=len(frontier))
        scored: list[tuple[float, Node]] = []

        for parent in frontier:
            prompt = PROMPT.format(
                goal=task.goal,
                context=(f"--- {task.target} ---\n{parent.content}\n\n"
                         f"{extra_context}"),
                failures=parent.failures,
                target=task.target,
            )
            replies = await asyncio.gather(
                *[
                    (
                        router.chat(propose_tier, prompt, system=SYSTEM,
                                    think=(False if propose_think is None
                                           else propose_think),
                                    temperature=t,
                                    max_tokens=12000 if propose_think else 2500)
                        if propose_tier
                        else router.act("propose", prompt, system=SYSTEM,
                                        temperature=t,
                                        max_tokens=12000 if propose_think else 2500,
                                        **({} if propose_think is None
                                           else {"think": propose_think}))
                    )
                    for t in _temperatures(width)
                ],
                return_exceptions=True,
            )

            # Apply locally first. A candidate whose blocks do not match is
            # rejected here, in Python, and never costs a container. This is
            # what makes width cheap: bad proposals are free.
            candidates: list[str] = []
            rejected = 0
            for r in replies:
                if isinstance(r, Exception):
                    rejected += 1
                    continue
                try:
                    patched, lenient = apply_text(parent.content, r.text)
                    lenient_used += int(lenient)
                    candidates.append(patched)
                except PatchError as e:
                    rejected += 1
                    log.emit("proposal.rejected", gen=gen, parent=parent.id,
                             reason=str(e)[:90])
            log.emit("propose", gen=gen, parent=parent.id, asked=width,
                     applied=len(candidates), rejected=rejected,
                     lenient=lenient_used)

            # k forks of the SAME checkpoint. No re-setup, ever.
            runs = await asyncio.gather(
                *[
                    parent.state.run(
                        f"cat > {task.target} && {task.test_cmd}",
                        stdin=c,
                        timeout_s=300,
                    )
                    for c in candidates
                ],
                return_exceptions=True,
            )

            # Score every branch before returning. The forks have already
            # run -- gather awaited them -- so stopping early does not save
            # work, it only loses the statistic we most need: how many of k
            # succeeded. Solve rate per generation is the number that says
            # whether width is buying anything.
            solved_here: list[tuple[float, Node]] = []

            for content, r in zip(candidates, runs):
                branches_run += 1
                if isinstance(r, Exception):
                    log.emit("branch", gen=gen, parent=parent.id,
                             verdict="error", detail=type(r).__name__)
                    continue
                outcome = parse_pytest(r.stdout + r.stderr)
                s: Score = score_branch(
                    baseline, outcome, _changed_lines(original, content)
                )
                child = Node(r.state, content, outcome,
                             r.stdout + r.stderr, s.value,
                             parent=parent.id, depth=gen)
                log.emit("branch", gen=gen, id=child.id, parent=parent.id,
                         verdict="PASS" if s.solved else "fail",
                         score=round(s.value, 2), tests=str(outcome),
                         seconds=round(r.duration_s, 1))

                if s.solved:
                    solved_here.append((s.value, child))
                else:
                    scored.append((s.value, child))

            if solved_here:
                solved_here.sort(key=lambda pair: pair[0], reverse=True)
                best_solved = solved_here[0][1]
                log.emit("solved", gen=gen, id=best_solved.id,
                         solved_branches=len(solved_here),
                         of_candidates=len(candidates),
                         branches_run=branches_run,
                         cost=round(router.ledger.total_cost, 4))
                return SearchResult(True, best_solved, gen, branches_run,
                                    router.ledger.total_cost)

        if not scored:
            log.emit("gen.dead", gen=gen)
            break

        scored.sort(key=lambda p: p[0], reverse=True)
        frontier = [n for _, n in scored[:beam]]
        log.emit("gen.prune", gen=gen, kept=len(frontier),
                 discarded=len(scored) - len(frontier),
                 best=round(scored[0][0], 2))

    best = frontier[0] if frontier else Node(root_state, original, baseline,
                                             baseline_out)
    log.emit("run.end", solved=False, branches_run=branches_run,
             cost=round(router.ledger.total_cost, 4))
    return SearchResult(False, best, depth, branches_run, router.ledger.total_cost)


async def _main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--task", default="widgets-2.0")
    ap.add_argument("--backend", default="docker", choices=["docker", "contree"])
    ap.add_argument("--width", type=int, default=6)
    ap.add_argument("--beam", type=int, default=2)
    ap.add_argument("--depth", type=int, default=3)
    ap.add_argument("--propose-tier", default=None,
                    choices=["nano", "super", "ultra"],
                    help="override the tier used for candidate generation")
    ap.add_argument("--think", dest="propose_think", action="store_true",
                    default=None, help="reasoning ON for candidate generation")
    ap.add_argument("--max-p2p", type=int, default=40,
                    help="regression tests sampled per branch")
    ap.add_argument("--log", default=None)
    args = ap.parse_args()

    if args.task in TASKS:
        task = TASKS[args.task]
    else:  # treat it as a SWE-bench instance id
        from .swebench import load_lite, to_task

        match = [i for i in load_lite() if i.instance_id == args.task]
        if not match:
            raise SystemExit(f"unknown task {args.task!r}")
        task = to_task(match[0], max_p2p=args.max_p2p)
        print(f"swe-bench: {task.name}  target={task.target}")

    if args.backend == "docker":
        from .executor.docker_exec import DockerExecutor

        ex = DockerExecutor()
    else:
        from .executor.contree_exec import ContreeExecutor

        ex = ContreeExecutor()

    router = Router()
    log = EventLog(Path(args.log) if args.log else Path("runs/search-latest.jsonl"))
    try:
        res = await search(task, ex, router, log,
                           width=args.width, beam=args.beam, depth=args.depth,
                           propose_tier=args.propose_tier,
                           propose_think=args.propose_think)
        print()
        print(f"  solved       : {res.solved}")
        print(f"  generations  : {res.generations}")
        print(f"  branches run : {res.branches_run}")
        print(f"  model cost   : ${res.cost_usd:.4f}")
        if res.solved:
            print("\n--- winning file ---")
            print(res.best.content)
        print(router.ledger.report())
    finally:
        log.close()
        await router.aclose()
        await ex.aclose()


if __name__ == "__main__":
    asyncio.run(_main())
