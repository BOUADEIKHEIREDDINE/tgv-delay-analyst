"""Command-line interface: ask questions about TGV punctuality.

    tgv "What was the delay rate in 2024?"   one question, then exit
    tgv                                      the full-screen app (until /quit)

(`tgv` is installed by `pip install -e .`; `python main.py` does the same.)

Options: --no-think (faster, less reliable), --show-thinking (print the model's
reasoning), --no-anim (no animation), --plain (no colors, no boxes),
--simple (line-by-line mode in the normal screen instead of the full-screen app).
The display is in src/tgv_analyst/ui.py; the logic is in agent.py.
"""

import argparse
import sys

from tgv_analyst import ui
from tgv_analyst.agent import check_startup, run_agent
from tgv_analyst.app import TgvApp, read_cleaning_log

QUIT_WORDS = {"/quit", "/exit", "quit", "exit"}


def ask(display, question, think):
    """Answer one question; the display draws each step. Errors become one clear line."""
    display.start_question()
    try:
        result = run_agent(question, think=think, on_event=display.on_event)
    except ConnectionError:
        display.show_error(f"The model server does not answer. Run: {ui.SERVER_FIX_COMMAND}")
        return
    except RuntimeError as error:  # the server answered with an error (wrong model name...)
        display.show_error(str(error))
        return
    finally:
        display.stop_spinner()
    display.show_result(result)


def run_command(display, command):
    """Run a /command typed in the REPL."""
    if command == "/help":
        display.show_help()
    elif command == "/trace":
        display.show_trace()
    elif command == "/log":
        rows = read_cleaning_log()
        if rows:
            display.show_log(rows)
        else:
            display.show_error(f"No cleaning log. Run: {ui.DATA_FIX_COMMAND}")
    elif command == "/status":
        with display.checking():
            status = check_startup()
        display.show_status(status)
    else:
        display.show_error(f"Unknown command: {command}. Type /help.")


def repl(display, think):
    """Ask questions until /quit, Ctrl-D or Ctrl-C at the prompt."""
    while True:
        try:
            line = display.read_question().strip()
        except (KeyboardInterrupt, EOFError):
            break
        if not line:
            continue
        if line.lower() in QUIT_WORDS:
            break
        if line.startswith("/"):
            run_command(display, line.lower())
            continue
        try:
            ask(display, line, think)
        except KeyboardInterrupt:  # Ctrl-C during a question: cancel it, keep the REPL
            display.stop_spinner()
            display.show_error("Question cancelled.")


def main():
    parser = argparse.ArgumentParser(description="Ask questions about TGV punctuality (SNCF data).")
    parser.add_argument("question", nargs="?", help="one question; without it, the full-screen app")
    parser.add_argument("--no-think", action="store_true", help="turn the model's thinking off (faster)")
    parser.add_argument("--show-thinking", action="store_true", help="print the model's reasoning")
    parser.add_argument("--no-anim", action="store_true", help="no animation")
    parser.add_argument("--plain", action="store_true", help="plain text: no colors, no boxes")
    parser.add_argument("--simple", action="store_true", help="simple line-by-line mode in the normal screen")
    args = parser.parse_args()
    think = not args.no_think

    display = ui.Display(plain=args.plain, animate=not args.no_anim, show_thinking=args.show_thinking)

    # One question: normal screen, so the answer stays in the terminal after exit.
    if args.question:
        status = start(display, think)
        if ui.classify_arrival(status) is ui.Arrival.SUPPRIME:
            return 1  # the banner already shows what to fix
        ask(display, args.question, think)
        return 0

    # Interactive: the full-screen app (like Claude Code). The terminal's previous
    # content comes back on exit. --simple, --plain or no real terminal: line-by-line mode.
    if not (args.simple or args.plain) and sys.stdout.isatty():
        TgvApp(think=think, show_thinking=args.show_thinking, animate=not args.no_anim).run()
    else:
        start(display, think)
        repl(display, think)
    display.show_goodbye()
    return 0


def start(display, think):
    """Startup check, then the banner. Returns the StartupStatus."""
    with display.checking():
        status = check_startup()
    display.show_startup(status, think)
    return status
