"""Migration tasks.

A task is: an environment to build, a file to fix, a command that judges
the result, and enough context for a model to know what changed upstream.

The demo task is synthetic and offline on purpose. Real repositories come
later -- they are the honest benchmark -- but iterating on search
behaviour against a 60-second deterministic loop beats waiting three
minutes for a clone every time we change a prompt.

It encodes three *independent* renames, so partial credit is real: a
branch that fixes one of three genuinely outranks one that fixes none.
Without that gradient, beam search has nothing to climb.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Task:
    name: str
    image: str
    setup: str        # build the environment; run once, checkpointed
    target: str       # the single file the agent rewrites
    test_cmd: str     # judges a branch
    context_cmd: str  # gathers what the model is shown each generation
    goal: str
    setup_stdin: str | None = None  # piped into setup (e.g. a test patch)


_DEMO_SETUP = r"""
set -e
mkdir -p /w/widgets && cd /w
pip install --quiet --disable-pip-version-check pytest 2>&1 | tail -1

cat > /w/widgets/limits.py <<'EOF'
MAX_WIDGETS = 10
EOF

cat > /w/widgets/__init__.py <<'EOF'
# widgets 2.0 -- three public names changed since 1.x.
from .limits import MAX_WIDGETS


class Widget:
    def __init__(self, name, size=1):
        self.name = name
        self._size = size

    @property
    def size(self):
        return self._size


def create_widget(name, size=1):
    return Widget(name, size)
EOF

cat > /w/app.py <<'EOF'
import widgets


def build(name):
    return widgets.make_widget(name, size=3)


def total_size(items):
    return sum(w.get_size() for w in items)


def capacity_left(used):
    return widgets.WIDGET_MAX - used
EOF

cat > /w/test_app.py <<'EOF'
import app
import widgets


def test_build():
    assert app.build("a").name == "a"


def test_total_size():
    items = [widgets.create_widget("a", 2), widgets.create_widget("b", 3)]
    assert app.total_size(items) == 5


def test_capacity():
    assert app.capacity_left(4) == 6
EOF
"""

DEMO = Task(
    name="widgets-2.0",
    image="python:3.12",
    setup=_DEMO_SETUP,
    target="/w/app.py",
    test_cmd="cd /w && python -m pytest -q 2>&1 | tail -25",
    context_cmd=(
        "echo '--- app.py ---'; cat /w/app.py; "
        "echo '--- widgets/__init__.py ---'; cat /w/widgets/__init__.py; "
        "echo '--- widgets/limits.py ---'; cat /w/widgets/limits.py"
    ),
    goal=(
        "app.py was written against widgets 1.x and the library is now 2.0. "
        "Three names it uses no longer exist. Update app.py to the 2.0 API so "
        "the test suite passes. Do not modify the widgets package or the tests."
    ),
)

TASKS = {t.name: t for t in (DEMO,)}
