"""Two new ways to turn word boxes into text for the pack-text reader (development; scan_layout.py is NOT changed, so the frozen method keeps its own text).

The old `rows_text` puts every word on its row by height and marks wide gaps with ' | '. On a label with two panels side by side (a common US layout) the left panel's row and the right panel's row
land on the same line and the reader has to tell them apart. Both functions here work from boxes ({text, x0, x1, y0, y1, block}), from any OCR engine, so the same renderers can be used for
Google Vision (OFF's stored scan) and for other engines:

  layout_text(words)  the words keep their horizontal position (like `pdftotext -layout`): a row is padded with spaces so that words that sit above each other stay above each other,
                      and two panels side by side stay visibly apart.
  block_text(words)   each text block the engine found is rebuilt on its own (rows inside the block, ' | ' for wide gaps) and the blocks follow one another, separated by a blank line.

Pure code, no model call.
"""
from __future__ import annotations

import math
from statistics import median


def google_words(scan: dict) -> list[dict]:
    """Boxes from OFF's stored Google Vision scan, page tilt corrected: [{text, x0, x1, y0, y1, block}]."""
    raw = []
    for resp in scan.get("responses") or []:
        for page in ((resp.get("fullTextAnnotation") or {}).get("pages") or []):
            for b, block in enumerate(page.get("blocks") or []):
                for par in block.get("paragraphs") or []:
                    for w in par.get("words") or []:
                        v = (w.get("boundingBox") or {}).get("vertices") or []
                        text = "".join(s.get("text", "") for s in w.get("symbols") or [])
                        if len(v) == 4 and text:
                            raw.append((text, b, [(p.get("x", 0), p.get("y", 0)) for p in v]))
    return straighten(raw)


def straighten(raw: list[tuple[str, int, list[tuple[float, float]]]]) -> list[dict]:
    """raw = (text, block, four corner points). Rotates every point by minus the median baseline angle so rows are horizontal and returns upright boxes."""
    if not raw:
        return []
    angles = [math.degrees(math.atan2(p[1][1] - p[0][1], p[1][0] - p[0][0])) for _, _, p in raw]
    a = math.radians(median(angles))
    c, s = math.cos(-a), math.sin(-a)
    out = []
    for text, block, pts in raw:
        rot = [(x * c - y * s, x * s + y * c) for x, y in pts]
        xs, ys = [p[0] for p in rot], [p[1] for p in rot]
        out.append({"text": text, "x0": min(xs), "x1": max(xs), "y0": min(ys), "y1": max(ys), "block": block})
    return out


def _rows(words: list[dict], row_factor: float = 0.55) -> list[list[dict]]:
    if not words:
        return []
    h = median(max(w["y1"] - w["y0"], 1.0) for w in words)
    ordered = sorted(words, key=lambda w: (w["y0"] + w["y1"]) / 2)
    rows: list[list[dict]] = []
    for w in ordered:
        cy = (w["y0"] + w["y1"]) / 2
        if rows and abs(cy - sum((x["y0"] + x["y1"]) / 2 for x in rows[-1]) / len(rows[-1])) <= row_factor * h:
            rows[-1].append(w)
        else:
            rows.append([w])
    return [sorted(r, key=lambda w: w["x0"]) for r in rows]


def layout_text(words: list[dict], columns: int = 140) -> str:
    """Rows of words placed at their horizontal position on a grid of `columns` characters across the page width (a word never overlaps the one before it)."""
    if not words:
        return ""
    left, right = min(w["x0"] for w in words), max(w["x1"] for w in words)
    char_w = max((right - left) / columns, 1e-6)
    lines = []
    for row in _rows(words):
        line = ""
        for w in row:
            pos = int((w["x0"] - left) / char_w)
            if line and pos < len(line) + 1:
                pos = len(line) + 1
            line += " " * (pos - len(line)) + w["text"]
        lines.append(line.rstrip())
    return "\n".join(lines)


def block_text(words: list[dict], gap_factor: float = 2.0) -> str:
    """Each engine block on its own: rows inside the block, ' | ' for a wide gap, a blank line between blocks (in the engine's own block order)."""
    if not words:
        return ""
    h = median(max(w["y1"] - w["y0"], 1.0) for w in words)
    out = []
    for b in sorted({w["block"] for w in words}):
        lines = []
        for row in _rows([w for w in words if w["block"] == b]):
            parts = [row[0]["text"]]
            for prev, w in zip(row, row[1:]):
                gap = w["x0"] - prev["x1"]
                parts.append(" | " if gap > gap_factor * h else " ")
                parts.append(w["text"])
            lines.append("".join(parts))
        out.append("\n".join(lines))
    return "\n\n".join(out)
