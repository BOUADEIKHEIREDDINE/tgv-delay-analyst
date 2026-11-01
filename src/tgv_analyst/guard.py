"""Brick 3: reject any answer containing a number that no tool computed.

This rule is enforced by code, not by the prompt: the agent calls
check_answer() before showing an answer, whatever the model says.
"""

import re

# Matches 12, 12.5 and 12,5 (French decimal comma). The sign is ignored.
NUMBER_PATTERN = re.compile(r"\d+(?:[.,]\d+)?")


def extract_numbers(text):
    """Return the numbers written in a text, as strings with a "." decimal point."""
    return [match.replace(",", ".") for match in NUMBER_PATTERN.findall(text)]


def is_supported(number, known_numbers):
    """True if `number` equals a known number rounded to the same decimals.

    Example: the tool printed 0.84567, so the answer may say 0.85 or 0.846,
    but not 0.84.
    """
    decimals = len(number.split(".")[1]) if "." in number else 0
    value = float(number)
    return any(round(float(known), decimals) == value for known in known_numbers)


def check_answer(answer, tool_outputs, question=""):
    """Check that every number in the answer comes from a tool output or the question.

    Returns (ok, unsupported_numbers).
    """
    known_numbers = extract_numbers(question)
    for output in tool_outputs:
        known_numbers += extract_numbers(output)

    unsupported = [n for n in extract_numbers(answer) if not is_supported(n, known_numbers)]
    return len(unsupported) == 0, unsupported
