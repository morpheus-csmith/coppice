"""Turn a width-curve run into the result table the submission reports.

The aggregate curve averages three populations that behave completely
differently (findings-04): instances the model already solves reliably,
instances where it has a real but unreliable shot, and instances it never
solves. Reporting only the average understates the effect where it exists
and implies one where it does not.

    python bench/analyze.py [runs/width_curve.json]
"""

from __future__ import annotations

import json
import math
import sys
from pathlib import Path

WIDTHS = [1, 2, 4, 8, 16]


def p_solve_at(n: int, solved: int, k: int) -> float:
    """P(a random k-subset of n samples contains >=1 solver). Exact."""
    if solved == 0 or k > n:
        return 0.0 if solved == 0 else float("nan")
    fails = n - solved
    return 1.0 if k > fails else 1.0 - math.comb(fails, k) / math.comb(n, k)


def main(path: Path) -> None:
    rows = [r for r in json.loads(path.read_text()) if r.get("asked")]
    rows.sort(key=lambda r: (-r["solved"] / r["asked"], r["instance"]))

    print(f"\n{path}   n={len(rows)} instances\n")
    hdr = f"{'INSTANCE':<26}{'APPLIED':>9}{'SOLVED':>8}{'PER-SHOT':>10}{'COST':>9}"
    print(hdr + "".join(f"{'w'+str(k):>7}" for k in WIDTHS))
    print("-" * (len(hdr) + 7 * len(WIDTHS)))
    for r in rows:
        n, s = r["asked"], r["solved"]
        cells = "".join(f"{p_solve_at(n, s, k):>6.0%} " for k in WIDTHS)
        print(f"{r['instance']:<26}{r['applied']:>4}/{n:<4}{s:>6}/{n:<2}"
              f"{s/n:>9.0%}{r['cost']:>9.4f}{cells}")

    bands = {
        "already easy  (>50% per shot)": [r for r in rows if r["solved"]/r["asked"] > 0.5],
        "SWEET SPOT    (1-50%)":         [r for r in rows if 0 < r["solved"]/r["asked"] <= 0.5],
        "out of reach  (0 in 16)":       [r for r in rows if r["solved"] == 0],
    }
    print(f"\n{'REGIME':<32}{'n':>4}" + "".join(f"{'w'+str(k):>8}" for k in WIDTHS))
    print("-" * (36 + 8 * len(WIDTHS)))
    for label, rs in bands.items():
        if not rs:
            continue
        cells = "".join(
            f"{sum(p_solve_at(r['asked'], r['solved'], k) for r in rs)/len(rs):>7.0%} "
            for k in WIDTHS
        )
        print(f"{label:<32}{len(rs):>4}{cells}")

    print(f"\n{'ALL INSTANCES':<32}{len(rows):>4}" + "".join(
        f"{sum(p_solve_at(r['asked'], r['solved'], k) for r in rows)/len(rows):>7.0%} "
        for k in WIDTHS
    ))

    asked = sum(r["asked"] for r in rows)
    applied = sum(r["applied"] for r in rows)
    solved = sum(r["solved"] for r in rows)
    cost = sum(r["cost"] for r in rows)
    print(f"\n  apply rate       : {applied}/{asked} = {applied/asked:.0%}"
          f"   (patcher tax {1-applied/asked:.0%})")
    print(f"  per-proposal     : {solved}/{asked} = {solved/asked:.1%}")
    print(f"  per-applied      : {solved}/{applied} = {solved/applied:.1%}")
    print(f"  instances solved : {sum(1 for r in rows if r['solved'])}/{len(rows)}")
    print(f"  total cost       : ${cost:.4f}   (${cost/len(rows):.4f}/instance)\n")


if __name__ == "__main__":
    main(Path(sys.argv[1] if len(sys.argv) > 1 else "runs/width_curve.json"))
