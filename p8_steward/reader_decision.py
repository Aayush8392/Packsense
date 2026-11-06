"""What the method does with one record once a model has READ the pack's scan text (item 23, development). Pure code, no model call, so it is tested on real rows.

The reader's reading is only evidence. Code decides, and the default is to say nothing:
  - no table in the scan text, no usable reading, or too few printed values -> abstain;
  - the reading breaks one of our arithmetic rules: if the record says the same thing and breaks the same rules, the PACK's own numbers disagree -> 'no change' with the computed
    figures; if dropping exactly ONE field of the reading clears every violation, that field is a misread and is left out; otherwise abstain;
  - the record is already what the reading says: 'no change'. If the record itself breaks the salt/sodium rule and the printed side agrees with the record, the field the pack does not
    print is the inconsistent one -> 'no change' with the computed figures; any other rule the reading did not cover -> abstain;
  - (A121 11 (e)) a record that holds a value for a field of the flagged group which the pack does not print is never 'no change': 'not assessed: the pack does not print it';
  - the reading only swaps values the record already holds (the scan cannot say which label a value belongs to) -> abstain;
  - otherwise propose every field of the flagged group where the reading differs from the record.
Every outcome carries 'evidence': plain sentences with the figures computed by code (rule_evidence.py). Every proposal still needs a human before anything leaves the system.
"""
from __future__ import annotations

from itertools import combinations

import answer_key_lib as ak
import fix_candidates as fc
from rule_evidence import explain

UNPRINTED = "abstain (the pack does not print it)"        # public status: not assessed: the pack does not print it (A121 11 (e))
MIN_FIELDS = 2          # a reading with fewer printed, grounded values than this is not a table
OPTIONS = {"table_guard", "min_fields", "uncovered", "swap", "explain", "dropone", "unprinted"}      # guards that are ON ("unprinted_inconsistent", A121 11 (e) in full, is OFF: it cost 8 to 9 points of coverage for one silent miss; see the worklog); "minimal" (smallest change) was measured, lost fixes, and stays off


def _is_permutation(stored: dict, read: dict, fields: list[str]) -> bool:
    """True when the reading's values on these fields are the record's own values in another order (a label/value swap)."""
    if len(fields) < 2 or any(stored.get(f) is None for f in fields):
        return False
    a, b = sorted(stored[f] for f in fields), sorted(read[f] for f in fields)
    return all(ak.field_matches(fields[0], x, y) or abs(x - y) <= 0.05 for x, y in zip(a, b))


def grounded_reading(reading: dict | None, text: str) -> tuple[dict, list[str]]:
    """The reading with every value that is not printed in the text taken out, and the names of the fields taken out."""
    kept, dropped = ak.grounded_values({f: v for f, v in ((reading or {}).get("values_per_100") or {}).items() if isinstance(v, (int, float)) and not isinstance(v, bool)}, text)
    return {**(reading or {}), "values_per_100": kept}, dropped


def reading_problems(reading: dict | None, text: str) -> list[str] | None:
    """For a retry: None when there is no usable reading at all, [] when the reading breaks no rule, else one sentence per broken rule (figures computed by code,
    about the reading itself, never about the stored record)."""
    if not reading:
        return None
    conv = ak.reading_to_per100(grounded_reading(reading, text)[0])
    if not conv["usable"]:
        return []                                                                # a different problem (for example no serving size): a retry cannot fix it
    return [explain(conv["per100"], r) for r in sorted(fc.violations(conv["per100"]))]


