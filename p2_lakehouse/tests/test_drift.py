"""Schema-drift checks, on real numbers.

fixtures/drift_metrics.json: per-source-file metrics measured on production silver (aggregates only, no personal data) for the 14 real
delta days (13-14 Oct 2026 files) and the 13 parts of the India seed from the full dump.
fixtures/field_names_first_run.txt: the 6,121 real top-level field names OFF sent in those 14 days.
Edge cases change one number of a real day, the way the other silver tests change one field of a real record.
"""
import copy
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from silver_lib import contract, drift, transform  # noqa: E402

FIX = Path(__file__).resolve().parent / "fixtures"
M = json.loads((FIX / "drift_metrics.json").read_text(encoding="utf-8"))
DAYS, SEED = M["delta_days"], M["seed_parts"]
NAMES = (FIX / "field_names_first_run.txt").read_text(encoding="utf-8").split()
C = contract.load()


def alerts(findings):
    return [f for f in findings if f.level == "ALERT"]


def checks(findings):
    return {(f.check, f.detail.split(":")[0].split(" ")[0]) for f in findings}


def planted(day, **changes):
    d = copy.deepcopy(day)
    for k, v in changes.items():
        d[k].update(v) if isinstance(v, dict) else d.__setitem__(k, v)
    return d


# ---- what is measured ---------------------------------------------------------------------------------------------------

def test_coverage_columns_are_the_nullable_public_and_hashed_contract_columns():
    cols = drift.coverage_columns(C)
    by_name = {c["name"]: c for c in C["columns"]}
    assert len(cols) == 59 and "nutrients" in cols and "input_sets" in cols and "creator_hmac" in cols
    assert all(by_name[c]["nullable"] and by_name[c]["class"] in ("public", "hashed") for c in cols)
    assert "code" not in cols and "nutrition_format" not in cols and "source_file" not in cols
    assert set(cols) == set(DAYS[0]["coverage"])          # the fixture was measured with exactly these columns


def test_metrics_sql_has_one_share_per_column_the_format_mix_and_an_exact_prefix_match():
    sql = drift.metrics_sql(C, C["table"], "openfoodfacts_products_")
    for c in drift.coverage_columns(C):
        assert f"AS cov_{c}" in sql
    for f in drift.FORMATS:
        assert f"nutrition_format = '{f}'" in sql
    assert f"FROM {C['table']}" in sql and "left(source_file, 23) = 'openfoodfacts_products_'" in sql and "GROUP BY source_file" in sql
    assert "left(source_file, 10) = 'seed-dump:'" in drift.metrics_sql(C, C["table"], "seed-dump:")
    assert "o''brien" in drift.metrics_sql(C, C["table"], "o'brien")      # a quote cannot break out of the string


def test_a_sql_row_round_trips_into_the_metrics_dict():
    d = DAYS[3]
    row = {"source_file": d["file"], "rows": str(d["rows"]), "schema_versions": ",".join(d["schema_versions"])}
    row.update({f"cov_{c}": str(v) for c, v in d["coverage"].items()})
    row.update({f"fmt_{f}": str(v) for f, v in d["format"].items()})
    assert drift.metrics_from_row(row, list(d["coverage"])) == d


# ---- real days: quiet when nothing changed ------------------------------------------------------------------------------

def test_the_first_days_are_only_warm_up_and_never_judged():
    for i in range(drift.MIN_BASELINE):
        f = drift.judge(DAYS[i], drift.baseline_for(DAYS, i))
        assert [x.level for x in f] == ["WARMUP"]


def test_the_14_real_days_judged_one_after_another_raise_no_alert():
    for i in range(drift.MIN_BASELINE, len(DAYS)):
        assert alerts(drift.judge(DAYS[i], drift.baseline_for(DAYS, i))) == [], DAYS[i]["file"]


def test_each_real_day_judged_against_all_the_others_raises_no_alert():
    for i, d in enumerate(DAYS):
        others = [x for j, x in enumerate(DAYS) if j != i]
        assert alerts(drift.judge(d, others)) == [], d["file"]


