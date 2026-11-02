"""Clean the raw SNCF TGV data: data/raw/ -> data/clean/ + data/cleaning_log.csv.

Each step is a small function that returns the cleaned table and one log
entry (what was done and how many rows it touched).
"""

from pathlib import Path

import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parent.parent
RAW_FILE = PROJECT_ROOT / "data" / "raw" / "regularite-mensuelle-tgv-aqst.csv"
CLEAN_FILE = PROJECT_ROOT / "data" / "clean" / "tgv_clean.csv"
LOG_FILE = PROJECT_ROOT / "data" / "cleaning_log.csv"

COMMENT_COLUMNS = [
    "commentaire_annulation",
    "commentaire_retards_depart",
    "commentaires_retard_arrivee",
]
CAUSE_COLUMNS = [
    "prct_cause_externe",
    "prct_cause_infra",
    "prct_cause_gestion_trafic",
    "prct_cause_materiel_roulant",
    "prct_cause_gestion_gare",
    "prct_cause_prise_en_charge_voyageurs",
]
# Averages computed only over late trains: they can never be negative.
LATE_ONLY_AVERAGES = [
    "retard_moyen_depart",
    "retard_moyen_arrivee",
    "retard_moyen_trains_retard_sup15",
]
COUNT_COLUMNS = [
    "nb_train_prevu",
    "nb_annulation",
    "nb_train_depart_retard",
    "nb_train_retard_arrivee",
    "nb_train_retard_sup_15",
    "nb_train_retard_sup_30",
    "nb_train_retard_sup_60",
]
KEY = ["date", "gare_depart", "gare_arrivee"]


def log_entry(step, rule, rows_affected):
    return {"step": step, "rule": rule, "rows_affected": int(rows_affected)}


def load_raw(path=RAW_FILE):
    # utf-8-sig removes the BOM, otherwise the first column is read as "﻿date".
    # A real CSV parser is needed: some comments contain line breaks inside quotes.
    return pd.read_csv(path, sep=";", encoding="utf-8-sig")


def drop_comment_columns(df):
    df = df.drop(columns=COMMENT_COLUMNS)
    entry = log_entry(
        "drop_comment_columns",
        "Dropped the 3 free-text comment columns (2 fully empty, 1 95% empty)",
        0,
    )
    return df, entry


def remove_impossible_rows(df):
    impossible = (df["nb_train_prevu"] == 0) | (df["nb_annulation"] > df["nb_train_prevu"])
    entry = log_entry(
        "remove_impossible_rows",
        "Removed rows with 0 planned trains or more cancellations than planned trains (COVID 2020)",
        impossible.sum(),
    )
    return df[~impossible].copy(), entry


def fix_broken_sup30(df):
    # Every train more than 60 min late is also more than 30 min late,
    # so sup_30 < sup_60 (or a negative count) means sup_30 is wrong.
    broken = (df["nb_train_retard_sup_30"] < 0) | (
        df["nb_train_retard_sup_30"] < df["nb_train_retard_sup_60"]
    )
    df = df.copy()
    df.loc[broken, "nb_train_retard_sup_30"] = float("nan")
    entry = log_entry(
        "fix_broken_sup30",
        "Set nb_train_retard_sup_30 to missing when negative or smaller than nb_train_retard_sup_60",
        broken.sum(),
    )
    return df, entry


def fix_negative_delays(df):
    negative = (df[LATE_ONLY_AVERAGES] < 0).any(axis=1)
    df = df.copy()
    for column in LATE_ONLY_AVERAGES:
        df.loc[df[column] < 0, column] = float("nan")
    entry = log_entry(
        "fix_negative_delays",
        "Set negative average delays of late trains to missing (averages over all trains can be negative: early trains)",
        negative.sum(),
    )
    return df, entry


def fix_copied_sup15_average(df):
    # Trains more than 15 min late have an average delay of at least 15 min.
    # In many rows (mostly 2018-2019) the value is a copy of
    # retard_moyen_tous_trains_arrivee, so it is wrong.
    broken = (df["retard_moyen_trains_retard_sup15"] < 15) | (
        df["retard_moyen_trains_retard_sup15"] == df["retard_moyen_tous_trains_arrivee"]
    )
    df = df.copy()
    df.loc[broken, "retard_moyen_trains_retard_sup15"] = float("nan")
    entry = log_entry(
        "fix_copied_sup15_average",
        "Set retard_moyen_trains_retard_sup15 to missing when below 15 min or identical to retard_moyen_tous_trains_arrivee (copied value)",
        broken.sum(),
    )
    return df, entry


