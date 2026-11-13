"""Tests for one night of the photo-reading job (nightly/night.py) with fake readers: every outcome, the cheap-first order, the stops, the retry queue across nights."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "bootstrap"))
import photo_method as pm  # noqa: E402
from nightly import line_record as lr  # noqa: E402
from nightly import night as nt  # noqa: E402
from nightly import queue_lib as ql  # noqa: E402
from nightly.budget import Budget, Stop, TransientError  # noqa: E402

TEXT = "Nutrition facts per 100 g Energy 376 kJ / 90 kcal Fat 0.5 g Saturates 0.3 g Carbohydrate 8.9 g Sugars 6.5 g Protein 12.4 g Salt 0.06 g"
VALUES = {"energy_kcal": 90, "energy_kj": 376, "fat": 0.5, "saturated_fat": 0.3, "carbohydrates": 8.9, "sugars": 6.5, "proteins": 12.4, "salt": 0.06}
STORED = {"energy_kcal": 90.0, "energy_kj": 376.0, "fat": 0.5, "saturated_fat": 0.3, "carbohydrates": 8.9, "sugars": 6.5, "proteins": 12.4, "salt": 0.06}
NIGHT = "2026-11-13"


def entry(values, model=pm.MODEL, basis="per 100 g"):
    return {"reading": {"basis": basis, "serving_size": None, "values_per_100": dict(values)}, "model": model}


def product(text=TEXT, text_v=VALUES, photo_v=VALUES, has_photo=True, stored=STORED):
    return {"fetch": {"has_photo": has_photo, "ocr_text": text, "photo": b"jpg" if has_photo else None},
            "text": entry(text_v) if isinstance(text_v, dict) else text_v, "photo": entry(photo_v) if isinstance(photo_v, dict) else photo_v, "stored": stored}


class Fake:
    """Scripted readers: p maps code -> product(); a value that is an Exception is raised; every call is logged."""

    def __init__(self, p):
        self.p, self.log, self.priors = p, [], []

    def _get(self, kind, code):
        self.log.append((kind, code))
        v = self.p[code][kind]
        if isinstance(v, list):                                          # a script: one answer per request
            v = v.pop(0)
        if isinstance(v, Exception):
            raise v
        return v

    def fetch(self, code):
        return self._get("fetch", code)

    def text_reader(self, code, text, prior=None):
        self.priors.append(prior)
        return self._get("text", code)

    def photo_reader(self, code, photo):
        return self._get("photo", code)

    def count(self, kind):
        return sum(1 for k, _ in self.log if k == kind)


def budget(**kw):
    return Budget(sleep=lambda s: None, **kw)


def cand(code, stored=STORED, new=False):
    return {"code": code, "stored": stored, "new": new}


def one(p, **kw):
    return nt.process_product(cand("10000001", p["stored"]), Fake({"10000001": p}), budget(), NIGHT, **kw)


# ---------------------------------------------------------------- one product
def test_agreeing_readings_on_a_clean_record_give_a_checked_line_for_two_calls():
    r = one(product())
    assert r["outcome"] == "line" and r["calls"] == 2 and r["line"]["statement"] == "checked" and r["line"]["line_type"] == "match" and lr.validate_line(r["line"]) == []
    assert r["line"]["record_hash"] == lr.record_hash(STORED)


def test_a_stored_record_that_breaks_a_rule_and_a_photo_that_fixes_it_gives_a_repaired_line():
    bad = {**STORED, "fat": 0.1, "saturated_fat": 3.0}                    # saturated fat above fat
    r = one(product(stored=bad))
    assert r["outcome"] == "line" and r["line"]["statement"] == "repaired" and r["line"]["line_type"] == "differ"


def test_a_stale_stored_value_the_line_does_not_replace_gives_a_bound_statement_with_no_text():
    bad = {**STORED, "saturated_fat": 5.0}
    values = {k: v for k, v in VALUES.items() if k != "saturated_fat"}
    text = "Nutrition facts per 100 g Energy 376 kJ / 90 kcal Fat 0.5 g Carbohydrate 8.9 g Sugars 6.5 g Protein 12.4 g Salt 0.06 g"
    r = one(product(text=text, text_v=values, photo_v=values, stored=bad))
    ln = r["line"]
    assert r["outcome"] == "line" and ln["statement"] == "bound" and ln["bounds"][0]["stale_field"] == "saturated_fat" and "text" not in ln["bounds"][0]
    assert lr.validate_line(ln) == []


def test_a_rule_still_broken_after_the_repair_with_no_hard_law_is_an_open_statement():
    bad = {**STORED, "energy_kcal": 300.0, "energy_kj": 1255.0}
    values = {k: v for k, v in VALUES.items() if k not in ("energy_kcal", "energy_kj")}
    text = "Nutrition facts per 100 g Fat 0.5 g Saturates 0.3 g Carbohydrate 8.9 g Sugars 6.5 g Protein 12.4 g Salt 0.06 g"
    r = one(product(text=text, text_v=values, photo_v=values, stored=bad))
    assert r["outcome"] == "line" and r["line"]["statement"] in ("open", "bound", "repaired")


def test_guard_v2_only_adds_to_a_shown_line_the_original_guard_drops_a_value_the_ocr_misprints():
    text = "Nutrition facts per 100 g Energy 376 kJ / 90 kcal Fat 7,79 Saturates 0.3 g Carbohydrate 8.9 g Sugars 6.5 g Protein 12.4 g Salt 0.06 g"
    values = {**VALUES, "fat": 7.7}
    r = one(product(text=text, text_v=values, photo_v=values))
    assert r["outcome"] == "line" and r["line"]["values"]["fat"] == 7.7


def test_no_photo_no_table_and_an_unusable_text_reading_are_silences_and_save_quota():
    f = Fake({"10000001": product(has_photo=False)})
    r = nt.process_product(cand("10000001"), f, budget(), NIGHT)
    assert (r["outcome"], r["reason"], r["calls"]) == ("silence", "no_photo", 0) and f.count("text") == 0
    f = Fake({"10000001": product(text="no table here")})
    r = nt.process_product(cand("10000001"), f, budget(), NIGHT)
    assert (r["reason"], r["calls"]) == ("no_ocr_table", 0) and f.count("text") == 0
    f = Fake({"10000001": product(text_v={"energy_kcal": 90})})
    r = nt.process_product(cand("10000001"), f, budget(), NIGHT)
    assert (r["reason"], r["calls"]) == ("text_unusable", 1) and f.count("photo") == 0            # the photo reader is never called


def test_disagreeing_readings_are_silence_never_the_text_reading():
    r = one(product(photo_v={**VALUES, "fat": 5.0, "carbohydrates": 89.0, "proteins": 1.0}))
    assert (r["outcome"], r["reason"], r["line"], r["calls"]) == ("silence", "no_agreement", None, 2)


def test_a_transient_error_is_an_error_not_a_silence_and_any_other_failure_is_too():
    r = one(product(photo_v=TransientError("503")))
    assert (r["outcome"], r["reason"]) == ("error", "unavailable")
    r = one(product(photo_v=KeyError("boom")))
    assert (r["outcome"], r["reason"]) == ("error", "unexpected:KeyError")


def test_a_wrong_model_name_ends_the_whole_night_it_is_not_a_per_product_failure():
    p = product()
    p["photo"] = entry(VALUES, model="gemini-other")
    with pytest.raises(Stop) as e:
        one(p)
    assert e.value.reason == "model_mismatch"
    p["photo"] = {"reading": entry(VALUES)["reading"]}                    # no model named at all
    with pytest.raises(Stop):
        one(p)


def test_a_run_of_transient_errors_stops_the_night_through_the_budget():
    f = Fake({f"1000000{i}": product(text_v=TransientError("503")) for i in range(6)})            # the service is down for both readers
    b = budget(max_503_streak=3)
    with pytest.raises(Stop) as e:
        for i in range(6):
            nt.process_product(cand(f"1000000{i}"), f, b, NIGHT)
    assert e.value.reason == "503_streak"


def unusable(model=pm.MODEL):
    return {"reading": None, "answer": "{cut off", "model": model}


def test_an_unusable_text_reply_gets_exactly_one_retry_that_sees_the_first_reply():
    f = Fake({"10000001": product(text_v=[unusable(), entry(VALUES)])})
    r = nt.process_product(cand("10000001"), f, budget(), NIGHT)
    assert r["outcome"] == "line" and r["calls"] == 3 and f.priors[0] is None and f.priors[1]["answer"] == "{cut off"


def test_a_second_unusable_text_reply_is_silence_and_the_photo_reader_is_never_called():
    f = Fake({"10000001": product(text_v=[unusable(), unusable()])})
    r = nt.process_product(cand("10000001"), f, budget(), NIGHT)
    assert (r["outcome"], r["reason"], r["calls"]) == ("silence", "text_unusable", 2) and f.count("photo") == 0


def test_an_unusable_photo_reply_gets_one_retry_and_a_second_failure_is_photo_unusable():
    f = Fake({"10000001": product(photo_v=[unusable(), entry(VALUES)])})
    assert nt.process_product(cand("10000001"), f, budget(), NIGHT)["calls"] == 3
    f = Fake({"10000001": product(photo_v=[unusable(), unusable()])})
    r = nt.process_product(cand("10000001"), f, budget(), NIGHT)
    assert (r["outcome"], r["reason"], r["calls"]) == ("silence", "photo_unusable", 3)


def test_a_retry_is_a_counted_request_and_the_ceiling_can_stop_it():
    f = Fake({"10000001": product(text_v=[unusable(), entry(VALUES)])})
    with pytest.raises(Stop) as e:
        nt.process_product(cand("10000001"), f, budget(max_calls=1), NIGHT)
    assert e.value.reason == "call_ceiling" and f.count("text") == 1


# ---------------------------------------------------------------- one night
def canary_rows(n=3):
    return [{"code": f"2000000{i}", "stored": STORED, "expected": dict(VALUES)} for i in range(n)]


def readers_for(codes, extra=None, **kw):
    p = {f"2000000{i}": product() for i in range(3)}
    p.update({c: product(**kw) for c in codes})
    p.update(extra or {})
    return Fake(p)


def night(state, cands, f, b=None, rows=None, freeze=lambda: []):
    return nt.run_night(state, cands, f, b or budget(), NIGHT, canary_rows() if rows is None else rows, freeze_problems=freeze)


def test_a_full_night_reads_the_canary_then_the_queue_and_settles_every_product():
    codes = ["30000001", "30000002", "30000003"]
    f = readers_for(codes, {"30000002": product(has_photo=False), "30000003": product(photo_v=TransientError("503"))})
    s = ql.new_state()
    out = night(s, [cand(c) for c in codes], f)
    assert out["stopped"] is None and out["canary"]["passed"] and len(out["lines"]) == 1 and out["silences"] == {"no_photo": 1} and out["errors"] == {"unavailable": 1}
    assert s["items"]["30000003"]["attempts"] == 1 and set(s["done"]) == {"30000001", "30000002"} and out["calls"] == 6 + 2 + 0 + 2
    assert [k for k, c in f.log if k == "fetch"][:3] == ["fetch"] * 3 and f.log[0] == ("fetch", "20000000")           # the canary is read first


def test_a_missed_product_is_retried_on_a_later_night_and_a_done_product_is_not_read_again():
    s = ql.new_state()
    f = readers_for(["30000001", "30000002"], {"30000002": product(photo_v=TransientError("503"))})
    night(s, [cand("30000001"), cand("30000002")], f)
    f2 = readers_for(["30000001", "30000002"])
    out = nt.run_night(s, [cand("30000001"), cand("30000002")], f2, budget(), "2026-11-14", canary_rows(), freeze_problems=lambda: [])
    assert [ln["code"] for ln in out["lines"]] == ["30000002"] and f2.count("text") == 3 + 1 and ("fetch", "30000001") not in f2.log
    assert s["items"] == {} and s["done"]["30000002"]["outcome"] == "line"


def test_a_broken_freeze_stops_before_any_call():
    f = readers_for(["30000001"])
    s = ql.new_state()
    out = night(s, [cand("30000001")], f, freeze=lambda: ["p8_steward/guard_v2.py"])
    assert out["stopped"] == "freeze_broken" and out["freeze_problems"] == ["p8_steward/guard_v2.py"] and f.log == [] and s == ql.new_state()


def test_a_failing_canary_writes_no_lines_and_leaves_the_queue_untouched():
    f = readers_for(["30000001"], {"20000000": product(photo_v={**VALUES, "fat": 5.0, "carbohydrates": 89.0, "proteins": 1.0}),
                             "20000001": product(photo_v={**VALUES, "fat": 5.0, "carbohydrates": 89.0, "proteins": 1.0})})
    s = ql.new_state()
    out = night(s, [cand("30000001")], f)
    assert out["stopped"] == "canary_failed" and out["lines"] == [] and s == ql.new_state() and ("fetch", "30000001") not in f.log


def test_an_empty_canary_never_lets_the_night_run():
    f = readers_for(["30000001"])
    out = night(ql.new_state(), [cand("30000001")], f, rows=[])
    assert out["stopped"] == "canary_failed" and f.log == []


def test_the_call_ceiling_ends_the_night_and_leaves_unread_products_queued():
    codes = [f"3000000{i}" for i in range(5)]
    f = readers_for(codes)
    s = ql.new_state()
    out = night(s, [cand(c) for c in codes], f, b=budget(max_calls=6 + 4))          # canary 6 calls + two products
    assert out["stopped"] == "call_ceiling" and len(out["lines"]) == 2 and out["calls"] <= 10 and len(s["items"]) == 3


def test_new_flags_are_read_before_the_backlog():
    f = readers_for(["40000001", "50000001"])
    s = ql.new_state()
    out = night(s, [cand("40000001"), cand("50000001", new=True)], f, b=budget(max_calls=6 + 2))
    assert [ln["code"] for ln in out["lines"]] == ["50000001"] and "40000001" in s["items"]