def test_a_busy_real_day_is_noted_as_a_rise_but_not_alerted():
    f = drift.judge(DAYS[5], drift.baseline_for(DAYS, 5))
    assert f and all(x.level == "WARN" and x.check == "coverage_rise" for x in f)


# ---- a real change: the India seed is a different population ------------------------------------------------------------

def test_the_seed_from_the_full_dump_is_flagged_against_the_daily_baseline():
    big = max(SEED, key=lambda s: s["rows"])
    found = alerts(drift.judge(big, DAYS))
    names = {f.detail.split(":")[0].split(" ")[-1].strip("'") for f in found}
    assert {"new", "none"} <= names                              # the nutrition-format mix
    assert {"nutrients", "input_sets", "energy_kcal"} <= names   # the columns that go empty for old-format products
    assert len(found) >= 25


def test_every_seed_part_is_flagged():
    assert all(alerts(drift.judge(s, DAYS)) for s in SEED)


# ---- planted changes on a real day --------------------------------------------------------------------------------------

def test_a_renamed_nutrition_object_is_flagged_by_name():
    day = DAYS[10]
    dead = {c: 0.0 for c in ("nutrients", "input_sets", "nutrition_per", "nutrition_preparation", "energy_kj", "energy_kcal", "fat",
                             "saturated_fat", "carbohydrates", "sugars", "proteins", "salt", "sodium", "fiber")}
    broken = planted(day, coverage=dead, format={"new": 0.0, "legacy": 0.0, "none": 100.0})
    found = alerts(drift.judge(broken, drift.baseline_for(DAYS, 10)))
    text = " | ".join(f.detail for f in found)
    for name in ("nutrients", "input_sets", "energy_kcal"):
        assert name in text
    assert "product_name" not in text and "brands" not in text          # unrelated columns are not blamed
    assert {f.check for f in found} == {"coverage_drop", "format_mix"}


def test_a_new_schema_version_is_an_alert_and_a_known_one_is_not():
    assert [f.check for f in alerts(drift.judge(planted(DAYS[9], schema_versions=["1005"]), drift.baseline_for(DAYS, 9)))] == ["schema_version"]
    assert alerts(drift.judge(planted(DAYS[9], schema_versions=["1004"]), drift.baseline_for(DAYS, 9))) == []


def test_a_collapsed_or_doubled_volume_is_a_warning_only():
    base = drift.baseline_for(DAYS, 9)
    low, high = planted(DAYS[9], rows=900), planted(DAYS[9], rows=DAYS[9]["rows"] * 3)
    for day in (low, high):
        f = drift.judge(day, base)
        assert [x.check for x in f] == ["volume"] and f[0].level == "WARN"


def test_rare_real_columns_that_vanish_are_caught_even_though_they_cannot_drop_five_points():
    base = drift.baseline_for(DAYS, 12)
    for col in ("last_checker_hmac", "quantity_multiplier"):          # present on 0.3-0.9% and 1.1-2.5% of real products
        lo = min(b["coverage"][col] for b in base)
        assert lo < drift.MARGIN_POINTS                              # the five-point rule alone could never fire
        f = alerts(drift.judge(planted(DAYS[12], coverage={col: 0.0}), base))
        assert [x.check for x in f] == ["coverage_drop"] and col in f[0].detail


def test_a_rare_column_wobbling_within_its_normal_range_is_not_an_alert():
    base = drift.baseline_for(DAYS, 12)
    for col in ("last_checker_hmac", "quantity_multiplier", "owner_hmac"):
        lo = min(b["coverage"][col] for b in base)
        assert alerts(drift.judge(planted(DAYS[12], coverage={col: round(lo * 0.8, 3)}), base)) == []


def test_a_rise_beyond_the_range_is_a_warning_not_an_alert():
    base = drift.baseline_for(DAYS, 12)
    hi = max(b["coverage"]["nova_group"] for b in base)             # about 30-45% of real products: room to rise
    f = drift.judge(planted(DAYS[12], coverage={"nova_group": hi + 6.0}), base)
    assert hi + 6.0 <= 100.0 and [(x.level, x.check) for x in f] == [("WARN", "coverage_rise")]


