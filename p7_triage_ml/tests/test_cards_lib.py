"""The labelling cards (Phase D item 16): scope of the flags, the photos, the card text and the deterministic selection, on REAL data:
flag family names as they occur on production, OFF API answers kept in fixtures/off_selected_images_real.json, product rows from the real DuckDB fixture."""
import hashlib
import json
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "labelling"))
import cards_lib as cl  # noqa: E402

OFF = json.loads((HERE / "fixtures" / "off_selected_images_real.json").read_text(encoding="utf-8"))
FIXTURE = HERE.parents[1] / "p4_modelling" / "fixtures" / "stg_silver_versions.jsonl"


def real_rows(n):
    out, seen = [], set()
    for line in FIXTURE.read_text(encoding="utf-8").splitlines():
        d = json.loads(line)
        if d["code"] in seen or d.get("energy_kj") is None:
            continue
        seen.add(d["code"])
        out.append({"code": d["code"], "product_name": d["product_name"], "brands": d["brands"], "quantity_amount": d.get("quantity_amount"),
                    "quantity_unit": d.get("quantity_unit"), "serving_amount": d.get("serving_amount"), "serving_unit": d.get("serving_unit"),
                    "nutrition_per": d.get("nutrition_per"), "nutrition_preparation": d.get("nutrition_preparation"),
                    **{k: d.get(k) for k, _, _ in cl.VALUE_ROWS}})
        if len(out) == n:
            break
    return out


# the family names are the ones seen on production on 2026-10-25
IN = ["value-very-high-for-category-salt", "value-very-low-for-category-energy", "value-very-high-for-category-saturated-fat", "value-under-0-01-g-salt",
      "value-under-0-001-g-salt", "3-or-more-values-are-identical"]
OUT = ["environmental-score-production-system-no-label", "food-groups-1-unknown", "energy-value-in-kcal-does-not-match-value-in-kj", "value-over-105-water",
       "serving-quantity-defined-but-quantity-undefined", "value-total-over-105", "salt-does-not-match-sodium", "no-nutrition-data"]


def test_the_scope_is_the_nutrition_number_flags_no_rule_decides():
    assert all(cl.in_scope(f) for f in IN)
    assert not any(cl.in_scope(f) for f in OUT)


def test_every_in_scope_flag_has_plain_words_and_nothing_else_does():
    for f in IN:
        assert cl.plain_flag(f).endswith(".")
    assert cl.plain_flag("value-very-high-for-category-saturated-fat") == "Saturated fat is very high for its category."
    assert cl.plain_flag("value-under-0-01-g-salt") == "Salt is recorded as under 0.01 g."
    with pytest.raises(ValueError):
        cl.plain_flag(OUT[0])


def test_the_scope_does_not_overlap_the_arithmetic_rules():
    sys.path.insert(0, str(HERE.parents[0]))
    import rules_lib as rl
    assert not any(rl.rule_for_family(f) for f in IN)


def test_photos_need_a_selected_nutrition_photo():
    assert cl.photo_urls(OFF["8906097598241"]) is None                        # real product with only a front photo
    assert cl.photo_urls(OFF["20240066"]) is None                             # real product with front, ingredients and packaging, no nutrition photo
    p = cl.photo_urls(OFF["4070765054392"])
    assert p["nutrition_full"].endswith("nutrition_en.5.full.jpg") and p["nutrition_400"].endswith("nutrition_en.5.400.jpg") and p["nutrition_lang"] == "en"
    assert p["front"].startswith("https://images.openfoodfacts.org/")


def test_a_card_shows_the_record_in_plain_words_and_nothing_personal():
    row = real_rows(1)[0]
    photos = cl.photo_urls(OFF["4070765054392"])
    t = cl.make_task(row, ["value-very-high-for-category-salt"], photos, "practice_1", 3)
    d = t["data"]
    assert d["card"] == "practice_1 03" and d["barcode"] == row["code"] and d["flags"] == "Salt is very high for its category."
    assert d["link"] == "https://world.openfoodfacts.org/product/" + row["code"]
    assert "Energy:" in d["values"] and "e+" not in d["values"] and "000000" not in d["values"]
    assert set(d) == {"card", "name", "brand", "barcode", "pack_size", "serving_size", "basis", "flags", "values", "link", "nutrition_photo", "nutrition_photo_small", "front_photo", "photo_languages"}
    assert t["meta"]["set"] == "practice_1"                                   # the set name is metadata; no contributor field exists in a task


