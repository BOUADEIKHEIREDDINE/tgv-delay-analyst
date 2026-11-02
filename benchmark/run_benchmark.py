"""Brick 9: our system against the bare model, on questions with a known answer.

    python benchmark/run_benchmark.py              # 3 runs per question and per system (about 40 min)
    python benchmark/run_benchmark.py --runs 1     # quicker
    python benchmark/run_benchmark.py --summary    # only rebuild the summary from results.csv

A = the bare model: Qwen alone, the question only (no prompt, no tools, no data).
B = our system: Qwen + harness (run_agent: system prompt, tools, guard, turn limit).
Same model, same thinking setting: the only difference is the harness.

The true answers are computed here with pandas from the clean data, never by
the agent (like the kit's comparer.py). An answer is correct if it contains a
number equal to the truth (rates: in % or as a fraction). For B, a blocked or
unfinished answer is wrong.

Each run is appended to results/results.csv as soon as it ends: if the script
stops, running it again skips the runs already done. Traces of every run are
kept in traces/ (system.jsonl from run_agent, bare_model.jsonl).
"""

import argparse
import csv
import json
import statistics
import sys
import time
from datetime import datetime
from pathlib import Path

import pandas as pd

BENCH_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(BENCH_DIR.parent / "src"))  # run without installing, like main.py

from tgv_analyst import llm  # noqa: E402
from tgv_analyst.agent import run_agent  # noqa: E402
from tgv_analyst.config import CLEAN_CSV  # noqa: E402
from tgv_analyst.guard import extract_numbers  # noqa: E402

TASKS_FILE = BENCH_DIR / "tasks.json"
RESULTS_FILE = BENCH_DIR / "results" / "results.csv"
SUMMARY_FILE = BENCH_DIR / "results" / "summary.md"
SYSTEM_TRACES = BENCH_DIR / "traces" / "system.jsonl"
BARE_TRACES = BENCH_DIR / "traces" / "bare_model.jsonl"

SYSTEMS = {"A": "Qwen alone", "B": "Qwen + harness"}
THINK = True  # same setting for both systems (the app's default)
RATE_TOLERANCE_PCT = 0.1  # 9.5 or 9.6 for 9.5465 %: right to 0.1 percentage point
COLUMNS = ["task", "system", "run", "correct", "status", "seconds", "tokens", "turns", "truth", "answer", "trace"]


# --- Truths: computed from the data, independently of the model ----------------

def truth_helpers(df):
    """Small functions the truth expressions of tasks.json can use."""

    def route(departure, arrival):
        return (df["gare_depart"] == departure) & (df["gare_arrivee"] == arrival)

    def late_rate(rows):
        return rows["nb_train_retard_arrivee"].sum() / rows["nb_circules"].sum()

    def cancel_rate(rows):
        return rows["nb_annulation"].sum() / rows["nb_train_prevu"].sum()

    def yearly_late_rates(rows):
        by_year = rows.groupby("year")[["nb_train_retard_arrivee", "nb_circules"]].sum()
        return by_year["nb_train_retard_arrivee"] / by_year["nb_circules"]

    return {"df": df, "route": route, "late_rate": late_rate,
            "cancel_rate": cancel_rate, "yearly_late_rates": yearly_late_rates}


def compute_truth(task, df):
    """Evaluate the task's pandas expression on the clean data (our own file, not model output)."""
    return float(eval(task["truth"], {"__builtins__": {}}, truth_helpers(df)))


def load_tasks(path=TASKS_FILE):
    with open(path, encoding="utf-8") as file:
        return json.load(file)


# --- Scoring --------------------------------------------------------------------

def is_correct(answer, truth, kind):
    """True if the answer contains a number equal to the truth.

    count: the exact number ("6,673", "6 673" and "6673" all read as 6673).
    rate:  in % to 0.1 point (truth 0.0955 -> 9.5 or 9.6), or as a fraction (0.0955).
    Limit (same as the kit's comparer.py): an answer listing many numbers can be right by luck.
    """
    numbers = [float(n) for n in extract_numbers(answer)]
    if kind == "count":
        return any(n == truth for n in numbers)
    return any(abs(n - truth * 100) <= RATE_TOLERANCE_PCT or abs(n - truth) <= RATE_TOLERANCE_PCT / 100
               for n in numbers)


# --- The two systems --------------------------------------------------------------

def run_bare(question):
    """System A: one call, the question only."""
    reply = llm.chat([{"role": "user", "content": question}], think=THINK)
    answer = reply["message"].get("content") or ""
    trace = {
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "model": llm.MODEL,
        "think": THINK,
        "question": question,
        "answer": answer,
        "reasoning": reply["message"].get("reasoning") or reply["message"].get("reasoning_content"),
        "tokens": reply["usage"].get("total_tokens", 0),
        "seconds": reply["seconds"],
    }
    BARE_TRACES.parent.mkdir(parents=True, exist_ok=True)
    with open(BARE_TRACES, "a", encoding="utf-8") as file:
        file.write(json.dumps(trace, ensure_ascii=False) + "\n")
    return {"answer": answer, "status": "answered", "seconds": trace["seconds"],
            "tokens": trace["tokens"], "turns": 1, "trace": trace["timestamp"]}


def run_system(question):
    """System B: our harness (the trace is saved by run_agent)."""
    result = run_agent(question, think=THINK, trace_file=SYSTEM_TRACES)
    trace = result["trace"]
    return {"answer": result["answer"], "status": result["status"], "seconds": trace["seconds"],
            "tokens": trace["tokens"], "turns": trace["turns"], "trace": trace["timestamp"]}


