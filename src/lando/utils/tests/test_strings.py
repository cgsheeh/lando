import pytest

from lando.utils.strings import (
    LOG_OUTPUT_HEAD_LIMIT,
    LOG_OUTPUT_TAIL_LIMIT,
    truncate_output,
)


@pytest.mark.parametrize(
    "case_name,input_string",
    [
        ("empty", ""),
        ("short", "hello world"),
        (
            "just_under_boundary",
            "x" * (LOG_OUTPUT_HEAD_LIMIT + LOG_OUTPUT_TAIL_LIMIT - 1),
        ),
        ("at_boundary", "x" * (LOG_OUTPUT_HEAD_LIMIT + LOG_OUTPUT_TAIL_LIMIT)),
    ],
)
def test_truncate_output_passes_short_input_through(case_name, input_string):
    assert (
        truncate_output(input_string) == input_string
    ), f"`truncate_output` should leave `{case_name}` input unchanged."


@pytest.mark.parametrize("middle_size", [1, 1000, 100_000])
def test_truncate_output_long_keeps_head_and_tail(middle_size):
    head = "H" * LOG_OUTPUT_HEAD_LIMIT
    middle = "M" * middle_size
    tail = "T" * LOG_OUTPUT_TAIL_LIMIT
    long_output = head + middle + tail

    result = truncate_output(long_output)

    assert result.startswith(
        head
    ), "Truncated output should preserve the first `LOG_OUTPUT_HEAD_LIMIT` characters."
    assert result.endswith(
        tail
    ), "Truncated output should preserve the last `LOG_OUTPUT_TAIL_LIMIT` characters."
    assert (
        f"[{middle_size} bytes omitted]" in result
    ), "Truncated output should include a marker reporting the omitted byte count."
    assert (
        "M" not in result
    ), "Truncated output should not contain any of the omitted middle section."
