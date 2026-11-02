"""Tests for guard.py (R2, and the evidence for brick 3).

The tool outputs and the answers below are copied from real Qwen runs of
2026-11-02 (question: late rate Paris Lyon -> Marseille St Charles in 2024).
No model is called: the guard is plain Python.
"""

import pytest

from tgv_analyst.guard import check_answer, check_code, extract_numbers, is_supported
from tgv_analyst.prompts import DATA_FACTS

# Real outputs of run_python and confidence_interval for that question.
RUN_PYTHON_OUTPUT = "Total trains (circules): 6704\nLate trains at arrival: 640\nRate of late trains: 0.0955\n"
INTERVAL_OUTPUT = "rate: 0.0955 (9.5 %)\n95% confidence interval: [0.0887, 0.1027] ([8.9 %, 10.3 %])"
TOOL_OUTPUTS = [RUN_PYTHON_OUTPUT, INTERVAL_OUTPUT]
QUESTION = "Quel est le taux de retard à l'arrivée de Paris Lyon vers Marseille St Charles en 2024 ?"


# --- Reading numbers in a text ---------------------------------------------

@pytest.mark.parametrize(
    "text, expected",
    [
        ("12,792 rows", ["12792"]),  # comma = thousands separator
        ("1,234,567.5", ["1234567.5"]),
        ("6 704 trains", ["6704"]),  # French: space = thousands separator
        ("6 704 trains", ["6704"]),  # no-break space
        ("6 704 trains", ["6704"]),  # narrow no-break space (French typography)
        ("9,5 %", ["9.5"]),  # French decimal comma
        ("12.5 min", ["12.5"]),
        ("entre 8,9 % et 10,3 %", ["8.9", "10.3"]),
        ("en 2024 640 trains", ["2024", "640"]),  # a 4-digit year is not merged with the next number
        ("-2.5 min", ["2.5"]),  # the sign is ignored
        ("no number here", []),  # edge case: nothing to read
        ("", []),  # edge case: empty text
    ],
)
def test_extract_numbers(text, expected):
    assert extract_numbers(text) == expected


@pytest.mark.parametrize(
    "text, expected",
    [
        ("15 150\n", ["15", "150"]),  # print(late, total): two numbers, not 15150
        ("Late trains: 640 / ran: 6704", ["640", "6704"]),
        ("12,792", ["12792"]),  # a comma is still a thousands separator (f"{n:,}")
        ("0.0955 (9.5 %)", ["0.0955", "9.5"]),
    ],
)
def test_extract_numbers_from_tool_output_space_is_not_thousands(text, expected):
    assert extract_numbers(text, spaces=False) == expected


def test_limit_comma_with_three_digits_is_always_thousands():
    """Known limit (written in the docstring of extract_numbers): "12,500" is never 12.5."""
    assert extract_numbers("12,500") == ["12500"]


# --- Rounding rule ------------------------------------------------------------

@pytest.mark.parametrize(
    "number, accepted",
    [
        ("0.85", True),  # 0.84567 rounded to 2 decimals
        ("0.846", True),  # rounded to 3 decimals
        ("0.84567", True),  # copied exactly
        ("0.84", False),  # wrong rounding
        ("1", True),  # rounded to 0 decimals
        ("0.9", False),
    ],
)
def test_is_supported_rounding(number, accepted):
    assert is_supported(number, ["0.84567"]) is accepted


def test_is_supported_with_no_known_number():
    """Edge case: no tool printed anything, so nothing is supported."""
    assert is_supported("12", []) is False


# --- check_answer: real answers that must pass ------------------------------

def test_correct_answer_passes():
    answer = (
        "Le taux de retard à l'arrivée de Paris Lyon vers Marseille St Charles en 2024 "
        "est de **9,5 %** (640 trains retards sur 6704 trains qui ont couru), avec un "
        "intervalle de confiance à 95 % s'étalant de **8,9 % à 10,3 %**."
    )
    assert check_answer(answer, TOOL_OUTPUTS, QUESTION) == (True, [])


def test_correct_answer_with_french_thousands_passes():
    """Real answer that was wrongly blocked before the fix of 2026-11-02 ("6 704")."""
    answer = (
        "Sur les 6 704 trains qui ont circulé cette année-là, 640 étaient en retard. "
        "Le taux est de 9,5 %, entre 8,9 % et 10,3 %."
    )
    assert check_answer(answer, TOOL_OUTPUTS, QUESTION) == (True, [])


