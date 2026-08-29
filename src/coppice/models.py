"""Tiered Nemotron client.

Three tiers, one router. The tier split is not decoration -- it is the
cost strategy. Nano does the breadth (many cheap candidates), Super
repairs its own near-misses, Ultra is called a handful of times per run
where a wrong decision wastes a whole generation.

Two things this layer owns because nothing above it can:

* **Rate limiting.** Free-tier NVIDIA Build allows ~40 req/min. Branch
  generation is bursty by construction, so without a limiter here the
  first width-8 expansion earns a wall of 429s. The limiter is per
  router, shared across tiers, because the quota is.

* **Accounting.** Every call's token usage is recorded per tier. Tokens
  are the hard number; cost is derived from a price table that must be
  verified against live pricing before any of it goes in the submission.
"""

from __future__ import annotations

import asyncio
import time
from collections import defaultdict
from dataclasses import dataclass, field

from openai import AsyncOpenAI
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from .config import Provider, provider

# USD per 1M tokens (input, output).
#
# ULTRA IS VERIFIED against Nebius published pricing ($1.00 / $3.00).
# NANO AND SUPER ARE ESTIMATES and must be confirmed before any cost
# figure derived from them appears in the submission. Token counts below
# are always exact; only the multiplication is uncertain.
PRICES: dict[str, tuple[float, float]] = {
    "nano": (0.10, 0.30),    # UNVERIFIED
    "super": (0.30, 0.90),   # UNVERIFIED
    "ultra": (1.00, 3.00),   # verified
}
VERIFIED = {"ultra"}


@dataclass
class TierUsage:
    calls: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    seconds: float = 0.0

    @property
    def cost(self) -> float:
        return 0.0  # filled by Ledger, which knows the tier name


@dataclass
class Ledger:
    """Per-tier accounting. The cost story of the whole project lives here."""

    tiers: dict[str, TierUsage] = field(default_factory=lambda: defaultdict(TierUsage))

    def record(self, tier: str, prompt: int, completion: int, seconds: float) -> None:
        u = self.tiers[tier]
        u.calls += 1
        u.prompt_tokens += prompt
        u.completion_tokens += completion
        u.seconds += seconds

    def cost_for(self, tier: str) -> float:
        u = self.tiers[tier]
        pin, pout = PRICES[tier]
        return (u.prompt_tokens * pin + u.completion_tokens * pout) / 1_000_000

    @property
    def total_cost(self) -> float:
        return sum(self.cost_for(t) for t in self.tiers)

    def report(self) -> str:
        rows = [
            f"{'TIER':<7}{'CALLS':>7}{'PROMPT':>10}{'OUTPUT':>10}{'SECONDS':>9}{'COST':>10}"
        ]
        rows.append("-" * len(rows[0]))
        for tier in ("nano", "super", "ultra"):
            if tier not in self.tiers:
                continue
            u = self.tiers[tier]
            flag = "" if tier in VERIFIED else "*"
            rows.append(
                f"{tier:<7}{u.calls:>7}{u.prompt_tokens:>10}{u.completion_tokens:>10}"
                f"{u.seconds:>8.1f}s{'$' + format(self.cost_for(tier), '.4f'):>10}{flag}"
            )
        rows.append("-" * len(rows[0]))
        rows.append(f"{'total':<7}{'':>7}{'':>10}{'':>10}{'':>9}{'$' + format(self.total_cost, '.4f'):>10}")
        if any(t not in VERIFIED for t in self.tiers):
            rows.append("* price estimated -- verify against live pricing before quoting")
        return "\n".join(rows)


# Role -> (tier, think). One place, so the routing policy is a table you
# can read rather than behaviour scattered through the search loop.
#
# Breadth runs with reasoning OFF: measured at ~25x fewer output tokens
# with no accuracy loss on transformation-shaped tasks (see
# docs/findings-02-reasoning-cost.md). Planning and adjudication keep it
# ON -- those are the judgement calls, made a handful of times per run,
# where the token cost is irrelevant and being wrong is expensive.
ROLES: dict[str, tuple[str, bool]] = {
    "propose":    ("nano",  False),  # generate candidate patches at width
    "triage":     ("nano",  False),  # classify a failing test log
    "repair":     ("super", False),  # fix a near-miss inside one branch
    "adjudicate": ("ultra", True),   # rank tied branches
    "plan":       ("ultra", True),   # decompose the migration up front
    "explain":    ("ultra", True),   # write the final diff rationale
}


