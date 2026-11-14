"""The site side of the nightly photo-read lines: the selection (validator, candidate, record hash), the shards, the licence gate's line rules and the fetch step.
One rule is broken at a time; the gate must name each break and never repeat a value."""
import json
import sys
import urllib.error
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT / "p6_serving"))
sys.path.insert(0, str(ROOT / "p5_governance"))
sys.path.insert(0, str(ROOT / "p8_steward" / "nightly"))
import licence_gate as gate  # noqa: E402
import line_record as lr  # noqa: E402
import nightly_lines as nl  # noqa: E402

STORED = {"energy_kcal": 276.0, "carbohydrates": 66.7, "fat": 0.7, "proteins": 1.3}
TABLE = {"energy_kcal": 276.666667, "carbohydrates": 66.666667, "fat": 0.666667, "proteins": 1.333333}


def line(code="8901071732857", stored=STORED, **kw):
    out = lr.build_line(code, "2026-11-14", TABLE, {}, False, "checked", [], "per 100 g", stored)
    out.update(kw)
    return out


def public(x):
    return {k: x[k] for k in nl.PUBLIC_COLUMNS}


def cands(*codes_and_stored):
    return {"exported": "2026-11-14", "candidates": [{"code": c, "stored": s, "new": False} for c, s in codes_and_stored]}


def data_folder(tmp_path, lines):
    (tmp_path / "cards").mkdir()
    (tmp_path / "cards" / "splits.json").write_text(json.dumps({"version": 1, "splits": ["890"]}), encoding="utf-8")
    nl.write_shards(lines, tmp_path)
    return tmp_path


def test_a_fresh_valid_line_is_kept_without_its_hash():
    keep, counts = nl.select_lines({"8901071732857": line()}, cands(("8901071732857", STORED)))
    assert counts == {"held": 1, "kept": 1, "invalid": 0, "not_a_candidate": 0, "stale": 0}
    assert sorted(keep[0]) == sorted(gate.LINE_COLUMNS)


def test_a_line_whose_stored_record_changed_is_stale():
    changed = dict(STORED, energy_kcal=300.0)
    keep, counts = nl.select_lines({"8901071732857": line()}, cands(("8901071732857", changed)))
    assert keep == [] and counts["stale"] == 1


def test_a_line_without_a_candidate_is_dropped():
    keep, counts = nl.select_lines({"8901071732857": line()}, cands(("8908019140019", STORED)))
    assert keep == [] and counts["not_a_candidate"] == 1


@pytest.mark.parametrize("damage", [
    {"basis": "something else"}, {"statement": "maybe"}, {"values": {"energy_kcal": 1.0}}, {"night": "yesterday"}, {"extra": 1},
])
def test_an_invalid_line_is_dropped(damage):
    bad = line(**damage)
    keep, counts = nl.select_lines({"8901071732857": bad}, cands(("8901071732857", STORED)))
    assert keep == [] and counts["invalid"] == 1


def test_a_line_filed_under_another_code_is_dropped():
    keep, counts = nl.select_lines({"8908019140019": line()}, cands(("8901071732857", STORED), ("8908019140019", STORED)))
    assert keep == [] and counts["invalid"] == 1


def test_a_broken_candidates_file_stops_the_build():
    with pytest.raises(nl.LinesError):
        nl.select_lines({}, {"candidates": "no"})
    with pytest.raises(nl.LinesError):
        nl.select_lines([], cands())


def test_shards_follow_the_card_lookup_rule_and_pass_the_gate(tmp_path):
    data = data_folder(tmp_path, [public(line("8901071732857")), public(line("8908019140019"))])
    assert sorted(p.name for p in (data / "lines").iterdir()) == ["8901.json", "8908.json"]
    assert gate.check_lines(data) == []


def test_no_lines_folder_is_fine_and_an_old_one_is_removed(tmp_path):
    assert gate.check_lines(tmp_path) == []
    data = data_folder(tmp_path, [public(line())])
    assert (data / "lines").is_dir()
    nl.write_shards([], data)
    assert not (data / "lines").exists()


def broken(tmp_path, mutate):
    data = data_folder(tmp_path, [public(line())])
    f = next((data / "lines").iterdir())
    obj = json.loads(f.read_text(encoding="utf-8"))
    mutate(obj)
    f.write_text(json.dumps(obj), encoding="utf-8")
    return gate.check_lines(data)


