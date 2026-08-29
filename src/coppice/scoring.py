"""Turning a test run into a number the search can rank by.

The reward signal is the existing test suite, not a model's opinion of
its own patch. That is the whole reason migrations are the right product
wrapper -- search needs ground truth, and here it is free.

Scoring rewards newly-passing tests, punishes regressions harder than it
rewards fixes (a patch that fixes two things and breaks one is usually
worse than one that fixes one and breaks nothing), and applies a small
penalty for diff size so the search prefers minimal changes when
outcomes tie.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# pytest -q tail: "2 failed, 3 passed, 1 skipped in 0.42s"
_COUNT = re.compile(r"(\d+)\s+(passed|failed|error|errors|skipped|xfailed|xpassed)")
# collection blew up entirely -- syntax error, bad import
_COLLECT_FAIL = re.compile(r"(ERROR collecting|INTERNALERROR|SyntaxError)")


@dataclass(frozen=True)
class TestOutcome:
    passed: int = 0
    failed: int = 0
    errors: int = 0
    skipped: int = 0
    collected_ok: bool = True

    @property
    def total(self) -> int:
        return self.passed + self.failed + self.errors

    @property
    def green(self) -> bool:
        return self.collected_ok and self.failed == 0 and self.errors == 0 and self.passed > 0

    def __str__(self) -> str:
        if not self.collected_ok:
            return "collection failed"
        return f"{self.passed}P/{self.failed}F/{self.errors}E"


def parse_pytest(text: str) -> TestOutcome:
    """Parse `pytest -q` output. Tolerant: unparseable means 'broken', not crash."""
    if _COLLECT_FAIL.search(text):
        return TestOutcome(collected_ok=False)

    counts = {"passed": 0, "failed": 0, "error": 0, "errors": 0, "skipped": 0}
    for n, label in _COUNT.findall(text):
        counts[label] = counts.get(label, 0) + int(n)

    outcome = TestOutcome(
        passed=counts["passed"],
        failed=counts["failed"],
        errors=counts["error"] + counts["errors"],
        skipped=counts["skipped"],
        collected_ok=True,
    )
    # No counts at all and no summary line -> we did not really run.
    if outcome.total == 0 and "no tests ran" not in text.lower():
        return TestOutcome(collected_ok=False)
    return outcome


# Regressions cost more than fixes earn. A branch that trades one break
# for one fix is not progress, and without this the search happily
# wanders sideways forever.
REGRESSION_WEIGHT = 1.5
DIFF_PENALTY_PER_LINE = 0.002


@dataclass(frozen=True)
class Score:
    value: float
    fixed: int
    broken: int
    outcome: TestOutcome
    solved: bool

    def __str__(self) -> str:
        return f"{self.value:+.2f} (+{self.fixed}/-{self.broken}) {self.outcome}"


def score_branch(before: TestOutcome, after: TestOutcome, diff_lines: int = 0) -> Score:
    if not after.collected_ok:
        # Worse than any failing test: the branch is not even runnable.
        return Score(-100.0, 0, 0, after, False)

    fixed = max(0, after.passed - before.passed)
    broken = max(0, after.failed - before.failed) + max(0, after.errors - before.errors)

    value = fixed - REGRESSION_WEIGHT * broken - DIFF_PENALTY_PER_LINE * diff_lines
    return Score(value, fixed, broken, after, after.green)
