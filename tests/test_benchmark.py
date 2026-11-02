"""Tests for benchmark/run_benchmark.py (R2): truths, scoring, resume, mean and spread.

No model is called and the real data is not needed: the truths are checked on
the 3-row fixture of test_tools.py, the summary on rows written by hand.
"""

import csv
from pathlib import Path

import pandas as pd
import pytest

import run_benchmark as bench

SMALL = pd.read_csv(Path(__file__).parent / "fixtures" / "tgv_small.csv")


# --- tasks.json -----------------------------------------------------------------

def test_tasks_file():
    tasks = bench.load_tasks()
    assert len(tasks) >= 10  # the spec asks for at least 10 tasks
    assert [t["id"] for t in tasks] == list(range(1, len(tasks) + 1))
    assert all(t["kind"] in ("count", "rate") for t in tasks)
    assert all(t["question"].strip() for t in tasks)


@pytest.mark.filterwarnings("ignore:invalid value encountered")  # 0 / 0 for a route absent from the fixture
def test_every_truth_expression_runs():
    """Each pandas expression evaluates (on the fixture some routes are absent: NaN is fine)."""
    for task in bench.load_tasks():
        bench.compute_truth(task, SMALL)


# --- Truths: known values on the fixture ----------------------------------------------

def test_truth_late_rate_of_a_route():
    """PARIS LYON -> MARSEILLE ST CHARLES 2024 in the fixture: 15 late out of 150 that ran."""
    task = {"truth": "late_rate(df[route('PARIS LYON', 'MARSEILLE ST CHARLES') & (df['year'] == 2024)])"}
    assert bench.compute_truth(task, SMALL) == pytest.approx(0.1)


def test_truth_count_and_number_of_routes():
    assert bench.compute_truth({"truth": "df['nb_circules'].sum()"}, SMALL) == 190
    assert bench.compute_truth({"truth": "df.groupby(['gare_depart', 'gare_arrivee']).ngroups"}, SMALL) == 2


def test_truth_cancel_rate():
    """Cancelled / planned (not / ran): 10 / 200."""
    assert bench.compute_truth({"truth": "cancel_rate(df)"}, SMALL) == pytest.approx(0.05)


def test_truth_expressions_cannot_use_builtins():
    """Only df and the helpers are available in an expression."""
    with pytest.raises(NameError):
        bench.compute_truth({"truth": "open('x')"}, SMALL)


# --- Scoring ----------------------------------------------------------------------------

@pytest.mark.parametrize(
    "answer, truth, kind, expected",
    [
        ("Le taux est de 9,5 %, entre 8,9 % et 10,3 %.", 0.0955, "rate", True),
        ("The rate was 9.6%.", 0.0955, "rate", True),  # within 0.1 point
        ("The rate was 0.0955.", 0.0955, "rate", True),  # as a fraction
        ("The rate was 9.7%.", 0.0955, "rate", False),
        ("About 12% of trains were late.", 0.0955, "rate", False),  # invented (bare model)
        ("6 673 TGV ont circulé.", 6673, "count", True),  # French thousands
        ("6,673 trains ran.", 6673, "count", True),
        ("6672 trains ran.", 6673, "count", False),  # a count must be exact
        ("The worst full year was 2018.", 2018, "count", True),
        ("I don't have access to that data.", 6673, "count", False),  # edge case: no number
        ("", 0.0955, "rate", False),  # edge case: empty answer
    ],
)
def test_is_correct(answer, truth, kind, expected):
    assert bench.is_correct(answer, truth, kind) is expected


# --- Resume and summary -------------------------------------------------------------------

def row(task, system, run, correct, seconds=10.0, tokens=100):
    return {"task": task, "system": system, "run": run, "correct": correct, "status": "ok",
            "seconds": seconds, "tokens": tokens, "turns": 1, "truth": 1, "answer": "", "trace": ""}


def test_done_runs_lets_a_stopped_benchmark_resume(tmp_path):
    path = tmp_path / "results.csv"
    assert bench.done_runs(path) == set()  # edge case: no file yet
    bench.append_row(row(1, "A", 1, True), path)
    bench.append_row(row(1, "B", 1, False), path)
    assert bench.done_runs(path) == {(1, "A", 1), (1, "B", 1)}
    with open(path, encoding="utf-8") as file:
        assert next(csv.reader(file)) == bench.COLUMNS  # one header only


def test_summary_mean_and_spread():
    """B: run 1 gets 2/2 right, run 2 gets 1/2, run 3 gets 0/2 -> 100 %, 50 %, 0 % -> mean 50 %, sd 50 %."""
    rows = [
        row(1, "B", 1, True, seconds=40), row(2, "B", 1, True, seconds=60),
        row(1, "B", 2, True, seconds=40), row(2, "B", 2, False, seconds=60),
        row(1, "B", 3, False, seconds=40), row(2, "B", 3, False, seconds=60),
        row(1, "A", 1, False, seconds=5), row(2, "A", 1, False, seconds=5),
    ]
    summary = bench.summarize(rows)
    assert summary["B"]["accuracy_per_run"] == [1.0, 0.5, 0.0]
    assert summary["B"]["accuracy"] == pytest.approx((0.5, 0.5))
    assert summary["B"]["seconds"][0] == 50
    assert summary["B"]["per_task"] == {1: (2, 3), 2: (1, 3)}
    assert summary["A"]["accuracy"] == (0.0, 0.0)  # edge case: a single run has no spread


def test_summary_markdown_table():
    rows = [row(1, "A", 1, False), row(1, "B", 1, True)]
    text = bench.summary_markdown(bench.summarize(rows), [{"id": 1, "question": "How many?"}])
    assert "| A · Qwen alone | 0% | 0% ± 0% |" in text
    assert "| B · Qwen + harness | 100% | 100% ± 0% |" in text
    assert "| 1 | How many? | 0/1 | 1/1 |" in text