@pytest.mark.parametrize("name,mutate,needle", [
    ("free text", lambda o: o["lines"][0].update(note="hello"), "line columns"),
    ("bad basis", lambda o: o["lines"][0].update(basis="per piece"), "basis outside"),
    ("value too big", lambda o: o["lines"][0]["values"].update(fat=1e9), "out of range"),
    ("unknown field", lambda o: o["lines"][0]["values"].update(colour=1), "field that is not allowed"),
    ("too few values", lambda o: o["lines"][0].update(values={"fat": 1}), "fewer than 3"),
    ("bounds on a checked line", lambda o: o["lines"][0].update(bounds=[{}]), "wrong keys"),
    ("image address", lambda o: o["lines"][0].update(night="2026-11-14 https://images.openfoodfacts.org/a.jpg"), "image URL"),
    ("wrong version", lambda o: o.update(version=2), "version 1"),
])
def test_the_gate_names_each_break(tmp_path, name, mutate, needle):
    out = broken(tmp_path, mutate)
    assert any(needle in v for v in out), out


def test_a_line_in_the_wrong_file_and_a_stray_file_are_refused(tmp_path):
    data = data_folder(tmp_path, [public(line())])
    f = next((data / "lines").iterdir())
    f.rename(data / "lines" / "123.json")
    (data / "lines" / "notes.txt").write_text("hi", encoding="utf-8")
    out = gate.check_lines(data)
    assert any("does not belong" in v for v in out) and any("only files named" in v for v in out)


def test_the_gate_never_repeats_a_value(tmp_path):
    out = broken(tmp_path, lambda o: o["lines"][0]["values"].update(fat=987654321.5))
    assert out and not any("987654321" in v for v in out)


def test_the_gate_lists_equal_the_nightly_validators():
    assert tuple(gate.LINE_FIELDS) == lr.FIELDS
    assert gate.LINE_TYPES == lr.LINE_TYPES and gate.LINE_STATEMENTS == lr.STATEMENTS and gate.LINE_BASES == lr.BASES
    assert gate.LINE_BOUND_KEYS == lr.BOUND_KEYS and gate.LINE_BOUND_RULES == lr.BOUND_RULES and gate.LINE_BOUND_KINDS == lr.BOUND_KINDS
    assert gate.LINE_MAX_VALUE == lr.MAX_VALUE
    assert sorted(nl.PUBLIC_COLUMNS) == sorted(gate.LINE_COLUMNS)


class Resp:
    def __init__(self, data):
        self.data = data

    def read(self):
        return self.data

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def opener_for(files):
    def opener(req, timeout=0):
        path = req.full_url.split("/resolve/main/")[1].replace("%2F", "/")
        if path not in files:
            raise urllib.error.HTTPError(req.full_url, 404, "nf", {}, None)
        value = files[path]
        if isinstance(value, int):
            raise urllib.error.HTTPError(req.full_url, value, "err", {}, None)
        return Resp(json.dumps(value).encode())
    return opener


def test_build_end_to_end(tmp_path):
    data = data_folder(tmp_path, [])
    files = {"lines/current.json": {"8901071732857": line()}, "input/candidates.json": cands(("8901071732857", STORED))}
    counts = nl.build(data, "owner/nightly", "tok", opener=opener_for(files))
    assert counts["kept"] == 1 and counts["files"] == 1
    assert gate.check_lines(data) == []


def test_a_dataset_with_no_lines_file_builds_without_lines(tmp_path):
    data = data_folder(tmp_path, [public(line())])
    counts = nl.build(data, "owner/nightly", "tok", opener=opener_for({}))
    assert counts["kept"] == 0 and not (data / "lines").exists()


def test_a_dataset_that_cannot_be_read_stops_the_build(tmp_path):
    data = data_folder(tmp_path, [])
    with pytest.raises(nl.LinesError):
        nl.build(data, "owner/nightly", "tok", opener=opener_for({"lines/current.json": 500}))
    with pytest.raises(nl.LinesError):
        nl.build(data, "owner/nightly", "tok", opener=opener_for({"lines/current.json": {}}))     # candidates missing


def test_the_gate_refusing_stops_the_build_and_leaves_no_lines(tmp_path, monkeypatch):
    data = data_folder(tmp_path, [])
    monkeypatch.setattr(nl.licence_gate, "check_lines", lambda d: ["lines/x.json: 1 line(s): something"])
    files = {"lines/current.json": {"8901071732857": line()}, "input/candidates.json": cands(("8901071732857", STORED))}
    with pytest.raises(nl.LinesError):
        nl.build(data, "owner/nightly", "tok", opener=opener_for(files))
    assert not (data / "lines").exists()


def test_not_configured_means_no_lines_and_success(tmp_path, monkeypatch, capsys):
    monkeypatch.delenv("HF_NIGHTLY_READ_TOKEN", raising=False)
    data = data_folder(tmp_path, [public(line())])
    assert nl.main([str(data), "owner/nightly"]) == 0
    assert not (data / "lines").exists()
    assert "not configured" in capsys.readouterr().out
