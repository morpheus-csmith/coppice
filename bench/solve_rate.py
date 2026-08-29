"""Can the model solve ANY of these at all?

This question comes before every other question we have. Beam search
amplifies a non-zero success probability; it cannot manufacture one. If
single-shot solve rate is 0/N, then search is an expensive way to fail
and the thesis is unmeasurable on this benchmark.

So: width 1, depth 1, one shot per instance. No search, no beam, no
pruning. Just "does the proposer ever produce a patch that turns the
suite green."

  python bench/solve_rate.py --tier super --think --instances a,b,c
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from coppice.events import EventLog          # noqa: E402
from coppice.executor.docker_exec import DockerExecutor  # noqa: E402
from coppice.models import Router            # noqa: E402
from coppice.search import search            # noqa: E402
from coppice.swebench import load_lite, to_task  # noqa: E402

DEFAULT = [
    "pylint-dev__pylint-7993",   # f2p=1  p2p=10   small file
    "astropy__astropy-14365",    # f2p=1  p2p=8
    "pallets__flask-4992",       # f2p=1  p2p=18   known-hard control
]


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tier", default="super", choices=["nano", "super", "ultra"])
    ap.add_argument("--think", action="store_true")
    ap.add_argument("--width", type=int, default=1)
    ap.add_argument("--depth", type=int, default=1)
    ap.add_argument("--instances", default=",".join(DEFAULT))
    args = ap.parse_args()

    wanted = [x.strip() for x in args.instances.split(",") if x.strip()]
    by_id = {i.instance_id: i for i in load_lite()}
    missing = [w for w in wanted if w not in by_id]
    if missing:
        raise SystemExit(f"unknown instances: {missing}")

    router = Router()
    rows = []
    print(f"tier={args.tier} think={args.think} width={args.width} depth={args.depth}\n")

    for iid in wanted:
        task = to_task(by_id[iid])
        ex = DockerExecutor()
        log = EventLog(Path(f"runs/solverate-{iid}.jsonl"), echo=False)
        t0 = time.perf_counter()
        before = router.ledger.total_cost
        try:
            res = await search(task, ex, router, log,
                               width=args.width, beam=1, depth=args.depth,
                               propose_tier=args.tier, propose_think=args.think)
            rows.append((iid, res.solved, res.branches_run,
                         router.ledger.total_cost - before,
                         time.perf_counter() - t0, ""))
        except Exception as e:
            rows.append((iid, False, 0, router.ledger.total_cost - before,
                         time.perf_counter() - t0, f"{type(e).__name__}"))
        finally:
            log.close()
            await ex.aclose()
        i, solved, br, cost, secs, err = rows[-1]
        mark = "SOLVED" if solved else (err or "no")
        print(f"  {i:<34} {mark:<10} branches={br:<3} ${cost:.4f} {secs:>6.0f}s")

    n = sum(1 for r in rows if r[1])
    print(f"\n  solve rate: {n}/{len(rows)}")
    print(f"  total cost: ${sum(r[3] for r in rows):.4f}")
    print()
    print(router.ledger.report())
    await router.aclose()


if __name__ == "__main__":
    asyncio.run(main())
