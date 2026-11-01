"""Events sent by the agent to the display (ui.py).

The agent only creates these objects; it never prints anything. The UI only
reads them; it never calls the model, the tools or the guard. Tests can build
events by hand to check the display without the model.
"""

from dataclasses import dataclass, field


@dataclass(frozen=True)
class StartupStatus:
    """Result of agent.check_startup(), shown by the startup banner."""

    server_ok: bool
    latency_s: float | None  # time for a tiny ping request; None if unreachable
    data_ok: bool  # data/clean/ exists and is readable
    n_rows: int | None  # rows in the cleaned dataset
    model_name: str
    endpoint: str  # e.g. "localhost:11434", never a key
    guard_enabled: bool


@dataclass(frozen=True)
class Thinking:
    """The model is about to be called (turn number `step`)."""

    step: int


@dataclass(frozen=True)
class Reasoning:
    """The model's reasoning text for one turn (shown only with --show-thinking)."""

    step: int
    text: str


@dataclass(frozen=True)
class ToolCall:
    """The model asked for a tool. For run_python, `code` is the Python code;
    for the other tools, it is their arguments as text."""

    call_id: int
    code: str
    name: str = "run_python"


@dataclass(frozen=True)
class ToolResult:
    """What a tool returned: the exact text the model receives."""

    call_id: int
    output: str
    numbers: list[float] = field(default_factory=list)
    error: str | None = None  # last line of the error message, if the tool failed


@dataclass(frozen=True)
class GuardVerdict:
    """Brick 3: result of guard.check_answer on the model's answer."""

    passed: bool
    checked: list[str]  # numbers found in the answer (normalized: "9.5")
    rejected: list[str]  # numbers that no tool printed
    will_retry: bool = False  # True if the model gets a second chance


@dataclass(frozen=True)
class FinalAnswer:
    """The answer accepted by the guard."""

    text: str
    sources: dict[str, int]  # number as written in the text -> call_id that printed it


@dataclass(frozen=True)
class ConfidenceInterval:
    """A rate with its interval, from the confidence_interval tool."""

    label: str
    estimate: float
    low: float
    high: float
    level: float = 0.95
