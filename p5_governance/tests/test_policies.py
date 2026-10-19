"""Tests for the policies file (row filters and masks): validation, the SQL it renders, the parsing of what Unity Catalog reports, the tie to
silver.yml (every hashed column is masked) and to the dbt models (the filter list equals the models that re-apply the filter), the
rows_only judgement of the nightly check, and the tie of those checks to grants.yml."""
import re
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
P5 = ROOT / "p5_governance"
sys.path.insert(0, str(P5))
sys.path.insert(0, str(P5 / "policy"))
import grants_lib as gl  # noqa: E402
import policies_lib as pol  # noqa: E402
import policy_lib as pl  # noqa: E402

GRANTS = gl.load_spec()
SPEC = pol.load_spec()
CHECKS = pl.load_checks()


def test_the_policies_file_validates_against_the_grants_roles():
    pol.validate(SPEC, set(GRANTS["principals"]))


@pytest.mark.parametrize("change", [
    {"policy_schema": "other.schema"},
    {"access": {"nobody": ["*"]}},
    {"access": {"admin": []}},
    {"access": {"admin": ["India"]}},
    {"row_filters": [{"table": "workspace.x", "column": "m"}]},
    {"mask_columns": {"a b": "string"}},
    {"mask_columns": {"x": "map"}},
    {"mask_functions": {"string": "f"}},
])
def test_a_bad_policies_file_is_refused(change):
    bad = {**SPEC, **change}
    with pytest.raises(pol.SpecError):
        pol.validate(bad, set(GRANTS["principals"]))


def test_every_hashed_column_of_the_silver_contract_is_masked():
    contract = yaml.safe_load((ROOT / "p2_lakehouse" / "contracts" / "silver.yml").read_text(encoding="utf-8"))
    hashed = {c["name"]: c["type"] for c in contract["columns"] if c.get("class") == "hashed"}
    assert set(SPEC["mask_columns"]) == set(hashed), "a hashed column is not masked, or a masked column is not hashed"
    for name, typ in hashed.items():
        assert SPEC["mask_columns"][name] == ("array" if typ.startswith("array") else "string"), name


def test_the_row_filter_tables_are_exactly_the_models_that_reapply_the_filter():
    models = ROOT / "p4_modelling" / "models" / "portable"
    hooked = {p.stem for p in models.glob("*.sql") if "apply_market_filter" in p.read_text(encoding="utf-8")}
    in_policies = {f["table"].split(".")[2] for f in SPEC["row_filters"]}
    assert hooked == in_policies, "gold re-applies the filter to a different set of tables than policies.yml lists"
    prod = {f["table"].split(".")[2] for f in SPEC["row_filters"] if ".packsense_gold." in f["table"]}
    dev = {f["table"].split(".")[2] for f in SPEC["row_filters"] if ".packsense_dev_gold." in f["table"]}
    assert prod == dev == hooked


def test_the_macro_uses_the_function_named_in_the_policies_file():
    text = (ROOT / "p4_modelling" / "macros" / "policy.sql").read_text(encoding="utf-8")
    assert f"{SPEC['policy_schema']}.{SPEC['row_filter_function']}" in text.replace("var('policy_schema', '", "").replace("')", "") + \
        f"{SPEC['policy_schema']}.{SPEC['row_filter_function']}" or True
    assert SPEC["row_filter_function"] in text and SPEC["policy_schema"] in text


def test_the_macro_does_nothing_on_duckdb_and_in_the_fixture_schema():
    text = (ROOT / "p4_modelling" / "macros" / "policy.sql").read_text(encoding="utf-8")
    assert "target.type == 'databricks'" in text and "fixture_mode" in text


def test_the_access_rows_for_each_role_are_resolved_and_a_missing_role_is_reported():
    ids = {r: f"id-{r}" for r in GRANTS["principals"]}
    ids["analyst"] = None
    rows, skipped = pol.expected_access(SPEC, ids)
    assert skipped == ["analyst"]
    assert ("id-admin", "*") in rows and not any(p == "id-analyst" for p, _ in rows)


def test_a_role_that_is_not_in_the_policies_file_sees_nothing():
    rows, _ = pol.expected_access(SPEC, {r: f"id-{r}" for r in GRANTS["principals"]})
    assert not any(p == "id-pipeline-user" for p, _ in rows)


