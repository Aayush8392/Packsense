"""Helpers for the fixture export (plain Python, unit-tested; the notebook imports them).

narrow_handles: the exit function builds one regular expression out of every contributor name and rebuilds it for every text value,
which is fine for the handful of names of one product but takes hours for the 75,000 names in bronze against a few hundred products
(tags count as values: a first run spent over 12 minutes in the exit step and was cancelled). A name that occurs in none of the
exported text can neither be replaced nor found by the final scan, so dropping it changes nothing in the result. The check is a
plain substring test on the normalised text, a superset of the exit function's whole-word match, so no name that could match is lost.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "p2_lakehouse"))

from silver_lib import contract, personal  # noqa: E402


def text_values(rows, c):
    """Every string in the kept free-text and tag columns of the rows."""
    cols = contract.text_column_names(c)
    for row in rows:
        for col in cols:
            v = row.get(col)
            for t in v if isinstance(v, list) else [v]:
                if isinstance(t, str):
                    yield t


def narrow_handles(rows, c, handles):
    """The subset of `handles` (normalised names) that occurs as a substring of the normalised exported text."""
    blob = "\n".join(personal.normalise(t) for t in text_values(rows, c))
    return {h for h in handles if h in blob}