def test_two_numbers_printed_on_one_line_pass():
    """Bug found by test_agent.py (2026-11-02): run_python printed "15 150" (print(late, total))
    and the guard read it as 15150, so the correct answer "15 sur 150" was blocked."""
    answer = "10.0 % des trains étaient en retard (15 sur 150)."
    outputs = ["15 150\n", "rate: 0.1000 (10.0 %)"]
    assert check_answer(answer, outputs) == (True, [])


def test_numbers_from_the_question_and_data_facts_pass():
    """2024 comes from the question, 2018 and 2026 from DATA_FACTS: not made up."""
    answer = "The data covers 2018 to 2026; in 2024 the rate was 9.5 %."
    assert check_answer(answer, TOOL_OUTPUTS, f"{DATA_FACTS}\n{QUESTION}") == (True, [])


def test_answer_without_numbers_passes():
    """Edge case: nothing to check (e.g. "Hello! Ask me about TGV punctuality.")."""
    assert check_answer("Hello! Ask me a question about TGV punctuality.", []) == (True, [])


# --- check_answer: attempts to break the rule (brick 3) ---------------------

def test_rate_converted_by_the_model_is_blocked():
    """Real Qwen answer: it turned 0.0955 into 9,55 % by itself. No tool printed 9.55."""
    answer = "Le taux de retard est de **9,55 %**, entre **8,9 % et 10,3 %**."
    assert check_answer(answer, TOOL_OUTPUTS, QUESTION) == (False, ["9.55"])


def test_wrong_rounding_by_the_model_is_blocked():
    """Real Qwen answer: 0.0955 written as 9,6 % (the tool printed 9.5 %)."""
    answer = "Le taux de retard est de **9,6 %** (640 trains retardés sur 6704)."
    assert check_answer(answer, TOOL_OUTPUTS, QUESTION) == (False, ["9.6"])


def test_invented_number_is_blocked():
    answer = "About 700 trains were late, a rate of 9.5 %."
    assert check_answer(answer, TOOL_OUTPUTS, QUESTION) == (False, ["700"])


def test_every_invented_number_is_listed():
    answer = "12.3 % of 5000 trains, so 615 late trains."
    assert check_answer(answer, TOOL_OUTPUTS, QUESTION) == (False, ["12.3", "5000", "615"])


def test_number_without_any_tool_call_is_blocked():
    """Edge case: the model answers from memory, with no tool output at all."""
    assert check_answer("The late rate was 11 % in 2024.", [], QUESTION) == (False, ["11"])


def test_numbers_of_the_prompt_rules_are_not_trusted():
    """Only DATA_FACTS is trusted, not the rest of the system prompt (e.g. its "13.1 %" example)."""
    ok, unsupported = check_answer("The rate is 13.1 %.", TOOL_OUTPUTS, f"{DATA_FACTS}\n{QUESTION}")
    assert not ok and unsupported == ["13.1"]


def test_limit_number_used_for_the_wrong_thing_passes():
    """Known limit: the guard checks that a tool printed the number, not what it means.

    "9 %" passes because the interval bound 8.9 rounds to 9, although the rate is 9.5 %.
    """
    assert check_answer("About 9 % of trains were late.", TOOL_OUTPUTS, QUESTION) == (True, [])


# --- check_code: run_python may not write files -----------------------------

@pytest.mark.parametrize(
    "code, found",
    [
        ("df.to_csv('copy.csv')", ["to_csv"]),  # real Qwen code of 2026-11-01
        ("open('data/clean/tgv_clean.csv', 'w').write('')", ["open("]),
        ("import os\nos.remove('x')", ["import os"]),
        ("from os import remove", ["from os"]),
        ("import shutil", ["shutil"]),
        ("import subprocess", ["subprocess"]),
        ("df.to_excel('a.xlsx'); df.to_json('a.json')", ["to_excel", "to_json"]),
    ],
)
def test_forbidden_code_is_blocked(code, found):
    assert check_code(code) == (False, found)


@pytest.mark.parametrize(
    "code",
    [
        "print(len(df))",
        "d = df[(df['year'] == 2024) & (df['month'] == 7)]\nprint(d['nb_circules'].sum())",
        "",  # edge case: empty code
    ],
)
def test_reading_code_is_allowed(code):
    assert check_code(code) == (True, [])
