# 2026-10-31 — Project setup

Tool: Claude Code (Claude Opus 5.5)

## 1. User
> hey claude

**Claude:** Greeted and asked what to work on.

## 2. User
> read the files in this local folder but don't do anything. just save the info in memory related to this project.

**Claude:** Read the 4 PDFs in `final_exam/` (project spec, French summary, architecture diagram, TGV delay analyst plan). Saved two memory notes: the project rules (model, 9 bricks, R1–R4, deliverables, grading) and the chosen topic (TGV delay analyst, bricks 1, 3, 6, 8, 9). No project files changed.

## 3. User
> i need you to create the following structure: [tree of `tgv-delay-analyst/` with README.md, AGENTS.md, EVIDENCE.md, requirements.txt, .gitignore, .env.example, main.py, data/, scripts/, src/tgv_analyst/, tests/, benchmark/, docs/, ai_log/]
> the files must be empty. and from now on. conversations in this folder must be added to conversations folder in md format. add that rule to memory please.

**Claude:** Created `tgv-delay-analyst/` with every listed folder and file, all empty. Saved a memory rule: every conversation in this project is logged as Markdown in `ai_log/conversations/`. Created this log file.

## 4. User
> did you initiate a git?

**Claude:** No — `tgv-delay-analyst/` is not a git repository yet. Offered to run `git init`.

## 5. User
> yea you're right well do it in that folder. what we wil be doing from now on is creatig this project file by file assisted by me. i will tell you exactly what and how to do things ok?

**Claude:** Ran `git init` in `tgv-delay-analyst/` (no commit). Agreed to the workflow: the project is built file by file, following the user's exact instructions.

## 6. User
> yea rename it to main.

**Claude:** Renamed the branch from `master` to `main` (`git branch -m main`).

## 7. User
> first we must find the TGV database. try to find me a tgv in france database aligned with my idea in TGV delay analyst file. better if it comes with variables that could help me later build a logitic or KNN prediction model. give me links for opensource data

**Claude:** Searched the web and queried the SNCF Open Data API. Recommended the SNCF dataset "Régularité mensuelle TGV par liaisons" (`regularite-mensuelle-tgv-aqst`): 12,907 rows, one per route per month, 2018-01 to 2026-09, ODbL license, 26 columns (planned trains, cancellations, late counts, average delays, delays >15/30/60 min, % delay by cause). Also listed the companion dataset by axis (`regularite-mensuelle-tgv-axes`, 835 rows from 2015) and gave the CSV export URLs. Noted that the data is monthly per route, not per train, so a logistic/kNN model would predict something like "route-month punctuality below a threshold" rather than whether a single train is late.

## 8. User
> dans la documentation de la bdd on a : Les chiffres de ce jeu de données ne doivent donc pas être utilisés pour calculer une régularité globale TGV ou par axe. est ce que cela veut dire que la bdd n'est pas adapté a notre projet?

**Claude:** Non. The warning only forbids adding routes together to get a national or per-axis rate, because one TGV can count on several routes. Per-route questions (e.g. "which route was least punctual in 2025?") remain valid. The constraint can be reused: as a sourced rule for brick 6, as a "what the data can't conclude" sentence for brick 8, and possibly as a code-enforced rule for brick 3. For national/axis figures, use the companion datasets (by axis, global).

## 9. User
> c celle la le lien opensource de requetes api? /api/explore/v2.1/catalog/datasets/regularite-mensuelle-tgv-aqst/records?limit=20

**Claude:** Yes, it's the SNCF Open Data API (Opendatasoft Explore v2.1), but it's a relative path: the full URL starts with `https://ressources.data.sncf.com`. No API key needed. The `/records` endpoint returns at most 100 rows per call (paged with `offset`), so it suits small queries; to download the full dataset in `download_data.py`, use the `/exports/csv` endpoint instead.

## 10. User
> yea youre right.i have installed the local data in .../tgv-delay-analyst/data/raw much better like that.

**Claude:** Checked `data/raw/regularite-mensuelle-tgv-aqst.csv` (2.9 MB, UTF-8 with BOM, `;` separator, 26 columns). `wc -l` shows 15,425 lines but the CSV parses into 12,907 rows (matching the API count): some comment fields contain line breaks inside quotes, so the file must be read with a real CSV parser (`encoding="utf-8-sig"`, `sep=";"`), not line by line. Reminded that `data/raw/` is gitignored, so `download_data.py` is still needed for R1.

