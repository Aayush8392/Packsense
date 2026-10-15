"""India seed logic.

Real records only: the India records and the "en:india appears in another field" records are real bronze records (sanitised, see
bootstrap/extract_seed_fixtures.py); the non-India records are the real ones in bronze_records.jsonl. The dump is imitated by
gzipping these real lines and cutting the bytes at arbitrary places, which is exactly what the archive's 1 GiB parts are.
"""
import gzip
import hashlib
import json
import sys
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import seed_lib as s  # noqa: E402

FIX = Path(__file__).resolve().parent / "fixtures"


def load(name):
    return [json.loads(x) for x in (FIX / name).read_text(encoding="utf-8").splitlines() if x.strip()]


SEED = load("seed_india_lines.jsonl")
OTHER = load("bronze_records.jsonl")
INDIA = [r["raw_json"] for r in SEED if r["case"].startswith("india_") and r["case"] != "india_text_but_not_a_country"]
TEXT_ONLY = [r["raw_json"] for r in SEED if r["case"] == "india_text_but_not_a_country"]
NON_INDIA = [r["raw_json"] for r in OTHER]


def dump_of(lines, members=1):
    """One gzip stream (or several members in a row) of the given JSON lines."""
    text = ("\n".join(lines) + "\n").encode("utf-8")
    if members == 1:
        return gzip.compress(text)
    third = len(text) // members
    return b"".join(gzip.compress(text[i * third:(i + 1) * third if i < members - 1 else len(text)]) for i in range(members))


def cut(data, points):
    edges = [0, *points, len(data)]
    return [data[a:b] for a, b in zip(edges, edges[1:])]


def test_fixtures_are_what_the_tests_assume():
    assert len(INDIA) >= 4 and len(TEXT_ONLY) == 2
    assert all(b"en:india" in x.encode() for x in TEXT_ONLY)       # the byte search hits them...
    assert all(s.india_record(x.encode()) is None for x in TEXT_ONLY)  # ...and the tag check rejects them


def test_every_india_record_is_found_and_keeps_the_line_as_received():
    for raw in INDIA:
        rec = s.india_record(raw.encode())
        d = json.loads(raw)
        assert rec == {"code": d["code"], "last_modified_t": d["last_modified_t"], "raw_json": raw}


def test_non_india_lines_are_ignored():
    assert all(s.india_record(x.encode()) is None for x in NON_INDIA)


def test_a_line_that_is_not_json_or_not_an_object_is_ignored():
    assert s.india_record(b'broken en:india {') is None
    assert s.india_record(b'["en:india"]') is None


def test_a_record_without_a_usable_key_is_still_returned_with_nulls():
    rec = s.india_record(b'{"countries_tags":["en:india"],"last_modified_t":true}')
    assert rec["code"] is None and rec["last_modified_t"] is None


def test_the_stream_gives_the_same_records_wherever_the_parts_are_cut():
    lines = [*INDIA[:2], *NON_INDIA[:3], *TEXT_ONLY, *INDIA[2:], *NON_INDIA[3:6]]
    data = dump_of(lines)
    expected = [json.loads(x)["code"] for x in INDIA]
    n = len(data)
    for points in ([], [n // 2], [7, 19, n // 3, n - 5], list(range(40, n, 2500))):
        stream = s.DumpStream()
        got = []
        for part in cut(data, points):
            recs, _ = s.scan_chunks(stream, [part])
            got += recs
        got += [r for r in (s.india_record(x) for x in stream.finish()) if r]
        assert stream.complete
        assert [r["code"] for r in got] == expected, points


def test_a_line_that_straddles_two_parts_belongs_to_the_part_where_it_ends():
    data = dump_of(INDIA[:1] + NON_INDIA[:2])
    # cut the compressed bytes into small pieces and find the piece in which the first line completes
    pieces = cut(data, list(range(10, len(data), 10)))
    stream, owner = s.DumpStream(), None
    for i, piece in enumerate(pieces):
        recs, _ = s.scan_chunks(stream, [piece])
        if recs:
            owner = i
            break
    assert owner is not None and owner > 0     # not the first piece: the line needed several pieces


def test_catching_up_over_finished_parts_still_advances_the_stream():
    data = dump_of(INDIA + NON_INDIA[:4])
    parts = cut(data, [len(data) // 3, 2 * len(data) // 3])
    stream = s.DumpStream()
    s.scan_chunks(stream, [parts[0]], collect=False)      # a part the stage already holds: advance only
    recs, _ = s.scan_chunks(stream, [parts[1], parts[2]])
    stream_full = s.DumpStream()
    full, _ = s.scan_chunks(stream_full, parts)
    full_codes = [r["code"] for r in full]
    # lines completed after the skipped part are all found, and none is damaged by the carried bytes
    assert [r["code"] for r in recs] == full_codes[len(full_codes) - len(recs):]
    assert all(json.loads(r["raw_json"])["code"] == r["code"] for r in recs)


def test_a_dump_without_a_final_newline_gives_its_last_line_on_finish():
    text = "\n".join(INDIA[:1] + NON_INDIA[:1] + INDIA[1:2]).encode()   # no trailing newline
    stream = s.DumpStream()
    recs, _ = s.scan_chunks(stream, [gzip.compress(text)])
    last = [r for r in (s.india_record(x) for x in stream.finish()) if r]
    assert len(recs) == 1 and len(last) == 1 and last[0]["code"] == json.loads(INDIA[1])["code"]


def test_several_gzip_members_in_a_row_are_read_as_one_stream():
    lines = INDIA + NON_INDIA[:5]
    stream = s.DumpStream()
    recs, _ = s.scan_chunks(stream, [dump_of(lines, members=3)])
    recs += [r for r in (s.india_record(x) for x in stream.finish()) if r]
    assert [r["code"] for r in recs] == [json.loads(x)["code"] for x in INDIA] and stream.complete


def test_a_truncated_download_is_detected():
    data = dump_of(INDIA + NON_INDIA)
    stream = s.DumpStream()
    s.scan_chunks(stream, [data[: len(data) // 2]])
    assert not stream.complete


def test_plan_parts_are_in_stream_order_and_mark_finished_ones():
    manifest = {"parts": {"0001": {"bytes": 5, "sha256": "b"}, "0000": {"bytes": 4, "sha256": "a"}, "0002": {"bytes": 6, "sha256": "c"}}}
    plan = s.plan_parts(manifest, {"seed-dump:2026-10-13:part-0001"}, "2026-10-13")
    assert [p["key"] for p in plan] == ["0000", "0001", "0002"]
    assert [p["done"] for p in plan] == [False, True, False]
    assert plan[0]["source_file"] == "seed-dump:2026-10-13:part-0000"


def test_a_part_that_does_not_match_the_archive_manifest_is_refused():
    part = {"key": "0003", "bytes": 4, "sha256": hashlib.sha256(b"abcd").hexdigest()}
    assert s.verify_part(part, 4, hashlib.sha256(b"abcd").hexdigest()) is None
    assert "bytes downloaded" in s.verify_part(part, 5, hashlib.sha256(b"abcd").hexdigest())
    assert "sha256 differs" in s.verify_part(part, 4, hashlib.sha256(b"abce").hexdigest())


def test_stage_tuple_matches_the_bronze_column_order():
    rec = s.india_record(INDIA[0].encode())
    row = s.stage_tuple(rec, "seed-dump:2026-10-13:part-0002", "f" * 64, "T")
    assert row == (rec["code"], rec["last_modified_t"], "seed-dump:2026-10-13:part-0002", "f" * 64, "T", INDIA[0])
