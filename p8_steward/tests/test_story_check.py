"""The story facts, the checker and the code-planned story (item 15), on the real daily aggregates of 2026-10-01 to 2026-10-23 (counts only, p8_steward/tests/fixtures).
Every rule of the checker is shown to go red on a planted violation and green on a good story; the planned story is shown to pass the checker on every day and scope we hold."""
import copy
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
import story_check as sc  # noqa: E402
import story_facts as sf  # noqa: E402
import story_lib as sl  # noqa: E402
import story_plan as sp  # noqa: E402

FIX = HERE / "fixtures"
DAYS = sl.load_days(FIX / "signal_days.csv")
DRIFT = sl.drift_events(FIX / "drift_events.csv")
QUALITY = sf.load_quality(FIX / "quality_days.csv")


def req(day, scope):
    return sf.build_request(DAYS, DRIFT, day, scope, QUALITY)


def fact(r, column):
    return next(f for f in r["facts"] if f["column"] == column)


def derived(r, kind):
    return next(d for d in r["derived"] if d["derived"] == kind)


def s(text, typ, *cites):
    return {"text": text, "type": typ, "cites": list(cites)}


def texts(r):
    return " ".join(x["text"] for x in sp.plan(r))


# ---- the facts ------------------------------------------------------------------------------------------------------------------------------

def test_the_facts_come_from_the_real_data():
    assert len(sf.story_days(DAYS)) == 18
    r = req("2026-10-17", "india")
    assert r["events"] == ["P1", "F5", "F4", "F1"]
    f1 = fact(r, "any_products")
    assert (f1["value"], f1["usual"], f1["times_usual"], f1["direction"], f1["days_in_a_row"]) == ("271", "22", "12.3", "up", "1")
    assert f1["rank_phrase"] == "the largest of the 17 days held so far"
    assert fact(req("2026-10-18", "india"), "any_products")["days_in_a_row"] == "2"
    assert req("2026-10-07", "all")["events"] == [] and req("2026-10-07", "all")["patterns"] == []
    p3 = req("2026-10-16", "all")["patterns"][0]
    assert (p3["id"], p3["label"], p3["dropped_per_100"], p3["must_state"]) == ("P3", "traces tags", "10.41", ["10.41", "0.29", "3.41"])
    assert req("2026-10-06", "all")["patterns"][0]["fields_with_a_jump"] == "8"
    assert req("2026-10-17", "india")["date_words"] == "17 October"


def test_the_usual_level_leaves_out_the_days_of_an_earlier_burst():
    plain_window = 39.5                                      # the median of India's 14 days before 23 October, burst days included
    assert float(fact(req("2026-10-23", "india"), "any_products")["usual"].replace(",", "")) < plain_window - 5
    assert fact(req("2026-10-15", "india"), "any_products")["direction"] == "up_slight"      # 38 against 24 is no longer 'about the usual'


def test_the_derived_facts_are_exact_identities_on_the_real_data():
    bridge = derived(req("2026-10-23", "all"), "flag_bridge")
    assert bridge["identity"] == "44,445 = 44,426 + 1,157 - 1,138" and bridge["conclusion"] == "rise_from_newly_seen_products" and bridge["carried_share"] == "97.5%"
    assert "Open flags rose by 44,445" in bridge["statement"] and bridge["sign"] == "up"
    split = derived(req("2026-10-17", "india"), "new_and_existing")
    assert split["identity"] == "271 = 10 + 261" and split["existing_pct"] == "96%"
    rest = derived(req("2026-10-06", "all"), "india_and_rest")
    assert rest["identity"] == "1,645 = 22 + 1,623" and rest["conclusion"] == "outside_india"
    assert "india_and_rest" not in {d["derived"] for d in req("2026-10-17", "india")["derived"]}
    part = derived(req("2026-10-23", "all"), "part_of_whole")
    assert [(p["label"], p["india"], p["all"], p["pct"]) for p in part["parts"]] == [("nutrition changes", "320", "694", "46%"), ("ingredients changes", "210", "370", "57%")] and part["base_pct"] == "20%"
    contrast = derived(req("2026-10-23", "all"), "rest_contrast")
    assert {e["label"]: e["kind"] for e in contrast["entries"]} == {"nutrition changes": "all_in_india", "ingredients changes": "part_not_all"}
    for scope in ("all", "india"):                      # every flag bridge in the data adds up
        for day in sf.story_days(DAYS):
            for d in req(day, scope)["derived"]:
                if d["derived"] == "flag_bridge":
                    left, right = d["identity"].split(" = ")
                    a, b, c = (float(x.replace(",", "")) for x in right.replace(" - ", " + ").split(" + "))
                    assert float(left.replace(",", "")) == a + b - c, (day, scope)