## 11. User
> yea. let's then start by writing download_data.py the only thing it must do is download the dataset into the designed space (relative and not absolute)

**Claude:** Wrote `scripts/download_data.py`: downloads the `/exports/csv` endpoint with `urllib.request.urlretrieve` (standard library, no extra package) to `data/raw/regularite-mensuelle-tgv-aqst.csv`. The path is built from the script's own location (`Path(__file__).resolve().parent.parent`), so it is relative to the project and works whatever folder it is run from; `data/raw/` is created if missing. Syntax-checked only, not run, to avoid overwriting the user's existing raw file without asking.

## 12. User
> i tested it it works. so now we gotta start cleaning it. it's easy. the first step is to start by listing the cleaning tools we need. run the whole logic of cleaning the dataset and preparing it for analysis and ML. in your backlground. then conclude the needed tools for Qwen to use

**Claude:** Profiled the raw CSV with pandas in a scratch venv (no project file changed). Findings: 3 fully empty/near-empty comment columns; 42 duplicate (date, route) keys from 2025-07 on because rows are split National/International; 73 rows with 0 planned trains and 0 duration (COVID, mostly 2020-04), 63 of them with cancellations > planned; 43 negative `nb_train_retard_sup_30` (2025-01→03); 354 rows in 2025 where `sup_60 > sup_30`; negative average delays (122 arrival, 170 departure); 272 rows whose cause % sum to 0 (80 with late trains); 10 whose causes sum to 85–99; "ITALIE" used as a station (202 rows); 16 routes whose service label changes over time. Proposed cleaning steps for `clean_data.py` (each logged in `cleaning_log.csv`) and derived ML features, and concluded which tools Qwen needs: `run_python` (brick 1) as the core tool, plus optionally `describe_dataset` and `confidence_interval`. Cleaning stays in the script, not done by Qwen.

## 13. User
> ok. do the 4 things you said : run_python describe_dataset, confidence_interval and the guard

**Claude:** Wrote:
- `src/tgv_analyst/stats.py`: `confidence_interval(successes, total, level)` — Wilson interval (stays within 0–1, OK near 0 or 1), stdlib only, raises ValueError on total ≤ 0 or successes out of range.
- `src/tgv_analyst/tools.py`: `run_python(code)` (separate process, `df`/`pd` preloaded from the clean CSV, 30 s timeout, output capped at 4000 chars, errors returned as text), `describe_dataset()` (rows, months, routes, columns with descriptions, stations), `confidence_interval(late, total)` (wraps stats.py, returns text), plus `TOOL_SCHEMAS` (OpenAI tool format for llama-server/Ollama) and `call_tool(name, arguments)` (unknown tool or bad arguments → error message, not a crash).
- `src/tgv_analyst/guard.py`: `check_answer(answer, tool_outputs, question)` → `(ok, unsupported_numbers)`. Every number in the answer (12, 12.5 or 12,5) must equal a number from a tool output or the question, rounded to the same number of decimals.
- `src/tgv_analyst/config.py`: only `PROJECT_ROOT` and `CLEAN_CSV` (`data/clean/tgv_clean.csv`), needed by tools.py.

Smoke-tested in a scratch venv on a temporary copy of the raw data: all tools work, timeout and errors handled, guard accepts copied/rounded numbers and rejects invented ones. Known limit: the guard rejects a percentage converted by the model itself (0.1313 → "13.1 %"), so the prompt must ask Qwen to compute percentages in code. No test files written.

## 14. User
> write this system prompt rule in a not to forget.md file welll delete it at the end

**Claude:** Created `not to forget.md` at the project root with the rule for `prompts.py`: Qwen must compute every number (including percentages) inside `run_python` and copy numbers exactly, otherwise the guard rejects them. To be deleted at the end of the project.

## 15. User
> ok so if i understood well: it's qwen itself that is gonna create the code to be ran. is it intelligent enough to do that?

**Claude:** Yes, Qwen writes the pandas code. A 4B model usually handles simple one-step queries (filter, groupby, sort) but makes typical mistakes: wrong column or station names, forgetting print(), weighting rates wrongly (averaging monthly rates instead of summing trains), multi-step questions. Mitigations: describe_dataset, error messages sent back so it can retry, precomputed columns in the clean file, worked examples in the system prompt, a cap on attempts. Can't be confirmed without running the model: suggested a quick test with 5 questions once llama-server runs; brick 9 will measure it properly anyway. Fallback if too weak: narrower tools (e.g. route_punctuality(dep, arr, year)).

