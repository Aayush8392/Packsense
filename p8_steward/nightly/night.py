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
        try:
            got = readers.fetch(code)
        except TransientError:                                # OFF did not answer: kept apart from a model outage, because the night watches the two differently
            return _result(code, "error", "fetch_unavailable", calls=spent())
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


class _SavedFetch:
    """What the canary reads from. A canary row that carries its own SAVED inputs ('ocr_text' and 'photo': the scan text and the resized photo, as the night's fetch makes them) is read from
    those, with no Open Food Facts request at all: a failed or changed OFF record can then never look like a wrong reading, and a miss means the model or the method changed (decided 2026-11-18
    after the 17 and 18 Nov canary failures). A row without saved inputs (an older file, a unit test) still reads live. The two model readers are the real ones either way."""

    def __init__(self, readers, row: dict):
        self._readers, self._row = readers, row

    def fetch(self, code: str) -> dict:
        if self._row.get("ocr_text") is not None and self._row.get("photo") is not None:
            return {"has_photo": True, "ocr_text": self._row["ocr_text"], "photo": self._row["photo"]}
        return self._readers.fetch(code)

    def text_reader(self, *args, **kwargs):
        return self._readers.text_reader(*args, **kwargs)

    def photo_reader(self, *args, **kwargs):
        return self._readers.photo_reader(*args, **kwargs)


def run_canary(canary_rows: list[dict], readers, budget: Budget, night: str, model: str = pm.MODEL, max_miss: int = cn.MAX_MISS) -> dict:
    """canary_rows: [{'code', 'stored', 'expected': table, optional saved 'ocr_text' and 'photo'}]; reads each through the same pipeline and compares with the saved right tables.
    The result also says WHY each product missed ('missed_detail': code -> outcome:reason, or 'disagrees' for a shown line that differs) and counts them ('missed_reasons': counts only)."""
    produced, detail = {}, {}
    for row in canary_rows:
        r = process_product(row, _SavedFetch(readers, row), budget, night, model)
        produced[row["code"]] = r["line"]["values"] if r["line"] else None
        if r["line"] is None:
            detail[row["code"]] = f"{r['outcome']}:{r['reason']}"
    result = cn.compare(produced, {r["code"]: r["expected"] for r in canary_rows}, max_miss)
    result["missed_detail"] = {c: detail.get(c, "disagrees") for c in result["missed"]}
    reasons: dict[str, int] = {}
    for why in result["missed_detail"].values():
        reasons[why] = reasons.get(why, 0) + 1
    result["missed_reasons"] = reasons
    return result


OFF_STREAK = 5               # provisional: consecutive products whose OFF fetch failed before the night stops (red)
LOW_YIELD = 0.40             # provisional: a night with fewer lines than this share of its products (and enough products) goes red; stage 1a gave 65%, batch A 74.5%
LOW_YIELD_MIN_PRODUCTS = 30
CHECKPOINT_EVERY = 50        # settled products between two saves
TRANSIENT = ("unavailable", "fetch_unavailable")
# Two guards added 2026-11-19 (owner's decision; the re-read of 23 silenced products on 19 Nov: 6 of 6 photo_unusable and 5 of 17 text_unusable read usable again):
SOFT = ("text_unusable", "photo_unusable")   # model-side silences: NOT final on the first try; they take the retry path (up to 3 attempts, then gave_up, read afresh after 14 days)
HOLD = 20                    # provisional: the newest HOLD results are held back, not settled, so a bad stretch can be undone (the products stay queued, no attempt charged)
MODEL_TROUBLE_MIN = 8        # provisional: this many model-side failures (SOFT or a model 503) among the newest results stop the night red as model_trouble (about 4.6% is normal)
MIN_LINES_IN_WINDOW = 3      # provisional: this many lines or fewer among a FULL window of HOLD results stop the night red as low_yield (about 67% is normal)


