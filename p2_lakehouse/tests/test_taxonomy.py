"""Taxonomy snapshots -> silver_taxonomy_tag rows. The excerpt is real OFF taxonomy data (ODbL): all 27 allergens plus a few real tags of
countries, labels (including labels that carry organisations' contact data), data_quality and categories. Edge cases are made by
changing one field of a real tag."""
import copy
import datetime as dt
import gzip
import hashlib
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from silver_lib import contract, taxonomy  # noqa: E402

C = taxonomy.load()
S = contract.load()
EXCERPT = json.loads((Path(__file__).resolve().parent / "fixtures" / "taxonomy_excerpt.json").read_text(encoding="utf-8"))
CONTACT_FIELDS = ("auth_name", "auth_address", "auth_url", "web")


def raw_of(name, data=None):
    return json.dumps(data if data is not None else EXCERPT[name], ensure_ascii=False).encode("utf-8")


def parsed(name, data=None):
    return taxonomy.parse_snapshot(name, raw_of(name, data), C, S)


def ddl_columns(sql):
    body = sql[sql.index("(\n") + 2: sql.rindex("\n)")]
    return {line.strip().partition(" ")[0]: line.strip().partition(" ")[2] for line in body.split(",\n")}


# ---- contract and table ---------------------------------------------------------------------------------------------------

def test_contract_loads_and_table_follows_it():
    cols = ddl_columns(taxonomy.table_sql(C))
    assert list(cols) == taxonomy.column_names(C)
    assert cols["names"].startswith("MAP<STRING,STRING>") and cols["parents"].startswith("ARRAY<STRING>") and cols["valid_from"].startswith("TIMESTAMP")
    assert cols["name_en"] == "STRING" and "NOT NULL" not in cols["name_en"]      # the only nullable data column
    assert all("NOT NULL" in v for k, v in cols.items() if k != "name_en")


def test_manifest_table_has_the_hand_off_counts():
    cols = ddl_columns(taxonomy.manifest_sql(C))
    assert {"snapshot", "snapshot_sha256", "tags_in", "tags_silver", "tags_skipped", "values_scrubbed"} <= set(cols)


def test_relocate_moves_both_tables_and_leaves_the_original():
    moved = taxonomy.relocate(C, silver_schema="workspace.packsense_dev_silver")
    assert moved["table"] == "workspace.packsense_dev_silver.silver_taxonomy_tag"
    assert moved["manifest_table"] == "workspace.packsense_dev_silver.silver_taxonomy_manifest"
    assert C["table"] == "workspace.packsense_silver.silver_taxonomy_tag"


def test_contract_refuses_a_wrong_version_or_missing_key():
    bad = copy.deepcopy(C)
    bad["version"] = 2
    with pytest.raises(ValueError):
        taxonomy.validate(bad)
    bad = copy.deepcopy(C)
    del bad["props_allowlist"]
    with pytest.raises(ValueError):
        taxonomy.validate(bad)


# ---- one snapshot -> rows -------------------------------------------------------------------------------------------------

def test_every_tag_becomes_one_row_with_all_data_columns():
    for name, tags in EXCERPT.items():
        rows, stats = parsed(name)
        assert len(rows) == len(tags) == stats["tags_in"] == stats["tags_silver"] and stats["tags_skipped"] == 0
        data_columns = {"taxonomy", "tag", "name_en", "names", "parents", "children", "props"}
        assert all(set(r) == data_columns and r["taxonomy"] == name for r in rows)


def test_contact_data_of_organisations_never_reaches_a_row():
    labels = EXCERPT["labels"]
    with_contact = [t for t, v in labels.items() if any(f in v for f in CONTACT_FIELDS)]
    assert with_contact, "the excerpt must contain labels that carry contact data, or this test proves nothing"
    rows, _ = parsed("labels")
    blob = json.dumps(rows, ensure_ascii=False)
    for tag in with_contact:
        for f in CONTACT_FIELDS:
            for value in (labels[tag].get(f) or {}).values() if isinstance(labels[tag].get(f), dict) else [labels[tag].get(f)]:
                if isinstance(value, str) and len(value) > 5:
                    assert value not in blob, f"{f} of {tag} is in the output"
    assert all(set(r["props"]) <= set(C["props_allowlist"]) for r in rows)


