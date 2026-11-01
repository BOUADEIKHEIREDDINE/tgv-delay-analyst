"""Brick 1: the tools Qwen can call."""

import subprocess
import sys

import pandas as pd

from tgv_analyst.config import CLEAN_CSV, PROJECT_ROOT
from tgv_analyst.stats import confidence_interval as wilson_interval

TIMEOUT_SECONDS = 30
MAX_OUTPUT_CHARS = 4000  # keeps tool results small for the model's context

COLUMN_DESCRIPTIONS = {
    "date": "month (YYYY-MM)",
    "year": "year",
    "month": "month number (1-12)",
    "service": "National, International, or International/National (both merged)",
    "gare_depart": "departure station",
    "gare_arrivee": "arrival station",
    "duree_moyenne": "average trip duration in minutes",
    "nb_train_prevu": "number of trains planned",
    "nb_annulation": "number of trains cancelled",
    "nb_circules": "number of trains that ran (planned - cancelled)",
    "nb_train_depart_retard": "number of trains late at departure",
    "retard_moyen_depart": "average departure delay of late trains (min)",
    "retard_moyen_tous_trains_depart": "average departure delay of all trains (min)",
    "nb_train_retard_arrivee": "number of trains late at arrival (SNCF definition)",
    "retard_moyen_arrivee": "average arrival delay of late trains (min)",
    "retard_moyen_tous_trains_arrivee": "average arrival delay of all trains (min)",
    "nb_train_retard_sup_15": "number of trains more than 15 min late",
    "retard_moyen_trains_retard_sup15": "average delay of trains more than 15 min late (min)",
    "nb_train_retard_sup_30": "number of trains more than 30 min late",
    "nb_train_retard_sup_60": "number of trains more than 60 min late",
    "prct_cause_externe": "% of delays due to external causes (weather, people on tracks...)",
    "prct_cause_infra": "% of delays due to the rail infrastructure",
    "prct_cause_gestion_trafic": "% of delays due to traffic management",
    "prct_cause_materiel_roulant": "% of delays due to rolling stock (the trains)",
    "prct_cause_gestion_gare": "% of delays due to station management",
    "prct_cause_prise_en_charge_voyageurs": "% of delays due to passenger handling",
    "taux_retard_arrivee": "share of trains late at arrival (0-1)",
    "taux_annulation": "share of planned trains cancelled (0-1)",
    "seuil_retard": "SNCF late threshold for this route in minutes (5, 10 or 15)",
}


def run_python(code):
    """Run Python code with `df` (the clean dataset) and `pd` already loaded.

    The code runs in a separate process with a time limit. Only what it
    prints is returned, so the model must print() its results.
    """
    prelude = (
        "import pandas as pd\n"
        f"df = pd.read_csv({str(CLEAN_CSV)!r})\n"
    )
    try:
        result = subprocess.run(
            [sys.executable, "-c", prelude + code],
            capture_output=True,
            text=True,
            timeout=TIMEOUT_SECONDS,
            cwd=PROJECT_ROOT,
        )
    except subprocess.TimeoutExpired:
        return f"Error: code took more than {TIMEOUT_SECONDS} seconds."

    output = result.stdout
    if result.returncode != 0:
        output += "\nError:\n" + result.stderr
    if not output.strip():
        output = "(no output: use print() to show results)"
    return output[:MAX_OUTPUT_CHARS]


def describe_dataset():
    """Describe the clean dataset so the model uses the right column names."""
    df = pd.read_csv(CLEAN_CSV)
    stations = sorted(set(df["gare_depart"]) | set(df["gare_arrivee"]))

    lines = [
        f"Rows: {len(df)} (one row = one route in one month)",
        f"Months: {df['date'].min()} to {df['date'].max()}",
        f"Routes: {df.groupby(['gare_depart', 'gare_arrivee']).ngroups}",
        "Columns:",
    ]
    for column in df.columns:
        lines.append(f"- {column}: {COLUMN_DESCRIPTIONS.get(column, '')}")
    lines.append("Stations: " + ", ".join(stations))
    return "\n".join(lines)


def confidence_interval(late, total, level=0.95):
    """Late-train rate with its confidence interval, as text for the model."""
    try:
        rate, low, high = wilson_interval(late, total, level)
    except ValueError as error:
        return f"Error: {error}"
    return (
        f"rate: {rate:.4f}\n"
        f"{level:.0%} confidence interval: [{low:.4f}, {high:.4f}]"
    )


# Tool descriptions sent to the model (OpenAI format, used by llama-server and Ollama).
TOOL_SCHEMAS = [
    {
        "type": "function",
        "function": {
            "name": "run_python",
            "description": (
                "Run Python code on the TGV punctuality data. `df` (pandas "
                "DataFrame) and `pd` are already loaded. Use print() to show results."
            ),
            "parameters": {
                "type": "object",
                "properties": {"code": {"type": "string", "description": "Python code to run"}},
                "required": ["code"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "describe_dataset",
            "description": "List the columns, their meaning, the date range and the stations.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "confidence_interval",
            "description": "Rate of late trains (late / total) with its 95% confidence interval.",
            "parameters": {
                "type": "object",
                "properties": {
                    "late": {"type": "integer", "description": "number of late trains"},
                    "total": {"type": "integer", "description": "number of trains that ran"},
                },
                "required": ["late", "total"],
            },
        },
    },
]

TOOLS = {
    "run_python": run_python,
    "describe_dataset": describe_dataset,
    "confidence_interval": confidence_interval,
}


def call_tool(name, arguments):
    """Run the tool the model asked for. Unknown tools return an error, not a crash."""
    if name not in TOOLS:
        return f"Error: unknown tool {name!r}. Available: {', '.join(TOOLS)}"
    try:
        return TOOLS[name](**arguments)
    except TypeError as error:
        return f"Error: wrong arguments for {name}: {error}"
