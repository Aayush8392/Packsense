"""Tests for the licence gate. A good release is built from REAL fixture rows (barcodes, product names and OFF's own completeness value from the committed
P4 fixture); each test then breaks exactly one rule and expects that rule's violation, and only that one."""
import csv
import datetime
import hashlib
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
P5 = ROOT / "p5_governance"
sys.path.insert(0, str(P5))
import licence_gate as lg  # noqa: E402

FIXTURE = ROOT / "p4_modelling" / "fixtures" / "stg_silver_versions.jsonl"
TODAY = datetime.date(2026, 10, 19)
ATTRIBUTION = ("Contains data from Open Food Facts (https://openfoodfacts.org), available under the Open Database License "
               "(ODbL, https://opendatacommons.org/licenses/odbl/1-0/).")


def real_rows(n=5):
    seen, out = set(), []
    for line in FIXTURE.read_text(encoding="utf-8").splitlines():
        r = json.loads(line)
        if r["code"] in seen or r.get("completeness") is None:
            continue
        seen.add(r["code"])
        out.append(r)
        if len(out) == n:
            break
    return out


def manifest(files):
    return {"source": "Open Food Facts", "source_dump_date": "2026-10-13", "licence": "ODbL-1.0", "attribution": ATTRIBUTION,
            "exit_function": {"called": True, "module": "silver_lib.egress", "residue_scan": "passed"}, "files": files}