def run_night(state: dict, candidates: list[dict], readers, budget: Budget, night: str, canary_rows: list[dict], freeze_problems=fz.problems, model: str = pm.MODEL,
              checkpoint=None, checkpoint_every: int | None = None, off_streak: int | None = None) -> dict:
    """candidates: [{'code', 'stored', 'new': bool}] = every product whose flag is open tonight. Updates `state` in place; returns the night's summary.
    Order: freeze check, canary, then the queue (new, missed, backlog). Any Stop ends the night with its reason; products not finished stay in the queue untouched.
    A transient failure (OFF or the model did not answer) is charged to the product ONLY when a later product gets through (a line or a silence): in an outage, nobody is charged, and a run of
    `off_streak` failed fetches ends the night (red). `checkpoint(summary)` is called every `checkpoint_every` settled products, so a crash loses at most that many."""
    out = {"stopped": None, "canary": None, "lines": [], "silences": {}, "errors": {}, "products": 0, "merge": None, "invalid_candidates": 0}
    problems = freeze_problems()
    if problems:
        out["stopped"] = "freeze_broken"
        out["freeze_problems"] = problems
        return out
    every, limit = checkpoint_every or CHECKPOINT_EVERY, off_streak or OFF_STREAK
    pending: list[tuple[str, str]] = []                       # transient failures not yet charged
    held: list[tuple[str, dict]] = []                         # the newest results (a line or a silence), NOT yet settled in the queue: a Stop drops them and the products stay queued
    recent: list[str] = []                                    # what the newest HOLD products ended as: 'line', 'soft' (a model-side failure) or 'other'
    streak = settled = 0

    def fill() -> None:
        out["calls"] = budget.calls
        out["queue"] = ql.counts(state)

    def flush() -> None:
        for c, reason in pending:
            ql.settle(state, c, "error", night, reason)
        pending.clear()

    def settle_one(code: str, r: dict) -> None:
        nonlocal settled
        if r["outcome"] == "line":
            ql.settle(state, code, "line", night)
            out["lines"].append(r["line"])
        elif r["outcome"] == "silence" and r["reason"] not in SOFT:
            ql.settle(state, code, "silence", night, r["reason"])
            out["silences"][r["reason"]] = out["silences"].get(r["reason"], 0) + 1
        else:                                                 # a SOFT silence goes down the retry path, not into the final silences
            ql.settle(state, code, "error", night, r["reason"])
            out["errors"][r["reason"]] = out["errors"].get(r["reason"], 0) + 1
        settled += 1
        if checkpoint and settled % every == 0:
            fill()
            checkpoint(out)

    def watch(kind: str) -> None:
        """The rolling guards over the newest HOLD products. A Stop here leaves everything in `held` and `pending` unsettled."""
        recent.append(kind)
        del recent[:-HOLD]
        if recent.count("soft") >= MODEL_TROUBLE_MIN:
            raise Stop("model_trouble")
        if len(recent) == HOLD and recent.count("line") <= MIN_LINES_IN_WINDOW:
            raise Stop("low_yield")

    try:
        out["canary"] = run_canary(canary_rows, readers, budget, night, model)
        if not out["canary"]["passed"]:
            raise Stop("canary_failed")
        cands = {}
        for c in candidates:                                  # a candidate that cannot be hashed is skipped and counted, never fatal
            try:
                cands[c["code"]] = {**c, "record_hash": c.get("record_hash") or lr.record_hash(c["stored"])}
            except (KeyError, TypeError, ValueError):
                out["invalid_candidates"] += 1
        out["merge"] = ql.merge_candidates(state, list(cands.values()), night)
        for code in ql.take(state, night, 10 ** 9):
            if budget.remaining() < ql.CALLS_PER_PRODUCT:
                raise Stop("call_ceiling")
            r = process_product(cands[code], readers, budget, night, model)
            out["products"] += 1
            if r["outcome"] == "error" and r["reason"] in TRANSIENT:
                out["errors"][r["reason"]] = out["errors"].get(r["reason"], 0) + 1
                pending.append((code, r["reason"]))
                streak = streak + 1 if r["reason"] == "fetch_unavailable" else streak
                if streak >= limit:
                    raise Stop("off_unavailable")
                watch("soft" if r["reason"] == "unavailable" else "other")
                continue
            if r["outcome"] in ("line", "silence"):
                streak = 0
                flush()
                held.append((code, r))                        # settled only when HOLD newer products have come after it, or when the night ends normally
                while len(held) > HOLD:
                    settle_one(*held.pop(0))
                watch("line" if r["outcome"] == "line" else "soft" if r["reason"] in SOFT else "other")   # after the append: a guard Stop drops THIS result with the held ones
            else:                                             # a failure of this product alone: charged at once
                ql.settle(state, code, "error", night, r["reason"])
                out["errors"][r["reason"]] = out["errors"].get(r["reason"], 0) + 1
                watch("other")
        flush()                                               # the loop ended normally: the last failures stand
        lines_all = len(out["lines"]) + sum(1 for _, r in held if r["outcome"] == "line")
        if out["products"] >= LOW_YIELD_MIN_PRODUCTS and lines_all / out["products"] < LOW_YIELD:
            raise Stop("low_yield")                           # checked BEFORE the held results are settled: a bad night no longer burns its last products
        for code, r in held:
            settle_one(code, r)
        held.clear()
    except Stop as s:
        out["stopped"] = s.reason                             # pending failures are NOT charged: a Stop means the service, not the products, was the problem
        if s.reason in ("model_trouble", "low_yield"):
            if held:
                out["held_back"] = len(held)                  # the suspect stretch is thrown away unsettled: its products are still queued, no attempt charged
        else:                                                 # any other stop (the call ceiling is the NORMAL end, an outage, a wrong model): what was read before it stands, as it always did
            for code, r in held:
                settle_one(code, r)
            held.clear()
    fill()
    return out
