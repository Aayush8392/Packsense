"""Export everything the JavaScript matcher needs from the frozen Python matcher (Phase C item 14, the browser port).

Run from the scratch environment that has sentence-transformers (see the buildlog):

    <scratch venv>/Scripts/python.exe p6_serving/bot/port/export_bot_data.py

Writes to p6_serving/bot/port/data/: bot_data.json (wordings, answers, families, follow-ups, constants, the regular expressions as source text, the final synonym map)
and wording_embeddings.f32 (one float32 row of 384 numbers per wording, MiniLM-L6, normalised). Nothing is tuned here: the numbers are read from the Python modules
after the shipping settings of FROZEN_V7 (blend 0.7, answer 0.50, strong 0.65, margin 0.10) are applied, so the two versions cannot drift apart.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
BOT = HERE.parent
sys.path.insert(0, str(BOT))
import catalogue as cat  # noqa: E402
import cross_validate as cv  # noqa: E402
import matcher as mt  # noqa: E402
import segment as sg  # noqa: E402
import segment_matcher as sm  # noqa: E402
import trial_embeddings as te  # noqa: E402

SHIP = (0.7, 0.50, 0.10)
REGEXES = {
    "ADVICE": mt.ADVICE, "MEDICAL": mt.MEDICAL, "PREDICT": mt.PREDICT, "RANK_CUE": mt.RANK_CUE, "COMPLETENESS": mt.COMPLETENESS, "OPINION": mt.OPINION,
    "TRICK": mt.TRICK, "HEALTH_MORE": mt.HEALTH_MORE, "ROMAN_HINDI": mt.ROMAN_HINDI, "REQUEST_CUE": mt.REQUEST_CUE, "COUNT_CUE": mt.COUNT_CUE,
    "PRIVATE_CUE": mt.PRIVATE_CUE, "OUTSIDE_CUE": mt.OUTSIDE_CUE, "PRODUCT_FACT_CUE": mt.PRODUCT_FACT_CUE, "COMPARE_CUE": mt.COMPARE_CUE,
    "NOT_OFFERED_CUE": mt.NOT_OFFERED_CUE, "BARCODE": mt.BARCODE, "BARCODE_WORD": mt.BARCODE_WORD, "OTHER_LANGUAGE_WORDS": mt.OTHER_LANGUAGE_WORDS,
    "PRONOUN": mt.PRONOUN, "FOLLOW_OPENER": mt.FOLLOW_OPENER, "SEG_BREAK": sg.BREAK, "SEG_LEAD": sg.LEAD, "SEG_QUESTION": sg.QUESTION,
}


def main() -> None:
    entries, fixed = cat.load_entries(), cat.load_fixed()
    m = sm.SegmentMatcher(cv.MODEL, SHIP[0], entries, fixed)
    cv.set_params(m, SHIP)
    follow = cat.load_follow_ups(entries)
    out = {
        "constants": {
            "WEIGHT_WORD": mt.WEIGHT_WORD, "WEIGHT_CHAR": mt.WEIGHT_CHAR, "WEIGHT_ANSWER": mt.WEIGHT_ANSWER, "SUBJECT_MISS": mt.SUBJECT_MISS, "OOV_FACTOR": mt.OOV_FACTOR,
            "WH_BONUS": mt.WH_BONUS, "CONFIDENT": mt.CONFIDENT, "NEAR_EXACT": mt.NEAR_EXACT, "THIRD_WINDOW": mt.THIRD_WINDOW, "LEX_FLOOR": mt.LEX_FLOOR, "MARGIN": mt.MARGIN,
            "STRONG": mt.STRONG, "SHORT_EXTRA": mt.SHORT_EXTRA, "DATA_NEEDS_CUE": mt.DATA_NEEDS_CUE, "LAMBDA": mt.LAMBDA, "BETA": mt.BETA, "SHORT": mt.SHORT,
            "ALPHA": m.alpha, "LONG_WORDS": sg.LONG_WORDS, "MIN_PIECE": sg.MIN_PIECE, "VARIANT": m.variant,
        },
        "stop": sorted(mt.STOP),
        "synonyms": mt.SYNONYMS,
        "subjects": sorted(mt.SUBJECTS),
        "wh": list(mt.WH),
        "regexes": {k: [v.pattern, v.flags] for k, v in REGEXES.items()},
        "entries": [{"id": e["id"], "kind": e.get("kind")} for e in m.entries],
        "alias": m.alias,
        "wordings": [[eid, w] for eid, w in m.wordings],
        "answers": m.answers,
        "families": [{"hub": f["hub"], "details": list(f["details"])} for f in m.families],
        "followups": follow,
        "replies": {
            "generic": cat.resolve("@generic_reply", fixed),
            "choice": cat.resolve("@choice_reply", fixed),
            "groups": {action: cat.resolve(fixed["decline_groups"][group], fixed) for action, group in mt.REPLY_GROUP.items()},
        },
    }
    data = HERE / "data"
    data.mkdir(exist_ok=True)
    (data / "bot_data.json").write_text(json.dumps(out, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    emb = np.asarray(m.emb, dtype="<f4")
    (data / "wording_embeddings.f32").write_bytes(emb.tobytes())
    print(f"entries {len(m.entries)}, wordings {len(m.wordings)}, embedding matrix {emb.shape}, bytes {emb.nbytes}")


if __name__ == "__main__":
    main()
