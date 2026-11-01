"""The Porter stemmer (M. F. Porter, 1980, "An algorithm for suffix stripping"), written out in plain Python so the browser port can follow it step by step.

It joins word forms the matcher's own suffix stripping misses (barcode/barcodes, compare/compared, failure/failures, anonymity/anonymous ...). The matcher uses it only when
the environment variable PACKSENSE_STEMMER is set to "porter"; otherwise matcher.stem() is the original, simpler rule.
"""
from __future__ import annotations

_VOWELS = "aeiou"


def _is_consonant(word: str, i: int) -> bool:
    ch = word[i]
    if ch in _VOWELS:
        return False
    if ch == "y":
        return i == 0 or not _is_consonant(word, i - 1)
    return True


def _measure(stem: str) -> int:
    """The number of vowel-consonant sequences in the stem: [C](VC){m}[V]."""
    n, i, length = 0, 0, len(stem)
    while i < length and _is_consonant(stem, i):
        i += 1
    while i < length:
        while i < length and not _is_consonant(stem, i):
            i += 1
        if i >= length:
            break
        n += 1
        while i < length and _is_consonant(stem, i):
            i += 1
    return n


def _has_vowel(stem: str) -> bool:
    return any(not _is_consonant(stem, i) for i in range(len(stem)))


def _ends_double_consonant(word: str) -> bool:
    return len(word) >= 2 and word[-1] == word[-2] and _is_consonant(word, len(word) - 1)


def _ends_cvc(word: str) -> bool:
    """consonant-vowel-consonant, the last consonant not w, x or y."""
    n = len(word)
    return n >= 3 and _is_consonant(word, n - 3) and not _is_consonant(word, n - 2) and _is_consonant(word, n - 1) and word[-1] not in "wxy"


def _replace(word: str, suffix: str, replacement: str, min_measure: int) -> tuple[str, bool]:
    """If the word ends with the suffix: the word with it replaced when the stem's measure is above min_measure; (word, True) says the suffix matched either way."""
    if not word.endswith(suffix):
        return word, False
    stem = word[: len(word) - len(suffix)]
    if _measure(stem) > min_measure:
        return stem + replacement, True
    return word, True


def _step1a(word: str) -> str:
    if word.endswith("sses"):
        return word[:-2]
    if word.endswith("ies"):
        return word[:-2]
    if word.endswith("ss"):
        return word
    if word.endswith("s"):
        return word[:-1]
    return word


def _step1b(word: str) -> str:
    if word.endswith("eed"):
        stem = word[:-3]
        return word[:-1] if _measure(stem) > 0 else word
    for suffix in ("ed", "ing"):
        if word.endswith(suffix):
            stem = word[: -len(suffix)]
            if not _has_vowel(stem):
                return word
            word = stem
            if word.endswith(("at", "bl", "iz")):
                return word + "e"
            if _ends_double_consonant(word) and word[-1] not in "lsz":
                return word[:-1]
            if _measure(word) == 1 and _ends_cvc(word):
                return word + "e"
            return word
    return word


def _step1c(word: str) -> str:
    if word.endswith("y") and _has_vowel(word[:-1]):
        return word[:-1] + "i"
    return word


_STEP2 = [("ational", "ate"), ("tional", "tion"), ("enci", "ence"), ("anci", "ance"), ("izer", "ize"), ("abli", "able"), ("alli", "al"), ("entli", "ent"), ("eli", "e"),
          ("ousli", "ous"), ("ization", "ize"), ("ation", "ate"), ("ator", "ate"), ("alism", "al"), ("iveness", "ive"), ("fulness", "ful"), ("ousness", "ous"),
          ("aliti", "al"), ("iviti", "ive"), ("biliti", "ble")]
_STEP3 = [("icate", "ic"), ("ative", ""), ("alize", "al"), ("iciti", "ic"), ("ical", "ic"), ("ful", ""), ("ness", "")]
_STEP4 = ["al", "ance", "ence", "er", "ic", "able", "ible", "ant", "ement", "ment", "ent", "ion", "ou", "ism", "ate", "iti", "ous", "ive", "ize"]


def _step_table(word: str, table: list[tuple[str, str]]) -> str:
    for suffix, replacement in sorted(table, key=lambda x: -len(x[0])):       # the longest matching suffix decides
        if word.endswith(suffix):
            return _replace(word, suffix, replacement, 0)[0]
    return word


def _step4(word: str) -> str:
    for suffix in sorted(_STEP4, key=lambda s: -len(s)):
        if word.endswith(suffix):
            stem = word[: len(word) - len(suffix)]
            if suffix == "ion" and not stem.endswith(("s", "t")):
                return word
            return stem if _measure(stem) > 1 else word
    return word


def _step5(word: str) -> str:
    if word.endswith("e"):
        stem = word[:-1]
        m = _measure(stem)
        if m > 1 or (m == 1 and not _ends_cvc(stem)):
            word = stem
    if _measure(word) > 1 and _ends_double_consonant(word) and word.endswith("l"):
        word = word[:-1]
    return word


def stem(word: str) -> str:
    """The Porter stem of a lower-case word. Words of one or two letters are left alone."""
    if len(word) <= 2:
        return word
    word = _step1a(word)
    word = _step1b(word)
    word = _step1c(word)
    word = _step_table(word, _STEP2)
    word = _step_table(word, _STEP3)
    word = _step4(word)
    return _step5(word)