def decide(stored: dict, reading: dict | None, text: str, group: str, version: str, options: set | None = None) -> dict:
    """Returns {'action', 'per100' (the PROPOSED values only), 'reading100' (the whole converted reading), 'dropped', 'evidence' (sentences)}."""
    on = OPTIONS if options is None else options
    out = {"action": "abstain (no usable reading)", "per100": {}, "reading100": {}, "dropped": [], "evidence": []}
    guarded = version != "v1"
    if guarded and "table_guard" in on and not ak.text_has_table(text):
        out["action"] = "abstain (no readable table in the scan)"
        return out
    if not reading:
        return out
    if guarded:
        reading, out["dropped"] = grounded_reading(reading, text)
    conv = ak.reading_to_per100(reading)
    if not conv["usable"]:
        return out
    read = conv["per100"]
    out["reading100"] = read
    if guarded and "min_fields" in on and len(read) < MIN_FIELDS:
        out["action"] = "abstain (too few printed values read)"
        return out
    fields = [f for f in ak.GROUP_FIELDS[group] if f in read]
    both = [f for f in fields if stored.get(f) is not None]
    base = fc.violations(stored)
    vr = fc.violations(read)
    if vr and guarded and "explain" in on and len(both) >= 3 and all(ak.field_matches(f, stored[f], read[f]) for f in both) and vr <= base:
        out["action"] = "no change (the pack's own numbers disagree)"                    # the record says what the pack says, and the pack contradicts itself
        out["evidence"] = [explain(read, r) for r in sorted(vr)]
        return out
    if vr and guarded and "dropone" in on:
        singles = [f for f in read if not fc.violations({k: x for k, x in read.items() if k != f})]
        if len(singles) == 1 and len(read) - 1 >= MIN_FIELDS:                           # one misread field spoils an otherwise consistent reading
            out["dropped"] = out["dropped"] + [singles[0]]
            read = {k: x for k, x in read.items() if k != singles[0]}
            out["reading100"] = read
            vr = set()
            fields = [f for f in fields if f != singles[0]]
            both = [f for f in both if f != singles[0]]
    if vr:
        out["action"] = "abstain (the reading breaks a rule)"
        return out
    if not guarded:                                                              # v1 as it was
        out["per100"] = read
        vs = ak.matches_key_for_group(stored, read, group)
        out["action"] = "no change" if vs["match"] else ("fill in" if vs["compared"] == 0 else "change to reading")
        return out
    if not both:                                                                 # nothing the record carries can be compared: only a fill-in is possible
        out["per100"] = {f: read[f] for f in fields}
        if not fields and "unprinted" in on and any(stored.get(f) is not None for f in ak.GROUP_FIELDS[group]):
            out["action"] = UNPRINTED                                            # A121 11 (e): the record holds a value the pack does not print: never 'matches'
            out["evidence"] = ["the record holds a value for a field of the flagged group that the pack does not print"]
            return out
        out["action"] = "fill in" if fields else "no change"
        return out
    diff = [f for f in both if not ak.field_matches(f, stored[f], read[f])]
    if not diff:
        if base and "uncovered" in on:
            printed = [f for f in ("salt", "sodium") if f in read and stored.get(f) is not None]
            if "explain" in on and base == {"salt-does-not-match-sodium"} and len(printed) == 1 and stored.get("salt") is not None and stored.get("sodium") is not None:
                # the printed side agrees with the record; the other side is the one that does not (it was 'no change (an unprinted field is inconsistent)' before A121 11 (e))
                out["action"] = UNPRINTED if "unprinted_inconsistent" in on else "no change (an unprinted field is inconsistent)"
                out["evidence"] = [explain(stored, "salt-does-not-match-sodium")]
            else:
                out["action"] = "abstain (the record breaks a rule the reading did not cover)"
        else:
            out["action"] = "no change"
        return out
    if "swap" in on and _is_permutation(stored, read, diff):
        out["action"] = "abstain (the reading only swaps values the record holds)"
        return out
    chosen = diff
    if "minimal" in on and base:
        chosen = None
        for k in range(1, len(diff) + 1):
            for combo in combinations(diff, k):
                v = fc.violations({**stored, **{f: read[f] for f in combo}})
                if not v or v < base or len(v) < len(base):
                    chosen = list(combo)
                    break
            if chosen:
                break
        if chosen is None:
            out["action"] = "abstain (no small change removes the violation)"
            return out
    out["per100"] = {f: read[f] for f in chosen}
    out["action"] = "change to reading"
    return out