def test_names_keep_every_language_and_name_en_is_null_when_missing():
    rows = {r["tag"]: r for r in parsed("allergens")[0]}
    milk = rows["en:milk"]
    assert milk["name_en"] == EXCERPT["allergens"]["en:milk"]["name"]["en"]
    assert milk["names"] == EXCERPT["allergens"]["en:milk"]["name"]
    no_english = [t for t, v in EXCERPT["labels"].items() if "en" not in v["name"]]
    assert no_english
    label_rows = {r["tag"]: r for r in parsed("labels")[0]}
    for tag in no_english:
        assert label_rows[tag]["name_en"] is None and label_rows[tag]["names"]


def test_parents_and_children_are_sorted_lists_of_tags():
    rows = {r["tag"]: r for r in parsed("categories")[0]}
    with_parents = [r for r in rows.values() if r["parents"]]
    assert with_parents
    for r in rows.values():
        assert r["parents"] == sorted(r["parents"]) and r["children"] == sorted(r["children"])
    tag = next(t for t, v in EXCERPT["categories"].items() if v.get("children"))
    assert rows[tag]["children"] == sorted(EXCERPT["categories"][tag]["children"])


def test_allowlisted_properties_are_kept_as_one_english_string():
    rows = {r["tag"]: r for r in parsed("countries")[0]}
    assert rows["en:india"]["props"]["country_code_2"] == EXCERPT["countries"]["en:india"]["country_code_2"]["en"]
    assert rows["en:india"]["props"]["country_code_3"] == EXCERPT["countries"]["en:india"]["country_code_3"]["en"]
    assert set(rows["en:india"]["props"]) <= set(C["props_allowlist"])
    # a property outside the allowlist is dropped: osm_relation is on the real country entries
    assert "osm_relation" in EXCERPT["countries"]["en:india"] and "osm_relation" not in rows["en:india"]["props"]


def test_a_property_without_english_uses_the_first_language_by_code():
    data = copy.deepcopy(EXCERPT["countries"])
    data["en:india"]["country_code_2"] = {"fr": "ZZ", "de": "YY"}
    assert {r["tag"]: r for r in parsed("countries", data)[0]}["en:india"]["props"]["country_code_2"] == "YY"


def test_bad_tags_and_non_object_entries_are_skipped_and_counted():
    data = copy.deepcopy(EXCERPT["allergens"])
    data["not a tag"] = data.pop("en:milk")
    data["en:egg-broken"] = "just a string"
    rows, stats = parsed("allergens", data)
    assert stats["tags_skipped"] == 2 and stats["tags_silver"] == len(EXCERPT["allergens"]) - 1 and stats["tags_in"] == len(data)
    assert "not a tag" not in {r["tag"] for r in rows}


def test_contact_shaped_text_in_a_name_is_scrubbed_and_counted():
    data = copy.deepcopy(EXCERPT["allergens"])
    data["en:milk"]["name"]["en"] = "Milk, see www.example.org or write to info@example.org"
    rows, stats = parsed("allergens", data)
    milk = next(r for r in rows if r["tag"] == "en:milk")
    assert "example.org" not in json.dumps(milk) and S["scrub"]["replacement"] in milk["name_en"]
    assert stats["values_scrubbed"] >= 2


def test_a_snapshot_that_is_not_an_object_is_refused():
    with pytest.raises(ValueError):
        taxonomy.parse_snapshot("allergens", b"[1, 2]", C, S)


# ---- which snapshots to load and integrity --------------------------------------------------------------------------------

def entry(name, key, sha="a" * 64, last_modified="Fri, 16 Oct 2026 10:32:04 GMT"):
    return {"name": name, "sha256": sha, "last_modified": last_modified, "tags": 10, "bytes": 100, "changed": False, "snapshot": key}


def log(captured_at, *entries):
    return {"log_version": 1, "captured_at": captured_at, "entries": list(entries), "failed": []}


