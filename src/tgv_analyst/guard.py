"""Brick 3: reject any answer containing a number that no tool computed.

This rule is enforced by code, not by the prompt: the agent calls
check_answer() before showing an answer, whatever the model says.
"""

import re

# In text written by the model or a person, a comma or a space followed by exactly
# 3 digits is a thousands separator: 12,792 or 1,234,567.5, and the French 6 704
# (normal or no-break space).
THOUSANDS_PATTERN = re.compile(r"\d{1,3}(?:[, \u00a0\u202f]\d{3})+(?:\.\d+)?(?!\d)")
# Matches 12,792 (thousands) first, otherwise 12, 12.5 and 12,5 (French decimal comma).
# The sign is ignored.
NUMBER_PATTERN = re.compile(THOUSANDS_PATTERN.pattern + r"|\d+(?:[.,]\d+)?")

# In tool output, a space is never a thousands separator: print(15, 150) gives
# "15 150", two numbers. Only the comma counts (Python prints f"{n:,}" as 12,792).
TOOL_THOUSANDS_PATTERN = re.compile(r"\d{1,3}(?:,\d{3})+(?:\.\d+)?(?!\d)")
TOOL_NUMBER_PATTERN = re.compile(TOOL_THOUSANDS_PATTERN.pattern + r"|\d+(?:[.,]\d+)?")


def extract_numbers(text, spaces=True):
    """Return the numbers written in a text, as strings with a "." decimal point.

    "12,792" and "12 792" -> "12792" (thousands separator), "12,5" -> "12.5" (decimal comma).
    spaces=False for tool output: "15 150" -> "15", "150".
    Limit: "12,500" is always read as twelve thousand five hundred, never as 12.5.
    """
    if spaces:
        thousands, number = THOUSANDS_PATTERN, NUMBER_PATTERN
    else:
        thousands, number = TOOL_THOUSANDS_PATTERN, TOOL_NUMBER_PATTERN
    numbers = []
    for match in number.findall(text):
        if thousands.fullmatch(match):
            numbers.append(re.sub(r"[, \u00a0\u202f]", "", match))
        else:
            numbers.append(match.replace(",", "."))
    return numbers


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
        known_numbers += extract_numbers(output, spaces=False)

    unsupported = [n for n in extract_numbers(answer) if not is_supported(n, known_numbers)]
    return len(unsupported) == 0, unsupported


# Code the model may not run: anything that writes files or reaches the system.
# Changes to `df` are lost anyway (separate process), but files on disk are not.
FORBIDDEN_CODE = [
    "open(",
    "to_csv",
    "to_excel",
    "to_json",
    "to_parquet",
    "to_pickle",
    "import os",
    "from os",
    "shutil",
    "subprocess",
]


def check_code(code):
    """Check the code sent to run_python before it runs.

    Returns (ok, forbidden_parts_found).
    Limit: this is a text search, so a determined user could hide a forbidden
    call; it stops the model from writing files by mistake.
    """
    found = [part for part in FORBIDDEN_CODE if part in code]
    return len(found) == 0, found