# ---- the checker ----------------------------------------------------------------------------------------------------------------------------

def good(name):
    """Hand-written model-style stories on four real days, in the form the narrator returns them."""
    if name == "burst":
        r = req("2026-10-17", "india")
        f1, f4, f5 = fact(r, "any_products"), fact(r, "nutrition_products"), fact(r, "ingredients_products")
        return r, [
            s(f"On 17 October, India had {f1['value']} products with at least one change, {f1['times_usual']} times the usual {f1['usual']}.", "fact", f1["id"]),
            s("This is consistent with a burst of edits concentrated in India.", "pattern", "P1"),
            s(f"In India there were {f4['value']} products with a nutrition change and {f5['value']} products with an ingredients change, up from a usual {f4['usual']} and {f5['usual']}.", "fact", f4["id"], f5["id"]),
            s("The rise in products with a nutrition change and in products with an ingredients change in India is not explained by any known pattern.", "unexplained", f4["id"], f5["id"])]
    if name == "quiet":
        r = req("2026-10-07", "all")
        f1 = fact(r, "any_products")
        return r, [s(f"On 7 October, there were {f1['value']} products with at least one change, in line with the usual {f1['usual']}.", "fact", f1["id"])]
    if name == "tags":
        r = req("2026-10-16", "all")
        f1 = fact(r, "any_products")
        return r, [s(f"On 16 October, there were {f1['value']} products with at least one change, in line with the usual {f1['usual']}.", "fact", f1["id"]),
                   s("The traces tags were dropped for 10.41 of every 100 products, against a usual 0.29-3.41, consistent with a formatting problem in that day's file.", "pattern", "P3")]
    r = req("2026-10-06", "all")
    f1, d = fact(r, "any_products"), derived(r, "india_and_rest")
    return r, [s(f"On 6 October, there were {f1['value']} products with at least one change, a little higher than the usual {f1['usual']}.", "fact", f1["id"]),
               s(f"Outside India, {d['rest_value']} products changed while India had {d['india_value']}, which means the increase is outside India.", "derived", d["id"]),
               s("8 fields were filled more often than usual in that day's file, consistent with a batch of products added with unusually complete entries.", "pattern", "P2")]


def codes(name, mutate=None, strict=False):
    r, sentences = good(name)
    sentences = copy.deepcopy(sentences)
    if mutate:
        sentences = mutate(sentences, r)
    return {c for c, _ in sc.check({"sentences": sentences}, r, strict=strict)}


def test_good_stories_pass_every_rule_strictly():
    for name in ("burst", "quiet", "coverage"):
        r, ss = good(name)
        assert codes(name, strict=True) == set(), (name, sc.check({"sentences": ss}, r, strict=True))
    assert codes("tags") == set()                         # on this day a clear change in nutrition changes is not told, which only the strict check requires


