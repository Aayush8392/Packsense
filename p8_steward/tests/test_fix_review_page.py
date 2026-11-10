import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import fix_review_page as p  # noqa: E402

ROW = {"code": "123", "a_fat": 30.0, "b_fat": 3.0, "a_carbohydrates": 20.0, "b_carbohydrates": 20.0, "serving_size": "50 g"}


def rows(n, cls):
    return [({"code": f"{cls}{i}"}, cls) for i in range(n)]


def test_selection_takes_all_alternatives_and_a_fixed_agreeing_sample():
    cl = rows(30, "valid_alternative") + rows(100, "agrees") + rows(5, "abstain")
    chosen = p.select(cl)
    assert len(chosen) == 30 + p.AGREEING_SAMPLE
    assert p.select(list(reversed(cl))) == chosen                                  # the same set and order whatever the input order
    assert not any(r["code"].startswith("abstain") for r in chosen)


def test_blind_assignment_is_consistent_and_hides_the_source():
    item, key = p.build_item(ROW, {"fat": 3.0, "carbohydrates": 20.0})
    assert set(key) == {"A", "B"} and {key["A"], key["B"]} == {"hybrid", "contributor"}
    assert "hybrid" not in str(item) and "contributor" not in str(item)
    assert (item["A"] if key["A"] == "hybrid" else item["B"]) == {"fat": 3.0, "carbohydrates": 20.0}


def test_join_counts_by_kind():
    key = {"1": {"A": "hybrid", "B": "contributor", "kind": "differs"}, "2": {"A": "contributor", "B": "hybrid", "kind": "differs"}, "3": {"A": "hybrid", "B": "contributor", "kind": "agrees"}}
    out = p.join({"1": "A", "2": "A", "3": "both"}, key)
    assert out == {"differs": {"hybrid": 1, "contributor": 1}, "agrees": {"both": 1}}


def test_page_embeds_data_and_nothing_about_sources():
    page = p.render([{"code": "1", "A": {"fat": 1.0}, "B": {"fat": 2.0}, "stored_before": {}, "serving": ""}], {"1": "https://example/x.jpg"}, "round1")
    assert "Which table matches the pack?" in page and "https://example/x.jpg" in page and "hybrid" not in page.lower() and "contributor" not in page.lower()


def test_serving_size_is_shown_without_float_noise():
    item, _ = p.build_item({**ROW, "serving_size": "56.00000000000001 g"}, {"fat": 3.0})
    assert item["serving"] == "56 g"


def test_serving_comes_from_the_pack_text_first_then_the_record():
    assert p.serving_for_page({**ROW, "serving_size": "50 g"}, {"serving_size": "1 rice cake ( about 13g )"}) == (13.0, "read from the pack text")
    assert p.serving_for_page({**ROW, "serving_size": "50 g"}, {"serving_size": "1 package"}) == (50.0, "from the product record")
    assert p.serving_for_page({**ROW, "serving_size": None}, None) == (None, "")
    item, key = p.build_item({**ROW, "serving_size": "30 g"}, {"fat": 3.0}, {"basis": "per serving only", "serving_size": "30 g"})
    assert item["serving_g"] == 30.0 and item["basis_hint"] == "per serving only" and "hybrid" not in str(item)


def scan_with(*langs):
    return {"responses": [{"fullTextAnnotation": {"pages": [{"property": {"detectedLanguages": [{"languageCode": c, "confidence": conf} for c, conf in langs]}}]}}]}


def test_glossary_lists_words_only_for_foreign_languages():
    de = p.glossary_from_scan(scan_with(("de", 0.9), ("en", 0.2)))
    assert "German" in de["title"] and len(de["lines"]) == 11 and de["lines"][0].endswith("= Energy") and "Energie" in de["lines"][0] or "energie" in de["lines"][0].lower()
    en = p.glossary_from_scan(scan_with(("en", 0.95)))
    assert en["lines"] == [] and "no translation needed" in en["note"]
    none = p.glossary_from_scan(None)
    assert none["lines"] == [] and "No listed language" in none["note"]


def test_page_never_keeps_the_previous_photo_on_screen_while_the_next_one_loads():
    page = p.render([{"code": "1", "A": {"fat": 1.0}, "B": {"fat": 2.0}, "stored_before": {}, "serving": "", "glossary": {"title": "", "note": "", "lines": []}}], {"1": "https://example/x.full.jpg"}, "round1")
    assert 'img.style.visibility="hidden"' in page and "loadTok" in page and ".400.jpg" in page and "Try again" in page and "prefetch(i+1)" in page