class RateLimiter:
    """Simple sliding-window limiter. Shared across tiers -- quota is per key."""

    def __init__(self, per_minute: int):
        self.per_minute = per_minute
        self._hits: list[float] = []
        self._lock = asyncio.Lock()

    async def acquire(self) -> None:
        while True:
            async with self._lock:
                now = time.monotonic()
                self._hits = [t for t in self._hits if now - t < 60.0]
                if len(self._hits) < self.per_minute:
                    self._hits.append(now)
                    return
                sleep_for = 60.0 - (now - self._hits[0]) + 0.05
            await asyncio.sleep(sleep_for)


@dataclass
class Reply:
    text: str
    tier: str
    prompt_tokens: int
    completion_tokens: int
    seconds: float


class Router:
    def __init__(
        self,
        p: Provider | None = None,
        *,
        per_minute: int | None = None,
        max_concurrency: int = 8,
    ):
        self.p = p or provider()
        self.client = AsyncOpenAI(api_key=self.p.api_key, base_url=self.p.base_url)
        # NVIDIA Build free tier is ~40/min; Token Factory is far higher.
        default_rpm = 35 if self.p.name == "nvidia_build" else 300
        self.limiter = RateLimiter(per_minute or default_rpm)
        self.sem = asyncio.Semaphore(max_concurrency)
        self.ledger = Ledger()

    @retry(
        stop=stop_after_attempt(4),
        wait=wait_exponential(multiplier=1, min=2, max=30),
        retry=retry_if_exception_type(Exception),
        reraise=True,
    )
    async def _call(self, tier: str, messages: list[dict], **kw):
        await self.limiter.acquire()
        async with self.sem:
            return await self.client.chat.completions.create(
                model=self.p.model_for(tier), messages=messages, **kw
            )

    async def chat(
        self,
        tier: str,
        prompt: str,
        *,
        system: str | None = None,
        temperature: float = 0.7,
        max_tokens: int = 2048,
        think: bool | None = None,
        **kw,
    ) -> Reply:
        """think=False suppresses reasoning traces.

        Nemotron 3 reasoning arrives inside `content` and is billed as
        output tokens, so leaving it on for breadth generation means
        paying for prose we discard. Two mechanisms exist and the docs
        disagree across model generations, so we send both: Nemotron 3
        honours chat_template_kwargs, older Llama-Nemotron honours the
        system prompt directive. The unused one is ignored.
        """
        if think is False:
            extra = dict(kw.pop("extra_body", {}) or {})
            ctk = dict(extra.get("chat_template_kwargs", {}) or {})
            ctk["enable_thinking"] = False
            extra["chat_template_kwargs"] = ctk
            kw["extra_body"] = extra
            system = system or "/no_think"
            temperature = 0.0
        elif think is True:
            extra = dict(kw.pop("extra_body", {}) or {})
            ctk = dict(extra.get("chat_template_kwargs", {}) or {})
            ctk["enable_thinking"] = True
            extra["chat_template_kwargs"] = ctk
            kw["extra_body"] = extra

        messages = ([{"role": "system", "content": system}] if system else []) + [
            {"role": "user", "content": prompt}
        ]
        t0 = time.perf_counter()
        resp = await self._call(
            tier, messages, temperature=temperature, max_tokens=max_tokens, **kw
        )
        elapsed = time.perf_counter() - t0

        usage = getattr(resp, "usage", None)
        pt = getattr(usage, "prompt_tokens", 0) or 0
        ct = getattr(usage, "completion_tokens", 0) or 0
        self.ledger.record(tier, pt, ct, elapsed)

        return Reply(
            text=resp.choices[0].message.content or "",
            tier=tier,
            prompt_tokens=pt,
            completion_tokens=ct,
            seconds=elapsed,
        )

    async def act(self, role: str, prompt: str, **kw) -> Reply:
        """Call by role rather than by tier. Prefer this in the search loop."""
        tier, think = ROLES[role]
        kw.setdefault("think", think)
        return await self.chat(tier, prompt, **kw)

    async def nano(self, prompt: str, **kw) -> Reply:
        return await self.chat("nano", prompt, **kw)

    async def super_(self, prompt: str, **kw) -> Reply:
        return await self.chat("super", prompt, **kw)

    async def ultra(self, prompt: str, **kw) -> Reply:
        return await self.chat("ultra", prompt, **kw)

    async def aclose(self) -> None:
        await self.client.close()
