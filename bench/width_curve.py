"""The headline experiment: does solve rate actually rise with width?

Design note. The obvious approach -- run each width separately -- burns
1+2+4+8+16 = 31 proposals per instance to produce five points. Instead we
draw 16 samples once, evaluate all of them, and read the curve off by
subsampling: of all C(16,k) ways to pick k of our samples, what fraction
contain at least one solver?

That is an exact combinatorial estimate over the samples we actually
drew. It assumes nothing about independence between candidates -- which
matters, because samples from one model at spread temperatures are
correlated to an unknown degree, and a model-based curve would quietly
overstate what width buys.

Rejected proposals count as failures at their width. They cost no
container, but they did consume a slot, so counting them any other way
would flatter us.

    python bench/width_curve.py --samples 16
"""

from __future__ import annotations

import argparse
import asyncio
import json
import math
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from coppice.events import EventLog                      # noqa: E402
from coppice.executor.docker_exec import DockerExecutor   # noqa: E402
from coppice.models import Router                         # noqa: E402
from coppice.search import search                         # noqa: E402
from coppice.swebench import load_lite, to_task           # noqa: E402

INSTANCES = [
    "pylint-dev__pylint-7993",
    "pylint-dev__pylint-5859",
    "pylint-dev__pylint-7228",
    "pylint-dev__pylint-6506",
    "astropy__astropy-14365",
    "astropy__astropy-14182",
    "astropy__astropy-12907",
    "mwaskom__seaborn-3010",
    "pydata__xarray-4248",
    "pallets__flask-4992",
]
WIDTHS = [1, 2, 4, 8, 16]
OUT = Path("runs/width_curve.json")


def p_solve_at(n: int, solved: int, k: int) -> float:
    """P(a random k-subset of n samples contains >=1 solver). Exact."""
    if k > n:
        return float("nan")
    if solved == 0:
        return 0.0
    fails = n - solved
    if k > fails:
        return 1.0
    # C(fails,k)/C(n,k) = P(all k drawn are failures)
    return 1.0 - math.comb(fails, k) / math.comb(n, k)


def tally(log_path: Path) -> tuple[int, int, int]:
    """(asked, applied, solved) from one run's event log."""
    ev = [json.loads(l) for l in log_path.read_text().splitlines()]
    asked = sum(e.get("asked", 0) for e in ev if e["kind"] == "propose")
    applied = sum(e.get("applied", 0) for e in ev if e["kind"] == "propose")
    solved = sum(1 for e in ev if e["kind"] == "branch" and e.get("verdict") == "PASS")
    if solved == 0:
        solved = sum(e.get("solved_branches", 0) for e in ev if e["kind"] == "solved")
    return asked, applied, solved


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--samples", type=int, default=16)
    ap.add_argument("--tier", default="super")
    ap.add_argument("--instances", default=",".join(INSTANCES))
    args = ap.parse_args()

    wanted = [x.strip() for x in args.instances.split(",") if x.strip()]
    by_id = {i.instance_id: i for i in load_lite()}
    router = Router()
    OUT.parent.mkdir(exist_ok=True)
    results: list[dict] = []
    if OUT.exists():  # resume -- these runs are long, do not repeat work
        results = json.loads(OUT.read_text())
        done = {r["instance"] for r in results}
        wanted = [w for w in wanted if w not in done]
        if done:
            print(f"resuming; {len(done)} already done\n")

    print(f"{args.samples} samples per instance, tier={args.tier}\n")
    print(f"{'INSTANCE':<32}{'ASKED':>6}{'APPLIED':>8}{'SOLVED':>7}{'COST':>9}{'TIME':>7}")
    print("-" * 69)

    for iid in wanted:
        if iid not in by_id:
            print(f"  {iid}: unknown, skipping")
            continue
        task = to_task(by_id[iid])
        ex = DockerExecutor()
        log_path = Path(f"runs/width-{iid}.jsonl")
        log = EventLog(log_path, echo=False)
        t0, c0 = time.perf_counter(), router.ledger.total_cost
        try:
            await search(task, ex, router, log, width=args.samples,
                         beam=1, depth=1, propose_tier=args.tier)
            log.close()
            asked, applied, solved = tally(log_path)
            row = {"instance": iid, "asked": asked, "applied": applied,
                   "solved": solved, "cost": router.ledger.total_cost - c0,
                   "seconds": time.perf_counter() - t0}
        except Exception as e:
            log.close()
            row = {"instance": iid, "asked": 0, "applied": 0, "solved": 0,
                   "cost": router.ledger.total_cost - c0,
                   "seconds": time.perf_counter() - t0,
                   "error": f"{type(e).__name__}: {e}"[:120]}
        finally:
            await ex.aclose()

        # A row that cost nothing is a row where no model call happened --
        # a swallowed error, a stale resume, an interrupted run. Such a row
        # scores 0/16 and silently drags the published average down. This
        # has nearly reached a published claim three times; assert on it.
        if not row.get("error") and row["cost"] <= 0.0:
            row["error"] = "zero cost -- no model call was made; row is invalid"
            row["asked"] = 0

        results.append(row)
        OUT.write_text(json.dumps(results, indent=2))
        note = row.get("error", "")
        print(f"  {iid:<30}{row['asked']:>6}{row['applied']:>8}{row['solved']:>7}"
              f"{row['cost']:>8.4f}{row['seconds']:>6.0f}s {note}")

    # ---- the curve ----
    usable = [r for r in results if r["asked"] >= max(WIDTHS)]
    print(f"\n\nSOLVE RATE BY WIDTH   (n={len(usable)} instances, "
          f"{args.samples} samples each)\n")
    print(f"{'WIDTH':<8}{'SOLVE RATE':>12}{'INSTANCES SOLVED':>20}")
    print("-" * 40)
    for k in WIDTHS:
        per = [p_solve_at(r["asked"], r["solved"], k) for r in usable]
        rate = sum(per) / len(per) if per else float("nan")
        print(f"{k:<8}{rate:>11.1%}{sum(1 for p in per if p > 0):>15} / {len(per)}")

    solved_any = [r for r in usable if r["solved"] > 0]
    print(f"\n  instances with >=1 solve : {len(solved_any)}/{len(usable)}")
    tot_asked = sum(r["asked"] for r in usable)
    tot_solved = sum(r["solved"] for r in usable)
    if tot_asked:
        print(f"  pooled per-proposal rate : {tot_solved/tot_asked:.1%} "
              f"({tot_solved}/{tot_asked})")
    print(f"  total cost               : ${sum(r['cost'] for r in results):.4f}")
    print(f"\n  raw results: {OUT}")
    await router.aclose()


if __name__ == "__main__":
    asyncio.run(main())
