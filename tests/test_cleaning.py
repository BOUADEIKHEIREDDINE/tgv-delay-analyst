"""Tests for scripts/clean_data.py (R2, and code behind brick 6).

Each step gets a small table written in the test, with the anomalies found
when profiling the real SNCF file (2026-10-31). The last tests run the whole
pipeline on tests/fixtures/tgv_raw_small.csv: 9 rows in the raw SNCF format
(";" separator, BOM, Windows line ends, a comment with a line break inside
quotes), one anomaly per row:

    row  date     route                              anomaly
    1    2024-01  PARIS LYON -> MARSEILLE ST CHARLES  none
    2    2024-02  PARIS LYON -> MARSEILLE ST CHARLES  comment on 2 lines (not an anomaly)
    3    2020-04  PARIS NORD -> LILLE                 0 planned trains (COVID)
    4    2025-01  PARIS EST -> STRASBOURG             nb_train_retard_sup_30 = -3
    5    2019-03  NANTES -> PARIS MONTPARNASSE        negative average delay of late trains
    6    2018-05  LYON PART DIEU -> MARSEILLE         sup15 average copied from the all-trains average
    7    2021-06  RENNES -> PARIS MONTPARNASSE        all 6 cause percentages are 0
    8-9  2025-07  PARIS LYON -> GENEVE                same month twice: National + International

The counts on the real file (73, 354, 2183...) are in data/cleaning_log.csv:
the raw file is not in git, so a test on it would fail on a fresh clone.
"""

from math import isnan
from pathlib import Path

import pandas as pd
import pytest

import clean_data
from clean_data import (
    CAUSE_COLUMNS,
    COMMENT_COLUMNS,
    add_derived_columns,
    clean,
    convert_dates,
    drop_comment_columns,
    fix_broken_sup30,
    fix_copied_sup15_average,
    fix_empty_causes,
    fix_negative_delays,
    late_threshold,
    load_raw,
    merge_service_duplicates,
    remove_impossible_rows,
    weighted_mean,
)

FIXTURES = Path(__file__).parent / "fixtures"
RAW_SMALL = FIXTURES / "tgv_raw_small.csv"
CLEAN_SMALL = FIXTURES / "tgv_small.csv"  # the fixture of test_tools.py


@pytest.fixture
def raw():
    return load_raw(RAW_SMALL)


# --- load_raw -------------------------------------------------------------------

def test_load_raw_removes_the_bom(raw):
    """Without utf-8-sig the first column would be read as "\\ufeffdate"."""
    assert raw.columns[0] == "date"


def test_load_raw_keeps_a_comment_with_a_line_break_in_one_row(raw):
    assert len(raw) == 9
    assert raw.loc[1, "commentaires_retard_arrivee"] == "Mouvement social\nsur la ligne"


# --- One test per step ------------------------------------------------------------

def test_drop_comment_columns(raw):
    df, entry = drop_comment_columns(raw)
    assert not set(COMMENT_COLUMNS) & set(df.columns)
    assert len(df.columns) == len(raw.columns) - 3
    assert len(df) == len(raw)
    assert entry["rows_affected"] == 0


def test_remove_impossible_rows():
    df = pd.DataFrame({
        "nb_train_prevu": [100, 0, 50],
        "nb_annulation": [5, 0, 60],  # row 2: 0 planned; row 3: more cancelled than planned
    })
    result, entry = remove_impossible_rows(df)
    assert result["nb_train_prevu"].tolist() == [100]
    assert entry["rows_affected"] == 2


def test_fix_broken_sup30():
    df = pd.DataFrame({
        "nb_train_retard_sup_30": [-3, 2, 5],  # negative; smaller than sup_60; fine
        "nb_train_retard_sup_60": [1, 4, 2],
    })
    result, entry = fix_broken_sup30(df)
    assert result["nb_train_retard_sup_30"].isna().tolist() == [True, True, False]
    assert result.loc[2, "nb_train_retard_sup_30"] == 5
    assert result["nb_train_retard_sup_60"].tolist() == [1, 4, 2]  # never changed
    assert entry["rows_affected"] == 2