def test_the_baseline_is_the_last_window_of_earlier_days_only():
    files = [{"file": str(i)} for i in range(40)]
    assert [x["file"] for x in drift.baseline_for(files, 35)] == [str(i) for i in range(5, 35)]
    assert [x["file"] for x in drift.baseline_for(files, 3)] == ["0", "1", "2"] and drift.baseline_for(files, 0) == []


# ---- layer 2: fields we do not use --------------------------------------------------------------------------------------

def test_generated_field_names_are_grouped_into_families():
    assert drift.field_family("ingredients_text_de_ocr_1668029324_result") == "ingredients_text_<lang>_ocr_#_result"
    assert drift.field_family("ingredients_text_ro_ocr_1728499351") == "ingredients_text_<lang>_ocr_#"
    assert drift.field_family("product_name_fr") == "product_name_<lang>"
    for plain in ("lc", "rev", "nutrition", "nutriments", "brands", "countries_tags", "last_modified_t"):
        assert drift.field_family(plain) == plain


def test_6121_real_field_names_collapse_to_a_few_hundred_families_and_keep_every_contract_field_apart():
    assert len(NAMES) == 6121
    fam = drift.families(NAMES)
    assert 300 <= len(fam) <= 450
    roots = {transform.root_field(c) for c in C["columns"] if transform.root_field(c)}
    assert roots <= set(NAMES) | {"code"}, roots - set(NAMES)
    assert len({drift.field_family(r) for r in roots}) == len(roots)         # no two contract fields share a family


def test_only_a_really_new_family_is_reported():
    known = drift.families(NAMES)
    assert drift.new_families(NAMES, known) == []
    assert drift.new_families(["ingredients_text_pt_ocr_1799999999", "product_name_xx", "lc"], known) == []   # generated parts are not new
    assert drift.new_families(["nutrition_v2", "lc", "brand_new_field"], known) == ["brand_new_field", "nutrition_v2"]
    assert drift.field_family("pnns_groups_1") != drift.field_family("pnns_groups_2")


# ---- putting it together --------------------------------------------------------------------------------------------------

def test_pending_days_are_judged_once_in_order_and_a_quiet_day_gets_one_ok_row():
    first = drift.evaluate_pending(DAYS, set())
    assert [f for f, _ in first] == [d["file"] for d in DAYS]
    levels = [{x.level for x in findings} for _, findings in first]
    assert levels[:5] == [{"WARMUP"}] * 5 and "ALERT" not in set().union(*levels)
    assert levels[6] == {"OK"} and first[6][1][0].check == "all_checks"
    done = {f for f, _ in first[:10]}
    assert [f for f, _ in drift.evaluate_pending(DAYS, done)] == [d["file"] for d in DAYS[10:]]
    assert drift.evaluate_pending(DAYS, {d["file"] for d in DAYS}) == []


def test_the_seed_can_be_judged_against_the_daily_days_as_baseline():
    out = drift.evaluate_pending(SEED, set(), baseline_days=DAYS)
    assert len(out) == len(SEED) and all(any(f.level == "ALERT" for f in findings) for _, findings in out)


def test_family_pass_records_the_first_run_then_reports_only_new_families():
    half = len(NAMES) // 2
    runs = [{"run": "r1", "fields": NAMES[:half]}, {"run": "r2", "fields": NAMES[:half] + ["nutrition_v2"]},
            {"run": "r3", "fields": NAMES}, {"run": "r4", "fields": NAMES + ["ingredients_text_pt_ocr_1799999999"]}]
    out = dict(drift.family_pass(runs, set()))
    assert [f.level for f in out["r1"]] == ["WARMUP"]
    assert [(f.level, f.detail) for f in out["r2"]] == [("WARN", "new field family: nutrition_v2")]
    assert all(f.level == "WARN" for f in out["r3"]) and len(out["r3"]) > 0      # the second half of the names brings families r1 and r2 never saw
    assert [f.level for f in out["r4"]] == ["OK"]                                 # a generated name is not a new family
    assert list(drift.family_pass(runs, {"r1", "r2", "r3"})) == [("r4", out["r4"])]


