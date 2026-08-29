"""Conformance suite -- every executor backend must pass this.

This exists to be an *oracle*. Docker is a backend we have already
verified by hand, so a suite that passes against Docker is trustworthy.
Point it at a new backend and it answers, in about a minute, whether
that backend actually implements the model Coppice assumes.

The load-bearing test is `test_fork_isolation`. If two runs from the
same state can see each other's writes, beam search silently produces
garbage: branches contaminate their siblings, scores become meaningless,
and nothing looks broken. Everything else here is hygiene by comparison.

    pytest tests/ -v                 # docker only
    pytest tests/ -v --backend all   # docker + contree (needs key)
"""

from __future__ import annotations

import hashlib
import os

import pytest

from coppice.executor.docker_exec import DockerExecutor

IMAGE = "python:3.12"

# Patches contain quotes, backslashes, dollar signs and backticks. Every
# one of those is a chance for a backend to corrupt input through some
# shell interpolation. Byte-exactness is not negotiable.
NASTY = (
    "diff --git a/x.py b/x.py\n"
    "@@ -1,2 +1,2 @@\n"
    "-old = 'single' + \"double\"  # $HOME `whoami`\n"
    "+new = r'\\backslash' + f\"{interp}\"  # 100% & <tag>\n"
)


def _backends():
    names = os.environ.get("COPPICE_BACKENDS", "docker").split(",")
    out = []
    for n in [x.strip() for x in names if x.strip()]:
        if n == "docker":
            out.append(pytest.param("docker", id="docker"))
        elif n == "contree":
            out.append(
                pytest.param(
                    "contree",
                    id="contree",
                    marks=pytest.mark.skipif(
                        not os.environ.get("NEBIUS_API_KEY"),
                        reason="NEBIUS_API_KEY not set",
                    ),
                )
            )
    return out


@pytest.fixture(params=_backends())
async def executor(request):
    if request.param == "docker":
        ex = DockerExecutor()
    else:
        from coppice.executor.contree_exec import ContreeExecutor

        ex = ContreeExecutor()
    try:
        yield ex
    finally:
        await ex.aclose()


@pytest.fixture
async def base(executor):
    return await executor.base(IMAGE)


# --------------------------------------------------------------------
# the premise
# --------------------------------------------------------------------

async def test_fork_isolation(base):
    """Two runs from one state must not observe each other. THE test."""
    seed = (await base.run("mkdir -p /w && echo parent > /w/f.txt")).state

    a = await seed.run("echo A >> /w/f.txt && cat /w/f.txt")
    b = await seed.run("echo B >> /w/f.txt && cat /w/f.txt")

    assert "A" in a.stdout and "B" not in a.stdout, "branch A saw B's write"
    assert "B" in b.stdout and "A" not in b.stdout, "branch B saw A's write"


async def test_parent_state_is_immutable(base):
    """Forking must leave the parent untouched, however many children."""
    seed = (await base.run("mkdir -p /w && echo parent > /w/f.txt")).state
    for i in range(3):
        await seed.run(f"echo child{i} >> /w/f.txt")

    after = await seed.run("cat /w/f.txt")
    assert after.stdout.strip() == "parent", "children mutated their parent"


async def test_state_accumulates_sequentially(base):
    """A chain of runs must build on each other -- depth has to work."""
    s1 = (await base.run("mkdir -p /w && echo one > /w/f.txt")).state
    s2 = (await s1.run("echo two >> /w/f.txt")).state
    r = await s2.run("cat /w/f.txt")
    assert r.stdout.split() == ["one", "two"]
    assert s2.depth > s1.depth


# --------------------------------------------------------------------
# fidelity
# --------------------------------------------------------------------

async def test_stdin_is_byte_exact(base):
    """Patches go in over stdin. A single mangled byte fails the apply."""
    r = await base.run(
        "cat > /tmp/p.diff && md5sum /tmp/p.diff | cut -d' ' -f1", stdin=NASTY
    )
    assert r.stdout.strip() == hashlib.md5(NASTY.encode()).hexdigest()


async def test_streams_are_separate(base):
    r = await base.run("echo to-out; echo to-err >&2")
    assert "to-out" in r.stdout and "to-out" not in r.stderr
    assert "to-err" in r.stderr and "to-err" not in r.stdout


async def test_failure_is_returned_not_raised(base):
    """A failing test suite is data, not an exception. Search depends on it."""
    r = await base.run("echo nope >&2; exit 3")
    assert r.exit_code == 3
    assert not r.ok
    assert "nope" in r.stderr


async def test_success_is_flagged(base):
    r = await base.run("true")
    assert r.ok and r.exit_code == 0


async def test_timeout_is_flagged_not_hung(base):
    """Runaway branches must be reaped, not allowed to stall the frontier."""
    r = await base.run("sleep 30", timeout_s=3)
    assert r.timed_out
    assert not r.ok


async def test_tail_returns_recent_output(base):
    r = await base.run("for i in $(seq 1 100); do echo line$i; done")
    tail = r.tail(5)
    assert "line100" in tail and "line1\n" not in tail
