# EVIDENCE: TGV Delay Analyst

One section per brick: what is shown, the files, the command that reproduces it, and
what you should see. Bricks: **1, 3, 6, 8, 9**. Model: Qwen3.5-4B Q4_K_M, local (Ollama),
see the README for setup.

Quick check of everything that needs no model (about 15 s, works on a fresh clone):

```bash
python -m pytest            # expected: 287 passed
```

---

## Brick 1: Own tool

**What is shown.** Three Python functions I wrote, that Qwen calls through tool calling
in my own loop (`agent.py`): `run_python` (runs Qwen's pandas code on the clean data in a
separate process, 30 s limit, returns what it printed), `describe_dataset` (columns,
months, stations) and `confidence_interval` (Wilson interval, brick 8). Every call and its
result is recorded in a trace.

**Files.** `src/tgv_analyst/tools.py` (the tools and their schemas), `src/tgv_analyst/agent.py`
(the loop that runs them), traces in `benchmark/traces/system.jsonl` (36 real runs).

**Real call, from the trace** (`benchmark/traces/system.jsonl`, `"timestamp": "2026-11-02T18:11:48"`).
Question: *"Combien de TGV ont circulé de Paris Est à Strasbourg en 2022 ?"* Qwen called
`describe_dataset`, then `run_python` with:

```python
result = df[(df['gare_depart'] == 'PARIS EST') & (df['gare_arrivee'] == 'STRASBOURG') & (df['year'] == 2022)]
total_nb_circules = result['nb_circules'].sum()
print(f"Nombre total de TGV circulant de Paris Est à Strasbourg en 2022: {total_nb_circules}")
```

The tool returned `Nombre total de TGV circulant de Paris Est à Strasbourg en 2022: 6673`
(plus the 12 monthly values), and the answer was *"En 2022, 6 673 TGV ont circulé…"*:
the true value. The same trace also shows a failed call coming back to Qwen as an error
(`NameError: name 'result' is not defined`: each call starts from scratch) and Qwen fixing it.

**Reproduce.**
```bash
tgv "Combien de TGV ont circulé de Paris Est à Strasbourg en 2022 ?"   # then /trace in the app
python -m pytest tests/test_tools.py -v                                # the tools, without the model (26 tests)
```

---

## Brick 3: A rule enforced by code

**What is shown.** The rule: *the system never shows an answer containing a number that
no tool printed.* It is enforced in `agent.py` by `guard.check_answer()`, whatever the model
writes: the answer is checked, the model gets one second chance with the list of
unverified numbers, then the answer is blocked. A second rule: `run_python` never writes
files (`guard.check_code()` refuses `to_csv`, `open(`, `import os`… before running anything).

**Files.** `src/tgv_analyst/guard.py`, `src/tgv_analyst/agent.py` (where it is called),
`tests/test_guard.py`, `tests/test_agent.py`.

**Tests that try to break the rule and get blocked.**
- `tests/test_guard.py`: real Qwen answers: "9,55 %" and "9,6 %" (it converted 0.0955 itself),
  an invented "700 trains", an answer with no tool call, the "13.1 %" example of the prompt,
  and forbidden code (`df.to_csv('copy.csv')`, `open(...)`, `import os`) → all blocked.
- `tests/test_agent.py::test_invented_number_is_blocked_end_to_end`: a fake Qwen answers
  "9,55 %" twice → status `rejected`, the user sees *"Answer blocked: these numbers were not
  computed by a tool: 9.55"*.
- Two known limits are written as tests too: "12,500" is always read as twelve thousand
  five hundred; "9 %" passes because a tool printed 8.9 (the guard checks that a number was
  printed, not what it means).

**Live, in the benchmark.** The guard rejected an answer 5 times out of 36 runs and the
second chance fixed it each time, for example (`benchmark/traces/system.jsonl`):
- `2026-11-02T19:56:03`: Qwen wrote "6 683 TGV": the tool had printed 6673 → rejected → corrected.
- `2026-11-02T18:45:40`: Qwen wrote "11,8 %": the tool had printed 12.0 % → rejected → corrected.

**Reproduce.**
```bash
python -m pytest tests/test_guard.py tests/test_agent.py -v
```
To see a test fail when the rule is broken: in `guard.py`, remove `"to_csv",` from
`FORBIDDEN_CODE` and run `python -m pytest tests/test_guard.py -q` → `test_forbidden_code_is_blocked` fails.
`git checkout src/tgv_analyst/guard.py` puts it back.

---

## Brick 6: Dirty data, written decisions

**What is shown.** Real open data (SNCF, *Régularité mensuelle TGV par liaisons*, 12,907 rows)
cleaned by my script in 9 logged steps (12,907 → 12,792 rows), and two rules the file does
not say, taken from SNCF's documentation of the dataset, with the source named and quoted.

**Files.** `scripts/download_data.py`, `scripts/clean_data.py`, `data/cleaning_log.csv`
(the log), `data/RULES.md` (the sourced rules and the origin of every step),
`tests/test_cleaning.py`.

**The cleaning log** (`data/cleaning_log.csv`, rows affected on the real file):

