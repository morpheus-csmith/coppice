"""SWE-bench Lite as a task source.

Ground truth we did not author. 300 instances across 11 Python repos,
each one a real GitHub issue with a human-validated gold patch and two
test lists: FAIL_TO_PASS (broken before, fixed after) and PASS_TO_PASS
(must not regress). That second list is what makes it a real benchmark
rather than a fix-it-somehow exercise -- a patch that fixes the bug and
breaks the suite scores worse than doing nothing.

Environments come from Epoch AI's prebuilt per-instance images, so the
repo is already checked out at base_commit with dependencies installed.

  A NOTE ON WHAT THIS MEASURES. Because the image is prebuilt, the
  "setup amortized once" half of our thesis mostly does not apply here
  -- a Docker baseline gets the same free checkpoint. What remains
  measurable is per-fork overhead and the concurrency ceiling. That is
  the narrower claim, and the one finding-01 says is defensible. We
  benchmark the narrow claim on purpose.

SCOPE LIMIT: our patcher rewrites one file whole, so `single_file_only`
filters to instances whose gold patch touches exactly one file. This is
a real restriction on generality and is disclosed in the results.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass

from .tasks import Task

IMAGE_TMPL = "ghcr.io/epoch-research/swe-bench.eval.x86_64.{instance_id}"
WORKDIR = "/testbed"

# Every SWE-bench image puts the project in a conda env named `testbed`;
# the image's default PATH points at base conda, which does NOT have the
# project or pytest installed. Calling the env's interpreter by absolute
# path is more robust than `source activate` in a non-interactive shell,
# and it is uniform across all instances.
PYTHON = "/opt/miniconda3/envs/testbed/bin/python"

_DIFF_FILE = re.compile(r"^diff --git a/(\S+) b/(\S+)", re.MULTILINE)

# django drives tests through ./tests/runtests.py, not pytest, so its 114
# instances (38% of Lite) cannot use our test_cmd. Excluded rather than
# special-cased -- 186 instances is more than enough.
NON_PYTEST_REPOS = {"django/django"}

# Small, fast, pip-installable repos. Start here: the images are a
# fraction of the size of scikit-learn or sympy, and a wrong turn costs
# minutes instead of an evening.
SMALL_REPOS = {
    "psf/requests",
    "pallets/flask",
    "pydata/xarray",
    "mwaskom/seaborn",
    "astropy/astropy",
    "pylint-dev/pylint",
}


@dataclass(frozen=True)
class Instance:
    instance_id: str
    repo: str
    base_commit: str
    patch: str
    test_patch: str
    problem_statement: str
    fail_to_pass: list[str]
    pass_to_pass: list[str]
    version: str = ""

    @property
    def patched_files(self) -> list[str]:
        return sorted({m.group(1) for m in _DIFF_FILE.finditer(self.patch)})

    @property
    def image(self) -> str:
        return IMAGE_TMPL.format(instance_id=self.instance_id)


def _as_list(value) -> list[str]:
    if isinstance(value, list):
        return value
    try:
        return json.loads(value)
    except Exception:
        return []


def load_lite(split: str = "test", limit: int | None = None) -> list[Instance]:
    """Load SWE-bench Lite. Requires `pip install datasets`."""
    from datasets import load_dataset

    ds = load_dataset("SWE-bench/SWE-bench_Lite", split=split)
    out: list[Instance] = []
    for row in ds:
        out.append(
            Instance(
                instance_id=row["instance_id"],
                repo=row["repo"],
                base_commit=row["base_commit"],
                patch=row["patch"],
                test_patch=row["test_patch"],
                problem_statement=row["problem_statement"],
                fail_to_pass=_as_list(row["FAIL_TO_PASS"]),
                pass_to_pass=_as_list(row["PASS_TO_PASS"]),
                version=str(row.get("version", "")),
            )
        )
        if limit and len(out) >= limit:
            break
    return out


def single_file_only(instances: list[Instance]) -> list[Instance]:
    """Instances our whole-file patcher can actually express.

    In practice this filters nothing: SWE-bench Lite is already
    single-file by construction. Kept as a guard for other splits.
    """
    return [i for i in instances if len(i.patched_files) == 1]


def pytest_only(instances: list[Instance]) -> list[Instance]:
    return [i for i in instances if i.repo not in NON_PYTEST_REPOS]


def small_repos(instances: list[Instance]) -> list[Instance]:
    return [i for i in instances if i.repo in SMALL_REPOS]


def usable(instances: list[Instance], *, small: bool = False) -> list[Instance]:
    out = pytest_only(single_file_only(instances))
    return small_repos(out) if small else out


def _test_source_cmd(inst: Instance, max_files: int = 2) -> str:
    """Show the model the tests it has to satisfy.

    Without this the model sees an assertion failure but never the code
    that produced it, so it has to guess the API contract the test
    encodes. For a bug fix that is sometimes survivable; for a new
    parameter or changed signature it is impossible. Every serious
    SWE-bench scaffold reads the tests -- ours did not, which made the
    first solve-rate measurement meaningless.
    """
    files: list[str] = []
    for node in inst.fail_to_pass:
        path = node.split("::")[0]
        if path.endswith(".py") and path not in files:
            files.append(path)
        if len(files) >= max_files:
            break
    if not files:
        return "true"
    parts = [
        f"echo '--- {f} (the failing test) ---'; sed -n '1,400p' {f}"
        for f in files
    ]
    return f"cd {WORKDIR} && " + "; ".join(parts)


def to_task(inst: Instance, *, max_p2p: int = 40) -> Task:
    """Build a runnable Task from an instance.

    The test command runs FAIL_TO_PASS (what must start passing) plus a
    capped sample of PASS_TO_PASS (what must not break). The cap keeps
    branch evaluation fast; regressions outside the sample are caught by
    the full-suite verification pass on the winning patch only.
    """
    target = inst.patched_files[0]
    tests = inst.fail_to_pass + inst.pass_to_pass[:max_p2p]
    quoted = " ".join(f"'{t}'" for t in tests)

    setup = (
        f"cd {WORKDIR} && "
        f"git checkout -q {inst.base_commit} && "
        f"git checkout -q {inst.base_commit} -- . && "
        # test_patch arrives on stdin: it contains quotes, backslashes and
        # dollar signs, and must land byte-exact.
        f"cat > /tmp/test.patch && git apply -v /tmp/test.patch 2>&1 | tail -3"
    )

    return Task(
        name=inst.instance_id,
        image=inst.image,
        setup=setup,
        setup_stdin=inst.test_patch,
        target=f"{WORKDIR}/{target}",
        test_cmd=(
            f"cd {WORKDIR} && {PYTHON} -m pytest -q --no-header --tb=short "
            f"-p no:cacheprovider {quoted} 2>&1 | tail -60"
        ),
        context_cmd=_test_source_cmd(inst),
        goal=(
            f"Repository: {inst.repo}\n\n"
            f"Reported issue:\n{inst.problem_statement.strip()[:4000]}\n\n"
            f"Fix the issue by editing {target}. Do not modify tests."
        ),
    )


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser(description="Inspect SWE-bench Lite instances")
    ap.add_argument("--limit", type=int, default=300)
    ap.add_argument("--single-file", action="store_true")
    ap.add_argument("--usable", action="store_true", help="pytest-capable only")
    ap.add_argument("--small", action="store_true", help="small fast repos only")
    ap.add_argument("--repo", default=None)
    ap.add_argument("--show", type=int, default=15)
    args = ap.parse_args()

    inst = load_lite(limit=args.limit)
    print(f"loaded {len(inst)} instances")
    if args.single_file:
        inst = single_file_only(inst)
        print(f"single-file gold patch: {len(inst)}")
    if args.usable or args.small:
        inst = usable(inst, small=args.small)
        print(f"usable{' (small repos)' if args.small else ''}: {len(inst)}")
    if args.repo:
        inst = [i for i in inst if args.repo in i.repo]
        print(f"repo filter {args.repo!r}: {len(inst)}")

    from collections import Counter

    print("\nby repo:")
    for repo, n in Counter(i.repo for i in inst).most_common():
        print(f"  {n:>4}  {repo}")

    if inst:
        sizes = sorted(len(i.pass_to_pass) for i in inst)
        mid = sizes[len(sizes) // 2]
        over = sum(1 for n in sizes if n > 40)
        print(f"\nPASS_TO_PASS: median {mid}, max {sizes[-1]}, "
              f"{over}/{len(sizes)} exceed the 40-test sample cap")

    print(f"\nfirst {args.show}:")
    for i in inst[: args.show]:
        print(f"  {i.instance_id:<38} f2p={len(i.fail_to_pass):<3} "
              f"p2p={len(i.pass_to_pass):<4} {i.patched_files[0]}")