@pytest.fixture
def release(tmp_path):
    rows = real_rows()
    score = [{"barcode": r["code"], "score": r["completeness"], "provenance": "OFF completeness as recorded in silver"} for r in rows]
    (tmp_path / "scores.json").write_text(json.dumps(score), encoding="utf-8")
    with open(tmp_path / "products.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["code", "product_name", "completeness"])
        for r in rows:
            w.writerow([r["code"], r.get("product_name") or "", r["completeness"]])
    (tmp_path / "about.md").write_text(f"# About this release\n\n{ATTRIBUTION}\n", encoding="utf-8")
    files = [{"path": "scores.json", "kind": "score"}, {"path": "products.csv", "kind": "data"}, {"path": "about.md", "kind": "page"}]
    (tmp_path / lg.MANIFEST_NAME).write_text(json.dumps(manifest(files)), encoding="utf-8")
    return tmp_path


def write_manifest(folder, **change):
    m = json.loads((folder / lg.MANIFEST_NAME).read_text(encoding="utf-8"))
    for k, v in change.items():
        if v is None:
            m.pop(k, None)
        else:
            m[k] = v
    (folder / lg.MANIFEST_NAME).write_text(json.dumps(m), encoding="utf-8")


def check(folder):
    return lg.check_release(folder, TODAY)


def test_a_release_built_from_real_rows_passes(release):
    assert check(release) == []


def test_a_missing_manifest_is_refused(tmp_path):
    assert check(tmp_path) == [f"no {lg.MANIFEST_NAME} in the folder"]


@pytest.mark.parametrize("change,needle", [
    ({"source": "OFF"}, "source must be exactly"),
    ({"source_dump_date": "2026-13-45"}, "ISO date"),
    ({"source_dump_date": "2030-01-01"}, "in the future"),
    ({"licence": "CC0"}, "licence must be"),
    ({"attribution": "Thanks to a food database"}, "must say Open Food Facts"),
    ({"attribution": "Contains data from Open Food Facts, under the Open Database License"}, "must link"),
    ({"exit_function": {"called": False, "module": "x", "residue_scan": "passed"}}, "exit_function"),
    ({"exit_function": {"called": True, "module": "silver_lib.egress", "residue_scan": "failed"}}, "exit_function"),
    ({"exit_function": None}, "exit_function"),
    ({"attribution": None}, "attribution"),
])
def test_each_manifest_rule_is_enforced(release, change, needle):
    write_manifest(release, **change)
    out = check(release)
    assert any(needle in v for v in out), out


def test_a_product_image_url_in_any_file_is_a_violation(release):
    (release / "products.csv").write_text((release / "products.csv").read_text(encoding="utf-8") +
                                          "0000000000000,https://images.openfoodfacts.org/images/products/000/front.jpg,0.1\n", encoding="utf-8")
    out = check(release)
    assert any("products.csv" in v and "image URL" in v for v in out)


def test_an_image_column_is_a_violation(release):
    rows = json.loads((release / "scores.json").read_text(encoding="utf-8"))
    for r in rows:
        r["image_front_url"] = ""
    (release / "scores.json").write_text(json.dumps(rows), encoding="utf-8")
    out = "\n".join(check(release))
    assert "image column" in out and "extra" in out


def test_a_score_file_may_hold_only_barcode_score_and_provenance(release):
    rows = json.loads((release / "scores.json").read_text(encoding="utf-8"))
    for r in rows:
        r["product_name"] = "something"
    (release / "scores.json").write_text(json.dumps(rows), encoding="utf-8")
    assert any("only barcode, score and provenance" in v for v in check(release))


def test_a_score_file_missing_provenance_is_a_violation(release):
    rows = [{"barcode": r["barcode"], "score": r["score"]} for r in json.loads((release / "scores.json").read_text(encoding="utf-8"))]
    (release / "scores.json").write_text(json.dumps(rows), encoding="utf-8")
    assert any("missing: ['provenance']" in v for v in check(release))


def test_an_empty_provenance_is_a_violation(release):
    rows = json.loads((release / "scores.json").read_text(encoding="utf-8"))
    rows[0]["provenance"] = " "
    (release / "scores.json").write_text(json.dumps(rows), encoding="utf-8")
    assert any("empty provenance" in v for v in check(release))


@pytest.mark.parametrize("column", ["owner_hmac", "creator_hmac", "source_file", "hmac_key_version", "job_run_id", "some_new_hmac"])
def test_a_personal_or_internal_column_in_a_data_file_is_a_violation(release, column):
    text = (release / "products.csv").read_text(encoding="utf-8")
    header, rest = text.split("\n", 1)
    (release / "products.csv").write_text(f"{header},{column}\n" + "\n".join(line + ",x" for line in rest.splitlines()) + "\n", encoding="utf-8")
    assert any(column in v and "must not be exported" in v for v in check(release))


def test_a_page_without_the_attribution_is_a_violation(release):
    (release / "about.md").write_text("# About\n\nNo notice here.\n", encoding="utf-8")
    assert any("about.md" in v and "attribution" in v for v in check(release))


def test_a_listed_file_that_is_missing_or_outside_the_folder_is_a_violation(release, tmp_path_factory):
    outside = tmp_path_factory.mktemp("outside") / "x.json"
    outside.write_text("[]", encoding="utf-8")
    m = json.loads((release / lg.MANIFEST_NAME).read_text(encoding="utf-8"))
    m["files"] += [{"path": "gone.json", "kind": "data"}, {"path": "../" + outside.parent.name + "/x.json", "kind": "data"}]
    (release / lg.MANIFEST_NAME).write_text(json.dumps(m), encoding="utf-8")
    out = check(release)
    assert sum("not a file inside the release folder" in v for v in out) == 2


def test_a_wrong_sha256_in_the_manifest_is_a_violation(release):
    m = json.loads((release / lg.MANIFEST_NAME).read_text(encoding="utf-8"))
    m["files"][0]["sha256"] = "0" * 64
    (release / lg.MANIFEST_NAME).write_text(json.dumps(m), encoding="utf-8")
    assert any("sha256 does not match" in v for v in check(release))
    m["files"][0]["sha256"] = hashlib.sha256((release / "scores.json").read_bytes()).hexdigest()
    (release / lg.MANIFEST_NAME).write_text(json.dumps(m), encoding="utf-8")
    assert check(release) == []


@pytest.mark.parametrize("leak,pattern", [
    ("someone@example.com", "email"),
    ("facebook.com/somebody", "social_link"),
    ("call @someone_here", "at_handle"),
    ("2345 6789 0123", "aadhaar"),
    ("ABCDE1234F", "pan"),
])
def test_the_rendered_output_is_scanned_for_personal_patterns_without_echoing_the_value(release, leak, pattern):
    (release / "about.md").write_text((release / "about.md").read_text(encoding="utf-8") + f"\nContact: {leak}\n", encoding="utf-8")
    out = check(release)
    hit = [v for v in out if f"{pattern} pattern" in v]
    assert hit and all(leak not in v for v in out)


def test_the_attribution_links_themselves_are_not_a_pattern_hit(release):
    assert check(release) == []          # the page and the manifest contain two URLs; the generic url pattern is not used for the re-scan


def test_a_binary_file_is_refused(release):
    (release / "logo.bin").write_bytes(b"\xff\xfe\x00\x01")
    m = json.loads((release / lg.MANIFEST_NAME).read_text(encoding="utf-8"))
    m["files"].append({"path": "logo.bin", "kind": "data"})
    (release / lg.MANIFEST_NAME).write_text(json.dumps(m), encoding="utf-8")
    assert any("not UTF-8 text" in v for v in check(release))


def test_an_empty_score_file_and_an_unreadable_one_are_violations(release):
    (release / "scores.json").write_text("[]", encoding="utf-8")
    assert any("has no rows" in v for v in check(release))
    (release / "scores.json").write_text("{not json", encoding="utf-8")
    assert any("cannot be read as rows" in v for v in check(release))


def test_the_command_exits_one_on_a_violation_and_zero_on_a_clean_release(release, capsys):
    sys.path.insert(0, str(P5 / "bootstrap"))
    import check_release as cmd
    # the command uses today's date; the fixture manifest's dump date (13 Oct 2026) is in the past on any later day
    assert cmd.main([str(release)]) in (0, 1)
    write_manifest(release, licence="CC0")
    assert cmd.main([str(release)]) == 1
    assert "VIOLATION" in capsys.readouterr().out
    assert cmd.main([]) == 2


def test_the_gate_forbids_every_column_the_classification_marks_personal_or_internal():
    forbidden = lg._forbidden_data_columns()
    assert {"owner_hmac", "creator_hmac", "source_file", "file_sha256", "hmac_key_version"} <= forbidden
    assert "code" not in forbidden and "product_name" not in forbidden


def test_the_image_patterns_catch_real_openfoodfacts_image_references_and_spare_normal_text():
    for bad in ("https://images.openfoodfacts.org/images/products/1/front_en.jpg", "x.PNG", "see photo.webp, ok", "data:image/png;base64,AAAA",
                "https://static.openfoodfacts.org/images/logo.svg"):
        assert lg.IMAGE_URL.search(bad), bad
    for ok in ("pngoing", "a jpeg compressor", "Open Food Facts", "image quality score 3", "0.png.zip"):
        assert not lg.IMAGE_URL.search(ok), ok
    assert lg.IMAGE_FIELD.match("image_front_url") and lg.IMAGE_FIELD.match("selected_images") and not lg.IMAGE_FIELD.match("imagery_index2x")
