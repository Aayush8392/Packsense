"""Product identity matching, baseline (design 7.4, roadmap item 19). Pure functions: text in, numbers out. No network, no Spark.

The baseline score is the cosine of two products' names as character trigrams weighted by how rare each trigram is across the market (TF-IDF). Names are lower-cased,
accents folded away and everything that is not a letter or digit becomes a space. The score looks at nothing else: pack size and nutrition are reported next to it, not mixed in.
"""
from __future__ import annotations

import hashlib
import math
import re
import unicodedata
from collections import Counter

NON_WORD = re.compile(r"[^a-z0-9]+")
STRATA = ((0.0, 0.3), (0.3, 0.5), (0.5, 0.7), (0.7, 0.85), (0.85, 1.0000001))
NUTRIENTS = ("energy_kcal", "fat", "carbohydrates", "proteins", "salt")


def normalise(text: str | None) -> str:
    folded = unicodedata.normalize("NFKD", (text or "").lower())
    return NON_WORD.sub(" ", "".join(c for c in folded if not unicodedata.combining(c))).strip()


def trigrams(text: str | None) -> Counter:
    s = f"  {normalise(text)} "
    return Counter(s[i:i + 3] for i in range(len(s) - 2)) if normalise(text) else Counter()


def idf_table(names: list[str | None]) -> dict[str, float]:
    """Rarer trigrams weigh more: log(1 + N / document frequency)."""
    df: Counter = Counter()
    for n in names:
        df.update(trigrams(n).keys())
    total = len(names)
    return {g: math.log(1 + total / c) for g, c in df.items()}


def vector(text: str | None, idf: dict[str, float]) -> dict[str, float]:
    tf = trigrams(text)
    v = {g: c * idf.get(g, 0.0) for g, c in tf.items()}
    norm = math.sqrt(sum(x * x for x in v.values()))
    return {g: x / norm for g, x in v.items()} if norm else {}


def cosine(a: dict[str, float], b: dict[str, float]) -> float:
    if len(a) > len(b):
        a, b = b, a
    return sum(x * b.get(g, 0.0) for g, x in a.items())


def size_relation(qa: float | None, qb: float | None) -> str:
    """`same` / `different` / `unknown` from the two pack quantities (grams or millilitres as OFF records them)."""
    if qa is None or qb is None or qa <= 0 or qb <= 0:
        return "unknown"
    return "same" if abs(qa - qb) <= 0.01 * max(qa, qb) else "different"


def nutrition_gap(a: dict, b: dict) -> float | None:
    """The largest relative gap over the five nutrients (a gap of 0.1 or less counts as none, for rounding); None when any is missing on either side."""
    worst = 0.0
    for k in NUTRIENTS:
        x, y = a.get(k), b.get(k)
        if x is None or y is None:
            return None
        gap = abs(x - y)
        if gap > 0.1:
            worst = max(worst, gap / max(x, y))
    return worst


def stratum(score: float) -> int:
    for i, (lo, hi) in enumerate(STRATA):
        if lo <= score < hi:
            return i
    raise ValueError(score)


def pair_key(code_a: str, code_b: str) -> str:
    a, b = sorted((code_a, code_b))
    return hashlib.md5(f"{a}|{b}".encode()).hexdigest()


def pick(pairs: list[tuple[str, str]], n: int) -> list[tuple[str, str]]:
    """The n pairs with the smallest hash of the two barcodes: deterministic, no random generator."""
    return sorted(pairs, key=lambda p: pair_key(*p))[:n]
