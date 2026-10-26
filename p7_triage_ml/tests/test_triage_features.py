"""The as-of features, run on a slice of the real snapshot tables (3 weekly snapshots, rows whose barcode has crc32 % 2000 = 0) against an independent
plain-Python formulation, plus the property that matters most: a snapshot's features never change when later snapshots are removed."""
import copy
import datetime as dt
import json
import sys
import tempfile
from pathlib import Path

import duckdb
import pytest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
import triage_features as tf  # noqa: E402
import triage_labels as tl  # noqa: E402

SLICE = json.loads((HERE / "fixtures" / "triage_features_slice.json").read_text(encoding="utf-8"))
DATES = [dt.date.fromisoformat(d) for d in SLICE["snapshot_dates"]]


def _rows(table):
    cols = SLICE[table]["columns"]
    return [{c: (dt.date.fromisoformat(v) if c == "snapshot_date" else v) for c, v in zip(cols, r)} for r in SLICE[table]["rows"]]


def _con(open_flags=None, features=None):
    open_flags = open_flags if open_flags is not None else _rows("open_flags")
    features = features if features is not None else _rows("features")
    con = duckdb.connect()
    with tempfile.TemporaryDirectory() as tmp:
        def load(name, columns, rows):
            path = Path(tmp) / f"{name}.json"
            path.write_text(json.dumps([{c: (v.isoformat() if isinstance(v, dt.date) else v) for c, v in r.items()} for r in rows]), encoding="utf-8")
            spec = ", ".join(f"'{c}': '{t}'" for c, t in columns.items())
            con.execute(f"create table {name} as select * from read_json('{path.as_posix()}', format='array', columns={{{spec}}})")
        load("snapshot_open_flags", {"snapshot_sha": "VARCHAR", "snapshot_date": "DATE", "code": "VARCHAR", "severity": "VARCHAR", "flag": "VARCHAR",
                                     "family": "VARCHAR", "lm": "BIGINT"}, [{**r, "snapshot_sha": "sha_" + str(r["snapshot_date"])} for r in open_flags])
        load("snapshot_features", {"snapshot_sha": "VARCHAR", "snapshot_date": "DATE", "code": "VARCHAR", "lm": "BIGINT", "serving_size": "VARCHAR",
                                   "brand": "VARCHAR", "categories": "VARCHAR[]", "nutrients": "MAP(VARCHAR, DOUBLE)", "n_nutrients": "INTEGER",
                                   "max_mass_g": "DOUBLE"}, [{**r, "snapshot_sha": "sha_" + str(r["snapshot_date"])} for r in features])
        load("snapshot_flag_events", {"date_from": "DATE", "date_to": "DATE", "code": "VARCHAR", "severity": "VARCHAR", "flag": "VARCHAR", "family": "VARCHAR",
                                      "event": "VARCHAR", "family_remains": "BOOLEAN", "edited": "BOOLEAN"}, [])
        load("snapshot_presence_events", {"date_from": "DATE", "date_to": "DATE", "code": "VARCHAR", "event": "VARCHAR"}, [])
    return con


def _features(con):
    cur = con.execute(tf.feature_sql(engine="duckdb"))
    cols = [d[0] for d in cur.description]
    return {(r[1], r[2], r[3], r[4]): dict(zip(cols, r)) for r in cur.fetchall()}


def _reference(open_flags, features):
    """The same columns worked out with dicts and sets."""
    dates = sorted({r["snapshot_date"] for r in open_flags})
    opened = {(r["snapshot_date"], r["code"], r["severity"], r["flag"]) for r in open_flags}
    feat = {(r["snapshot_date"], r["code"]): r for r in features}
    newest = {d: max(r["lm"] for r in features if r["snapshot_date"] == d) for d in dates}
    out = {}
    for r in open_flags:
        d, i = r["snapshot_date"], dates.index(r["snapshot_date"])
        age = 1
        while i - age >= 0 and (dates[i - age], r["code"], r["severity"], r["flag"]) in opened:
            age += 1
        same = [x for x in open_flags if x["snapshot_date"] == d and x["code"] == r["code"]]
        f = feat[(d, r["code"])]
        prev = feat.get((dates[i - 1], r["code"])) if i else None
        out[(d, r["code"], r["severity"], r["flag"])] = {
            "flag_age": age, "n_open_flags": len(same), "n_open_errors": sum(1 for x in same if x["severity"] == "error"),
            "edited_since_prev": None if prev is None else int(prev["lm"] != f["lm"]),
            "days_since_edit": (newest[d] - f["lm"]) / 86400.0, "n_categories": len(f["categories"]), "brand": f["brand"],
            "serving_size": f["serving_size"], "n_nutrients": f["n_nutrients"], "max_mass_g": f["max_mass_g"],
            **{c: f["nutrients"].get(k) for c, k in tf.NUTRIENT_COLUMNS}}
    return out