# --- Results ----------------------------------------------------------------------------

def done_runs(path=RESULTS_FILE):
    """(task, system, run) already in results.csv, so a stopped benchmark can resume."""
    if not path.exists():
        return set()
    with open(path, encoding="utf-8", newline="") as file:
        return {(int(r["task"]), r["system"], int(r["run"])) for r in csv.DictReader(file)}


def append_row(row, path=RESULTS_FILE):
    path.parent.mkdir(parents=True, exist_ok=True)
    new_file = not path.exists()
    with open(path, "a", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=COLUMNS)
        if new_file:
            writer.writeheader()
        writer.writerow(row)


def read_rows(path=RESULTS_FILE):
    with open(path, encoding="utf-8", newline="") as file:
        rows = list(csv.DictReader(file))
    for row in rows:
        row["task"], row["run"] = int(row["task"]), int(row["run"])
        row["correct"] = row["correct"] == "True"
        row["seconds"], row["tokens"] = float(row["seconds"]), int(row["tokens"])
    return rows


def mean_sd(values):
    """Mean and standard deviation (sample, n - 1); the deviation is 0 for a single value."""
    values = list(values)
    return statistics.mean(values), (statistics.stdev(values) if len(values) > 1 else 0.0)


def summarize(rows):
    """Per system: accuracy of each run (share of the tasks answered right), mean ± sd,
    min-max, and time and tokens per answer. Per task: right answers out of the runs."""
    summary = {}
    for system in SYSTEMS:
        mine = [r for r in rows if r["system"] == system]
        if not mine:
            continue
        runs = sorted({r["run"] for r in mine})
        accuracy = [statistics.mean(r["correct"] for r in mine if r["run"] == run) for run in runs]
        summary[system] = {
            "accuracy_per_run": accuracy,
            "accuracy": mean_sd(accuracy),
            "seconds": mean_sd(r["seconds"] for r in mine),
            "tokens": mean_sd(r["tokens"] for r in mine),
            "per_task": {t: (sum(r["correct"] for r in mine if r["task"] == t),
                             sum(1 for r in mine if r["task"] == t))
                         for t in sorted({r["task"] for r in mine})},
        }
    return summary


def summary_markdown(summary, tasks):
    lines = [
        "# Benchmark results (brick 9)",
        "",
        f"Model: {llm.MODEL}, thinking {'on' if THINK else 'off'}. "
        "A = Qwen alone (question only). B = Qwen + harness (run_agent).",
        "",
        "| System | Accuracy per run | Mean ± sd | Min–max | Seconds per answer | Tokens per answer |",
        "|---|---|---|---|---|---|",
    ]
    for system, s in summary.items():
        per_run = ", ".join(f"{a:.0%}" for a in s["accuracy_per_run"])
        (acc, acc_sd), (sec, sec_sd), (tok, tok_sd) = s["accuracy"], s["seconds"], s["tokens"]
        lines.append(
            f"| {system} · {SYSTEMS[system]} | {per_run} | {acc:.0%} ± {acc_sd:.0%} | "
            f"{min(s['accuracy_per_run']):.0%}–{max(s['accuracy_per_run']):.0%} | "
            f"{sec:.1f} ± {sec_sd:.1f} | {tok:.0f} ± {tok_sd:.0f} |"
        )
    lines += ["", "| Task | Question | " + " | ".join(summary) + " |", "|---|---|" + "---|" * len(summary)]
    for task in tasks:
        cells = [f"{s['per_task'].get(task['id'], (0, 0))[0]}/{s['per_task'].get(task['id'], (0, 0))[1]}"
                 for s in summary.values()]
        lines.append(f"| {task['id']} | {task['question']} | " + " | ".join(cells) + " |")
    return "\n".join(lines) + "\n"


def write_summary(tasks):
    text = summary_markdown(summarize(read_rows()), tasks)
    SUMMARY_FILE.write_text(text, encoding="utf-8")
    print(text)


# --- Main -------------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Brick 9: our system vs the bare model.")
    parser.add_argument("--runs", type=int, default=3, help="runs per question and per system")
    parser.add_argument("--summary", action="store_true", help="only rebuild the summary from results.csv")
    args = parser.parse_args()

    tasks = load_tasks()
    if args.summary:
        write_summary(tasks)
        return

    df = pd.read_csv(CLEAN_CSV)
    truths = {task["id"]: compute_truth(task, df) for task in tasks}
    done = done_runs()
    start = time.time()
    # Run by run, so that if the benchmark stops, the finished runs are complete for both systems.
    for run in range(1, args.runs + 1):
        for task in tasks:
            for system, function in [("A", run_bare), ("B", run_system)]:
                if (task["id"], system, run) in done:
                    continue
                try:
                    outcome = function(task["question"])
                except (ConnectionError, RuntimeError) as error:  # server down: stop, resume later
                    print(f"Stopped: {error}")
                    return
                correct = is_correct(outcome["answer"], truths[task["id"]], task["kind"])
                if system == "B" and outcome["status"] != "ok":
                    correct = False  # blocked or unfinished: no answer was given
                append_row({"task": task["id"], "system": system, "run": run, "correct": correct,
                            "truth": truths[task["id"]], **outcome})
                print(f"run {run} · task {task['id']:>2} · {system} · {'right' if correct else 'wrong'} "
                      f"· {outcome['seconds']:.0f} s · {time.time() - start:.0f} s total", flush=True)
    write_summary(tasks)


if __name__ == "__main__":
    main()
