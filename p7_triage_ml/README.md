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
