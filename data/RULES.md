# Data rules: where each cleaning decision comes from

Brick 6 asks for at least one rule that the data file itself does not say, taken
from a person or a document, with its source named. Rules 1 and 2 come from SNCF's
own description of the dataset. Rule 3 lists our other cleaning decisions and where
each one comes from.

**Source document:** "Régularité mensuelle TGV par liaisons (AQST)", the dataset's
information page on SNCF Open Data:
<https://ressources.data.sncf.com/explore/dataset/regularite-mensuelle-tgv-aqst/information/>
(read on 2026-11-02; publisher: SNCF; licence: ODbL).
The CSV file we download (`scripts/download_data.py`) contains none of this text.

---

## Rule 1: When is a TGV late? (SNCF definition)

Quoted from the source:

> « Un train est considéré à l'heure si son retard au terminus est inférieur à 5min pour un parcours inférieur à 1h30 »
> « Un train est considéré à l'heure si son retard au terminus est inférieur à 10min pour un parcours entre 1h30 et 3h »
> « Un train est considéré à l'heure si son retard au terminus est inférieur à 15min pour un parcours au-delà de 3h »

In English: a train is on time if it reaches its last stop less than 5 min late
(trip under 1h30), 10 min (1h30 to 3h) or 15 min (over 3h). So the late threshold
depends on the trip length.

| Trip length | Late from | Our code |
|---|---|---|
| under 1h30 (< 90 min) | 5 min | `duration < 90` → 5 |
| 1h30 to 3h (90–180 min) | 10 min | `duration <= 180` → 10 |
| over 3h (> 180 min) | 15 min | otherwise → 15 |

**How we use it:**
- `scripts/clean_data.py`, function `late_threshold()`: adds the column `seuil_retard`
  (5, 10 or 15) from `duree_moyenne`, so the model can say which definition of
  "late" applies to a route.
- `tests/test_cleaning.py::test_late_threshold_sncf_rule` checks the boundaries
  89 → 5, 90 → 10, 180 → 10, 181 → 15.
- The counts of late trains (`nb_train_retard_arrivee`) are computed by SNCF with this
  rule; we do not recompute them (the file has no per-train delays).

**Limit:** we apply the rule to the route's *average* trip duration (`duree_moyenne`).
A route whose trains take 1h25 to 1h35 sits on the boundary; SNCF classifies each
train by its own trip, which we cannot see.

---

## Rule 2: Route figures must not be added up (SNCF warning)

Quoted from the same source:

> « un même TGV peut compter dans plusieurs liaisons, mais il ne compte qu'une seule fois dans la régularité globale »
> « Les chiffres de ce jeu de données ne doivent donc pas être utilisés pour calculer une régularité globale TGV ou par axe. »

In English: one TGV can count in several routes, so summing the routes does not give
SNCF's national (or per-line) punctuality.

**How we use it (decided 2026-11-02, option 1):** the agent still answers "overall"
questions, but the answer must say that the figure is computed over the routes of
this dataset and is not SNCF's official national rate. This is part of the
"what the data can't conclude" sentence of brick 8.

---

## Rule 3: Our other cleaning decisions and where they come from

Every step of `scripts/clean_data.py`, with the number of rows it touched on the real
file in `data/cleaning_log.csv`.

| Step | Decision | Where it comes from |
|---|---|---|
| `drop_comment_columns` | drop the 3 free-text comment columns | profiling: 2 columns 100 % empty, 1 95 % empty |
| `remove_impossible_rows` | remove rows with 0 planned trains or more cancellations than planned | logic: impossible counts (COVID, 2020) |
| `fix_broken_sup30` | `nb_train_retard_sup_30` → missing if negative or smaller than `sup_60` | logic: a train > 60 min late is also > 30 min late |
| `fix_negative_delays` | average delay of *late* trains → missing if negative | logic: a late train has a positive delay; averages over *all* trains may be negative (early trains) and are kept |
| `fix_copied_sup15_average` | average delay of trains > 15 min late → missing if below 15 or equal to the all-trains average | logic + profiling: 2,135 rows were copies of another column |
| `fix_empty_causes` | the 6 cause percentages → missing when they are all 0 | logic: 0 % everywhere means "unknown", not "no cause" |
| `merge_service_duplicates` | merge National + International rows of the same route and month | profiling: since 2025-07 some routes are split in two rows |
| `convert_dates` | `date` (YYYY-MM) → `year`, `month` | format |
| `add_derived_columns` | add `nb_circules`, `taux_retard_arrivee`, `taux_annulation`, `seuil_retard` | Rule 1 for `seuil_retard` |
