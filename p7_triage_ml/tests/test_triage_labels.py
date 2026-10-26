"""The flag-triage labels, run on a slice of the real snapshot tables (3 weekly snapshots, rows whose barcode has crc32 % 250 = 0) with an
independent plain-Python formulation to compare against, and one-field changes of real rows to show that each rule decides what it should."""
import copy
import datetime as dt
import json
import sys
from collections import Counter
from pathlib import Path

import duckdb
import pytest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
import triage_labels as tl  # noqa: E402

SLICE = json.loads((HERE / "fixtures" / "triage_slice.json").read_text(encoding="utf-8"))
D0, D1, D2 = (dt.date.fromisoformat(d) for d in SLICE["snapshot_dates"])


def _rows(table):
    cols = SLICE[table]["columns"]
    return [{c: (dt.date.fromisoformat(v) if c.startswith("date") or c == "snapshot_date" else v) for c, v in zip(cols, r)} for r in SLICE[table]["rows"]]


def _con(open_flags=None, events=None, presence=None):
    open_flags = open_flags if open_flags is not None else _rows("open_flags")
    events = events if events is not None else _rows("flag_events")
    presence = presence if presence is not None else _rows("presence_events")
    import tempfile
    con = duckdb.connect()
    with tempfile.TemporaryDirectory() as tmp:                      # one JSON file per table and read_json: executemany is far too slow for 11,000 rows
        def load(name, columns, rows):
            path = Path(tmp) / f"{name}.json"
            path.write_text(json.dumps([{c: (v.isoformat() if isinstance(v, dt.date) else v) for c, v in r.items()} for r in rows]), encoding="utf-8")
            spec = ", ".join(f"'{c}': '{t}'" for c, t in columns.items())
            con.execute(f"create table {name} as select * from read_json('{path.as_posix()}', format='array', columns={{{spec}}})")
        load("snapshot_open_flags", {"snapshot_sha": "VARCHAR", "snapshot_date": "DATE", "code": "VARCHAR", "severity": "VARCHAR", "flag": "VARCHAR", "family": "VARCHAR", "lm": "BIGINT"},
             [{**r, "snapshot_sha": "sha_" + str(r["snapshot_date"])} for r in open_flags])
        load("snapshot_flag_events", {"date_from": "DATE", "date_to": "DATE", "code": "VARCHAR", "severity": "VARCHAR", "flag": "VARCHAR", "family": "VARCHAR", "event": "VARCHAR",
                                      "family_remains": "BOOLEAN", "edited": "BOOLEAN"}, events)
        load("snapshot_presence_events", {"date_from": "DATE", "date_to": "DATE", "code": "VARCHAR", "event": "VARCHAR"}, presence)
    return con


def _labels(con, steps, **kw):
    cur = con.execute(tl.label_sql(steps, **kw))
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, r)) for r in cur.fetchall()]


def _reference(steps, jump_weeks=tl.JUMP_WEEKS, open_flags=None, events=None, presence=None):
    """The same labels worked out directly from the rows with dicts and sets (an independent formulation)."""
    open_flags = open_flags if open_flags is not None else _rows("open_flags")
    events = events if events is not None else _rows("flag_events")
    presence = presence if presence is not None else _rows("presence_events")
    dates = sorted({r["snapshot_date"] for r in open_flags})
    opened = {(r["snapshot_date"], r["code"], r["severity"], r["flag"]) for r in open_flags}
    out = {}
    for r in open_flags:
        i = dates.index(r["snapshot_date"])
        target = dates[i + steps] if i + steps < len(dates) else None
        key = (r["snapshot_date"], r["code"], r["severity"], r["flag"])
        if target is None:
            out[key] = ("unlabelled", "censored")
            continue
        gone = sorted((e for e in events if e["event"] == "disappeared" and (e["code"], e["severity"], e["flag"]) == key[1:]
                       and r["snapshot_date"] < e["date_to"] <= target), key=lambda e: e["date_to"])
        left = any(p["event"] == "left" and p["code"] == r["code"] and r["snapshot_date"] < p["date_to"] <= target for p in presence)
        if gone:
            e = gone[0]
            if str(e["date_to"]) in jump_weeks:
                out[key] = ("unlabelled", "jump_week")
            elif e["family_remains"]:
                out[key] = ("unlabelled", "renamed")
            elif not e["edited"]:
                out[key] = ("unlabelled", "no_edit")
            else:
                out[key] = ("positive", "fixed")
        elif left:
            out[key] = ("unlabelled", "product_left")
        elif (target, r["code"], r["severity"], r["flag"]) in opened:
            out[key] = ("negative", "still_open")
        else:
            out[key] = ("unlabelled", "not_seen_again")
    return out


def _as_dict(rows):
    return {(r["snapshot_date"], r["code"], r["severity"], r["flag"]): (r["outcome"], r["reason"]) for r in rows}


@pytest.mark.parametrize("steps", [1, 2])
def test_the_sql_gives_the_same_labels_as_the_independent_reference(steps):
    rows = _labels(_con(), steps)
    assert len(rows) == len(_rows("open_flags")) == len({(r["snapshot_date"], r["code"], r["severity"], r["flag"]) for r in rows})   # one label per open flag
    assert _as_dict(rows) == _reference(steps)