def cand(row, families):
    return {"row": row, "families": families}


def test_selection_is_deterministic_capped_and_never_repeats_a_product():
    rows = real_rows(12)
    for i, r in enumerate(rows):
        r["code"] = f"{i:013d}"                                              # distinct codes; the other fields stay real
    fams = ["value-very-high-for-category-salt"] * 8 + ["value-under-0-01-g-salt"] * 4
    cands = sorted((cand(r, [f]) for r, f in zip(rows, fams)), key=lambda c: hashlib.md5(c["row"]["code"].encode()).hexdigest())
    photos = lambda code: {"nutrition_full": "u", "nutrition_400": "u", "front": None}      # noqa: E731
    a = cl.select(cands, photos, 6, 3)
    b = cl.select(cands, photos, 6, 3)
    assert [c["row"]["code"] for c in a] == [c["row"]["code"] for c in b]
    assert [c["families"][0] for c in a].count("value-very-high-for-category-salt") == 3     # the cap holds
    assert len({c["row"]["code"] for c in a}) == len(a) == 6


def test_a_taken_product_and_a_product_without_a_photo_are_skipped_and_taken_is_extended():
    rows = real_rows(4)
    for i, r in enumerate(rows):
        r["code"] = f"{i:013d}"
    cands = [cand(r, ["3-or-more-values-are-identical"]) for r in rows]
    taken = {rows[0]["code"]}
    ok = lambda code: None if code == rows[1]["code"] else {"nutrition_full": "u", "nutrition_400": "u", "front": None}      # noqa: E731
    got = cl.select(cands, ok, 5, 9, taken)
    assert [c["row"]["code"] for c in got] == [rows[2]["code"], rows[3]["code"]]
    assert rows[2]["code"] in taken and rows[3]["code"] in taken


def test_a_record_a_rule_decides_or_with_no_basis_is_not_usable():
    row = real_rows(1)[0]
    row["nutrition_per"] = "100g"
    assert cl.usable_record(row) and cl.rule_violations(row) == []
    over = {**row, "fat": 667.0}                                           # one field of a real record changed: fat over 105 g per 100 g
    assert "value-over-105" in cl.rule_violations(over) and not cl.usable_record(over)
    assert not cl.usable_record({**row, "nutrition_per": None})            # no basis recorded




def test_the_card_is_one_header_line_per_fact_and_every_field_the_screen_uses_exists():
    import re
    row = real_rows(1)[0]
    t = cl.make_task(row, ["value-very-high-for-category-salt"], cl.photo_urls(OFF["4070765054392"]), "practice_1", 1)
    lines = cl.card_lines(t["data"])
    assert len(lines) == len(cl.INFO_KEYS) + len(cl.VALUE_ROWS) + len(cl.CALC_KEYS)                  # the same lines on every card
    assert lines["l_barcode"] == "Barcode: " + row["code"] and lines["v_energy_kj"].startswith("Energy: ") and " kJ" in lines["v_energy_kj"] and " kcal" in lines["v_energy_kcal"]
    assert all(not re.search(r"<[a-zA-Z/]", v) and "\n" not in v for v in lines.values())            # no markup (a '<' sign in the words is fine)
    cfg = (HERE.parent / "labelling" / "project_config.xml").read_text(encoding="utf-8")
    fields = set(re.findall(r"[$]([a-z_0-9]+)", cfg))
    on_card = set(t["data"]) | set(lines) | set(cl.glossary_lines(t["data"]))
    assert fields <= on_card, fields - on_card                                                   # every $field of the screen is on the card
    assert not re.search(r"<(HyperText|Table|Text)\b|color", cfg)                              # only tags Label Studio themes itself (Header, Image, Choices, TextArea)


