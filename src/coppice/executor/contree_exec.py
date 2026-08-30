"""ConTree backend -- the primary executor.

Two things about this SDK are load-bearing and non-obvious. Both were
found by reading the installed source, and both silently destroy beam
search if you get them wrong.

1. `run()` does not execute. It is a builder: it copies the image,
   attaches a RunRequest, and returns a *prepared* image. Awaiting that
   object is what actually runs it.

2. `disposable` defaults to **True**, which discards the resulting image
   after execution. A discarded image has no uuid, so `run()` on it
   raises DisposableImageRunError. Every state we intend to fork from
   must be created with `disposable=False`. Forgetting this does not
   fail at the fork -- it fails one level deeper, looking like an API
   bug rather than our mistake.

The SDK reports `cost` per run, so unlike the Docker backend this one
returns real spend rather than None.
"""

from __future__ import annotations

import os
from pathlib import Path
import time

from contree_sdk import Contree
from dotenv import load_dotenv

# Resolve .env from the package root rather than the call stack:
# bare load_dotenv(_ENV_PATH) calls find_dotenv(), which asserts when there
# is no calling file (REPL, `python -` with a heredoc).
_ENV_PATH = Path(__file__).resolve().parents[3] / ".env"
from contree_sdk.sdk.exceptions import (
    ApiTimeoutError,
    CancelledOperationError,
    FailedOperationError,
    OperationTimedOutError,
)

from .base import ExecResult

_TIMEOUTS = (OperationTimedOutError, ApiTimeoutError)


def _text(value) -> str:
    """stdout/stderr come back as str when no sink was requested."""
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", "replace")
    return str(value)


class ContreeState:
    """A ConTree image. Forking = awaiting run() on it more than once."""

    __slots__ = ("_ex", "_img", "id", "depth")

    def __init__(self, ex: "ContreeExecutor", img, depth: int):
        self._ex = ex
        self._img = img
        self.id = str(getattr(img, "uuid", None) or getattr(img, "tag", "?"))
        self.depth = depth

    def __repr__(self) -> str:
        return f"<ContreeState {self.id[:19]} d={self.depth}>"

    async def run(
        self,
        shell: str,
        *,
        stdin: str | None = None,
        timeout_s: float = 600.0,
        cwd: str | None = None,
    ) -> ExecResult:
        t0 = time.perf_counter()

        # disposable=False keeps the produced state forkable. See module docstring.
        prepared = self._img.run(
            shell=shell,
            stdin=stdin,
            timeout=timeout_s,
            disposable=False,
            cwd=cwd or self._ex.workdir,
            truncate_output_at=self._ex.truncate_at,
        )

        timed_out = False
        try:
            done = await prepared
        except _TIMEOUTS:
            return ExecResult(
                state=self,           # nothing usable was produced
                stdout="",
                stderr=f"operation timed out after {timeout_s}s",
                exit_code=124,
                duration_s=time.perf_counter() - t0,
                timed_out=True,
            )
        except (FailedOperationError, CancelledOperationError) as e:
            return ExecResult(
                state=self,
                stdout="",
                stderr=f"{type(e).__name__}: {e}",
                exit_code=125,
                duration_s=time.perf_counter() - t0,
            )

        result = getattr(done, "result", None)
        if result is not None:
            stdout, stderr = _text(result.stdout), _text(result.stderr)
            exit_code, cost = result.exit_code, getattr(result, "cost", None)
        else:  # defensive: some SDK paths proxy onto the image itself
            stdout, stderr = _text(getattr(done, "stdout", "")), _text(getattr(done, "stderr", ""))
            exit_code, cost = getattr(done, "exit_code", 0), None

        return ExecResult(
            state=ContreeState(self._ex, done, self.depth + 1),
            stdout=stdout,
            stderr=stderr,
            exit_code=exit_code,
            duration_s=time.perf_counter() - t0,
            timed_out=timed_out,
            cost=cost,
        )


def _oci_ref(image: str) -> str:
    """Normalise an image name to a docker:// reference.

    Three shapes matter to us:
      python:3.12                      -> docker.io/library/python:3.12
      someorg/thing:tag                -> docker.io/someorg/thing:tag
      ghcr.io/epoch-research/x:latest  -> ghcr.io/... (already has a host)

    The third is the SWE-bench case. Prefixing docker.io onto it produced a
    reference that could never resolve.
    """
    if "://" in image:
        return image
    head = image.split("/")[0]
    if "/" in image and ("." in head or ":" in head or head == "localhost"):
        return f"docker://{image}"          # explicit registry host
    if "/" in image:
        return f"docker://docker.io/{image}"
    return f"docker://docker.io/library/{image}"


class ContreeExecutor:
    name = "contree"

    def __init__(
        self,
        *,
        workdir: str = "/w",
        truncate_at: int = 64_000,
    ):
        # IAMAuth's defaults are the NAMES of environment variables, not
        # values -- it resolves NEBIUS_API_KEY and NEBIUS_PROJECT_ID itself.
        # Passing token= to Contree() sets the credential but leaves the
        # project unset, which the API rejects with:
        #     400 Missing "Project" header
        # So we populate the environment and construct with no arguments.
        load_dotenv(_ENV_PATH)
        missing = [
            v for v in ("NEBIUS_API_KEY", "NEBIUS_PROJECT_ID")
            if not os.environ.get(v)
        ]
        if missing:
            raise RuntimeError(
                f"{' and '.join(missing)} not set -- add to .env. "
                f"ConTree scopes every request to a project."
            )
        self.client = Contree()
        self.workdir = workdir
        self.truncate_at = truncate_at
        self.total_cost = 0.0

    async def base(self, image: str) -> ContreeState:
        ref = _oci_ref(image)
        img = await self.client.images.oci(ref)
        root = ContreeState(self, img, 0)
        # Materialise the workdir so `cwd` is valid downstream. This one
        # run must NOT use it as cwd -- it does not exist yet.
        return (await root.run(f"mkdir -p {self.workdir}", cwd="/")).state

    async def aclose(self) -> None:
        close = getattr(self.client, "close", None) or getattr(self.client, "aclose", None)
        if close is None:
            return
        maybe = close()
        if hasattr(maybe, "__await__"):
            await maybe
