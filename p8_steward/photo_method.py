"""The photo-reading method of round 2, in ONE place (written 2026-11-10, before any round-2 call; the frozen pieces are imported, never copied).

What it does for one product, from three inputs: the text reader's answer, the photo reader's answer and OFF's OCR text of the same photo.
  text reading    dev_ocr_reader prompt 'v3rows' on the scan text (the frozen reader; made by fix_test_agent.py run --set round2)
  photo reading   Gemini looks at the photo (vision_variant_test.vision_system(), photo resized to 1,600 px; made by bootstrap/run_round2_readers.py)
  guard           a number counts only when the OCR text also prints it (ocr_variant_test.reading_of); a number only the photo shows is dropped
  agreement       ocr_variant_test.agree: at least 90% of at least 3 shared fields within the 10% rule (floors 2 kcal, 8 kJ, 0.05 g)
  the line        the PHOTO table, marked 'differs' where it disagrees with the stored values, 'matches' where it agrees
  silence         no photo, no OCR table, a reading that is unusable, or the two readings disagree: NO line. It never falls back to the text reading
                  (on disagreement in round 1 the photo was right 7 times of 9 and the text reading 0).

Candidate line types, written before any round-2 call; nothing outside this list may be chosen afterwards:
  rule2  the text reading and the photo reading agree (the photo table is shown)
  rule1  the narrow rule holds (the hybrid's table agrees with the text reading) AND the photo reading agrees with that table
  differ / match   rule2 lines split by whether the photo table differs from the stored values
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "p8_steward"))
sys.path.insert(0, str(ROOT / "p8_steward" / "bootstrap"))
import answer_key_lib as akl  # noqa: E402
import dev_ocr_reader as dr  # noqa: E402
import ocr_variant_test as ov  # noqa: E402
import vision_variant_test as vv  # noqa: E402

TEXT_VERSION = "v3rows"
TEXT_LIMIT = 6000                  # the characters of scan text the text reader sees
PHOTO_LONG_SIDE = 1600             # pixels; the photo is resized before it is sent
MODEL = ov.MODEL
LINE_TYPES = ("rule2", "rule1", "differ", "match")
SILENCE = ("no_photo", "no_ocr_table", "text_unusable", "photo_unusable", "no_agreement")


def ocr_text(code: str) -> str:
    """The scan text the text reader sees (frozen: the rows rendering, first 6,000 characters)."""
    return dr.scan_text(code, TEXT_VERSION)[:TEXT_LIMIT]


def text_system() -> str:
    return dr.SYSTEMS[TEXT_VERSION]


def photo_system() -> str:
    return vv.vision_system()


def differing_fields(table: dict, stored: dict) -> list[str]:
    """The fields where the table disagrees with the stored values (the 10% rule), plus fields the table has and the record lacks. A field only the record has is not a difference."""
    return sorted(f for f in ov.FIELDS if f in table and (f not in stored or not akl.field_matches(f, table[f], stored[f])))


def decide(code: str, text_entry: dict | None, photo_entry: dict | None, text: str, stored: dict, has_photo: bool = True, hybrid: dict | None = None) -> dict:
    """The whole rule for one product. text_entry / photo_entry are the saved reader answers ({'reading': ...}); text is the OCR text the reader saw; stored the pre-fix per-100 record;
    hybrid the hybrid's repaired table (only needed for rule 1). Returns {'code', 'silence': None or a reason, 'table', 'rule2', 'rule1', 'differs', 'differing_fields', 'types'}."""
    out = {"code": code, "silence": None, "table": None, "rule2": False, "rule1": False, "differs": None, "differing_fields": [], "types": []}
    if not has_photo:
        out["silence"] = "no_photo"
        return out
    if not akl.text_has_table(text):
        out["silence"] = "no_ocr_table"
        return out
    t, p = ov.reading_of(text_entry or {}, text), ov.reading_of(photo_entry or {}, text)
    if t is None:
        out["silence"] = "text_unusable"
        return out
    if p is None:
        out["silence"] = "photo_unusable"
        return out
    out["rule2"] = ov.agree(t, p)
    out["rule1"] = bool(hybrid) and ov.agree(hybrid, t) and ov.agree(p, hybrid)
    if not (out["rule2"] or out["rule1"]):
        out["silence"] = "no_agreement"
        return out
    out["table"] = p                                           # the line is always the photo table, whichever rule shows it
    out["differing_fields"] = differing_fields(p, stored)
    out["differs"] = bool(out["differing_fields"])
    out["types"] = (["rule2", "differ" if out["differs"] else "match"] if out["rule2"] else []) + (["rule1"] if out["rule1"] else [])
    return out