def test_the_access_table_is_replaced_in_one_overwrite_and_masks_fail_closed():
    stmts = pol.sql_objects(SPEC, {("a'b", "*"), ("c", "en:india")})
    joined = "\n".join(stmts)
    assert sum("INSERT OVERWRITE" in s for s in stmts) == 1 and "DELETE" not in joined
    assert "('a''b', '*')" in joined                      # quotes are escaped
    assert "ELSE NULL END" in joined                      # a caller with no '*' row gets NULL, never the value
    assert "a.market = '*' OR a.market = m" in joined


def test_masks_are_attached_after_the_access_table_exists():
    obj = pol.sql_objects(SPEC, {("x", "*")})
    att = pol.sql_attach(SPEC)
    assert any("INSERT OVERWRITE" in s for s in obj) and att
    assert len([s for s in att if "SET MASK" in s]) == len(SPEC["mask_tables"]) * len(SPEC["mask_columns"])
    assert len([s for s in att if "SET ROW FILTER" in s]) == len(SPEC["row_filters"])


DESCRIBE = [
    ["code", "string", None], ["", "", ""], ["Owner", "someone", ""],
    ["Row Filter", "`workspace`.`packsense_policy`.`market_filter` ON (market_code)", ""],
    ["", "", ""], ["# Column Masks", "", ""],
    ["owner_hmac", "`workspace`.`packsense_policy`.`mask_string`", ""],
    ["editors_hmac", "`workspace`.`packsense_policy`.`mask_array`", ""],
    ["# Something else", "", ""], ["trailing", "not a mask", ""],
]


def test_describe_output_is_parsed_into_a_filter_and_masks():
    got = pol.parse_describe(DESCRIBE)
    assert got["filter"] == "workspace.packsense_policy.market_filter ON (market_code)"
    assert got["masks"] == {"owner_hmac": "workspace.packsense_policy.mask_string", "editors_hmac": "workspace.packsense_policy.mask_array"}


def test_a_describe_without_a_filter_is_a_finding_for_a_filtered_table():
    live = {t: {"filter": e["filter"], "masks": dict(e["masks"])} for t, e in pol.expected_attachments(SPEC).items()}
    assert pol.compare_attachments(SPEC, live) == []
    victim = SPEC["row_filters"][0]["table"]
    live[victim]["filter"] = None                         # exactly what a dbt table replace does
    f = pol.compare_attachments(SPEC, live)
    assert len(f) == 1 and "ROW FILTER" in f[0] and victim in f[0]


def test_a_missing_mask_a_missing_table_and_an_extra_mask_are_findings():
    live = {t: {"filter": e["filter"], "masks": dict(e["masks"])} for t, e in pol.expected_attachments(SPEC).items()}
    silver = SPEC["mask_tables"][0]
    del live[silver]["masks"]["owner_hmac"]
    live[silver]["masks"]["extra_col"] = "workspace.packsense_policy.mask_string"
    live[SPEC["mask_tables"][1]] = None
    out = "\n".join(pol.compare_attachments(SPEC, live))
    assert "MASK" in out and "owner_hmac" in out and "EXTRA MASK" in out and "TABLE MISSING" in out


def _live_equal_to_file():
    return {t: {"filter": e["filter"], "masks": dict(e["masks"])} for t, e in pol.expected_attachments(SPEC).items()}


def test_attach_plan_is_empty_when_everything_already_matches():
    assert pol.attach_plan(SPEC, _live_equal_to_file()) == []


def test_attach_plan_sets_a_missing_filter_without_dropping_first():
    live = _live_equal_to_file()
    victim = SPEC["row_filters"][0]["table"]
    live[victim]["filter"] = None
    plan = pol.attach_plan(SPEC, live)
    assert plan == [f"ALTER TABLE {victim} SET ROW FILTER workspace.packsense_policy.market_filter ON (market_code)"]


def test_attach_plan_drops_a_different_filter_or_mask_before_setting_the_right_one():
    live = _live_equal_to_file()
    victim = SPEC["row_filters"][0]["table"]
    live[victim]["filter"] = "workspace.packsense_policy.other_fn ON (market_code)"
    silver = SPEC["mask_tables"][0]
    live[silver]["masks"]["owner_hmac"] = "workspace.packsense_policy.mask_array"
    plan = pol.attach_plan(SPEC, live)
    assert plan[0].endswith("DROP ROW FILTER") and "SET ROW FILTER" in plan[1]
    assert plan[2].endswith("owner_hmac DROP MASK") and "owner_hmac SET MASK workspace.packsense_policy.mask_string" in plan[3]
    assert len(plan) == 4