def test_the_sql_gives_the_same_features_as_the_independent_reference():
    got, want = _features(_con()), _reference(_rows("open_flags"), _rows("features"))
    assert got.keys() == want.keys() and len(got) == len(_rows("open_flags")) > 1000
    for key, ref in want.items():
        for col, value in ref.items():
            if isinstance(value, float):
                assert got[key][col] == pytest.approx(value), (key, col)
            else:
                assert got[key][col] == value, (key, col)


def test_the_real_slice_shows_every_kind_of_value():
    got = _features(_con()).values()
    assert {g["flag_age"] for g in got} >= {1, 2, 3}
    assert {g["edited_since_prev"] for g in got} >= {None, 0, 1}
    assert any(g["energy_kj"] is not None for g in got) and any(g["energy_kj"] is None for g in got)       # products with and without nutrition
    assert any(g["n_open_errors"] >= 1 for g in got) and any(g["n_open_flags"] >= 3 for g in got)


def test_features_of_a_snapshot_never_change_when_later_snapshots_are_removed():
    full = _features(_con())
    for cut in (DATES[2], DATES[1]):                                                   # drop the newest, then the two newest
        flags = [r for r in _rows("open_flags") if r["snapshot_date"] < cut]
        feats = [r for r in _rows("features") if r["snapshot_date"] < cut]
        part = _features(_con(open_flags=flags, features=feats))
        assert part and all(part[k] == full[k] for k in part)                          # not one column of an earlier snapshot moved


def test_a_gap_in_the_history_restarts_the_flag_age():
    flags = _rows("open_flags")
    three = next(k for k, v in _features(_con()).items() if v["flag_age"] == 3)
    d, code, sev, flag = three
    cut = [r for r in flags if not (r["snapshot_date"] == DATES[1] and (r["code"], r["severity"], r["flag"]) == (code, sev, flag))]
    assert _features(_con(open_flags=cut))[three]["flag_age"] == 1


def test_one_changed_last_modified_time_moves_only_the_edit_columns():
    feats = copy.deepcopy(_rows("features"))
    base = _features(_con())
    two = next(k for k, v in base.items() if k[0] == DATES[1] and v["edited_since_prev"] == 0)
    row = next(r for r in feats if r["snapshot_date"] == DATES[1] and r["code"] == two[1])
    row["lm"] += 1000
    moved = _features(_con(features=feats))
    assert moved[two]["edited_since_prev"] == 1
    assert moved[two]["fat"] == base[two]["fat"] and moved[two]["flag_age"] == base[two]["flag_age"]


def test_the_training_table_joins_labels_and_features_one_row_per_open_flag():
    con = _con()
    cur = con.execute(tf.training_sql(1, engine="duckdb"))
    cols = [d[0] for d in cur.description]
    rows = [dict(zip(cols, r)) for r in cur.fetchall()]
    assert len(rows) == len(_rows("open_flags"))
    assert {r["reason"] for r in rows} <= set(tl.REASONS) and {r["outcome"] for r in rows} <= set(tl.OUTCOMES)
    assert all(r["reason"] == "censored" for r in rows if r["snapshot_date"] == DATES[-1])
    assert "flag_age" in cols and "salt" in cols and "outcome" in cols


def test_the_engine_is_checked_and_the_spark_text_uses_safe_lookups():
    with pytest.raises(ValueError):
        tf.feature_sql(engine="oracle")
    sql = tf.feature_sql(engine="spark")
    assert "try_element_at" in sql and "map_extract_value" not in sql
    assert "map_extract_value" in tf.feature_sql(engine="duckdb")
