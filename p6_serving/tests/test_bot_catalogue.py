"""The answer catalogue: every answerable question has an answer, shared texts resolve, the voice rules hold, and `today` answers carry the closing line."""
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
BOT = HERE.parents[0] / "bot"
sys.path.insert(0, str(BOT))
import catalogue as cat  # noqa: E402
import split_questions as sq  # noqa: E402

FIXED = cat.load_fixed()
ENTRIES = cat.load_entries()
BY_ID = {e["id"]: e for e in ENTRIES}

COVERS = cat.COVERS


def test_ids_are_unique_and_every_answerable_question_has_an_answer():
    ids = [e["id"] for e in ENTRIES]
    assert len(ids) == len(set(ids))
    answerable = [r["id"] for r in sq.load(sq.HERE / "questions_all.psv") if not r["id"].startswith("17.")]
    answerable += [r["id"] for r in sq.load(sq.HERE / "questions_added_heldout.psv") if not r["id"].startswith("17.") and "-r" not in r["id"]]
    missing = [i for i in answerable if i not in BY_ID and COVERS.get(i) not in BY_ID]
    assert not missing, missing
    assert all(v in BY_ID for v in COVERS.values())


def test_every_working_set_question_is_a_wording_of_some_entry():
    known = {cat.normalise(w) for e in ENTRIES for w in cat.wordings(e)}
    working = [r for r in sq.load(sq.HERE / "questions_working.psv") if not r["id"].startswith("17.")]
    missing = [r["id"] for r in working if cat.normalise(r["text"]) not in known]
    assert not missing, missing


def test_shared_texts_resolve_and_every_decline_group_has_a_reply():
    for e in ENTRIES:
        assert cat.render(e, FIXED).strip(), e["id"]
    groups = {r["kind"].split(":", 1)[1] for r in sq.load(sq.HERE / "questions_all.psv") + sq.load(sq.HERE / "questions_added_heldout.psv") if r["kind"].startswith("Decline:")}
    assert groups <= set(FIXED["decline_groups"]), groups - set(FIXED["decline_groups"])
    for g, v in FIXED["decline_groups"].items():
        if isinstance(v, str):
            assert cat.resolve(v, FIXED)


def test_the_voice_is_impersonal_and_sentences_stay_short():
    texts = [cat.render(e, FIXED) for e in ENTRIES] + [v for k, v in FIXED["texts"].items() if k != "generic_reply"]
    for t in texts:
        assert not re.search(r"\b(we|our|ours|us)\b", t, re.I), t
        for s in re.split(r"(?<=[.!?])\s+", t):
            assert len(s.split()) <= 30, s
    assert [t for t in texts if re.search(r"\bI\b", t)] == []        # only the generic reply speaks as "I"


def test_today_answers_end_with_the_closing_line_and_deferred_ones_are_marked():
    closing = FIXED["texts"]["closing_line"]
    for e in ENTRIES:
        if e["kind"] == "today" and e["status"] != "deferred":
            assert cat.render(e, FIXED).endswith(closing), e["id"]
        if e["status"] == "deferred":
            assert e["id"].startswith("16.")
    assert FIXED["input_rules"]["max_characters"] == 300


def test_no_answer_claims_correctness_or_advice():
    for e in ENTRIES:
        t = cat.render(e, FIXED)
        claims = re.sub(r"(?:whether|not mean|never say|never)[^.]{0,60}\b(?:is|are) correct", "", t, flags=re.I)
        assert not re.search(r"\b(?:is|are) correct\b", claims, re.I) or e["id"] in {"6.9", "11.1"}, e["id"]


def test_follow_up_buttons_point_at_real_answered_entries_and_stay_short():
    follow = cat.load_follow_ups(ENTRIES)
    for eid, ids in follow.items():
        assert eid in BY_ID, eid
        assert BY_ID[eid]["status"] != "deferred", eid                                             # deferred AI answers carry no buttons
        assert 1 <= len(ids) <= 3, (eid, ids)
        for i in ids:
            assert i in BY_ID and not BY_ID[i].get("same_as") and BY_ID[i]["status"] != "deferred", (eid, i)
            assert i != eid
