# Plan — what's done and what's left

Updated each time a step is finished. Legend: ✅ done · 🟡 partly done · ⏳ not started · ❌ empty

Last update: 2026-11-02

## R1–R4 (mandatory)

| | Status | Done | Left |
|---|---|---|---|
| **R1** fresh clone runs from README | 🟡 | `requirements.txt` (pinned), `.venv`, `scripts/download_data.py` + `clean_data.py`, `tgv` command, `.env.example`, no secrets in git | `README.md` empty: title, setup commands, Ollama/model setup, how to run. Test on a real fresh clone |
| **R2** pytest, no model calls | 🟡 | 55 tests pass (UI, app, conversations) | `test_guard.py`, `test_stats.py`, `test_tools.py`, `test_cleaning.py` are empty |
| **R3** `ai_log/` | 🟡 | Conversation logs 10-31, 11-01 (morning), 11-02; `.gitignore` fixed so `ai_log/conversations/` is committed | `journal.md` empty (yours to write: kept / corrected / rewritten, per session). 11-01 afternoon session (agent, UI, English) not logged |
| **R4** oral defense | ⏳ | — | Rehearse the demo; be able to explain any file (agent.py, guard.py, tools.py first) |

## Bricks (5 × 2 pts)

| Brick | Code | Evidence |
|---|---|---|
| **1** own tool | ✅ `tools.py` (3 tools, tested live) | Trace of a real model call to cite in EVIDENCE.md (note: `traces/` is gitignored, `benchmark/traces/` is kept) |
| **3** rule enforced by code | ✅ `guard.py` (numbers + `check_code`) | pytest that tries to break it and gets blocked (`test_guard.py`); real blocked answers in the 11-02 traces ("9,55 %") |
| **6** dirty data | ✅ `clean_data.py`, `data/cleaning_log.csv` | `docs/sncf_rule.md` empty: SNCF late rule (5/10/15 min) with source named; spec also names `data/RULES.md` — decide which |
| **8** uncertainty | ✅ `stats.py` (Wilson interval), in every answer | Sentence on what the data can't conclude; `test_stats.py` |
| **9** measured comparison | ❌ `benchmark/run_benchmark.py`, `tasks.json` empty | 10+ known-answer questions, system vs bare model, ≥3 runs, mean + spread, one failure explained from a trace (11-02 tuning 0/3 → 10/10 is good material) |

## Also left

- `EVIDENCE.md` empty: one section per brick (what is shown, files, reproduce command)
- Decide the "national" rate question (sum over routes) — see `not to forget.md`

## Order

1. ✅ Fix `.gitignore` + commit (2026-11-02)
2. ⏳ R2 tests: `test_guard`, `test_stats`, `test_tools`, `test_cleaning`
3. ⏳ `docs/sncf_rule.md` (brick 6)
4. ⏳ Benchmark (brick 9)
5. ⏳ `README.md` + `EVIDENCE.md`
6. ⏳ `journal.md` (you), rehearse the defense (R4)