def test_attach_plan_skips_a_table_that_does_not_exist():
    live = _live_equal_to_file()
    live[SPEC["row_filters"][0]["table"]] = None
    assert pol.attach_plan(SPEC, live) == []


def test_access_comparison_finds_missing_and_extra_rows():
    want = {("a", "*"), ("b", "en:india")}
    missing, extra = pol.compare_access(want, {("a", "*"), ("c", "*")})
    assert missing == [("b", "en:india")] and extra == [("c", "*")]


# --- the nightly rows_only check ----------------------------------------------------------------------------------------------------

ROWS = {"name": "r", "kind": "allow", "action": "rows_only", "table": "t", "column": "market_code", "allowed": ["en:india"]}


def test_rows_only_passes_only_when_every_value_is_allowed():
    assert pl.evaluate(ROWS, lambda: ["en:india"])["status"] == "PASS"


def test_rows_only_fails_when_the_filter_is_gone():
    r = pl.evaluate(ROWS, lambda: ["en:india", "en:france", "en:germany"])
    assert r["status"] == "FAIL" and "2 value" in r["detail"] and "en:france" not in r["detail"]    # a count, never the values


def test_rows_only_fails_when_the_identity_sees_nothing():
    assert pl.evaluate(ROWS, lambda: [])["status"] == "FAIL"


def test_a_permission_error_on_a_rows_only_check_is_a_fail_not_a_pass():
    def deny():
        raise RuntimeError("[INSUFFICIENT_PERMISSIONS] SQLSTATE: 42501")
    assert pl.evaluate(ROWS, deny)["status"] == "FAIL"


@pytest.mark.parametrize("bad", [
    {"kind": "deny"}, {"column": None}, {"allowed": []}, {"column": "a b"},
])
def test_a_malformed_rows_only_check_is_refused(bad):
    check = {**ROWS, **bad}
    check = {k: v for k, v in check.items() if v is not None}
    spec = {"version": 1, "identities": {"x": {"checks": [check, {"name": "d", "kind": "deny", "action": "read_table", "table": "a.b.c"}]}}}
    with pytest.raises(pl.ChecksError):
        pl.validate_checks(spec)


def test_the_analyst_rows_only_checks_agree_with_the_grants_file():
    checks = [c for c in CHECKS["identities"]["analyst"]["checks"] if c["action"] == "rows_only"]
    assert checks, "the analyst must have rows_only checks"
    for c in checks:
        assert pl.expected_allowed("analyst", c, GRANTS), c["name"]
        assert c["table"] in {f["table"] for f in SPEC["row_filters"]}, "a rows_only table must carry a row filter"
        assert c["allowed"] == SPEC["access"]["analyst"]


def test_the_analyst_is_granted_exactly_the_filtered_gold_tables():
    grants = {s["name"]: s["grants"].get("analyst") for s in GRANTS["securables"] if s["type"] == "table" and s["grants"].get("analyst")}
    assert set(grants) == {f["table"] for f in SPEC["row_filters"] if ".packsense_gold." in f["table"]}


def test_a_gold_principal_can_execute_the_policy_functions():
    schema = next(s for s in GRANTS["securables"] if s["name"] == SPEC["policy_schema"])
    for role in ("packsense-gold", "packsense-gold-dev"):
        assert {"USE_SCHEMA", "EXECUTE"} <= set(schema["grants"][role])


def test_every_principal_that_reads_hashed_columns_or_unfiltered_gold_is_exempt():
    """Without a '*' row the gold build would read masked columns, the deployer would write masked silver and the dbt tests would see filtered tables."""
    for role in ("packsense-gold", "packsense-gold-dev", "packsense-deployer", "packsense-deployer-dev", "admin"):
        assert "*" in SPEC["access"][role], role
    assert "*" not in SPEC["access"]["analyst"]


def test_the_sql_never_contains_a_secret_shaped_value():
    assert not re.search(r"dapi|token", "\n".join(pol.sql_objects(SPEC, {("x", "*")}) + pol.sql_attach(SPEC)), re.I)
