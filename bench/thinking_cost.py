"""What do reasoning traces cost us, per tier?

Nemotron 3 returns reasoning inside `content` and bills it as output
tokens. Breadth generation discards that prose entirely -- we want a
patch, not an essay -- so if thinking can be switched off cheaply, it is
the single largest lever on our token budget.

Runs one realistic migration question against each tier, twice.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from coppice.models import Router  # noqa: E402

PROMPT = (
    "A Python project pins `requests==2.19` and calls "
    "`requests.packages.urllib3.disable_warnings()`. That import path was "
    "removed in later versions. Give the one-line modern replacement. "
    "Answer with code only, no prose."
)


async def main() -> None:
    r = Router()
    print(f"provider: {r.p.name}\n")
    hdr = f"{'TIER':<7}{'THINK':<7}{'OUT TOK':>9}{'SECONDS':>9}  ANSWER"
    print(hdr)
    print("-" * 92)

    stats: dict[tuple[str, bool], tuple[int, float]] = {}
    for tier in ("nano", "super", "ultra"):
        for think in (True, False):
            try:
                reply = await r.chat(
                    tier, PROMPT, think=think, max_tokens=1200,
                    temperature=0.2 if think else 0.0,
                )
                answer = " ".join(reply.text.strip().split())[:44]
                stats[(tier, think)] = (reply.completion_tokens, reply.seconds)
                print(
                    f"{tier:<7}{str(think):<7}{reply.completion_tokens:>9}"
                    f"{reply.seconds:>8.1f}s  {answer}"
                )
            except Exception as e:
                print(f"{tier:<7}{str(think):<7}{'--':>9}{'--':>9}  "
                      f"FAILED {type(e).__name__}: {str(e)[:60]}")

    print("\nreduction from disabling reasoning:")
    for tier in ("nano", "super", "ultra"):
        on, off = stats.get((tier, True)), stats.get((tier, False))
        if not on or not off:
            continue
        tok = on[0] / max(off[0], 1)
        spd = on[1] / max(off[1], 1e-9)
        print(f"  {tier:<6} {tok:>5.1f}x fewer output tokens   {spd:>5.1f}x faster")

    print()
    print(r.ledger.report())
    await r.aclose()


if __name__ == "__main__":
    asyncio.run(main())
