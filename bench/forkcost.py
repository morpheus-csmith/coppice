"""Week-one gate: what does a fork actually cost?

The whole Coppice thesis is that breadth is cheap because setup is paid
once. This measures whether that is true, and by how much.

Three arms, deliberately including an honest baseline:

  cold      n x [fresh container -> full setup -> attempt]
            The strawman. Nobody competent builds this, but it is what
            naive agent loops actually do.

  prepared  1 x setup -> commit -> n x [container from image -> attempt]
            The honest baseline: Docker doing its best impression of
            ConTree. If we cannot beat THIS, the project has no thesis.

  contree   1 x setup -> n x fork -> attempt
            The real thing. Requires NEBIUS_API_KEY.

Run:
    python bench/forkcost.py --width 6 --concurrency 6
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import statistics
import sys
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from coppice.executor.docker_exec import DockerExecutor  # noqa: E402

# pip install dominates real migration setup, so the workload is shaped
# like that: expensive prepare, cheap attempt.
SETUP = (
    "pip install --quiet --disable-pip-version-check "
    "pytest requests flask sqlalchemy 2>&1 | tail -2 && "
    "mkdir -p /w && printf 'def test_ok():\\n    assert True\\n' > /w/test_smoke.py"
)
ATTEMPT = (
    "cd /w && printf 'def test_new():\\n    assert 1 + 1 == 2\\n' > test_new.py "
    "&& python -m pytest -q 2>&1 | tail -3"
)


@dataclass
class ArmResult:
    arm: str
    width: int
    concurrency: int
    setup_s: float
    attempts_wall_s: float
    attempt_mean_s: float
    attempt_median_s: float
    marginal_s: float          # wall time per additional attempt
    failures: int
    note: str = ""


async def _gather(coros, concurrency: int):
    sem = asyncio.Semaphore(concurrency)

    async def guarded(c):
        async with sem:
            return await c

    return await asyncio.gather(*(guarded(c) for c in coros), return_exceptions=True)


async def arm_cold(image: str, width: int, concurrency: int) -> ArmResult:
    ex = DockerExecutor()
    try:
        base = await ex.base(image)
        t0 = time.perf_counter()

        async def one():
            s = await base.run(SETUP, timeout_s=900)
            return await s.state.run(ATTEMPT, timeout_s=300)

        results = await _gather([one() for _ in range(width)], concurrency)
        wall = time.perf_counter() - t0
        durs = [r.duration_s for r in results if not isinstance(r, Exception)]
        fails = sum(1 for r in results if isinstance(r, Exception) or not r.ok)
        return ArmResult(
            "cold", width, concurrency, 0.0, wall,
            statistics.mean(durs) if durs else float("nan"),
            statistics.median(durs) if durs else float("nan"),
            wall / width, fails,
            "setup repeated per attempt",
        )
    finally:
        await ex.aclose()


async def arm_prepared(image: str, width: int, concurrency: int) -> ArmResult:
    ex = DockerExecutor()
    try:
        base = await ex.base(image)
        t_setup = time.perf_counter()
        prepared = (await base.run(SETUP, timeout_s=900)).state
        setup_s = time.perf_counter() - t_setup

        t0 = time.perf_counter()
        results = await _gather(
            [prepared.run(ATTEMPT, timeout_s=300) for _ in range(width)], concurrency
        )
        wall = time.perf_counter() - t0
        durs = [r.duration_s for r in results if not isinstance(r, Exception)]
        fails = sum(1 for r in results if isinstance(r, Exception) or not r.ok)
        return ArmResult(
            "prepared", width, concurrency, setup_s, wall,
            statistics.mean(durs) if durs else float("nan"),
            statistics.median(durs) if durs else float("nan"),
            wall / width, fails,
            "docker commit as checkpoint -- the honest baseline",
        )
    finally:
        await ex.aclose()


async def arm_overhead(image: str, width: int, concurrency: int) -> ArmResult:
    """Pure per-fork tax: prepared state, then N no-op forks, serially.

    `true` does no work, so every second measured here is backend
    overhead -- create, start, wait, commit, remove. This is the number
    ConTree has to beat, and the only one that is workload-independent.
    """
    ex = DockerExecutor()
    try:
        base = await ex.base(image)
        t_setup = time.perf_counter()
        prepared = (await base.run(SETUP, timeout_s=900)).state
        setup_s = time.perf_counter() - t_setup

        durs: list[float] = []
        t0 = time.perf_counter()
        for _ in range(width):
            r = await prepared.run("true", timeout_s=120)
            durs.append(r.duration_s)
        wall = time.perf_counter() - t0
        return ArmResult(
            "overhead", width, 1, setup_s, wall,
            statistics.mean(durs), statistics.median(durs),
            wall / width, 0,
            "serial no-op forks -- pure backend tax",
        )
    finally:
        await ex.aclose()


ARMS = {"cold": arm_cold, "prepared": arm_prepared, "overhead": arm_overhead}


def render(results: list[ArmResult]) -> None:
    print()
    hdr = f"{'ARM':<10} {'SETUP':>9} {'ATTEMPTS':>10} {'PER-ATTEMPT':>12} {'MEDIAN':>9} {'FAIL':>5}{'THRUPUT':>11}"
    print(hdr)
    print("-" * len(hdr))
    for r in results:
        print(
            f"{r.arm:<10} {r.setup_s:>8.1f}s {r.attempts_wall_s:>9.1f}s "
            f"{r.marginal_s:>11.2f}s {r.attempt_median_s:>8.2f}s {r.failures:>5}"
            f"{r.width / max(r.attempts_wall_s, 1e-9):>10.2f}/s"
        )
    print()
    by = {r.arm: r for r in results}
    if "overhead" in by:
        o = by["overhead"]
        print(f"  per-fork tax (docker) : {o.attempt_median_s:>6.2f}s  median, zero workload")
        print(f"  -> contree must beat  : {o.attempt_median_s:>6.2f}s  to justify the thesis")
    if "cold" in by and "prepared" in by:
        ratio = by["cold"].marginal_s / max(by["prepared"].marginal_s, 1e-9)
        print(f"  prepared vs cold      : {ratio:>6.1f}x cheaper per attempt")
    if "contree" in by and "prepared" in by:
        ratio = by["prepared"].marginal_s / max(by["contree"].marginal_s, 1e-9)
        print(f"  contree vs prepared   : {ratio:>6.1f}x cheaper per attempt   <-- THE GATE")
    print()


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--image", default="python:3.12")
    ap.add_argument("--width", type=int, default=6, help="parallel attempts")
    ap.add_argument("--concurrency", type=int, default=6)
    ap.add_argument("--arms", default="cold,prepared")
    args = ap.parse_args()

    results: list[ArmResult] = []
    for name in [a.strip() for a in args.arms.split(",") if a.strip()]:
        if name not in ARMS:
            print(f"!! unknown arm {name!r}, skipping")
            continue
        print(f"==> {name} (width={args.width}, concurrency={args.concurrency})")
        results.append(await ARMS[name](args.image, args.width, args.concurrency))

    render(results)

    out = Path("runs")
    out.mkdir(exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    path = out / f"forkcost-{stamp}.json"
    path.write_text(json.dumps([asdict(r) for r in results], indent=2))
    print(f"  written: {path}\n")


if __name__ == "__main__":
    asyncio.run(main())
