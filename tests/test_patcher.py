"""Unit tests for the patcher.

The patcher is the only component that can be tested without a container,
a model, or a network -- and it is also the one whose failures are most
expensive, because it decides the apply rate, which is a headline number.
13% of proposals are discarded here. If that number is wrong, so is the
cost-per-solve of the entire project.

Two behaviours are load-bearing and get the most attention below:

- **Ambiguity is refused, not guessed.** A SEARCH string that matches
  twice, applied to the wrong occurrence, produces a patch that applies
  cleanly and is silently wrong. That is far worse than a loud failure,
  and it would be scored as a legitimate branch.
- **A no-op is a rejection.** A model that echoes the file back has not
  proposed anything. Forking for it would cost container time and score
  identically to the baseline, polluting the width curve with a free
  "candidate" that was never a candidate.
"""

import pytest

from coppice.patcher import (
    Block,
    PatchError,
    apply_blocks,
    apply_text,
    parse_blocks,
)

SRC = "def f(x):\n    return x + 1\n\n\ndef g(y):\n    return y * 2\n"


def block(search: str, replace: str) -> str:
    return f"<<<<<<< SEARCH\n{search}\n=======\n{replace}\n>>>>>>> REPLACE"


# --------------------------------------------------------------------- parse


def test_parses_a_well_formed_block():
    blocks, lenient = parse_blocks(block("    return x + 1", "    return x + 2"))
    assert lenient is False
    assert blocks == [Block("    return x + 1", "    return x + 2")]


def test_parses_several_blocks_in_order():
    text = block("a", "A") + "\n\nand also\n\n" + block("b", "B")
    blocks, lenient = parse_blocks(text)
    assert [(b.search, b.replace) for b in blocks] == [("a", "A"), ("b", "B")]
    assert lenient is False


def test_ignores_prose_around_the_blocks():
    text = "Here is the fix.\n\n" + block("a", "A") + "\n\nThat should do it."
    blocks, _ = parse_blocks(text)
    assert blocks == [Block("a", "A")]


def test_marker_length_is_tolerated():
    text = "<<<<< SEARCH\na\n=====\nA\n>>>>> REPLACE"
    blocks, lenient = parse_blocks(text)
    assert blocks == [Block("a", "A")]
    assert lenient is False


def test_prose_only_output_is_rejected():
    with pytest.raises(PatchError, match="no SEARCH/REPLACE block"):
        parse_blocks("You should change the return value to x + 2.")


def test_empty_output_is_rejected():
    with pytest.raises(PatchError):
        parse_blocks("")


# ------------------------------------------------------------------- lenient


def test_lenient_parse_recovers_nano_shaped_output_and_says_so():
    """Nano drops the divider and puts the replacement after the marker.

    We accept it -- but the caller is told, so we can measure how often
    we are compensating for a model that will not follow the contract.
    """
    text = "<<<<<<< SEARCH\n    return x + 1\n>>>>>>> REPLACE\n    return x + 2"
    blocks, lenient = parse_blocks(text)
    assert lenient is True
    assert blocks == [Block("    return x + 1", "    return x + 2")]


def test_lenient_parse_is_not_used_when_a_valid_block_exists():
    blocks, lenient = parse_blocks(block("a", "A"))
    assert lenient is False


def test_lenient_parse_rejects_an_empty_half():
    with pytest.raises(PatchError):
        parse_blocks("<<<<<<< SEARCH\na\n>>>>>>> REPLACE\n   \n")


# --------------------------------------------------------------------- apply


def test_applies_a_single_block():
    out = apply_blocks(SRC, [Block("    return x + 1", "    return x + 99")])
    assert "return x + 99" in out
    assert "return y * 2" in out          # untouched region survives
    assert out.count("def ") == 2


def test_applies_blocks_sequentially():
    out = apply_blocks(SRC, [
        Block("    return x + 1", "    return x + 99"),
        Block("    return y * 2", "    return y * 3"),
    ])
    assert "return x + 99" in out and "return y * 3" in out


def test_search_not_found_is_rejected_before_forking():
    with pytest.raises(PatchError, match="SEARCH not found"):
        apply_blocks(SRC, [Block("    return z - 1", "    return z")])


