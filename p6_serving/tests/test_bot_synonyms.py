"""catalogue/synonyms.yml: the owner-reviewed word list must stay consistent. A word maps to one concept only, a concept is never itself another concept's synonym, and a
word that matcher.py already maps keeps that mapping (so the new file never silently disagrees with the old one)."""
import importlib
import re
import sys
from collections import defaultdict
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "bot"))
import catalogue as cat  # noqa: E402
import matcher as mt  # noqa: E402

DOC = cat.load_synonyms()
CONCEPTS = DOC["concepts"]
WORD = re.compile(r"^[a-z0-9]+$")


def test_every_word_and_concept_is_one_clean_lower_case_word():
    for concept, words in CONCEPTS.items():
        assert WORD.match(concept), concept
        for w in words:
            assert WORD.match(w), (concept, w)
    assert all(WORD.match(w) for w in DOC["stop_words"])


def test_a_word_maps_to_one_concept_only():
    seen = defaultdict(set)
    for concept, words in CONCEPTS.items():
        for w in words:
            seen[w].add(concept)
    assert {w: sorted(c) for w, c in seen.items() if len(c) > 1} == {}


def test_a_concept_is_never_another_concepts_synonym_and_never_its_own():
    words = {w for ws in CONCEPTS.values() for w in ws}
    assert sorted(set(CONCEPTS) & words) == []


def test_a_word_already_mapped_in_the_matcher_agrees_with_it():
    clashes = {w: (mt.SYNONYMS[w], c) for c, ws in CONCEPTS.items() for w in ws if w in mt.SYNONYMS and mt.SYNONYMS[w] != c}
    # (when the switch is on, today's mapping wins; a clash would mean the owner's list says something else)
    assert clashes == {}


def test_filler_words_are_not_also_synonyms_or_concepts():
    stop = set(DOC["stop_words"])
    used = set(CONCEPTS) | {w for ws in CONCEPTS.values() for w in ws}
    assert sorted(stop & used) == []
    assert {"please", "can", "tell"} <= stop


def test_the_owner_and_creator_words_reach_the_same_concept():
    assert {w: next(c for c, ws in CONCEPTS.items() if w in ws) for w in ("owner", "creator", "author", "founder", "developer")} == {
        "owner": "maker", "creator": "maker", "author": "maker", "founder": "maker", "developer": "maker"}


def test_the_anonymity_family_reaches_hidden():
    for w in ("anonymous", "anonymity", "anonymised", "anonymized", "anonymisation"):
        assert w in CONCEPTS["hidden"], w


@pytest.mark.parametrize("text,fixed", [
    ("why not let people correct products", True), ("can i correct a product", True), ("who can correct the mistakes", True), ("allow users to correct entries", True),
    ("is the data correct", False), ("is it correct", False), ("how correct is this", False),
])
def test_the_verb_correct_goes_to_fix_but_the_adjective_stays(text, fixed):
    assert bool(mt.CORRECT_VERB.search(text)) is fixed


def test_the_switch_is_off_by_default_and_changes_nothing(monkeypatch):
    monkeypatch.delenv("PACKSENSE_NEW_SYNONYMS", raising=False)
    monkeypatch.delenv("PACKSENSE_STEMMER", raising=False)
    off = importlib.reload(mt)
    assert off.NEW_SYNONYMS is False and off.STEMMER == ""
    assert "owner" not in off.SYNONYMS and off.tokens("who is the owner") == ["who", "owner"]


def test_the_switch_on_maps_the_new_words_and_ignores_the_filler(monkeypatch):
    monkeypatch.setenv("PACKSENSE_NEW_SYNONYMS", "1")
    on = importlib.reload(mt)
    try:
        assert on.tokens("who is the owner") == ["who", "maker"]
        assert on.tokens("please tell me how the contributors stay anonymous") == ["how", "contributor", "stay", "hidden"]
        assert "fix" in on.tokens("why not let people correct products")
        assert "correct" in on.tokens("is the data correct")
    finally:
        monkeypatch.delenv("PACKSENSE_NEW_SYNONYMS", raising=False)
        importlib.reload(mt)
