"""Topic families: every hub and detail is a real answered entry, no entry is in two families, and a hub text really mentions each detail it claims to cover."""
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
BOT = HERE.parents[0] / "bot"
sys.path.insert(0, str(BOT))
import catalogue as cat  # noqa: E402
import matcher as mt  # noqa: E402

ENTRIES = cat.load_entries()
FIXED = cat.load_fixed()
BY_ID = {e["id"]: e for e in ENTRIES}
FAMILIES = cat.load_families(ENTRIES)


def test_every_hub_and_detail_is_a_real_answered_entry_and_no_entry_is_in_two_families():
    seen = []
    for f in FAMILIES:
        for eid in [f["hub"], *f["details"]]:
            assert eid in BY_ID and not BY_ID[eid].get("same_as") and BY_ID[eid]["status"] != "deferred", (f["name"], eid)
            seen.append(eid)
        assert f["hub"] not in f["details"], f["name"]
        assert 2 <= len(f["details"]) <= 8, f["name"]
    assert len(seen) == len(set(seen)), [x for x in seen if seen.count(x) > 1]


def test_a_hub_text_contains_the_cue_of_every_detail_it_covers():
    for f in FAMILIES:
        text = cat.render(BY_ID[f["hub"]], FIXED).lower()
        for eid, cue in f["details"].items():
            assert cue.lower() in text, (f["name"], eid, cue)


def test_a_tie_in_one_family_gives_the_hub_and_a_tie_across_families_gives_a_choice():
    m = mt.Matcher(ENTRIES, FIXED)
    fam = FAMILIES[0]
    a, b = fam["hub"], next(iter(fam["details"]))
    same = m.tie_result([(a, 0.70), (b, 0.69), ("1.14", 0.2)], 0.70)
    assert same.action == "hub" and same.entry_id == fam["hub"] and set(same.options) == set(fam["details"])
    other = next(f for f in FAMILIES if f is not fam)
    across = m.tie_result([(a, 0.70), (other["hub"], 0.69), ("1.14", 0.2)], 0.70)
    assert across.action == "choice" and across.options == [a, other["hub"]]
    m.use_families = False
    assert m.tie_result([(a, 0.70), (b, 0.69)], 0.70).action == "generic"
    assert "which one" in m.reply(across).lower() or "which" in cat.resolve("@choice_reply", FIXED).lower()


def test_a_request_for_advice_never_gets_a_hub_or_a_choice():
    m = mt.Matcher(ENTRIES, FIXED)
    fam = FAMILIES[0]
    ranked = [(fam["hub"], 0.70), (FAMILIES[1]["hub"], 0.69), ("1.14", 0.2)]
    assert m.tie_result(ranked, 0.70, "food allergy advice").action == "generic"
    assert m.tie_result(ranked, 0.70, "please recommend a brand").action == "generic"
    assert m.tie_result(ranked, 0.70, "barcode card").action == "choice"