def test_the_ping_summary_is_short_and_names_alerts_first():
    seed = drift.judge(max(SEED, key=lambda s: s["rows"]), DAYS)
    text = drift.summary(seed, files=1, runs=0)
    assert text.startswith("drift: 1 day(s) and 0 run(s) judged;") and "alert" in text and len(text) <= 1000
    assert "of products have a value" in text or "nutrition format" in text
    assert drift.summary([], 0, 0) == "drift: 0 day(s) and 0 run(s) judged; 0 alert, 0 warn, 0 warm-up"


# ---- layer 3: how often the shape checks change a value (measuring; the judging tests use real counts, see below) -------------

import datetime as dt  # noqa: E402

from silver_lib import run  # noqa: E402

KEY = "test-key-not-a-secret-0000000000000000000000000000000000"
RECORDS = [json.loads(line) for line in open(FIX / "bronze_records.jsonl", encoding="utf-8")]
NOW = dt.datetime(2026, 10, 14, 9, 5)


def bronze_row(raw):
    d = json.loads(raw)
    return {"code": d.get("code"), "last_modified_t": d.get("last_modified_t"), "raw_json": raw, "source_file": "f",
            "file_sha256": "ab" * 32, "ingested_at": NOW}


def measured(raws):
    return drift.measure(run.process_batch([bronze_row(r) for r in raws], transform.Context(C, KEY), "r", NOW))


def real(case):
    return next(r["raw_json"] for r in RECORDS if r["case"] == case)


def test_measure_counts_the_real_fixture_batch_and_keeps_only_non_zero_counts():
    raws = [r["raw_json"] for r in RECORDS]
    batch = run.process_batch([bronze_row(r) for r in raws], transform.Context(C, KEY), "r", NOW)
    m = drift.measure(batch)
    assert m[drift.ROWS_METRIC] == len(raws) and all(n > 0 for n in m.values())
    for k, n in batch.coerce_failures.items():
        assert m.get(f"coerce:{k}", 0) == n
    for k, n in batch.tags_dropped.items():
        assert m.get(f"tags:{k}", 0) == n
    assert all(k == drift.ROWS_METRIC or k.split(":")[0] in ("coerce", "tags") or k in ("nutrient_entries_dropped", "enums_nulled") for k in m)


def test_a_malformed_tag_added_to_a_real_record_shows_up_as_exactly_one_dropped_tag():
    raw = real("normal_new")
    before = measured([raw])
    d = json.loads(raw)
    d["categories_tags"] = list(d.get("categories_tags") or []) + ["en:not a tag!"]
    after = measured([json.dumps(d)])
    assert after.get("tags:categories_tags", 0) == before.get("tags:categories_tags", 0) + 1


def test_a_value_that_does_not_fit_its_type_shows_up_as_a_coercion_failure():
    raw = real("normal_new")
    d = json.loads(raw)
    d["last_modified_t"] = d["last_modified_t"]            # keep the key valid: the break goes in a nullable numeric column
    d["completeness"] = "not a number"
    after = measured([json.dumps(d)])
    assert after.get("coerce:completeness", 0) == 1 and after[drift.ROWS_METRIC] == 1


def test_failures_by_file_and_attach_round_trip_the_stored_rows():
    rows = [{"source_file": "a", "metric": "_rows", "count": "100"}, {"source_file": "a", "metric": "tags:labels_tags", "count": 7},
            {"source_file": "b", "metric": "_rows", "count": 50}]
    by = drift.failures_by_file(rows)
    assert by == {"a": {"_rows": 100, "tags:labels_tags": 7}, "b": {"_rows": 50}}
    days = drift.attach_failures([{"file": "a"}, {"file": "c"}], by)
    assert days[0]["failures"] == by["a"] and "failures" not in days[1]
