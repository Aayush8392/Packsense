"""Tests for the one-off that builds the canary's saved inputs (nightly/make_canary_inputs.py): all ten must agree or nothing is written."""
import base64
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "bootstrap"))
import photo_method as pm  # noqa: E402
from nightly import budget as bd  # noqa: E402
from nightly import make_canary_inputs as mk  # noqa: E402

TEXT = "Nutrition facts per 100 g Energy 376 kJ / 90 kcal Fat 0.5 g Saturates 0.3 g Carbohydrate 8.9 g Sugars 6.5 g Protein 12.4 g Salt 0.06 g"
VALUES = {"energy_kcal": 90, "energy_kj": 376, "fat": 0.5, "saturated_fat": 0.3, "carbohydrates": 8.9, "sugars": 6.5, "proteins": 12.4, "salt": 0.06}
STORED = {k: float(v) for k, v in VALUES.items()}


def entry(values=VALUES):
    return {"reading": {"basis": "per 100 g", "serving_size": None, "values_per_100": dict(values)}, "model": pm.MODEL}


class Readers:
    def __init__(self, bad_fetch=(), bad_read=()):
        self.bad_fetch, self.bad_read, self.fetched = set(bad_fetch), set(bad_read), []

    def fetch(self, code):
        self.fetched.append(code)
        if code in self.bad_fetch:
            raise ConnectionError("timed out")
        return {"has_photo": True, "ocr_text": TEXT, "photo": b"p" * 2000 + code.encode()}

    def text_reader(self, code, text, prior=None):
        return entry()

    def photo_reader(self, code, photo):
        return entry({**VALUES, "fat": 5.0, "carbohydrates": 89.0, "proteins": 1.0} if code in self.bad_read else VALUES)


def rows(n=3):
    return [{"code": f"2000000{i}", "stored": STORED, "expected": dict(VALUES)} for i in range(n)]


def run(r):
    return mk.build(rows(), r, bd.Budget(sleep=lambda s: None, max_calls=60), "2026-11-19")


def test_when_every_product_agrees_each_row_gets_its_scan_text_and_photo_fetched_once():
    r = Readers()
    fixed, problems = run(r)
    assert problems == {} and len(fixed) == 3 and r.fetched == ["20000000", "20000001", "20000002"]
    assert fixed[0]["ocr_text"] == TEXT and base64.b64decode(fixed[0]["photo_b64"]).startswith(b"p" * 2000) and fixed[0]["expected"] == VALUES


def test_one_failed_fetch_writes_nothing_and_names_the_product():
    fixed, problems = run(Readers(bad_fetch=["20000001"]))
    assert fixed == [] and problems == {"20000001": "fetch:ConnectionError"}


def test_one_product_that_does_not_agree_writes_nothing_and_says_why():
    fixed, problems = run(Readers(bad_read=["20000002"]))
    assert fixed == [] and problems == {"20000002": "silence:no_agreement"}