def test_every_reason_the_real_slice_can_show_does_occur():
    reasons = Counter(r["reason"] for r in _labels(_con(), 1))
    for needed in ("fixed", "still_open", "censored", "renamed", "no_edit"):
        assert reasons[needed] > 0, needed
    # no product that left had an in-scope flag in this slice (17 left, all with out-of-scope flags only), so product_left is shown by the planted test below
    assert reasons["jump_week"] == 0                                                         # none of the slice's dates is a jump week
    jumped = Counter(r["reason"] for r in _labels(_con(), 1, jump_weeks=(str(D1),)))
    assert jumped["jump_week"] > 0 and jumped["fixed"] < reasons["fixed"]                    # same rows, one more week called a jump
    assert _as_dict(_labels(_con(), 1, jump_weeks=(str(D1),))) == _reference(1, jump_weeks=(str(D1),))


def test_the_last_snapshot_has_no_window_and_a_longer_window_reaches_fewer_snapshots():
    one, two = _labels(_con(), 1), _labels(_con(), 2)
    assert all(r["reason"] == "censored" for r in one if r["snapshot_date"] == D2)
    assert all(r["reason"] == "censored" for r in two if r["snapshot_date"] in (D1, D2))
    assert sum(1 for r in two if r["snapshot_date"] == D0 and r["reason"] != "censored") == sum(1 for r in one if r["snapshot_date"] == D0)
    assert all(r["outcome"] in tl.OUTCOMES and r["reason"] in tl.REASONS for r in one + two)


def _first(rows, **where):
    return next(r for r in rows if all(r[k] == v for k, v in where.items()))


def _fixed_in_scope(events):
    """A real 'fixed' event whose flag is also an open flag at D0 (the events table holds every warning, the open-flag table only the in-scope ones)."""
    opened = {(r["code"], r["severity"], r["flag"]) for r in _rows("open_flags") if r["snapshot_date"] == D0}
    return next(e for e in events if e["event"] == "disappeared" and e["date_to"] == D1 and not e["family_remains"] and e["edited"]
                and (e["code"], e["severity"], e["flag"]) in opened)


def test_one_changed_field_of_a_real_event_moves_the_label_the_way_the_rule_says():
    events = _rows("flag_events")
    base = _as_dict(_labels(_con(), 1))
    fixed = _fixed_in_scope(events)
    key = (D0, fixed["code"], fixed["severity"], fixed["flag"])
    assert base[key] == ("positive", "fixed")

    def with_event(**change):
        ev = copy.deepcopy(events)
        _first(ev, event="disappeared", date_to=D1, code=fixed["code"], severity=fixed["severity"], flag=fixed["flag"]).update(change)
        return _as_dict(_labels(_con(events=ev), 1))[key]

    assert with_event(edited=False) == ("unlabelled", "no_edit")
    assert with_event(family_remains=True) == ("unlabelled", "renamed")
    assert _as_dict(_labels(_con(), 1, jump_weeks=(str(D1),)))[key] == ("unlabelled", "jump_week")
    gone = [e for e in events if not (e["event"] == "disappeared" and (e["code"], e["severity"], e["flag"], e["date_to"]) == (fixed["code"], fixed["severity"], fixed["flag"], D1))]
    assert _as_dict(_labels(_con(events=gone), 1))[key] == ("unlabelled", "not_seen_again")                   # absent, and no event explains it
    left = _rows("presence_events") + [{"date_from": D0, "date_to": D1, "code": fixed["code"], "event": "left"}]
    assert _as_dict(_labels(_con(events=gone, presence=left), 1))[key] == ("unlabelled", "product_left")
    # a flag that is still open: take a real negative and remove it from the later snapshot -> it can no longer be called negative
    neg = _first([r for r in _labels(_con(), 1) if r["snapshot_date"] == D0], reason="still_open")
    kept = [r for r in _rows("open_flags") if not (r["snapshot_date"] == D1 and (r["code"], r["severity"], r["flag"]) == (neg["code"], neg["severity"], neg["flag"]))]
    assert _as_dict(_labels(_con(open_flags=kept), 1))[(D0, neg["code"], neg["severity"], neg["flag"])] == ("unlabelled", "not_seen_again")


def test_the_first_disappearance_decides_and_a_bad_window_is_refused():
    events = _rows("flag_events")
    fixed = _fixed_in_scope(events)
    key = (D0, fixed["code"], fixed["severity"], fixed["flag"])
    later = events + [{**fixed, "date_from": D1, "date_to": D2, "edited": False}]               # it also 'disappears' again in the next pair
    assert _as_dict(_labels(_con(events=later), 2))[key] == ("positive", "fixed")
    for bad in (0, -1, 1.5, "2"):
        with pytest.raises(ValueError):
            tl.label_sql(bad)


def test_the_sql_uses_only_plain_constructs_and_the_table_names_it_is_given():
    sql = tl.label_sql(4, flags="ws.sc.snapshot_open_flags", events="ws.sc.snapshot_flag_events", presence="ws.sc.snapshot_presence_events")
    assert "ws.sc.snapshot_open_flags" in sql and "k + 4" in sql
    assert "DATE '2026-09-20'" in sql and "DATE '2026-10-25'" in sql