def test_each_snapshot_loads_once_even_though_every_log_repeats_it():
    first = log("2026-10-14T07:50:00+00:00", entry("allergens", "allergens/v1.json.gz"), entry("labels", "labels/v1.json.gz"))
    second = log("2026-10-15T07:50:00+00:00", entry("allergens", "allergens/v1.json.gz"), entry("labels", "labels/v2.json.gz"))
    out = taxonomy.entries_to_load([first, second], done=set())
    assert [e["snapshot"] for e in out] == ["allergens/v1.json.gz", "labels/v1.json.gz", "labels/v2.json.gz"] or len(out) == 3
    assert len({e["snapshot"] for e in out}) == 3


def test_already_loaded_snapshots_and_other_taxonomies_are_left_out():
    logs = [log("2026-10-14T07:50:00+00:00", entry("allergens", "allergens/v1.json.gz"), entry("labels", "labels/v1.json.gz"))]
    assert [e["snapshot"] for e in taxonomy.entries_to_load(logs, done={"allergens/v1.json.gz"})] == ["labels/v1.json.gz"]
    assert [e["taxonomy"] for e in taxonomy.entries_to_load(logs, done=set(), only={"labels"})] == ["labels"]


def test_valid_from_is_offs_last_modified_else_the_capture_time_and_older_loads_first():
    logs = [log("2026-10-14T07:50:00+00:00", entry("a_new", "a/new.json.gz", last_modified="Fri, 16 Oct 2026 10:32:04 GMT"),
                entry("b_old", "b/old.json.gz", last_modified="Mon, 12 Oct 2026 01:02:03 GMT"),
                entry("c_none", "c/none.json.gz", last_modified=None))]
    out = {e["taxonomy"]: e for e in taxonomy.entries_to_load(logs, done=set())}
    assert out["a_new"]["valid_from"] == dt.datetime(2026, 10, 16, 10, 32, 4)
    assert out["c_none"]["valid_from"] == dt.datetime(2026, 10, 14, 7, 50, 0)
    assert [e["taxonomy"] for e in taxonomy.entries_to_load(logs, done=set())] == ["b_old", "c_none", "a_new"]


def test_a_landed_file_must_match_the_hash_the_capture_recorded():
    raw = raw_of("allergens")
    gz = gzip.compress(raw, mtime=0)
    good = {"snapshot": "allergens/v1.json.gz", "sha256": hashlib.sha256(raw).hexdigest()}
    assert taxonomy.verify_snapshot(gz, good) == raw
    with pytest.raises(ValueError):
        taxonomy.verify_snapshot(gz, dict(good, sha256="0" * 64))
    with pytest.raises(Exception):
        taxonomy.verify_snapshot(gz[:-8], good)         # a truncated gzip file is refused too


# ---- the job task and the notebook agree --------------------------------------------------------------------------------

ROOT = Path(__file__).resolve().parents[2]


def job_tasks():
    import yaml
    d = yaml.safe_load((ROOT / "p3_delivery" / "resources" / "bronze_job.yml").read_text(encoding="utf-8"))
    return {t["task_key"]: t for t in d["resources"]["jobs"]["bronze_load"]["tasks"]}


def test_the_taxonomy_task_runs_after_silver_even_if_silver_failed():
    t = job_tasks()["taxonomy"]
    assert [d["task_key"] for d in t["depends_on"]] == ["silver"] and t["run_if"] == "ALL_DONE"
    assert t["notebook_task"]["notebook_path"] == "../../p2_lakehouse/notebooks/taxonomy_load.py"


def test_every_parameter_the_job_passes_is_a_widget_of_the_notebook():
    import re
    notebook = (ROOT / "p2_lakehouse" / "notebooks" / "taxonomy_load.py").read_text(encoding="utf-8")
    widgets = set(re.findall(r'dbutils\.widgets\.text\("([a-z_]+)"', notebook))
    passed = set(job_tasks()["taxonomy"]["notebook_task"]["base_parameters"])
    assert passed <= widgets, f"the job passes parameters the notebook does not declare: {sorted(passed - widgets)}"
    assert "ping_healthchecks" in passed, "dev must be able to switch the ping off"


def test_the_notebook_never_pings_success_only_failure():
    notebook = (ROOT / "p2_lakehouse" / "notebooks" / "taxonomy_load.py").read_text(encoding="utf-8")
    assert '"/fail"' in notebook and '"/start"' not in notebook
    assert "ping_url +" in notebook and notebook.count("ping_url + ") == 1
