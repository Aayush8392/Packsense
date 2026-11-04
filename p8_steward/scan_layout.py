"""Rebuilds the table rows of a nutrition photo from OFF's own scan (Google Vision output) using WORD POSITIONS (item 23, development).

OFF's plain scan text comes in reading blocks, so a table often arrives as all the row names first and all the numbers after them, and a model has to guess which number belongs to which
row. The raw scan also holds a box for every word. This module puts every word back on its row by its position: it corrects the page's tilt, groups words whose centres are on the same
height into one line, orders each line left to right and marks wide gaps between words with ' | '. Pure code, no model call.
"""
from __future__ import annotations

import math
from statistics import median


def words_of(scan: dict) -> list[dict]:
    """Every word of the scan as {text, cx, cy, h, angle} (centre, height and the angle of its baseline, from its four corner points)."""
    out = []
    for resp in scan.get("responses") or []:
        for page in ((resp.get("fullTextAnnotation") or {}).get("pages") or []):
            for block in page.get("blocks") or []:
                for par in block.get("paragraphs") or []:
                    for w in par.get("words") or []:
                        v = (w.get("boundingBox") or {}).get("vertices") or []
                        text = "".join(s.get("text", "") for s in w.get("symbols") or [])
                        if len(v) != 4 or not text:
                            continue
                        xs, ys = [p.get("x", 0) for p in v], [p.get("y", 0) for p in v]
                        angle = math.degrees(math.atan2(ys[1] - ys[0], xs[1] - xs[0]))
                        side = math.hypot(xs[3] - xs[0], ys[3] - ys[0])           # the word's height along its own vertical edge
                        out.append({"text": text, "cx": sum(xs) / 4.0, "cy": sum(ys) / 4.0, "h": max(side, 1.0), "angle": angle})
    return out


def _straighten(words: list[dict]) -> list[dict]:
    """Rotate every word centre by minus the median baseline angle so rows are horizontal (a tilted or sideways photo)."""
    if not words:
        return words
    a = math.radians(median(w["angle"] for w in words))
    c, s = math.cos(-a), math.sin(-a)
    return [{**w, "cx": w["cx"] * c - w["cy"] * s, "cy": w["cx"] * s + w["cy"] * c} for w in words]


def rows_text(scan: dict, gap_factor: float = 2.0, row_factor: float = 0.55) -> str:
    """The scan as text lines, one per row of words, wide gaps marked ' | '. Empty string when the scan has no words."""
    words = _straighten(words_of(scan))
    if not words:
        return ""
    h = median(w["h"] for w in words)
    words.sort(key=lambda w: w["cy"])
    rows: list[list[dict]] = []
    for w in words:
        if rows and abs(w["cy"] - sum(x["cy"] for x in rows[-1]) / len(rows[-1])) <= row_factor * h:
            rows[-1].append(w)
        else:
            rows.append([w])
    lines = []
    for row in rows:
        row.sort(key=lambda w: w["cx"])
        parts = [row[0]["text"]]
        for prev, w in zip(row, row[1:]):
            parts.append(" | " if w["cx"] - prev["cx"] > gap_factor * h * max(1.0, (len(prev["text"]) + len(w["text"])) / 2.0) else " ")
            parts.append(w["text"])
        lines.append("".join(parts))
    return "\n".join(lines)
