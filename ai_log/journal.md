# AI usage journal (R3)

One note per work session: what I kept as is, what I corrected by hand, which prompt
or pseudo-code I rewrote (which line, why). The full conversations are in
`conversations/full-*.md`, short summaries in `conversations/2026-*.md`.

Drafted with Claude (Claude Code) from the session logs on 2026-11-02, then read and
validated by me. AI assistant used for the code: Claude Code. Model of the project:
Qwen3.5-4B (local, Ollama).

---

## 2026-10-31: project setup, data, cleaning plan

**How I worked.** I chose the topic (TGV delay analyst) and the 5 bricks, gave the
project structure (I pasted the folder tree), and set the rule for the rest of the
project: the project is built file by file, I say what to write and validate it first.

**Kept as is.**
- `scripts/download_data.py` (downloads the SNCF file into `data/raw/`, relative path); I ran it myself to check.
- The list of tools for Qwen: `run_python`, `describe_dataset`, `confidence_interval`, and the guard.

**Corrected / decided by me.**
- I asked whether `clean_data.py` should contain tools for Qwen: no, it is a script run once before the agent. The cleaning stays in my script, not in the model.
- I found the warning in the SNCF documentation: route figures must not be added up into a national rate. It became rule 2 of `data/RULES.md`.
- I asked for a notebook copy of `clean_data.py` to check each cleaning function cell by cell before validating it.

**Prompt rule added.** Qwen must compute every number inside `run_python` (including percentages),
because the guard only accepts numbers printed by a tool. Noted first in my to-do notes, then written in `prompts.py`.

---

## 2026-11-01 (morning): cleaning validated, model installed, tools tested, LLM client

**Kept as is.**
- `scripts/clean_data.py` after my check in the notebook (notebook deleted after).
- `src/tgv_analyst/llm.py`: one `chat()` function with `urllib`, settings from environment variables.

**Corrected / decided by me.**
- The average delay of trains more than 15 min late was often a copy of another column. My rule: set it to missing when it is below 15 or identical to `retard_moyen_tous_trains_arrivee` → new step `fix_copied_sup15_average` (2,183 rows).
- I checked that a negative average over all trains means early trains (departure and arrival): those values are kept; only the averages of *late* trains are set to missing when negative.
- I chose Ollama to run Qwen (more comfortable for me) and asked to test it with thinking off and on.
- I asked to test each tool live with Qwen, one by one, before writing the loop.

**Prompt rules added (`prompts.py`).** Copy numbers exactly as printed; `run_python` never writes files
(also blocked in code by `guard.check_code`).

---

## 2026-11-01 (afternoon): agent loop, `tgv` command, full-screen app

**How I worked.** For `agent.py` and `main.py` I asked for the exact plan first and coded
only after my validation. For the interface I wrote the prompts myself (`prompt ui.md`,
then a second prompt for one visual style and a pixel-art TGV).

**Kept as is.** The loop in `agent.py` (model → tools → guard → one retry → trace in `traces.jsonl`).

**Corrected after my tests.**
- I typed "hello" and the guard blocked the answer (years 2018 and 2026 "not computed") → the data facts are trusted by the guard (`DATA_FACTS`) and prompt rule 9 (small talk) was added.
- Esc did not cancel at once; the animation was too high, then too low; I could not select and delete words or scroll with two fingers; the question box had to stay at the bottom; the app had to take the whole terminal and give it back on exit, like Claude Code. All fixed.
- I asked for a third car on the train and a right-hand panel to manage conversations; then less text in it, and **everything in English**.
- I named the command `tgv`.

---

## 2026-11-02: tuning, tests, rules, brick 8, benchmark, README

**Prompt rewritten (`prompts.py`), measured on one question (Paris Lyon → Marseille St Charles 2024):
0/3 correct before, 10/10 after.**
- Rule 2: call `describe_dataset` when a station is named: Qwen guessed names like 'PARIS GARE DE LYON'.
- Rule 3: each `run_python` call starts from scratch, never type numbers from an earlier output, put parentheses around each filter condition: Qwen lost turns on `NameError` and on `df[a == x & b == y]`.
- Rules 6–7: late rate = `nb_train_retard_arrivee / nb_circules`; `confidence_interval` is a tool, not a Python function: Qwen used planned trains and called it inside `run_python`.
- Rule 2 again: I removed the station names from the examples: Qwen copied 'PARIS MONTPARNASSE' into its code instead of the station asked.

**Rejected after measuring.** Asking Qwen to copy the "what the data can't conclude" sentence
from the tool output: it did it 0 times out of 5. Replaced by a fixed line written in code,
always shown under the question box (my idea: like "Claude can make mistakes").

**Corrected / decided by me.**
- The "Récapitulatif" PDF was not an official document: I checked the rules against the real spec.
- Brick 9 is my system against my model alone: 2 systems, not 3 levels.
- I asked for tests on every file of the code, even the small ones.
- National rate: answered, with the warning that a sum over routes is not SNCF's official rate (option 1).
- Benchmark: 12 questions, thinking on for both systems (fair comparison, even if slower).

**Bugs found by the tests and fixed.** Wilson lower bound above the rate (0 / 10); an empty reply
accepted as an answer; the guard reading "15 150" printed by a tool as 15150; `tgv "question"`
crashing (`ui.Arrival.SUPPRIME` left from the French interface); a wrong source label ("12.0[1]").

**Checked by me.** I broke the guard on purpose to see the tests fail; I ran the fresh-clone test
myself (every README step worked, same cleaning counts); I found that copy/paste and mouse
selection did not work in the app → fixed (drag to select, Ctrl+C to copy).