def test_every_rule_goes_red_on_a_planted_violation():
    def text(i, new):
        def f(ss, r):
            ss[i]["text"] = new
            return ss
        return f

    def meta(i, **kw):
        def f(ss, r):
            ss[i].update(kw)
            return ss
        return f

    assert sc.check(None, req("2026-10-07", "all"))[0][0] == "R1" and sc.check({"sentences": []}, req("2026-10-07", "all"))[0][0] == "R1"
    assert "R1" in codes("quiet", meta(0, type="story"))
    assert "R2" in codes("quiet", meta(0, cites=["F99"])) and "R2" in codes("quiet", meta(0, cites=[])) and "R2" in codes("quiet", meta(0, type="derived"))
    assert "R3" in codes("quiet", text(0, "On 7 October, there were 1,268 products with at least one change."))
    assert "R3" in codes("quiet", text(0, "On 7 October, two products with at least one change."))
    assert "R4" in codes("burst", text(0, "On 17 October, India had 271 products with at least one change, down from the usual 22."))
    assert "R4" in codes("burst", text(0, "On 17 October, India had the highest count of products with at least one change, 271."))
    assert "R4" in codes("quiet", text(0, "On 7 October, there were 1,267 products with at least one change, unusually close to the usual 1,264."))
    assert "R4" in codes("burst", text(0, "On 17 October, India had 271 products with at least one change, far above the usual 22."))
    assert "R4" in codes("coverage", text(0, "On 6 October, there were 1,645 products with at least one change, in line with the usual 1,224."))
    assert "R5" in codes("burst", text(0, "On 17 October, India had 271 products with at least one change because of a bulk upload."))
    assert "R6" in codes("burst", text(1, "This is consistent with a bulk upload."))
    assert "R6" in codes("quiet", text(0, "On 7 October, there were 1,267 products with at least one change, probably a normal day."))
    assert "R7" in codes("quiet", text(0, "On 7 October, there were 1,267 products with at least one change, and the page should be checked."))
    assert "R8" in codes("burst", text(3, "The rise in India is a mystery."), strict=True)
    assert "R8" in codes("burst", text(3, "This change is not explained by any known pattern."), strict=True)
    assert "R9" in codes("quiet", text(0, "On 7 October, there were 1,267 any_products changes."))
    assert "R9" in codes("quiet", text(0, "On 7 October, there were 1,267 products with at least one change, including Kinder bars."))
    assert "R10" in codes("quiet", text(0, "On 7 October, there were **1,267** products with at least one change."))
    assert "R10" in codes("quiet", text(0, "On 7 October, there were 1,267 products with at least one change é in line with the usual 1,264."))
    assert "R11" in codes("quiet", text(0, "On 7 October, we saw 1,267 products with at least one change."))
    assert "R11" in codes("quiet", text(0, "On 7 October, the data was correct for 1,267 products with at least one change."))
    assert "R11" in codes("quiet", text(0, "On 7 October, there were 1,267 products with at least one change, in line with the usual 1,264"))
    assert "R12" in codes("burst", lambda ss, r: ss[:2], strict=True)
    assert "R12" in codes("coverage", lambda ss, r: [ss[0], ss[1]])
    assert "R12" in codes("tags", lambda ss, r: ss[:1])
    assert "R13" in codes("burst", text(0, "On 17 October, there were 271 products with at least one change, 12.3 times the usual 22."))
    assert "R13" in codes("quiet", text(0, "There were 1,267 products with at least one change, in line with the usual 1,264."))
    assert "R13" in codes("tags", text(1, "The traces tags were dropped for 10.41 of every 100 products, consistent with a formatting problem in that day's file."))
    assert "R14" in codes("coverage", meta(1, cites=["D2", "D1"]))
    assert "R15" in codes("quiet", text(0, "On 7 October, India had 1,267 products with at least one change."))
    assert "R16" in codes("coverage", lambda ss, r: [ss[0], s("This means that the increase is outside India.", "derived", "D2"), ss[2]])
    assert "R17" in codes("coverage", lambda ss, r: [ss[0], s("Outside India, 1,623 products changed and India had 22.", "derived", "D2"), ss[2]])
    assert "R18" in codes("quiet", text(0, "On 7 October, there were 1,267 products with at least one change, although it was the usual 1,264."))
    assert "R18" in codes("burst", text(0, "On 17 October, about the usual number of products changed in India (271), but the mix was different."))
    assert "R18" in codes("quiet", text(0, "On 7 October, India had 1,267 products with at least one change, when it usually has 1,264."))
    assert "R18" in codes("quiet", lambda ss, r: ss + [s("Nutrition changes (1,267, against 1,264) were also higher than usual.", "fact", "F1")])
    assert "R19" in codes("quiet", lambda ss, r: ss + [s("Nutrition changes (1,267, against 1,264) were higher than usual.", "fact", "F1")])
    assert "R19" in codes("tags", lambda ss, r: [s("On 16 October, about the usual number of products changed (1,362), but the mix was different.", "fact", "F1"), ss[1]])


def test_the_rendered_story_ends_with_the_code_written_caveats_and_the_label():
    r, ss = good("quiet")
    out = sc.render({"sentences": ss}, r)
    assert out.startswith("On 7 October") and "Only complete days are used" in out and out.endswith(sf.FOOTER)


# ---- the code-planned story -----------------------------------------------------------------------------------------------------------------

