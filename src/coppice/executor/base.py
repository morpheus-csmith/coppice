"""Executor abstraction.

Coppice searches over *execution states*, not over text. Every executor
therefore models the thing ConTree gives us natively: an immutable,
forkable snapshot of a filesystem after some sequence of commands.

    s1 = await s0.run("pip install -e .")
    a  = await s1.run("git apply p1 && pytest")   # fork
    b  = await s1.run("git apply p2 && pytest")   # fork, same parent

`a` must not observe `b`'s writes, and neither may mutate `s1`. That
isolation is the entire premise of the project, so it is enforced by
conformance tests rather than by convention -- see
tests/test_executor_conformance.py, which every backend must pass.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable


@dataclass(frozen=True)
class ExecResult:
    """Outcome of one command, plus the state it produced."""

    state: "State"
    stdout: str
    stderr: str
    exit_code: int
    duration_s: float
    timed_out: bool = False
    cost: float | None = None  # backend-reported spend; None if unmetered

    @property
    def ok(self) -> bool:
        return self.exit_code == 0 and not self.timed_out

    def tail(self, n: int = 40) -> str:
        """Last n lines of combined output -- what we feed models."""
        combined = (self.stdout + "\n" + self.stderr).strip().splitlines()
        return "\n".join(combined[-n:])


@runtime_checkable
class State(Protocol):
    """An immutable filesystem snapshot. Forked by running from it twice."""

    id: str
    depth: int

    async def run(
        self,
        shell: str,
        *,
        stdin: str | None = None,
        timeout_s: float = 600.0,
    ) -> ExecResult:
        """Execute `shell` from this snapshot. Returns a NEW state.

        Must never mutate self. Callers rely on being able to run from the
        same State any number of times and get independent results.
        """
        ...


@runtime_checkable
class Executor(Protocol):
    """Creates root states and owns backend resources."""

    name: str

    async def base(self, image: str) -> State:
        """Root state for an OCI image reference."""
        ...

    async def aclose(self) -> None:
        """Release backend resources (containers, images, sessions)."""
        ...
