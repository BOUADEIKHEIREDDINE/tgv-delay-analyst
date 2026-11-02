# Plan — what's done and what's left

Updated each time a step is finished. Legend: ✅ done · 🟡 partly done · ⏳ not started · ❌ empty

Last update: 2026-11-02

## R1–R4 (mandatory)

| | Status | Done | Left |
|---|---|---|---|
| **R1** fresh clone runs from README | 🟡 | `requirements.txt` (pinned), `.venv`, `scripts/download_data.py` + `clean_data.py`, `tgv` command, `.env.example`, no secrets in git | `README.md` empty: title, setup commands, Ollama/model setup, how to run. Test on a real fresh clone |
| **R2** known-answer pytest, fresh clone | ✅ | 249 tests pass, every file of our code has tests (UI, app, conversations, **guard: 46, stats: 21, tools: 26, cleaning: 26, agent: 29** — fake model replaying real Qwen replies, **llm: 17** — fake network, **cli: 25, download_data: 4**); fixtures `tests/fixtures/tgv_small.csv` (3 clean rows) + `tgv_raw_small.csv` (9 raw rows, one anomaly each) | Check on a real fresh clone (with README, step 5) |
| **R3** `ai_log/` | 🟡 | Conversation logs 10-31, 11-01 (morning), 11-02; `.gitignore` fixed so `ai_log/conversations/` is committed | `journal.md` empty (yours to write: kept / corrected / rewritten, per session). 11-01 afternoon session (agent, UI, English) not logged |
| **R4** oral defense | ⏳ | — | Rehearse the demo; be able to explain any file (agent.py, guard.py, tools.py first) |

## Bricks (5 × 2 pts)

| Brick | Code | Evidence |
|---|---|---|
| **1** own tool | ✅ `tools.py` (3 tools, tested live; ✅ `test_tools.py`: R2 only) | Trace of a real model call to cite in EVIDENCE.md (note: `traces/` is gitignored, `benchmark/traces/` is kept) |
| **3** rule enforced by code | ✅ `guard.py` (numbers + `check_code`) | ✅ `tests/test_guard.py` tries to break it with real Qwen answers ("9,55 %", "9,6 %", `df.to_csv`) and gets blocked; end-to-end in ✅ `tests/test_agent.py` (fake Qwen writes "9,55 %" twice → answer blocked) |
| **6** dirty data | ✅ `clean_data.py`, `data/cleaning_log.csv` (✅ `test_cleaning.py`: R2, every step + whole pipeline) | `data/RULES.md` (decided 11-02, replaces `docs/sncf_rule.md`, as in the architecture diagram): SNCF late rule (5/10/15 min) with source named |
| **8** uncertainty | ✅ `stats.py` (Wilson interval), in every answer | Sentence on what the data can't conclude (✅ `test_stats.py`: R2 only; found + fixed a float bug, low > rate for 0 / 10) |
| **9** measured comparison | ❌ `benchmark/run_benchmark.py`, `tasks.json` empty | 10+ known-answer questions, system vs bare model, ≥3 runs, mean + spread, one failure explained from a trace (11-02 tuning 0/3 → 10/10 is good material) |

## Also left

- `EVIDENCE.md` empty: one section per brick (what is shown, files, reproduce command)
- Decide the "national" rate question (sum over routes) — see `not to forget.md`

## Order

1. ✅ Fix `.gitignore` + commit (2026-11-02)
2. ✅ R2 tests: `test_guard`, `test_stats`, `test_tools`, `test_cleaning`, `test_agent`, with edge cases (empty, missing value, single value — spec section 8). Then `test_llm`, `test_cli`, `test_download_data` (all our code tested). Found and fixed 4 bugs: Wilson bound > rate, empty reply accepted (live), guard reading "15 150" as 15150, `tgv "question"` crashing (ui.Arrival.SUPPRIME left from the French UI)
3. ⏳ `data/RULES.md` (brick 6)
4. ⏳ Benchmark (brick 9)
5. ⏳ `README.md` + `EVIDENCE.md`
6. ⏳ `journal.md` (you), rehearse the defense (R4)