| Step | Rows |
|---|---|
| drop the 3 free-text comment columns | 0 |
| remove rows with 0 planned trains or more cancellations than planned (COVID 2020) | 73 |
| `nb_train_retard_sup_30` → missing when negative or < `sup_60` | 354 |
| negative average delay of *late* trains → missing | 10 |
| average of trains > 15 min late → missing when < 15 or copied from another column | 2,183 |
| the 6 cause percentages → missing when all are 0 | 199 |
| merge National + International rows of the same route and month | 84 |
| `date` → `year`, `month` | 12,792 |
| add `nb_circules`, rates, `seuil_retard` | 12,792 |

**Rules from a document** (`data/RULES.md`), source: the dataset's page on SNCF Open Data,
<https://ressources.data.sncf.com/explore/dataset/regularite-mensuelle-tgv-aqst/information/>:
1. *« Un train est considéré à l'heure si son retard au terminus est inférieur à 5min pour un
   parcours inférieur à 1h30 »* (10 min for 1h30–3h, 15 min over 3h) → `late_threshold()` and
   the column `seuil_retard`; boundaries tested (89 → 5, 90 → 10, 180 → 10, 181 → 15).
2. *« Les chiffres de ce jeu de données ne doivent donc pas être utilisés pour calculer une
   régularité globale TGV »* → "overall" answers carry the warning (brick 8).

**Reproduce.**
```bash
python scripts/download_data.py && python scripts/clean_data.py   # prints the log above
python -m pytest tests/test_cleaning.py -v                         # each step on a raw fixture (26 tests)
```
On a fresh clone (2026-11-02) a new download gave exactly the counts above.

---

## Brick 8: Numbers with their uncertainty

**What is shown.** (1) Every late rate comes with a **95 % confidence interval** (Wilson),
computed by the `confidence_interval` tool. (2) A **sentence on what the data cannot
conclude**, written in code and always shown in the app under the question box:

> *Monthly totals per route: they don't say why trains were late, or whether your train
> will be. A sum over routes is not SNCF's official national rate.*

**Files.** `src/tgv_analyst/stats.py` (Wilson interval), `src/tgv_analyst/tools.py`
(`confidence_interval`), `src/tgv_analyst/ui.py` (`DATA_LIMITS`), `src/tgv_analyst/app.py`
(where it is shown), `tests/test_stats.py`, `tests/test_app.py`, `tests/test_ui.py`.

**Example** (benchmark trace `2026-11-02T17:49:48`): *"Le taux de retard à l'arrivée des
trains Paris Lyon vers Marseille St Charles en 2024 est de 9,5 %, avec une intervalle de
confiance à 95 % de [8,9 %, 10,3 %]."* (640 late trains out of 6,704.)

**What the data cannot conclude** (README, "What the data can't tell"): why trains were late
(only monthly shares of broad causes per route); whether a given train will be late; an
official national rate (routes overlap, SNCF warns against adding them up); and the interval
itself treats trains as independent, while trains of the same day share weather, strikes
and works: the real uncertainty is wider.

**Reproduce.**
```bash
python -m pytest tests/test_stats.py -v     # published values (50/100 → [0.4038, 0.5962]) and hand-derived edge cases
tgv "Quel est le taux de retard à l'arrivée de Paris Lyon vers Marseille St Charles en 2024 ?"
```
In the app the interval is drawn as a bar under the tool result; the limits line is at the bottom.

---

## Brick 9: Measured comparison

**What is shown.** My system (Qwen + harness) against my model alone (Qwen, the question
only), on 12 questions whose answer is computed separately with pandas, 3 runs each,
same model and settings (thinking on for both).

| System | Accuracy per run | Mean ± sd | Seconds per answer |
|---|---|---|---|
| A · Qwen alone | 8 %, 17 %, 25 % | 17 % ± 8 % | 210 ± 95 |
| B · Qwen + harness | 100 %, 92 %, 100 % | **97 % ± 5 %** | 57 ± 41 |

Read by hand, A's score is even lower (1–2 real answers out of 36: several "right" answers
only repeated a number from the question).

**One failure explained from its trace** (`benchmark/results/ANALYSIS.md`): task 4, run 2.
Qwen filtered with `df.year == 2025 & (...)` without parentheses; `&` binds tighter than
`==`, so the table was always empty; Qwen concluded "no data", fixed the station names but
not the parentheses, explored the data for 7 turns and hit the turn limit. Nothing false was
shown to the user.

**Files.** `benchmark/tasks.json` (questions + truth expressions), `benchmark/run_benchmark.py`,
`benchmark/results/results.csv`, `summary.md`, `ANALYSIS.md`, `benchmark/traces/`,
`tests/test_benchmark.py`.

**Reproduce.**
```bash
python benchmark/run_benchmark.py --summary    # rebuild the table from results.csv (instant)
python benchmark/run_benchmark.py --runs 1     # one new run of each question (~50 min)
python -m pytest tests/test_benchmark.py -v    # truths, scoring, mean and spread, without the model
```
The full run (`python benchmark/run_benchmark.py`, 3 runs) took 2 h 35 min on the test laptop.
To start from zero, move `benchmark/results/results.csv` away first (the script resumes from it).
