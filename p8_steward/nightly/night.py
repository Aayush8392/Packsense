"""One night of the photo-reading job (A121 settled 2026-11-13). No network and no files here: the OFF fetch and the two model readers are INJECTED (`readers`), so tests use fakes and the real
ones plug in at the soak test. The method itself is the frozen one, imported and never copied: photo_method.decide (rule2: the text reading and the photo reading agree), guard v2 (enrichment
of a shown line only), repair_record (partner values, bound statements) and fix_candidates.violations (our rule set).

`readers` provides (all may raise TransientError; any other error becomes a silence for that product):
  fetch(code)            -> {'has_photo': bool, 'ocr_text': str, 'photo': bytes | None}        (OFF; pacing is the reader's job)
  text_reader(code, text, prior=None) -> {'reading': {...}, 'model': str}      (one counted request; `prior` = the first entry, for the one JSON retry)
  photo_reader(code, photo)  -> {'reading': {...}, 'model': str}                                (one counted request)
Every product ends as exactly one of: a line, a silence with a reason (final for that record), or an error (transient: the queue retries it on a later night).
Order of work for one product, cheapest first, so quota is never spent on a product that cannot show a line: no photo, no table in the scan, an unusable text reading -> silence before the
photo reader is called. The shown line is always the PHOTO table; a stored record that breaks no rule gets the statement 'checked'.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "bootstrap"))
import answer_key_lib as akl  # noqa: E402
import fix_candidates as fc  # noqa: E402
import guard_v2 as g  # noqa: E402
import ocr_variant_test as ov  # noqa: E402
import photo_method as pm  # noqa: E402
import reader_decision as rd  # noqa: E402
import repair_record as rr  # noqa: E402
from nightly import canary as cn  # noqa: E402
from nightly import freeze_nightly as fz  # noqa: E402
from nightly import line_record as lr  # noqa: E402
from nightly import queue_lib as ql  # noqa: E402
from nightly.budget import Budget, Stop, TransientError  # noqa: E402


def _call(fn, budget: Budget, model: str, *args) -> dict:
    """One counted model request; a transient error feeds the 503 streak, a wrong model name ends the night."""
    budget.spend()
    try:
        entry = fn(*args)
    except TransientError:
        budget.unavailable()
        raise
    budget.ok()
    fz.check_model(entry.get("model") if isinstance(entry, dict) else None, model)
    return entry


def _result(code: str, outcome: str, reason: str | None = None, line: dict | None = None, calls: int = 0) -> dict:
    return {"code": code, "outcome": outcome, "reason": reason, "line": line, "calls": calls}


def process_product(cand: dict, readers, budget: Budget, night: str, model: str = pm.MODEL) -> dict:
    """cand: {'code', 'stored': per-100 record}. Returns {'code', 'outcome': 'line'|'silence'|'error', 'reason', 'line', 'calls'}; a Stop (ceiling, 503 streak, wrong model) propagates."""
    code, stored, c0 = cand["code"], cand["stored"], budget.calls
    spent = lambda: budget.calls - c0  # noqa: E731
    try:
        got = readers.fetch(code)
        text = got.get("ocr_text") or ""
        if not got.get("has_photo"):
            return _result(code, "silence", "no_photo", calls=spent())
        if not akl.text_has_table(text):
            return _result(code, "silence", "no_ocr_table", calls=spent())
        text_entry = _call(readers.text_reader, budget, model, code, text)
        if rd.reading_problems(text_entry.get("reading"), text) is None:             # the frozen retry rule (dr.retry_if_needed): ONE more request for an unusable reply
            text_entry = _call(readers.text_reader, budget, model, code, text, text_entry)
        if ov.reading_of(text_entry, text) is None:
            return _result(code, "silence", "text_unusable", calls=spent())
        photo_entry = _call(readers.photo_reader, budget, model, code, got["photo"])
        if photo_entry.get("reading") is None:                                       # the photo reader's one retry for unusable JSON (vision_variant_test.run)
            photo_entry = _call(readers.photo_reader, budget, model, code, got["photo"])
        d = pm.decide(code, text_entry, photo_entry, text, stored, has_photo=True)
        if d["silence"] or not d["rule2"] or d["table"] is None:
            return _result(code, "silence", d["silence"] or "no_agreement", calls=spent())
        with g.installed():                                   # guard v2 ONLY enriches a line that is already shown
            g.LOG.clear()
            richer = ov.reading_of(photo_entry, text) or {}
        table = {**d["table"], **{f: v for f, v in richer.items() if f not in d["table"] and v is not None}}
        rec, derived = rr.repaired_record(stored, table)
        before, after = fc.violations(stored), fc.violations(rec)
        bounds: list[dict] = []
        if not before:
            statement = "checked"
        elif not after:
            statement = "repaired"
        else:
            bounds = rr.bound_statements(stored, table, set(after))
            statement = "bound" if bounds else "open"
        line = lr.build_line(code, night, table, derived, bool(d["differs"]), statement, bounds, (photo_entry.get("reading") or {}).get("basis"), stored)
        problems = lr.validate_line(line)
        if problems:
            return _result(code, "silence", "invalid_line", calls=spent())
        return _result(code, "line", line=line, calls=spent())
    except Stop:
        raise
    except TransientError:
        return _result(code, "error", "unavailable", calls=spent())
    except Exception as e:                                    # any other failure is silence for this night, never a guess; the queue tries again
        return _result(code, "error", "unexpected:" + type(e).__name__, calls=spent())


def run_canary(canary_rows: list[dict], readers, budget: Budget, night: str, model: str = pm.MODEL, max_miss: int = cn.MAX_MISS) -> dict:
    """canary_rows: [{'code', 'stored', 'expected': table}]; reads each through the same pipeline and compares with the saved right tables."""
    produced = {}
    for row in canary_rows:
        r = process_product(row, readers, budget, night, model)
        produced[row["code"]] = r["line"]["values"] if r["line"] else None
    return cn.compare(produced, {r["code"]: r["expected"] for r in canary_rows}, max_miss)


def run_night(state: dict, candidates: list[dict], readers, budget: Budget, night: str, canary_rows: list[dict], freeze_problems=fz.problems, model: str = pm.MODEL) -> dict:
    """candidates: [{'code', 'stored', 'new': bool}] = every product whose flag is open tonight. Updates `state` in place; returns the night's summary.
    Order: freeze check, canary, then the queue (new, missed, backlog). Any Stop ends the night with its reason; products not finished stay in the queue untouched."""
    out = {"stopped": None, "canary": None, "lines": [], "silences": {}, "errors": {}, "products": 0, "merge": None}
    problems = freeze_problems()
    if problems:
        out["stopped"] = "freeze_broken"
        out["freeze_problems"] = problems
        return out
    try:
        out["canary"] = run_canary(canary_rows, readers, budget, night, model)
        if not out["canary"]["passed"]:
            raise Stop("canary_failed")
        cands = {c["code"]: c for c in candidates}
        for c in cands.values():
            c.setdefault("record_hash", lr.record_hash(c["stored"]))
        out["merge"] = ql.merge_candidates(state, list(cands.values()), night)
        for code in ql.take(state, night, 10 ** 9):
            if budget.remaining() < ql.CALLS_PER_PRODUCT:
                raise Stop("call_ceiling")
            r = process_product(cands[code], readers, budget, night, model)
            out["products"] += 1
            if r["outcome"] == "line":
                ql.settle(state, code, "line", night)
                out["lines"].append(r["line"])
            elif r["outcome"] == "silence":
                ql.settle(state, code, "silence", night, r["reason"])
                out["silences"][r["reason"]] = out["silences"].get(r["reason"], 0) + 1
            else:
                ql.settle(state, code, "error", night, r["reason"])
                out["errors"][r["reason"]] = out["errors"].get(r["reason"], 0) + 1
    except Stop as s:
        out["stopped"] = s.reason
    out["calls"] = budget.calls
    out["queue"] = ql.counts(state)
    return out
