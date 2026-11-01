## Layout

```
main.py                     runs cli.main() without installing (`tgv` after `pip install -e .`)
src/tgv_analyst/
├── cli.py      options; one question, or the app; --simple line-by-line mode
├── app.py      full-screen app (Textual): scrollable history, question box pinned at the bottom
├── sidebar.py  right panel: session, current conversation, history, starter questions, shortcuts
├── conversations.py  saved conversations (conversations/, gitignored): events replayed, no model call
├── config.py   paths, startup thresholds (EARLY_S, LATE_S, PING_TIMEOUT_S)
├── llm.py      talks to the model server (chat, ping)
├── agent.py    the loop: model -> tools -> guard -> trace; check_startup(); emits events
├── events.py   dataclasses the agent sends to the display (StartupStatus, ToolCall, ...)
├── ui.py       renderers (rich): banner, pixel train, board, tool panels, guard badge
├── theme.py    every color and box style (no color literal anywhere else)
├── tools.py    run_python, describe_dataset, confidence_interval (brick 1)
├── guard.py    rejects numbers no tool printed; blocks file writing (brick 3)
├── stats.py    Wilson confidence interval (brick 8)
└── prompts.py  system prompt
tests/          pytest, offline, never calls the model (hand-written events, fake agent in test_app.py)
```

`ui.py` never calls the model, the tools or the guard: it only renders events.
`app.py` and `cli.py` wire the agent to the display; the agent runs in a daemon thread.
`agent.py` never prints: without `on_event` (benchmark, tests) it runs headless.