def test_the_calculation_lines_are_plain_arithmetic_and_never_a_verdict():
    import re
    data = {"name": "x", "brand": "y", "barcode": "1", "pack_size": "1 kg", "serving_size": "30 g", "basis": "per 100 g, as sold",
            "values": "Energy: 362 kcal\nFat: 1.1 g\nSaturated fat: 0.23 g\nSalt: 0.005 g\nSodium: 0.002 g\nAdded sugars: 0 g"}
    lines = cl.card_lines(data)
    assert lines["v_fat"] == "Fat: 1.1 g   (pack agrees if 0.99 to 1.21 g; per 1 g: 0.011 g; per 30 g serving: 0.33 g)"           # 1.1 +- 10%
    assert lines["v_saturated_fat"].startswith("Saturated fat: 0.23 g   (pack agrees if 0.207 to 0.253 g; per 1 g: 0.0023 g; per 30 g serving: 0.069 g)")
    assert lines["v_salt"].startswith("Salt: 0.005 g = 5 mg") and lines["v_sodium"].startswith("Sodium: 0.002 g = 2 mg") and "per 30 g serving: 0.0006 g = 0.6 mg" in lines["v_sodium"]              # g to mg (F7), serving (F1 reversed)
    assert "pack agrees if it says 0, a trace or a '<' value" in lines["v_added_sugars"]
    assert lines["c_kj_from_kcal"] == "kJ from the kcal figure (4.184 x kcal): 1515 kJ"
    assert cl.window(0.2) == "0.1 to 0.3" and cl.window(28) == "25.2 to 30.8"                                  # one step of the last digit beats 10% for small numbers
    assert (cl._sig(0.0006), cl._sig(111.4), cl._sig(1535.0)) == ("0.0006", "111", "1535")
    assert not any(re.search(r"\b(error|differs|wrong|fails?|violat|ok|passes)\b", v, re.I) for v in lines.values())   # no verdict on any line
    no_serving = cl.card_lines({**data, "serving_size": "not recorded"})
    assert "serving:" not in no_serving["v_fat"] and no_serving["v_fat"].startswith("Fat: 1.1 g   (pack agrees if")



OCR = json.loads((HERE / "fixtures" / "off_ocr_languages_real.json").read_text(encoding="utf-8"))          # OFF's own text scan of four real nutrition photos (page languages only)


def test_the_languages_come_from_the_text_scan_of_the_photo_not_from_the_tag():
    pl_de = cl.ocr_languages(OCR["4070765054392"])                       # a real German and Polish pack that OFF tags as English
    assert [c for c, _ in pl_de[:3]] == ["pl", "de", "en"] and OCR["4070765054392"]["tag"] == "en"
    assert cl.printed_languages(pl_de) == ["pl", "de", "en"] and cl.readable(pl_de)
    en = cl.ocr_languages(OCR["8906002000876"])
    assert cl.printed_languages(en) == ["en"] and cl.readable(en)
    assert cl.ocr_languages({}) == [] and cl.ocr_languages({"responses": [{}]}) == [] and not cl.readable([])


def test_a_photo_whose_languages_have_no_word_list_is_not_kept():
    lemkuchen = cl.ocr_languages(OCR["4069366061434"])                  # the scan named hu, sk, sl (no list): the pack prints de, fr, it too, but the scan did not find them
    assert lemkuchen[0][0] == "hu" and not cl.readable(lemkuchen)
    assert cl.readable([("fr", 0.3)]) and not cl.readable([("fr", 0.2), ("hu", 0.6)])      # 25% needed for a listed language
    assert cl.printed_languages([("fr", 0.69), ("en", 0.25), ("da", 0.1), ("lb", 0.1)]) == ["fr", "en", "da"] and cl.printed_languages([("fr", 0.05)]) == []


