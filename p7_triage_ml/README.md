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

Six rules agree at 98.5% or better. The rest do not, and **the rules were not tuned to make them agree.** Examples of the gaps: a product with sugars 52.3, starch 2.46
(an unrounded value, so probably estimated) and carbohydrates 52.6 breaks the sum by 2.2 g and OFF does not flag it; a product whose kcal (144) is within 3% of the computed
value (147.6) is flagged by OFF. OFF runs these checks on each **input set** (one per source, estimates excluded), while silver's aggregated columns mix values from several
sets. The likely cause is therefore the input, not the rule, and the per-source slice (`input_sets` in gold) is what can confirm it. Until then, treat the rules in the
lower half of the table as unverified against OFF.