def fix_empty_causes(df):
    empty = df[CAUSE_COLUMNS].sum(axis=1) == 0
    df = df.copy()
    df.loc[empty, CAUSE_COLUMNS] = float("nan")
    entry = log_entry(
        "fix_empty_causes",
        "Set delay causes to missing when all 6 cause percentages are 0",
        empty.sum(),
    )
    return df, entry


def weighted_mean(values, weights):
    # Missing value in the group -> missing result. No weight -> simple mean.
    if values.isna().any():
        return float("nan")
    if weights.sum() == 0:
        return values.mean()
    return (values * weights).sum() / weights.sum()


def merge_group(group):
    circulating = group["nb_train_prevu"] - group["nb_annulation"]
    row = {
        "service": "/".join(sorted(group["service"].unique())),
        "duree_moyenne": round(weighted_mean(group["duree_moyenne"], circulating)),
    }
    for column in COUNT_COLUMNS:
        # skipna=False: a missing count stays missing after the sum.
        row[column] = group[column].sum(skipna=False)
    row["retard_moyen_depart"] = weighted_mean(group["retard_moyen_depart"], group["nb_train_depart_retard"])
    row["retard_moyen_tous_trains_depart"] = weighted_mean(group["retard_moyen_tous_trains_depart"], circulating)
    row["retard_moyen_arrivee"] = weighted_mean(group["retard_moyen_arrivee"], group["nb_train_retard_arrivee"])
    row["retard_moyen_tous_trains_arrivee"] = weighted_mean(group["retard_moyen_tous_trains_arrivee"], circulating)
    row["retard_moyen_trains_retard_sup15"] = weighted_mean(
        group["retard_moyen_trains_retard_sup15"], group["nb_train_retard_sup_15"]
    )
    for column in CAUSE_COLUMNS:
        row[column] = weighted_mean(group[column], group["nb_train_retard_arrivee"])
    return pd.Series(row)


def merge_service_duplicates(df):
    # Since 2025-07 some routes have one National row and one International row
    # for the same month. Counts are added, averages are weighted by trains.
    duplicated = df.duplicated(KEY, keep=False)
    merged = df[duplicated].groupby(KEY).apply(merge_group, include_groups=False).reset_index()
    df = pd.concat([df[~duplicated], merged], ignore_index=True)
    df = df.sort_values(KEY).reset_index(drop=True)
    entry = log_entry(
        "merge_service_duplicates",
        "Merged National and International rows of the same route and month (counts added, averages weighted by trains)",
        duplicated.sum(),
    )
    return df, entry


def convert_dates(df):
    # Fails loudly if a date is not in YYYY-MM format.
    dates = pd.to_datetime(df["date"], format="%Y-%m")
    df = df.copy()
    df["year"] = dates.dt.year
    df["month"] = dates.dt.month
    entry = log_entry("convert_dates", "Converted date (YYYY-MM text) to year and month columns", len(df))
    return df, entry


def late_threshold(duration):
    # SNCF rule (see data/RULES.md): a train is late from 5 min under 1h30,
    # 10 min from 1h30 to 3h, 15 min over 3h.
    if duration < 90:
        return 5
    if duration <= 180:
        return 10
    return 15


def add_derived_columns(df):
    df = df.copy()
    df["nb_circules"] = df["nb_train_prevu"] - df["nb_annulation"]
    ran = df["nb_circules"].where(df["nb_circules"] > 0)  # avoid division by 0
    df["taux_retard_arrivee"] = df["nb_train_retard_arrivee"] / ran
    df["taux_annulation"] = df["nb_annulation"] / df["nb_train_prevu"]
    df["seuil_retard"] = df["duree_moyenne"].apply(late_threshold)
    entry = log_entry(
        "add_derived_columns",
        "Added nb_circules, taux_retard_arrivee, taux_annulation and seuil_retard (SNCF late threshold)",
        len(df),
    )
    return df, entry


STEPS = [
    drop_comment_columns,
    remove_impossible_rows,
    fix_broken_sup30,
    fix_negative_delays,
    fix_copied_sup15_average,
    fix_empty_causes,
    merge_service_duplicates,
    convert_dates,
    add_derived_columns,
]


def clean(df):
    """Run every step in order. Returns (clean table, log table)."""
    log = []
    for step in STEPS:
        df, entry = step(df)
        log.append(entry)
    return df, pd.DataFrame(log)


def main():
    raw = load_raw()
    df, log = clean(raw)

    CLEAN_FILE.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(CLEAN_FILE, index=False)
    log.to_csv(LOG_FILE, index=False)

    print(f"Raw rows: {len(raw)} -> clean rows: {len(df)}")
    print(log.to_string(index=False))
    print(f"Saved {CLEAN_FILE.relative_to(PROJECT_ROOT)} and {LOG_FILE.relative_to(PROJECT_ROOT)}")


if __name__ == "__main__":
    main()
