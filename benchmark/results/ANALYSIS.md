# Benchmark analysis (brick 9)

Run on 2026-11-02 (72 runs, 2 h 35 min): `python benchmark/run_benchmark.py`.
Raw results: `results.csv` (one row per run). Table: `summary.md`.
Traces: `../traces/system.jsonl` (system B, one line per run, every step),
`../traces/bare_model.jsonl` (model A, answer and reasoning).

## Result

Same model (Qwen3.5-4B Q4_K_M, local, thinking on), same 12 questions, 3 runs each.

| System | Accuracy per run | Mean ± sd | Seconds per answer | Tokens per answer |
|---|---|---|---|---|
| A · Qwen alone | 8 %, 17 %, 25 % | 17 % ± 8 % | 210 ± 95 | 4,785 ± 1,972 |
| B · Qwen + harness | 100 %, 92 %, 100 % | **97 % ± 5 %** | 57 ± 41 | 13,822 ± 10,255 |

The harness turns a model that cannot answer (it has never seen the data) into one that
answers 35 of 36 questions right. B is also faster: with no data, A keeps reasoning for
minutes about what it cannot know. B uses more tokens because every tool result is sent
back to the model.

## A's "right" answers, checked by hand

The scoring is the kit's (`comparer.py`): an answer is right if it **contains** a number
equal to the truth. A's 6 "right" answers, read one by one:

| Task | Run | What A said | Really right? |
|---|---|---|---|
| 12 (worst full year: 2018) | 1, 2, 3 | "2022", "2021", "2023" — it only repeated "2018" from the range in the question | no (3 false positives) |
| 3 (late share: 12.0 %) | 3 | "likely between 8 % and 12 %" | no (a guess, the 12 matches by chance) |
| 11 (late threshold: 5 min) | 2 | "late if it arrives more than 5 minutes after its scheduled time" | yes (the SNCF rule is public) |
| 11 | 3 | discusses several definitions, "1 to 5 minutes" | unclear |

So the automatic score **overestimates A**: by hand, A got 1 or 2 answers right out of 36
(3–6 %), not 6. B's score is not affected the same way: its answers are short and every
number in them was checked by the guard against a tool output. This is the limit written
in `is_correct()`: an answer listing many numbers can be right by luck.

## One failure of the system, explained from its trace

**Task 4, run 2** — *"Quel est le taux de retard à l'arrivée de Lyon Part Dieu à Marseille
St Charles en juillet 2025 ?"* (truth: 27.7 %). Status `max_turns`: no answer after 10 turns.
Trace: line with `"timestamp": "2026-11-02T18:50:22"` in `traces/system.jsonl`.

What happened, turn by turn:

1. **Turn 1.** Qwen filters with
   `df[df.year == 2025 & (df.month == 7) & (df['gare_depart'] == 'Lyon Part Dieu') & ...]`.
   Two mistakes: the station names are not in capitals, and `df.year == 2025` has **no
   parentheses**. In Python `&` binds tighter than `==`, so this reads
   `df.year == (2025 & (df.month == 7) & ...)`: always false. The table is empty, the
   code prints "Aucune donnée trouvée pour cette route", then crashes on a variable that
   was never set (`NameError`).
2. **Turns 2–3.** It calls `describe_dataset`, sees that the names are in capitals, and
   fixes them — **but keeps the same filter without parentheses**. Still empty, still
   "no data". No error this time, so nothing tells it the filter is wrong.
3. **Turns 4–10.** It concludes the route may not exist in July 2025 and explores: lists
   stations, dates, routes. It even prints that the route exists (628 rows from LYON PART
   DIEU, 6 rows in 2025-07) but never goes back to its first filter. Three turns are lost
   on new syntax errors. The turn limit (10) stops it.

**Why.** Prompt rule 3 says to put parentheses around each condition of a filter, with an
example. Qwen followed it in 35 runs and broke it here; the empty result looked like a
plausible answer ("no data"), so it searched for the cause in the data instead of in its code.

**What the harness did right.** Nothing false was shown: the user got "did not finish",
not an invented rate. The guard was never reached because there was no answer.

**What could fix it** (not done, to keep the prompt short for a 4B model): reject a filter
of the form `df.col == value & ...` in `guard.check_code` with the message "put parentheses
around each condition", the same way file writing is refused; or make the tool say
"the filter returned 0 rows" so the model checks its code first.