## 16. User
> any ways well see when we test it later.

**Claude:** Agreed; asked for the next file.

## 17. User
> where did we write the tools we just did?

**Claude:** Listed the files: tools.py (run_python, describe_dataset, confidence_interval, TOOL_SCHEMAS, call_tool), stats.py (Wilson interval), guard.py (check_answer), config.py (paths).

## 18. User
> ok i see you created new files for them right?

**Claude:** No new files: the four files already existed (empty) in the planned structure; they were filled in. The only file added outside the structure is `not to forget.md`.

## 19. User
> ok so what should we put as tools in the clean_data.p?

**Claude:** Clarified that clean_data.py contains no Qwen tools: it is a script the user runs once, before the agent. Proposed one small function per cleaning step (each returns the cleaned DataFrame and a log entry), a `main()` that chains them and writes `data/clean/tgv_clean.csv` + `data/cleaning_log.csv`, and listed the function names and decisions to validate. Small functions make each step testable in tests/test_cleaning.py.

## 20. User
> are you sure this is permitted in the project? [quote: clean_data.py has no tools for Qwen ... run once, before the agent] can you read the project specifications by our teachers and verify¿

**Claude:** Re-read the three PDFs. Official spec (authors Çivitcioğlu & Appadourai), brick 6 requires: real data, a cleaning log (rows removed, values converted, labels corrected), and at least one rule not in the file, with its source. It does not require the model to do or call the cleaning; section 8 says "vous décidez quoi construire, quoi nettoyer". The architecture diagram lists "B6: pandas / clean.py + data/RULES.md" as a data capability next to the tools, not as a model tool. The Récapitulatif PDF says explicitly "C'est moi qui nettoie avec un script, pas le modèle" and lists cleaning among code to test with pytest — but that PDF has no author metadata (made with Chromium the same day), so it may be the user's own summary rather than a teacher document. Conclusion: a standalone cleaning script is allowed and matches the spec.

## 21. User
> ok then. let's do the clean_data.py

**Claude:** The 4 open decisions were not answered, so used the proposed defaults and flagged them: merge National/International duplicates, set broken values to NaN (not delete rows), keep "ITALIE", no ML target yet. Wrote `scripts/clean_data.py`: one function per step, each returning (df, log entry); `clean()` chains them; `main()` writes `data/clean/tgv_clean.csv` and `data/cleaning_log.csv`. Steps: drop comment columns; remove impossible rows (73); fix broken sup_30 (354); fix negative late-only averages (10); set empty causes to NaN (199); merge service duplicates (84 rows → 42); convert dates to year/month; add nb_circules, taux_retard_arrivee, taux_annulation, seuil_retard (SNCF threshold 5/10/15 min). Fixes run before the merge so a broken value can't be summed into a merged row. Ran it: 12,907 → 12,792 rows, 29 columns, no duplicate keys, no rate > 1. Tools (`run_python`, `describe_dataset`) now work on the clean file.

## 22. User
> ok i will be personnaly verifying each function in clean_data.py. i need you to update what is out of date

**Claude:** Updated `src/tgv_analyst/tools.py` (`COLUMN_DESCRIPTIONS`): `service` now mentions the merged value "International/National"; added the missing `seuil_retard` description. Checked that `describe_dataset()` now describes every column of the clean file. Updated the project memory note (which files are filled).

## 23. User
> i need you to create a copy of clean_data in the root and make it a ipynb and launch every cell for me to check easily what is going on

**Claude:** Created `clean_data.ipynb` at the project root. The functions are copied verbatim from `scripts/clean_data.py` (extracted with `ast`, so they are identical), one per cell, each followed by a cell that runs the step and shows the rows concerned before/after (e.g. COVID rows by month, the Dijon→Paris Lyon 2025-07 pair before/after merge, known-answer checks of `weighted_mean` and `late_threshold`). Only change: `PROJECT_ROOT = Path.cwd()` because a notebook has no `__file__`. The notebook does not write the clean files. Executed all cells with nbconvert: no errors, same result as the script (12,907 → 12,792 rows, 29 columns).

## 24. User
> add a file in the root called tomorrow is today.md thatn i will read tomorrow to pickup where we leftoff i aint got no time left today

**Claude:** Created `tomorrow is today.md` at the project root: what is done, what is in progress (verifying clean_data.py, the 4 unconfirmed default decisions), suggested next steps, and reminders (system prompt rule, journal note for today, no commit yet).