def test_ambiguous_search_is_refused_rather_than_guessed():
    """The most dangerous failure mode in the project.

    Picking an occurrence would produce a patch that applies cleanly,
    forks, runs, and scores -- while being silently wrong.
    """
    src = "x = 1\ny = 2\nx = 1\n"
    with pytest.raises(PatchError, match="ambiguous"):
        apply_blocks(src, [Block("x = 1", "x = 3")])


def test_ambiguity_error_reports_the_count():
    src = "a\na\na\n"
    with pytest.raises(PatchError, match=r"\(3x\)"):
        apply_blocks(src, [Block("a", "b")])


def test_empty_search_is_rejected():
    with pytest.raises(PatchError, match="empty SEARCH"):
        apply_blocks(SRC, [Block("", "anything")])


def test_no_op_is_rejected():
    """A model that echoes the file back has not proposed anything."""
    with pytest.raises(PatchError, match="no-op"):
        apply_blocks(SRC, [Block("    return x + 1", "    return x + 1")])


def test_a_reverting_pair_of_blocks_is_a_no_op():
    with pytest.raises(PatchError, match="no-op"):
        apply_blocks(SRC, [
            Block("    return x + 1", "    return x + 5"),
            Block("    return x + 5", "    return x + 1"),
        ])


def test_deletion_is_a_legitimate_patch():
    out = apply_blocks(SRC, [Block("\n\ndef g(y):\n    return y * 2\n", "\n")])
    assert "def g" not in out and "def f" in out


def test_matching_is_substring_not_line_based():
    """Documented, because it surprised us.

    A SEARCH string that omits the indentation still matches, because
    matching is `str.count` / `str.replace` over the whole file rather
    than a line-anchored comparison. Here the replacement inherits the
    original indentation, which is the benign case.
    """
    out = apply_blocks(SRC, [Block("return x + 1", "return x + 2")])
    assert "    return x + 2" in out


def test_KNOWN_GAP_a_search_string_can_match_mid_token():
    """The one silent-wrongness hazard the ambiguity check does not cover.

    Because matching is substring-based, a SEARCH of `x = 1` matches
    inside `max = 1` -- exactly once, so the ambiguity guard stays quiet
    -- and the patch applies cleanly while corrupting an identifier.

    We do not fix it here on purpose. Line-anchoring the matcher would
    change the apply rate, and the 87% figure in findings-04 was measured
    against *this* matcher; changing it and keeping the number would be
    the same class of error the findings documents warn about. It is
    logged in README's "what's next" and asserted here so that a future
    fix has to come with a re-measurement.

    In practice models emit whole indented lines, which is why this has
    not been observed in 160 proposals -- but "has not happened yet" is
    not a guard.
    """
    assert apply_blocks("max = 1\n", [Block("x = 1", "x = 3")]) == "max = 3\n"


def test_first_failing_block_aborts_the_whole_patch():
    """All-or-nothing. A half-applied patch is not what the model proposed."""
    with pytest.raises(PatchError, match="SEARCH not found"):
        apply_blocks(SRC, [
            Block("    return x + 1", "    return x + 99"),
            Block("    return nonexistent", "    return other"),
        ])


# ---------------------------------------------------------------- apply_text


def test_apply_text_round_trip():
    out, lenient = apply_text(SRC, block("    return x + 1", "    return x + 2"))
    assert "return x + 2" in out
    assert lenient is False


def test_apply_text_propagates_the_lenient_flag():
    text = "<<<<<<< SEARCH\n    return x + 1\n>>>>>>> REPLACE\n    return x + 7"
    out, lenient = apply_text(SRC, text)
    assert "return x + 7" in out
    assert lenient is True


def test_apply_text_rejects_prose():
    with pytest.raises(PatchError):
        apply_text(SRC, "I would change the increment to 2.")


# ------------------------------------------------------------- documented gap


def test_lenient_parse_swallows_trailing_prose():
    """Known limitation, asserted so it cannot change unnoticed.

    The lenient branch takes everything after the closing marker as the
    replacement, so a model that adds a sign-off would have it pasted
    into the source. It is only reachable for output that already broke
    the contract, and it fails loudly at the syntax check -- but if this
    test ever starts failing, someone tightened the regex and should say
    so in the findings.
    """
    text = ("<<<<<<< SEARCH\n    return x + 1\n>>>>>>> REPLACE\n"
            "    return x + 2\nHope that helps!")
    blocks, lenient = parse_blocks(text)
    assert lenient is True
    assert blocks[0].replace.endswith("Hope that helps!")
