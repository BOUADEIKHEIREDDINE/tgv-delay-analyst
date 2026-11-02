# Plan — what's done and what's left

Updated each time a step is finished. Legend: ✅ done · 🟡 partly done · ⏳ not started · ❌ empty

Last update: 2026-11-02

## R1–R4 (mandatory)

| | Status | Done | Left |
|---|---|---|---|
| **R1** fresh clone runs from README | ✅ | `README.md` (title, model, setup, run, tests, benchmark), `Modelfile`, pinned `requirements.txt`, no secrets in git. **Fresh clone tested 2026-11-02 by the user: every step worked** (same cleaning counts) | Update the README's benchmark time and results at the end |
| **R2** known-answer pytest, fresh clone | ✅ | 287 tests pass, every file of our code has tests (UI, app, conversations, **guard: 46, stats: 21, tools: 26, cleaning: 26, agent: 29** — fake model replaying real Qwen replies, **llm: 17** — fake network, **cli: 25, download_data: 4**); fixtures `tests/fixtures/tgv_small.csv` (3 clean rows) + `tgv_raw_small.csv` (9 raw rows, one anomaly each) | ✅ passed on the fresh clone (272 at the time) |
| **R3** `ai_log/` | ✅ | Conversation logs 10-31, 11-01 (morning), 11-02; `.gitignore` fixed so `ai_log/conversations/` is committed | ✅ full exports of the 4 sessions (`ai_log/conversations/full-*.md`, made by `ai_log/export_transcript.py`, personal data removed; 11-02 to refresh at the end) · ✅ `journal.md`: one note per session (kept / corrected / rewritten), drafted with Claude from the logs, validated by the user |
| **R4** oral defense | ⏳ | — | Rehearse the demo; be able to explain any file (agent.py, guard.py, tools.py first) |

## Bricks (5 × 2 pts)

| Brick | Code | Evidence |
|---|---|---|
| **1** own tool | ✅ `tools.py` (3 tools, tested live; ✅ `test_tools.py`: R2 only) | ✅ real traces committed: `benchmark/traces/system.jsonl` (36 runs of Qwen calling the tools, with results) — cite one in EVIDENCE.md |
| **3** rule enforced by code | ✅ `guard.py` (numbers + `check_code`) | ✅ `tests/test_guard.py` tries to break it with real Qwen answers ("9,55 %", "9,6 %", `df.to_csv`) and gets blocked; end-to-end in ✅ `tests/test_agent.py` (fake Qwen writes "9,55 %" twice → answer blocked) |
| **6** dirty data | ✅ `clean_data.py`, `data/cleaning_log.csv` (✅ `test_cleaning.py`: R2, every step + whole pipeline) | ✅ `data/RULES.md`: SNCF late rule (5/10/15 min) + "don't add up routes" warning, quoted from the dataset's SNCF Open Data page; boundaries checked = our code; table of every cleaning decision and its origin |
| **8** uncertainty — needs (1) a CI **or** A/B **or** replication, **and** (2) a sentence on what the data can't conclude | (1) ✅ Wilson CI: `stats.py`, `confidence_interval` tool, 95 % interval in every rate answer (`test_stats.py`: R2) | (2) ✅ `ui.DATA_LIMITS`, written in code: always under the question box in the app (like "Claude can make mistakes"), once after the banner in line-by-line / one-question modes; never inside an answer. Tested (`test_app.py`, `test_ui.py`). Still to write in EVIDENCE/README: the interval assumes independent trains |
| **9** measured comparison | ✅ `benchmark/tasks.json` (12 tasks, truths computed with pandas), `benchmark/run_benchmark.py` (A = Qwen alone vs B = Qwen + harness, same model, thinking on for both), `tests/test_benchmark.py` (20) | ✅ done 2026-11-02 (72 runs, 2 h 35): **A 17 % ± 8 %, B 97 % ± 5 %**; `results/summary.md`, `results/ANALYSIS.md` (A's lucky answers checked by hand; B's one failure explained from its trace: filter without parentheses → empty table → 10 turns lost) |

## Also left

- `EVIDENCE.md` empty: one section per brick (what is shown, files, reproduce command)

## Order (decided 2026-11-02, one by one)

1. ✅ Fix `.gitignore` + commit
2. ✅ R2 tests (252, 4 bugs found and fixed)
3. ✅ `data/RULES.md` — rules quoted from the SNCF dataset page; boundaries match `late_threshold()` (no code change)
4. ✅ Brick 8 sentence — first tried: tool prints it + prompt asks Qwen to copy → Qwen copied it 0/5 times (live). Now a fixed line in the UI (`ui.DATA_LIMITS`), includes the national-rate warning (option 1)
5. ✅ Brick 9 benchmark — A 17 % ± 8 % vs B 97 % ± 5 %, one failure explained (`benchmark/results/ANALYSIS.md`)
6. ✅ Brick 1 — real Qwen traces committed with the benchmark (`benchmark/traces/system.jsonl`)
7. ✅ `README.md` + `Modelfile` + fresh-clone test (all steps OK). Also from the test: copy/paste and mouse selection in the app, source labels fixed
8. ✅ R3 — full exports of all sessions + `journal.md` (refresh the 11-02 export at the very end)
9. ⏳ `EVIDENCE.md` — one section per brick, written so a teacher sees each brick working and proved (what is shown, files, command)
10. ⏳ R4 — rehearse the defense

Decided + done: "national" questions are answered; the permanent limits line says a sum over routes is not SNCF's official rate (option 1, data/RULES.md rule 2).
