"""Tests for tools.py: the tools Qwen calls (R2; brick 1's evidence is a real trace).

The tools read tests/fixtures/tgv_small.csv instead of the real dataset
(data/clean/ is not in git, so these tests also pass on a fresh clone).
The fixture has 3 rows written by hand, so every answer is known:

    date     route                                 planned  cancelled  ran  late at arrival
    2024-01  PARIS LYON -> MARSEILLE ST CHARLES    100      0          100  10
    2024-02  PARIS LYON -> MARSEILLE ST CHARLES    60       10         50   5   (sup_30 missing)
    2024-01  LYON PART DIEU -> MARSEILLE ST CHARLES 40      0          40   6
"""

from pathlib import Path

import pandas as pd
import pytest

from tgv_analyst import tools
from tgv_analyst.config import PROJECT_ROOT

SMALL_CSV = Path(__file__).parent / "fixtures" / "tgv_small.csv"


@pytest.fixture
def small_data(monkeypatch):
    """Every tool reads the 3-row file instead of data/clean/tgv_clean.csv."""
    monkeypatch.setattr(tools, "CLEAN_CSV", SMALL_CSV)


def test_fixture_has_the_columns_of_the_clean_data():
    """The fixture must keep the real column names, or the tests prove nothing."""
    columns = set(pd.read_csv(SMALL_CSV).columns)
    assert columns == set(tools.COLUMN_DESCRIPTIONS)  # same names, the order doesn't matter


# --- run_python: computes on df -------------------------------------------------

def test_run_python_counts_rows(small_data):
    assert tools.run_python("print(len(df))").strip() == "3"


def test_run_python_late_rate_of_a_route(small_data):
    code = (
        "d = df[(df['gare_depart'] == 'PARIS LYON') & (df['year'] == 2024)]\n"
        "print(d['nb_train_retard_arrivee'].sum(), d['nb_circules'].sum())"
    )
    assert tools.run_python(code).strip() == "15 150"


def test_run_python_sees_the_missing_value(small_data):
    """Edge case: a missing value stays missing (NaN), it is not read as 0."""
    assert tools.run_python("print(df['nb_train_retard_sup_30'].isna().sum())").strip() == "1"


def test_run_python_filter_with_no_row(small_data):
    """Edge case: a station that doesn't exist gives an empty table, and a sum of 0."""
    code = "d = df[df['gare_depart'] == 'Paris Lyon']\nprint(len(d), d['nb_circules'].sum())"
    assert tools.run_python(code).strip() == "0 0"


# --- run_python: what the model gets back when something goes wrong ------------

def test_run_python_without_print_gives_a_hint(small_data):
    assert tools.run_python("len(df)") == "(no output: use print() to show results)"


def test_run_python_error_comes_back_as_text(small_data):
    """Real Qwen mistake of 2026-11-01: confidence_interval called inside run_python."""
    result = tools.run_python("print(confidence_interval(640, 6704))")
    assert "Error" in result
    assert "NameError: name 'confidence_interval' is not defined" in result


def test_run_python_syntax_error_comes_back_as_text(small_data):
    result = tools.run_python("print(df[(df['year'] == 2024)")
    assert "Error" in result and "SyntaxError" in result


def test_run_python_keeps_what_was_printed_before_the_error(small_data):
    result = tools.run_python("print(len(df))\nprint(undefined_name)")
    assert result.startswith("3\n")
    assert "NameError" in result


def test_run_python_variables_do_not_survive_between_calls(small_data):
    """Each call is a new process (rule 3 of the system prompt)."""
    tools.run_python("total = 190")
    assert "NameError: name 'total' is not defined" in tools.run_python("print(total)")


def test_run_python_cannot_change_the_data(small_data):
    """Deleting rows of df only changes the copy in that process, never the file."""
    tools.run_python("df.drop(df.index, inplace=True)")
    assert tools.run_python("print(len(df))").strip() == "3"


def test_run_python_refuses_to_write_files(small_data):
    """Brick 3 inside the tool: the code is checked before anything runs."""
    result = tools.run_python("df.to_csv('copy.csv')")
    assert result.startswith("Error: forbidden in code: to_csv")
    assert not (PROJECT_ROOT / "copy.csv").exists()


def test_run_python_stops_endless_code(small_data, monkeypatch):
    monkeypatch.setattr(tools, "TIMEOUT_SECONDS", 1)
    assert tools.run_python("while True:\n    pass") == "Error: code took more than 1 seconds."


def test_run_python_cuts_long_output(small_data):
    """Keeps the model's context small: at most MAX_OUTPUT_CHARS characters."""
    assert len(tools.run_python("print('x' * 10000)")) == tools.MAX_OUTPUT_CHARS


# --- describe_dataset -------------------------------------------------------------

def test_describe_dataset(small_data):
    text = tools.describe_dataset()
    assert "Rows: 3 (one row = one route in one month)" in text
    assert "Months: 2024-01 to 2024-02" in text
    assert "Routes: 2" in text
    assert "Stations: LYON PART DIEU, MARSEILLE ST CHARLES, PARIS LYON" in text  # sorted, each once


def test_describe_dataset_lists_every_column_with_its_meaning(small_data):
    text = tools.describe_dataset()
    for column, meaning in tools.COLUMN_DESCRIPTIONS.items():
        assert f"- {column}: {meaning}" in text


# --- confidence_interval (the tool: text for the model) ---------------------------

def test_confidence_interval_tool_prints_rate_and_percent():
    """The % are printed too, so the model never converts numbers itself."""
    text = tools.confidence_interval(640, 6704)
    assert text == (
        "rate: 0.0955 (9.5 %)\n"
        "95% confidence interval: [0.0887, 0.1027] ([8.9 %, 10.3 %])"
    )


@pytest.mark.parametrize("late, total", [(5, 0), (11, 10), (-1, 10)])
def test_confidence_interval_tool_wrong_counts_give_an_error_text(late, total):
    """Edge case: the model gets an error message it can read, not a crash."""
    assert tools.confidence_interval(late, total).startswith("Error:")


# --- call_tool: what the agent uses to run the tool the model asked for ----------

def test_call_tool_runs_the_right_tool():
    assert tools.call_tool("confidence_interval", {"late": 640, "total": 6704}).startswith("rate: 0.0955")


def test_call_tool_unknown_tool():
    result = tools.call_tool("make_coffee", {})
    assert result == "Error: unknown tool 'make_coffee'. Available: run_python, describe_dataset, confidence_interval"


@pytest.mark.parametrize(
    "name, arguments",
    [
        ("confidence_interval", {"late": 640}),  # missing argument
        ("run_python", {"script": "print(1)"}),  # wrong argument name
        ("describe_dataset", {"verbose": True}),  # argument that doesn't exist
    ],
)
def test_call_tool_wrong_arguments_give_an_error_text(name, arguments):
    assert tools.call_tool(name, arguments).startswith(f"Error: wrong arguments for {name}:")


def test_every_schema_matches_a_tool():
    """The names sent to the model are the names call_tool knows."""
    assert [schema["function"]["name"] for schema in tools.TOOL_SCHEMAS] == list(tools.TOOLS)
