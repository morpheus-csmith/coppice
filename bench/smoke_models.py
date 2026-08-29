"""Smoke-test all three tiers: reachable, coherent, and accounted for."""

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
    print(f"provider: {r.p.name}  ({r.p.base_url})\n")
    for tier in ("nano", "super", "ultra"):
        try:
            reply = await r.chat(tier, PROMPT, temperature=0.2, max_tokens=300)
            answer = " ".join(reply.text.strip().split())[:110]
            print(f"[{tier:<5}] {reply.seconds:>5.1f}s  {answer}")
        except Exception as e:
            print(f"[{tier:<5}] FAILED  {type(e).__name__}: {str(e)[:160]}")
    print()
    print(r.ledger.report())
    await r.aclose()


if __name__ == "__main__":
    asyncio.run(main())
