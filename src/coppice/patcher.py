"""SEARCH/REPLACE patching.

Whole-file rewrites were the first implementation and they failed
measurably: on flask-4992, 5 of 12 candidates returned a file that no
longer parsed, and every candidate burned ~2,655 output tokens retyping
code it had no intention of changing. See findings-03.

Blocks fix that. The model emits only what changes:

    <<<<<<< SEARCH
    the exact lines to find
    =======
    what to replace them with
    >>>>>>> REPLACE

Matching is exact and literal -- no fuzzy alignment, no line numbers to
drift. A block that does not match is a *clean* failure we detect in
Python, before forking, so a bad candidate costs no sandbox time at all.
That is what makes width cheap.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

_BLOCK = re.compile(
    r"<{5,9}\s*SEARCH\s*\n(.*?)\n?={5,9}\s*\n(.*?)\n?>{5,9}\s*REPLACE",
    re.DOTALL,
)

# Nemotron Nano consistently emits a malformed variant: it drops the
# `=======` divider and puts the replacement AFTER the closing marker.
#
#   <<<<<<< SEARCH
#   x = 1
#   >>>>>>> REPLACE
#   x = 2
#
# The intent is unambiguous, so we accept it rather than throwing away
# every proposal from the cheapest tier. Parsed separately, and callers
# are told, so we can measure how often we are compensating for a model
# that will not follow the contract.
_LENIENT = re.compile(
    r"<{5,9}\s*SEARCH\s*\n(.*?)\n?>{5,9}\s*REPLACE\s*\n(.*)",
    re.DOTALL,
)


class PatchError(Exception):
    """A candidate we can reject without spending a container on it."""


@dataclass(frozen=True)
class Block:
    search: str
    replace: str


def parse_blocks(text: str) -> tuple[list[Block], bool]:
    """Returns (blocks, used_lenient_parse)."""
    blocks = [Block(m.group(1), m.group(2)) for m in _BLOCK.finditer(text)]
    if blocks:
        return blocks, False

    m = _LENIENT.search(text)
    if m and m.group(1).strip() and m.group(2).strip():
        return [Block(m.group(1), m.group(2).rstrip())], True

    raise PatchError("no SEARCH/REPLACE block found")


def apply_blocks(source: str, blocks: list[Block]) -> str:
    """Apply blocks in order. Raises PatchError rather than guessing.

    Ambiguity is an error, not a coin flip: if a SEARCH string appears
    more than once we refuse, because picking the wrong occurrence
    produces a patch that applies cleanly and is silently wrong -- far
    worse than one that fails loudly.
    """
    out = source
    for i, b in enumerate(blocks):
        if b.search == "":
            raise PatchError(f"block {i}: empty SEARCH")
        count = out.count(b.search)
        if count == 0:
            preview = " ".join(b.search.split())[:70]
            raise PatchError(f"block {i}: SEARCH not found: {preview!r}")
        if count > 1:
            preview = " ".join(b.search.split())[:70]
            raise PatchError(f"block {i}: SEARCH ambiguous ({count}x): {preview!r}")
        out = out.replace(b.search, b.replace, 1)
    if out == source:
        raise PatchError("patch is a no-op")
    return out


def apply_text(source: str, model_output: str) -> tuple[str, bool]:
    """Returns (patched_source, used_lenient_parse)."""
    blocks, lenient = parse_blocks(model_output)
    return apply_blocks(source, blocks), lenient
