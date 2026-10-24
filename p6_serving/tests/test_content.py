"""The page text in p6_serving/app/content: twelve files that agree with the menu, carry the notes the owner asked for, and keep the card wording of the lookup page in step with the data codes."""
import re
import sys
from pathlib import Path

import yaml

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
CONTENT = ROOT / "p6_serving" / "app" / "content"
sys.path.insert(0, str(ROOT / "p5_governance"))
import licence_gate as gate  # noqa: E402

SECTIONS = {"Home", "Explore the data", "How it works", "Get the data", "Look up", "About"}
TABLE_PAGES = {"brands", "quality-over-time", "daily-changes", "india-today", "how-we-work", "pipeline-health"}


def load(path: Path):
    text = path.read_text(encoding="utf-8")
    m = re.match(r"^---\n(.*?)\n---\n(.*)$", text, re.S)
    assert m, f"{path.name}: front matter missing"
    return yaml.safe_load(m.group(1)), m.group(2)


PAGES = {p.name: load(p) for p in sorted(CONTENT.glob("*.md"))}


def test_there_are_twelve_pages_numbered_in_order_with_unique_slugs():
    assert len(PAGES) == 12
    meta = [m for m, _ in PAGES.values()]
    assert [m["order"] for m in meta] == list(range(1, 13))
    assert len({m["slug"] for m in meta}) == 12
    for name, (m, _) in PAGES.items():
        assert name == f"{m['order']:02d}-{m['slug']}.md"
        assert m["section"] in SECTIONS and m["title"] and m["question"] and m["built_from"]


def test_the_lookup_pages_are_marked_later_and_nothing_else_is():
    later = {m["slug"] for m, _ in PAGES.values() if m.get("status") == "later"}
    assert later == {"barcode-lookup", "ask-a-question"}


def test_every_table_page_has_the_can_and_cannot_note():
    for m, body in PAGES.values():
        if m["slug"] in TABLE_PAGES:
            assert "What this page can and cannot tell you" in body, m["slug"]


def test_the_about_page_keeps_the_safety_line_and_the_wording_rule():
    _, body = PAGES["12-about.md"]
    assert "Do not use this site to decide whether a food is safe for you" in body
    assert 'We never say "correct"' in body
    assert "contact" not in body.lower().replace("no contact", "")


def test_the_checked_claims_are_listed_and_really_in_the_text():
    m, body = PAGES["02-how-we-differ.md"]
    assert "unverified_claims" not in m
    assert set(m["checked_claims"]) == {"more than four million products", "more than 100,000 contributors", "photos of the packs"}
    assert all(c in body for c in m["checked_claims"])


def test_page_two_lists_all_eleven_checks_in_the_order_of_the_rules():
    _, body = PAGES["02-how-we-differ.md"]
    section = body.split("## The 11 checks", 1)[1].split("**What we do not claim.**", 1)[0]
    items = re.findall(r"^(\d+)\. \*\*(.+?)\*\*", section, re.M)
    assert [n for n, _ in items] == [str(i) for i in range(1, 12)]
    sys.path.insert(0, str(ROOT / "p7_triage_ml"))
    import rules_lib  # noqa: E402
    assert len(items) == len(rules_lib.RULES)
    assert "A check is skipped when a number it needs is missing" in section


def test_the_lookup_signal_labels_cover_exactly_the_cards_light_codes():
    m, body = PAGES["10-barcode-lookup.md"]
    labels = m["signal_labels"]
    assert set(labels) == gate.CARD_LIGHTS
    assert [labels[k]["label"] for k in ("several_flagged", "one_flagged", "none_flagged", "not_enough_data")] == [
        "Several things flagged", "One thing flagged", "Nothing flagged", "Not enough data to check"]
    assert "does not mean the entry is correct" in labels["none_flagged"]["line"]
    assert "worth a look, not wrong" in labels["several_flagged"]["line"] and "no nutrition table" in labels["not_enough_data"]["line"]
    for v in labels.values():
        assert v["label"] in body or v["label"].split(" ")[0] in body


def test_no_page_makes_a_correctness_claim_or_names_a_person_or_contact():
    for name, (_, body) in PAGES.items():
        assert not re.search(r"[\w.]+@[\w.]+\.\w+", body), name
        assert not re.search(r"https?://", body), name
        claims = re.sub(r"(?:whether|not mean)[^.]{0,40}\b(?:is|are) correct", "", body, flags=re.I)      # "does not show whether the entries are correct" is the opposite of a claim
        assert not re.search(r"\b(?:is|are) correct\b", claims, re.I), name