def test_fix_negative_delays_only_for_averages_of_late_trains():
    """A late train has a delay > 0, so its average can't be negative.
    The average over all trains can be negative (early trains): it is kept."""
    df = pd.DataFrame({
        "retard_moyen_depart": [-2.0, 10.0],
        "retard_moyen_arrivee": [18.0, 20.0],
        "retard_moyen_trains_retard_sup15": [22.0, 25.0],
        "retard_moyen_tous_trains_arrivee": [-1.0, 2.0],
    })
    result, entry = fix_negative_delays(df)
    assert isnan(result.loc[0, "retard_moyen_depart"])
    assert result.loc[0, "retard_moyen_arrivee"] == 18.0  # same row, other column: kept
    assert result.loc[0, "retard_moyen_tous_trains_arrivee"] == -1.0  # kept
    assert entry["rows_affected"] == 1


def test_fix_copied_sup15_average():
    df = pd.DataFrame({
        "retard_moyen_trains_retard_sup15": [12.0, 18.0, 20.0],  # below 15; copy; fine
        "retard_moyen_tous_trains_arrivee": [3.0, 18.0, 4.0],
    })
    result, entry = fix_copied_sup15_average(df)
    assert result["retard_moyen_trains_retard_sup15"].isna().tolist() == [True, True, False]
    assert entry["rows_affected"] == 2


def test_fix_empty_causes():
    df = pd.DataFrame([[0.0] * 6, [30.0, 20.0, 10.0, 20.0, 10.0, 10.0]], columns=CAUSE_COLUMNS)
    result, entry = fix_empty_causes(df)
    assert result.loc[0].isna().all()  # 0 everywhere means "unknown", not "no cause"
    assert result.loc[1].sum() == 100.0
    assert entry["rows_affected"] == 1


def test_merge_service_duplicates(raw):
    """Rows 8-9: PARIS LYON -> GENEVE, 2025-07, National (100 trains) + International (50).
    Expected values computed by hand."""
    df, _ = drop_comment_columns(raw)
    result, entry = merge_service_duplicates(df)
    assert entry["rows_affected"] == 2
    assert len(result) == len(df) - 1

    merged = result[result["gare_arrivee"] == "GENEVE"]
    assert len(merged) == 1
    row = merged.iloc[0]
    assert row["service"] == "International/National"
    # Counts are added.
    assert row["nb_train_prevu"] == 150
    assert row["nb_train_retard_arrivee"] == 15
    assert row["nb_train_retard_sup_30"] == 3
    # Averages are weighted by the number of trains they are computed on.
    assert row["duree_moyenne"] == 210  # (200*100 + 230*50) / 150, weighted by trains that ran
    assert row["retard_moyen_arrivee"] == pytest.approx(22.0)  # (20*10 + 26*5) / 15 late trains
    assert row["retard_moyen_tous_trains_arrivee"] == pytest.approx(3.0)  # (2*100 + 5*50) / 150
    assert row["prct_cause_externe"] == pytest.approx(40.0)  # (30*10 + 60*5) / 15 late trains


def test_merge_service_duplicates_leaves_other_routes_alone(raw):
    df, _ = drop_comment_columns(raw)
    result, _ = merge_service_duplicates(df)
    route = result[(result["gare_depart"] == "PARIS EST") & (result["gare_arrivee"] == "STRASBOURG")]
    assert route.iloc[0]["service"] == "National"
    assert route.iloc[0]["nb_train_prevu"] == 200


def test_convert_dates():
    result, entry = convert_dates(pd.DataFrame({"date": ["2024-07", "2018-01"]}))
    assert result["year"].tolist() == [2024, 2018]
    assert result["month"].tolist() == [7, 1]
    assert result["date"].tolist() == ["2024-07", "2018-01"]  # the text column is kept
    assert entry["rows_affected"] == 2


