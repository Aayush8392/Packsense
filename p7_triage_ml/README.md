# p7_triage_ml

## Rule verdicts (`rules_lib.py`)

The nutrition flags that arithmetic or physics can decide, decided by code with OFF's own tolerances (read from `DataQualityFood.pm` and `Nutrition.pm`, 2026-10-21).
Pure Python: per-100 nutrient values in, one verdict per rule out (`violated` with a severity and a deviation, `ok`, or `not_applicable` when an input is missing).
`rule_for_family` maps a flag family (the flag with its `nutrition-<source>-<prepared>-<basis>-` prefix stripped) to the rule that decides it.
Tests: `tests/test_rules_lib.py` (both sides of every tolerance, missing inputs, the family map).

### Agreement with OFF on real data (2026-10-21)

20,000 current product versions (hash-sampled, `nutrition_per` 100 g or 100 ml), the rules run on silver's **aggregated** nutrient columns and compared with OFF's own
`nutrition-*` flags on the same version. "OFF fires" is the share of our violations that OFF also flags.

| rule | both | ours only | OFF only | OFF fires |
|---|---:|---:|---:|---:|
| kcal and kJ reversed | 47 | 0 | 0 | 100% |
| kcal greater than kJ | 149 | 0 | 0 | 100% |
| kcal does not match kJ | 1,431 | 8 | 0 | 99.4% |
| salt does not match sodium | 464 | 7 | 10 | 98.5% |
| value over 105 g | 93 | 0 | 168 | 100% |
| total over 105 g | 134 | 0 | 0 | 100% |
| energy over 3,911 kJ | 24 | 8 | 0 | 75.0% |
| saturated fat greater than fat | 18 | 9 | 0 | 66.7% |
| kJ does not match computed from nutrients | 193 | 95 | 108 | 67.0% |
| kcal does not match computed from nutrients | 746 | 178 | 3,304 | 80.7% |
| sugars + starch greater than carbohydrates | 32 | 379 | 0 | 7.8% |

### The same check per input set (2026-10-21, after the per-source table existed)

OFF runs these checks on each input set, so the rules were run again on the per-source rows (`product_nutrition_sets`; the 16,273 non-estimate sets in 100 g or 100 ml of 20,000 hash-sampled products), compared with the
flags OFF raised for that set. The first table did not agree on five rules, and the rules were not tuned to make them agree. The likely cause was the input: OFF checks each set (estimates excluded), while silver's aggregated columns mix values from several sets. Per set, agreement is much better, which supports that explanation:

| rule | both | ours only | OFF only | OFF fires |
|---|---:|---:|---:|---:|
| kcal and kJ reversed | 6 | 0 | 0 | 100% |
| kcal greater than kJ | 35 | 0 | 0 | 100% |
| kcal does not match kJ | 117 | 1 | 0 | 99.2% |
| salt does not match sodium | 302 | 3 | 10 | 99.0% |
| value over 105 g | 62 | 0 | 3 | 100% |
| total over 105 g | 72 | 0 | 0 | 100% |
| energy over 3,911 kJ | 2 | 0 | 0 | 100% |
| saturated fat greater than fat | 15 | 0 | 0 | 100% |
| sugars + starch greater than carbohydrates | 24 | 1 | 0 | 96.0% |
| kcal does not match computed from nutrients | 582 | 50 | 2 | 92.1% |
| kJ does not match computed from nutrients | 215 | 42 | 0 | 83.7% |

The two computed-energy rules still fire more often than OFF. The known causes are the two things this table does not carry (OFF's per-category switch that turns the check off, and the `<`/`~` modifiers on a value),
which can only make OFF fire less, so they are not tuned away.

**A unit trap found on the way:** every nutrient in an input set carries its own unit, and salt and sodium are in milligrams in about 7% of the sets (a median of 700 times the gram value). Read as grams, they made the salt rule
agree on only 70% and the 105 g rules on 8% and 60%. `product_nutrition_sets` converts g, mg, micrograms and kg to grams and leaves any other unit NULL (macro `grams`).

Of the two tables above, the first (aggregated columns) is kept as the record of why the per-source table exists; use the second.

## Rule verdicts in SQL (`product_rule_verdicts`, gold, 2026-10-23)

The same 11 rules as portable SQL in dbt (`p4_modelling/models/portable/product_rule_verdicts.sql`): one row per rule for every input set OFF itself checks (not an
estimate, given per 100 g or 100 ml), with `status` (`violated`, `ok`, `not_applicable`), `severity` and `deviation` (4 decimals). The tolerances sit at the top of the model and a
test pins them to the constants of `rules_lib.py`. `p4_modelling/tests/test_rule_verdicts_agree.py` runs the model's compiled SQL on the real fixture sets and on one-field
variants of each (a missing value, zero, halved, doubled, nudged past a tolerance, 150) plus a grid of energy pairs around every limit, and requires the same status, severity and
deviation as `rules_lib.py` on every row (about 224,000 comparisons, every rule violated at least once); the `engines` CI job runs it. The sets table gained the inputs the energy sum needs
(`polyols`, `erythritol`, `isomalt`, `maltitol`, `sorbitol`, the RAW `alcohol` value, which OFF stores in % vol and multiplies as it stands) and `max_mass_g` for the 105 g rule.
`organic_acids` and `salatrim` are in OFF's factor table but OFF's own code notes they have no nutrient, so they are not carried. Not applied, as before: the `<`/`~` modifiers and OFF's
per-category switch. `value-over-105` looks at mass-valued nutrients only (alcohol in % vol is left out; it cannot exceed 100).

## Replay harness (`replay_lib.py`, 2026-10-21; roadmap item 6)

The catalogue as OUR copy held it at the end of any past UTC day, rebuilt from `product_history` and `product_flag_spans` with no extra table:
a period is open at T (the last second of the day) when `valid_from_t <= T` and `valid_to_t` is empty or after T; a flag span is open when
`first_seen_t <= T` and `vanished_at_t` is empty or after T. Nothing dated after T can match either rule (the leakage guard a detector or
the steward needs: features as of T, labels from what happened after T). The rule exists twice, in dbt macros (`p4_modelling/macros/replay.sql`)
and in seconds in `replay_lib.py`; `tests/test_replay_lib.py` runs both sides of every boundary and checks that they agree.

**Proof of consistency (not of accuracy).** Two dbt data tests run in every gold build: `replay_matches_silver` (for the first, a middle and the last
complete day, the replayed state equals the newest silver version dated on or before the day, hash for hash, and the replayed flags equal that
version's own flags) and `replay_matches_quality_fact` (on every complete day, open spans per severity and products held equal the daily quality
fact). On the DuckDB fixture both pass; with the predicate off by one day both fail (39 and 543 rows). On production, 5 Oct: 60,170 products held and
3,508 error, 275,911 warning, 267,658 info and 1 bug spans open, identical to the quality fact.

**Limits.** It is the state of our copy, not of OFF: a product with no version dated on or before the day is absent (the seed arrived late and the
capture began on 30 Sep, so early days are thin and non-India products are only those edited since), and about 35% of consecutive versions have
unseen edits between them. Use it with the complete days (`complete_days`). `bootstrap/replay.py --day YYYY-MM-DD` prints counts only; a consumer
reads the state itself (`state_as_of_sql`) inside Databricks. The OFF weekly snapshots were deliberately not used as a second check (user decision).
