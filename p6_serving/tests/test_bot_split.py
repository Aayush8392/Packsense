"""The question split for the bot test: fixed, complete, and keeps rewordings and duplicates on the same side."""
import re
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
BOT = HERE.parents[0] / "bot"
sys.path.insert(0, str(BOT))
import split_questions as sq  # noqa: E402

ROWS = sq.load(BOT / "questions_all.psv")
needs_private_set = pytest.mark.skipif(not (BOT / "packsense_faq_test_questions.txt").exists(), reason="the outside question sets are private and not in the repository")


def test_the_split_is_complete_disjoint_and_repeatable():
    working, held = sq.split(ROWS)
    ids = [r["id"] for r in ROWS]
    assert len(ids) == len(set(ids))
    assert sorted(r["id"] for r in working + held) == sorted(ids)
    assert not {r["id"] for r in working} & {r["id"] for r in held}
    again = sq.split(ROWS)
    assert [r["id"] for r in again[1]] == [r["id"] for r in held]


def test_about_a_third_is_held_out_overall_and_in_every_big_topic():
    working, held = sq.split(ROWS)
    assert 0.30 <= len(held) / len(ROWS) <= 0.37
    for s in {sq.stratum(r["id"]) for r in ROWS}:
        n = sum(1 for r in ROWS if sq.stratum(r["id"]) == s)
        h = sum(1 for r in held if sq.stratum(r["id"]) == s)
        if n >= 15:
            assert h >= 1, s


def test_rewordings_and_identical_questions_never_straddle_the_split():
    _, held = sq.split(ROWS)
    held_ids = {r["id"] for r in held}
    for members in sq.groups(ROWS).values():
        sides = {m["id"] in held_ids for m in members}
        assert len(sides) == 1, [m["id"] for m in members]
    for r in ROWS:
        twins = [o["id"] for o in ROWS if re.sub(r"\W+", " ", o["text"].lower()) == re.sub(r"\W+", " ", r["text"].lower())]
        assert len({t in held_ids for t in twins}) == 1, twins


def test_every_question_has_a_known_kind_and_no_pipe_in_the_text():
    for r in ROWS + ADDED:
        assert "|" not in r["text"] and r["text"].strip() and r["kind"]


ADDED = sq.load(BOT / "questions_added_heldout.psv")


def _norm(t: str) -> str:
    return re.sub(r"\W+", " ", t.lower()).strip()


def test_the_added_questions_are_new_and_every_rewording_has_a_working_set_original():
    working, _ = sq.split(ROWS)
    working_ids = {r["id"] for r in working}
    ids = [r["id"] for r in ROWS + ADDED]
    assert len(ids) == len(set(ids))
    assert len({_norm(r["text"]) for r in ADDED}) == len(ADDED)                              # no wording twice among the new ones
    assert not {_norm(r["text"]) for r in ADDED} & {_norm(r["text"]) for r in ROWS}        # and none that an original already has (7.9 and 14.8 are a known identical pair, kept together)
    rewordings = [r for r in ADDED if "-r" in r["id"]]
    assert len(rewordings) == 60 and len(ADDED) == 140
    assert all(r["id"].split("-r")[0] in working_ids for r in rewordings)                  # the originals are in the working set, so the catalogue is written from them
    assert sum(1 for r in ADDED if r["kind"].startswith("Decline")) == 78


def test_the_written_files_match_the_rule_and_hold_every_question_once():
    working, held = sq.split(ROWS)
    on_disk_working = sq.load(BOT / "questions_working.psv")
    on_disk_held = sq.load(BOT / "questions_heldout.psv")
    assert [r["id"] for r in on_disk_working] == [r["id"] for r in working]
    assert [r["id"] for r in on_disk_held] == [r["id"] for r in held + ADDED]
    assert not {r["id"] for r in on_disk_working} & {r["id"] for r in on_disk_held}


@needs_private_set
def test_cross_validation_folds_are_stratified_disjoint_and_repeatable():
    import cross_validate as cv
    import evaluate_external as ee
    rows = ee.load()
    fs = cv.folds(rows)
    assert sorted(r["n"] for f in fs.values() for r in f) == [r["n"] for r in rows]
    assert [len(f) for f in fs.values()] == [30] * 5
    for f in fs.values():
        kinds = [r["kind"] for r in f]
        assert (kinds.count("ON"), kinds.count("OFF"), kinds.count("NEXT")) == (18, 8, 4)
    assert [[r["n"] for r in f] for f in cv.folds(rows).values()] == [[r["n"] for r in f] for f in fs.values()]


@needs_private_set
def test_extra_wordings_come_only_from_the_training_questions():
    import catalogue as cat
    import cross_validate as cv
    import evaluate_external as ee
    rows = ee.load()
    fs = cv.folds(rows)
    entries = cat.load_entries()
    before = {e["id"]: set(e.get("alt", [])) for e in entries}
    train = [r for j in range(1, 5) for r in fs[j]]
    es = cv.with_extra_wordings(entries, train)
    added = {w for e in es for w in set(e.get("alt", [])) - before[e["id"]]}
    assert added <= {r["text"] for r in train}
    assert not added & {r["text"] for r in fs[0]}                      # nothing from the test fold
    assert {e["id"]: set(e.get("alt", [])) for e in entries} == before   # the original catalogue is untouched