def test_convert_dates_fails_loudly_on_a_bad_date():
    with pytest.raises(ValueError):
        convert_dates(pd.DataFrame({"date": ["07/2024"]}))


def test_add_derived_columns():
    df = pd.DataFrame({
        "nb_train_prevu": [100, 20],
        "nb_annulation": [10, 20],  # row 2: every train cancelled, none ran
        "nb_train_retard_arrivee": [9, 0],
        "duree_moyenne": [196, 62],
    })
    result, _ = add_derived_columns(df)
    assert result["nb_circules"].tolist() == [90, 0]
    assert result.loc[0, "taux_retard_arrivee"] == pytest.approx(0.1)  # 9 / 90
    assert isnan(result.loc[1, "taux_retard_arrivee"])  # 0 trains ran: missing, no division by 0
    assert result["taux_annulation"].tolist() == [0.1, 1.0]
    assert result["seuil_retard"].tolist() == [15, 5]


# --- Helpers --------------------------------------------------------------------

def test_weighted_mean():
    assert weighted_mean(pd.Series([20.0, 26.0]), pd.Series([10, 5])) == pytest.approx(22.0)


def test_weighted_mean_with_a_missing_value_is_missing():
    """Edge case: one unknown value -> the merged value is unknown too."""
    assert isnan(weighted_mean(pd.Series([20.0, float("nan")]), pd.Series([10, 5])))


def test_weighted_mean_with_no_weight_is_the_simple_mean():
    """Edge case: e.g. no late train in either row -> nothing to weight by."""
    assert weighted_mean(pd.Series([10.0, 20.0]), pd.Series([0, 0])) == 15.0


def test_weighted_mean_of_a_single_value():
    assert weighted_mean(pd.Series([7.5]), pd.Series([3])) == 7.5


@pytest.mark.parametrize(
    "duration, threshold",
    [
        (30, 5),
        (89, 5),  # under 1h30
        (90, 10),  # from 1h30
        (180, 10),  # up to 3h
        (181, 15),  # over 3h
        (400, 15),
    ],
)
def test_late_threshold_sncf_rule(duration, threshold):
    """SNCF rule (brick 6): late from 5 min under 1h30, 10 min from 1h30 to 3h, 15 min over 3h.
    The boundaries must match the source cited in data/RULES.md."""
    assert late_threshold(duration) == threshold


# --- The whole pipeline -------------------------------------------------------------

def test_clean_whole_pipeline(raw):
    df, log = clean(raw)
    # 9 rows - 1 impossible row - 1 merged duplicate = 7
    assert len(df) == 7
    assert log["step"].tolist() == [step.__name__ for step in clean_data.STEPS]
    assert log["rows_affected"].tolist() == [0, 1, 1, 1, 1, 1, 2, 7, 7]


def test_clean_gives_the_columns_the_tools_expect(raw):
    """The clean file is what run_python loads as df: same columns, same order
    as the fixture of test_tools.py, and every column described for the model."""
    from tgv_analyst.tools import COLUMN_DESCRIPTIONS

    df, _ = clean(raw)
    assert list(df.columns) == list(pd.read_csv(CLEAN_SMALL).columns)
    assert set(df.columns) == set(COLUMN_DESCRIPTIONS)


def test_clean_table_goes_through_the_fixes_unchanged(raw):
    """Edge case: rows with no anomaly (rows 1-2) -> every fix touches 0 rows
    and the values come out exactly as they went in."""
    df, _ = drop_comment_columns(raw.iloc[[0, 1]].reset_index(drop=True))
    before = df.copy()
    for step in [remove_impossible_rows, fix_broken_sup30, fix_negative_delays,
                 fix_copied_sup15_average, fix_empty_causes, merge_service_duplicates]:
        df, entry = step(df)
        assert entry["rows_affected"] == 0, step.__name__
    # check_dtype=False: fix_broken_sup30 turns sup_30 from int to float even when it
    # changes no row (a column that can hold NaN is float in pandas). Same values.
    pd.testing.assert_frame_equal(df, before, check_dtype=False)
