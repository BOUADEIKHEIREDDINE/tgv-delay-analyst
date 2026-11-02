# TGV Delay Analyst

Ask questions about the punctuality of French high-speed trains (TGV) in plain
English or French — *"Quel est le taux de retard de Paris Lyon vers Marseille en 2024 ?"* —
and get an answer where **every number was computed by code** on SNCF open data.

A small local model (Qwen3.5-4B) cannot be trusted with numbers on its own. This
project is the harness around it: tools that compute on the data, a system prompt
with the real column names, and a guard that blocks any answer containing a number
that no tool printed.

Final project, *Coding for AI & Data Science* (PGE3, 2026–2027). Bricks 1, 3, 6, 8, 9 —
see [EVIDENCE.md](EVIDENCE.md) for the proof of each one.

## Model

**Qwen3.5-4B, Q4_K_M, running locally in Ollama**, with a 16K-token context
(`Modelfile`). No cloud model and no API key are used: the Cerebras fallback of the
project rules was not needed.

Tested on Ubuntu 24.04, Python 3.12, a laptop with an RTX 3050 Ti 4 GB GPU
(Ollama splits the model between GPU and CPU). About 3.3 GB of disk for the model,
8 GB of RAM.

## Setup (fresh clone)

You need [Python 3.11+](https://www.python.org/) and [Ollama](https://ollama.com/download).

```bash
git clone https://github.com/BOUADEIKHEIREDDINE/tgv-delay-analyst.git
cd tgv-delay-analyst

# 1. Python environment
python3 -m venv .venv
source .venv/bin/activate            # Windows: .venv\Scripts\activate
pip install -r requirements.txt
pip install -e .                     # creates the `tgv` command

# 2. The model (once, ~3.3 GB download)
ollama pull qwen3.5:4b-q4_K_M
ollama create qwen3.5-4b-16k -f Modelfile

# 3. The data (SNCF open data, ~3 MB, then cleaned)
python scripts/download_data.py
python scripts/clean_data.py
```

Ollama must be running (`ollama serve`, or the Ollama app / service). The default
settings need nothing else; to change them see `.env.example`.

## Run

```bash
tgv                                   # full-screen app (type /help inside)
tgv "What share of TGV trains from Paris Montparnasse to Bordeaux St Jean arrived late in 2023?"
tgv --no-think "..."                  # faster, less reliable
tgv --simple                          # line-by-line mode in the normal terminal
```

`python main.py` does the same as `tgv` without `pip install -e .`.

An answer takes about 30–90 s on the test laptop (model thinking on). The app shows
each step: the code Qwen wrote, what it printed, the guard's verdict, and where each
number of the answer comes from. `/trace` shows the last question in full, `/log` the
data cleaning log.

Copy and paste in the app: drag with the mouse to select (drag to the top or bottom
edge to scroll while selecting), **Ctrl+C** to copy; **Ctrl+Shift+V** pastes a question.
GNOME Terminal ignores the copy code apps use, so install `wl-clipboard`
(`sudo apt install wl-clipboard`) to paste the copied text outside the app.

Questions to try:
- *Quel est le taux de retard à l'arrivée de Paris Lyon vers Marseille St Charles en 2024 ?*
- *How many TGV trains were cancelled in 2023, all routes together?*
- *What was the cancellation rate of TGV trains from Paris Lyon to Nice Ville in 2024?*

## Tests

```bash
python -m pytest
```

284 tests, about 15 s. They need neither the model nor the downloaded data: the model
is replaced by a fake that replays real Qwen replies, and the data by small files in
`tests/fixtures/`.

## Benchmark (brick 9)

```bash
python benchmark/run_benchmark.py             # 12 questions × 3 runs × 2 systems (~3 h)
python benchmark/run_benchmark.py --runs 1    # one run each
python benchmark/run_benchmark.py --summary   # rebuild the table from results.csv
```

Qwen alone against Qwen + this harness, on questions whose answer is computed
separately with pandas. Results: `benchmark/results/summary.md`; traces of every run:
`benchmark/traces/`.

## How it works

```
question ─► agent.py ─► Qwen (llm.py) ─► asks for a tool? ──yes──► tools.py ─► result back to Qwen ─┐
                ▲                                                                                   │
                └──────────────────────────────────── next turn ◄──────────────────────────────────┘
                          no: final answer ─► guard.py: every number printed by a tool?
                                                 yes ─► shown    no ─► one retry, then blocked
                          every step saved in traces/traces.jsonl
```

| File | Role |
|---|---|
| `scripts/download_data.py`, `scripts/clean_data.py` | get the SNCF file, clean it (log in `data/cleaning_log.csv`, rules in `data/RULES.md`) |
| `src/tgv_analyst/agent.py` | the loop: model → tools → guard → trace |
| `src/tgv_analyst/tools.py` | `run_python`, `describe_dataset`, `confidence_interval` |
| `src/tgv_analyst/guard.py` | blocks numbers no tool printed; blocks code that writes files |
| `src/tgv_analyst/stats.py` | Wilson confidence interval |
| `src/tgv_analyst/prompts.py` | system prompt |
| `src/tgv_analyst/llm.py` | talks to Ollama |
| `src/tgv_analyst/cli.py`, `app.py`, `ui.py`, `sidebar.py` | the `tgv` command and its display |

## What the data can't tell

- **Why** trains were late: the file gives monthly shares of broad causes per route,
  not the cause of a given train.
- Whether **your** train will be late: the data are monthly totals per route.
- An **official national rate**: one train can count on several routes, so SNCF warns
  that route figures must not be added up. "Overall" answers are sums over the routes
  of this dataset (see `data/RULES.md`).
- The 95 % interval treats trains as independent; trains of the same day share the
  weather, strikes and works, so the real uncertainty is wider.
- The guard checks that each number was printed by a tool, not that it answers the
  question (a correct number used for the wrong thing passes).

## Data

[Régularité mensuelle TGV par liaisons (AQST)](https://ressources.data.sncf.com/explore/dataset/regularite-mensuelle-tgv-aqst/information/),
SNCF Open Data, licence ODbL. Downloaded by `scripts/download_data.py`, not stored in
the repository. No personal data.

## AI usage

Built with AI assistants, directed file by file. Conversation exports and session
notes: [`ai_log/`](ai_log/).
