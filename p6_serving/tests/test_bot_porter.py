"""The Porter stemmer against the examples in Porter's own paper, and the word forms the matcher's simple stripping did not join."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "bot"))
import porter  # noqa: E402

PAPER = {
    "caresses": "caress", "ponies": "poni", "ties": "ti", "caress": "caress", "cats": "cat", "feed": "feed", "agreed": "agre", "plastered": "plaster", "bled": "bled",
    "motoring": "motor", "sing": "sing", "conflated": "conflat", "troubled": "troubl", "sized": "size", "hopping": "hop", "tanned": "tan", "falling": "fall",
    "hissing": "hiss", "fizzed": "fizz", "failing": "fail", "filing": "file", "happy": "happi", "sky": "sky", "relational": "relat", "conditional": "condit",
    "rational": "ration", "valenci": "valenc", "digitizer": "digit", "conformabli": "conform", "radicalli": "radic", "differentli": "differ", "vileli": "vile",
    "analogousli": "analog", "vietnamization": "vietnam", "predication": "predic", "operator": "oper", "feudalism": "feudal", "decisiveness": "decis",
    "hopefulness": "hope", "callousness": "callous", "formaliti": "formal", "sensitiviti": "sensit", "sensibiliti": "sensibl", "triplicate": "triplic",
    "formative": "form", "formalize": "formal", "electriciti": "electr", "electrical": "electr", "hopeful": "hope", "goodness": "good", "revival": "reviv",
    "allowance": "allow", "inference": "infer", "airliner": "airlin", "gyroscopic": "gyroscop", "adjustable": "adjust", "defensible": "defens", "irritant": "irrit",
    "replacement": "replac", "adjustment": "adjust", "dependent": "depend", "adoption": "adopt", "homologous": "homolog", "communism": "commun", "activate": "activ",
    "angulariti": "angular", "effective": "effect", "bowdlerize": "bowdler", "probate": "probat", "rate": "rate", "cease": "ceas", "controll": "control", "roll": "roll",
}


@pytest.mark.parametrize("word,expected", sorted(PAPER.items()))
def test_porter_paper_examples(word, expected):
    assert porter.stem(word) == expected


@pytest.mark.parametrize("forms", [
    ("barcode", "barcodes"), ("cookie", "cookies"), ("username", "usernames"), ("additive", "additives"), ("failure", "failures"), ("compare", "compared", "compares", "comparing"),
    ("run", "runs"), ("complete", "completed"), ("flag", "flags", "flagged", "flagging"), ("update", "updated", "updates", "updating"), ("contributor", "contributors"),
    ("release", "releases", "released"), ("check", "checks", "checked", "checking"),
])
def test_forms_the_simple_stripping_did_not_join_now_share_a_stem(forms):
    assert len({porter.stem(f) for f in forms}) == 1, {f: porter.stem(f) for f in forms}


def test_short_words_are_left_alone():
    assert [porter.stem(w) for w in ("a", "is", "ai", "of")] == ["a", "is", "ai", "of"]
