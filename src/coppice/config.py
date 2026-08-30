"""Provider configuration.

The submission must run on Nebius Token Factory -- that is a hackathon
rule, not a preference. But Token Factory onboarding requires a verified
bank card, and NVIDIA Build serves the same Nemotron models free with no
card, over the same OpenAI-compatible protocol.

So the provider is a config value, set once in .env, and nothing above
this module knows which one is in use. Switching is one line:

    COPPICE_PROVIDER=nvidia_build   # develop today
    COPPICE_PROVIDER=nebius         # submit on this

Model ids are overridable per tier because provider catalogues drift.
Verify them against the live endpoint with:

    python -m coppice.config --check
"""

from __future__ import annotations

import os
from pathlib import Path
from dataclasses import dataclass

from dotenv import load_dotenv

# Resolve .env from the package root rather than the call stack:
# bare load_dotenv(_ENV_PATH) calls find_dotenv(), which asserts when there
# is no calling file (REPL, `python -` with a heredoc).
_ENV_PATH = Path(__file__).resolve().parents[2] / ".env"

load_dotenv(_ENV_PATH)


@dataclass(frozen=True)
class Provider:
    name: str
    base_url: str
    api_key_env: str
    nano: str
    super_: str
    ultra: str

    @property
    def api_key(self) -> str:
        key = os.environ.get(self.api_key_env, "")
        if not key:
            raise RuntimeError(
                f"{self.api_key_env} is not set (provider={self.name}). "
                f"Add it to .env"
            )
        return key

    def model_for(self, tier: str) -> str:
        return {"nano": self.nano, "super": self.super_, "ultra": self.ultra}[tier]


PROVIDERS = {
    "nebius": Provider(
        name="nebius",
        base_url=os.environ.get(
            "NEBIUS_BASE_URL", "https://api.tokenfactory.us-central1.nebius.com/v1"
        ),
        api_key_env="NEBIUS_API_KEY",
        # Verified against Token Factory's live catalogue. The three models
        # use three different naming conventions -- "nvidia/NVIDIA-" doubled
        # and TitleCase for Nano, all-lowercase for Super, mixed for Ultra --
        # so these cannot be derived and must be copied exactly.
        nano=os.environ.get("MODEL_NANO", "nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B"),
        super_=os.environ.get("MODEL_SUPER", "nvidia/nemotron-3-super-120b-a12b"),
        ultra=os.environ.get("MODEL_ULTRA", "nvidia/Nemotron-3-Ultra-550b-a55b"),
    ),
    "nvidia_build": Provider(
        name="nvidia_build",
        base_url=os.environ.get("NVIDIA_BASE_URL", "https://integrate.api.nvidia.com/v1"),
        api_key_env="NVIDIA_API_KEY",
        # NVIDIA Build uses all-lowercase for all three. Deliberately NOT
        # shared with the Nebius block: the same model has a different id on
        # each provider, so a single MODEL_NANO override would break one.
        nano=os.environ.get("NVIDIA_MODEL_NANO", "nvidia/nemotron-3-nano-30b-a3b"),
        super_=os.environ.get("NVIDIA_MODEL_SUPER", "nvidia/nemotron-3-super-120b-a12b"),
        ultra=os.environ.get("NVIDIA_MODEL_ULTRA", "nvidia/nemotron-3-ultra-550b-a55b"),
    ),
}


def provider() -> Provider:
    name = os.environ.get("COPPICE_PROVIDER", "nebius")
    if name not in PROVIDERS:
        raise RuntimeError(f"unknown COPPICE_PROVIDER={name!r}; pick one of {list(PROVIDERS)}")
    return PROVIDERS[name]


def _check() -> None:
    """List the live catalogue and say whether our tier ids resolve."""
    import httpx

    p = provider()
    print(f"provider : {p.name}\nbase_url : {p.base_url}")
    r = httpx.get(
        f"{p.base_url}/models",
        headers={"Authorization": f"Bearer {p.api_key}"},
        timeout=30,
    )
    r.raise_for_status()
    ids = sorted(m["id"] for m in r.json().get("data", []))
    print(f"catalogue: {len(ids)} models\n")

    nemotron = [i for i in ids if "nemotron" in i.lower()]
    print("nemotron models offered:")
    for i in nemotron:
        print("   ", i)

    print("\nour tiers:")
    for tier in ("nano", "super", "ultra"):
        want = p.model_for(tier)
        print(f"    {tier:<6} {want:<40} {'OK' if want in ids else 'NOT FOUND'}")


if __name__ == "__main__":
    import sys

    if "--check" in sys.argv:
        _check()
    else:
        p = provider()
        print(f"{p.name} -> {p.base_url}")