def test_the_word_lists_are_complete_and_the_lines_follow_the_languages_found():
    assert set(cl.GLOSSARY) | {"en"} == set(cl.GLOSSARY_NAMES)
    assert all(len(words) == len(cl.GLOSSARY_TERMS) == len(cl.GLOSSARY_LABELS) for words in cl.GLOSSARY.values())
    fr = cl.glossary_lines({"photo_languages": ["fr", "en"]})
    assert fr["g_title"].endswith("French, English") and fr["g_carbs"] == "glucides = Carbohydrates" and fr["g_salt"] == "sel = Salt"
    assert fr["g_note"].endswith("English is printed as well.") and fr["g_serving"] == "par portion = Per serving"
    two = cl.glossary_lines({"photo_languages": ["pl", "de", "en"]})
    assert two["g_salt"] == "sól / Salz = Salt" and two["g_fibre"] == "błonnik / Ballaststoffe = Fibre"
    only_en = cl.glossary_lines({"photo_languages": ["en"]})
    assert only_en["g_note"] == "English: no translation needed." and only_en["g_salt"] == "salt = Salt"
    assert set(cl.glossary_lines({})) == set(fr) and cl.glossary_lines({})["g_note"].startswith("No listed language")
    assert cl.GLOSSARY_KEYS == tuple(f"g_{x}" for x in cl.GLOSSARY_TERMS)


def test_a_task_carries_the_languages_found_on_its_photo():
    row = real_rows(1)[0]
    photos = {**cl.photo_urls(OFF["4070765054392"]), "ocr": [["pl", 0.35], ["de", 0.34], ["en", 0.18], ["da", 0.06]]}
    t = cl.make_task(row, ["value-very-high-for-category-salt"], photos, "practice_1", 1)
    assert t["data"]["photo_languages"] == ["pl", "de", "en"] and t["meta"]["ocr_languages"][0] == ["pl", 0.35]
    assert cl.make_task(row, ["3-or-more-values-are-identical"], cl.photo_urls(OFF["4070765054392"]), "practice_1", 2)["data"]["photo_languages"] == []


def test_each_mg_figure_sits_beside_the_gram_figure_it_converts_and_per_one_gram_times_the_serving_is_the_serving_value():
    import re
    data = {"name": "x", "brand": "y", "barcode": "1", "pack_size": "1 kg", "serving_size": "40 g", "basis": "per 100 g, as sold",
            "values": "Energy: 432.5 kJ\nEnergy: 112.5 kcal\nProtein: 17.5 g\nSalt: 3.5 g\nSodium: 1.4 g"}       # the real pollock roe record: pack says 560 mg sodium per 40 g piece
    lines = cl.card_lines(data)
    assert lines["v_sodium"] == "Sodium: 1.4 g = 1400 mg   (pack agrees if 1.26 to 1.54 g; per 1 g: 0.014 g; per 40 g serving: 0.56 g = 560 mg)"
    for key in ("salt", "sodium"):
        grams = [float(x) for x in re.findall(r"([0-9.]+) g(?: = ([0-9.]+) mg)?", lines[f"v_{key}"]) for x in x[:1]]
        pairs = re.findall(r"([0-9.]+) g = ([0-9.]+) mg", lines[f"v_{key}"])
        assert len(pairs) == 2 and all(abs(float(g) * 1000 - float(mg)) < 1e-9 for g, mg in pairs) and grams
    for key in ("energy_kj", "energy_kcal", "proteins"):                      # per 1 g x serving size = the per-serving figure
        per1 = float(re.search(r"per 1 g: ([0-9.]+)", lines[f"v_{key}"]).group(1))
        per_serving = float(re.search(r"serving: ([0-9.]+)", lines[f"v_{key}"]).group(1))
        assert abs(per1 * 40 - per_serving) / per_serving < 0.01
    millilitre = cl.card_lines({**data, "basis": "per 100 ml, as sold", "serving_size": "not recorded"})
    assert "per 1 ml:" in millilitre["v_proteins"] and "serving:" not in millilitre["v_proteins"]