GOLDEN = {
    ("2026-10-17", "india"): ("On 17 October, 271 products changed in India, 12.3 times the usual 22, and the largest of the 17 days held so far. This is consistent with a burst of edits concentrated in India. "
                              "Almost all of them (261 of 271) were existing products that were edited, and 91% had a nutrition change, against a usual 50%. "
                              "Ingredients changes (116, against 4.5) were also higher than usual. The number of new products stayed about the usual."),
    ("2026-10-23", "all"): ("On 23 October, about the usual number of products changed (1,785), but the mix was different. India had 20.1% of the changes, when it usually has 2.7%. "
                            "Outside India, 1,427 products changed, about the usual number. India made up 46% of the nutrition changes and 57% of the ingredients changes, although it had only 20% of all changed products. "
                            "Outside India, nutrition changes (374, against 324) were about the usual, so the rise is in India. "
                            "Outside India, ingredients changes (160, against 43) were also higher than usual, so India explains part of the rise, not all of it. "
                            "Open flags went up by 44,445. Almost all of that comes from products seen for the first time that arrived already flagged."),
    ("2026-10-12", "all"): ("On 12 October, about the usual number of products changed (1,331), but nutrition changes (217, against 129) were higher than usual. "
                            "Open flags went up by 44,288. Almost all of that comes from products seen for the first time that arrived already flagged."),
    ("2026-10-16", "all"): ("On 16 October, about the usual number of products changed (1,362), but the mix was different. "
                            "Of them, 475 were existing products that were edited, a little more than the usual 376, and 7.5% had an ingredients change, against a usual 3.2%. "
                            "The traces tags were dropped for 10.41 of every 100 products, against a usual 0.29-3.41, consistent with a formatting problem in that day's file. "
                            "Nutrition changes (276, against 131) were also higher than usual. Open flags went up by 40,984. Almost all of that comes from products seen for the first time that arrived already flagged."),
    ("2026-10-21", "india"): ("On 21 October, 772 products changed in India, 32.2 times the usual 24, and the largest of the 21 days held so far. This is consistent with a burst of edits concentrated in India. "
                              "Nutrition changes (751, against 11.5) and ingredients changes (300, against 5) were also higher than usual."),
}


def test_the_planned_stories_match_the_approved_style_word_for_word():
    for (day, scope), expected in GOLDEN.items():
        assert texts(req(day, scope)) == expected, (day, scope, texts(req(day, scope)))


def test_the_planned_story_passes_the_checker_on_every_day_and_scope_we_hold():
    for day in sf.story_days(DAYS):
        for scope in ("all", "india"):
            r = req(day, scope)
            ss = sp.plan(r)
            assert ss and sc.check({"sentences": ss}, r) == [], (day, scope, sc.check({"sentences": ss}, r))
            assert sp.plan(r) == ss                                    # the same facts always give the same story


def test_a_connecting_word_is_only_written_when_the_numbers_show_the_relation():
    for day in sf.story_days(DAYS):
        for scope in ("all", "india"):
            r = req(day, scope)
            out = texts(r)
            by = {d["derived"]: d for d in r["derived"]}
            if "although" in out:
                assert "part_of_whole" in by
            if "but the mix was different" in out:
                assert fact(r, "any_products")["direction"] == "usual"
            if "so the rise is in India" in out:
                assert any(e["kind"] == "all_in_india" for e in by["rest_contrast"]["entries"])
            if "not all of it" in out:
                assert any(e["kind"] == "part_not_all" for e in by["rest_contrast"]["entries"])
            if "when it usually has" in out:
                assert fact(r, "india_share")["direction"] in ("up", "down")


def test_a_change_of_the_facts_changes_the_story():
    flat = copy.deepcopy(DAYS)
    for day in [d for d in flat["india"] if d >= "2026-10-17"]:          # the real burst flattened to the level of the day before it
        flat["india"][day] = dict(flat["india"]["2026-10-16"])
        flat["all"][day]["india_share"] = flat["india"][day]["any_products"] / flat["all"][day]["any_products"]
    r = sf.build_request(flat, DRIFT, "2026-10-17", "india", QUALITY)
    assert "burst" not in " ".join(x["text"] for x in sp.plan(r)) and "burst" in texts(req("2026-10-17", "india"))
