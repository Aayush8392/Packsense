import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import scan_layout2 as sl  # noqa: E402


def box(text, x, y, block=0, w=None, h=10):
    w = w if w is not None else len(text) * 6
    return text, block, [(x, y), (x + w, y), (x + w, y + h), (x, y + h)]


# two panels side by side on the same three rows: left = fats, right = sodium and carbohydrate
RAW = [box("Total", 0, 0, 0), box("Fat", 40, 0, 0), box("2.5g", 62, 0, 0), box("Sodium", 400, 0, 1), box("10mg", 460, 0, 1),
       box("Saturated", 0, 20, 0), box("Fat", 60, 20, 0), box("0.5g", 90, 20, 0), box("Carbohydrate", 400, 20, 1), box("39g", 480, 20, 1),
       box("Trans", 0, 40, 0), box("Fat", 40, 40, 0), box("0g", 70, 40, 0), box("Fibre", 400, 40, 1), box("2g", 450, 40, 1)]


def test_layout_text_keeps_the_two_panels_apart_and_aligned():
    t = sl.layout_text(sl.straighten(RAW), columns=100)
    lines = t.splitlines()
    assert len(lines) == 3
    assert lines[0].split()[:3] == ["Total", "Fat", "2.5g"] and lines[0].split()[3:] == ["Sodium", "10mg"] and lines[0].index("Sodium") > 50          # the right panel stays far to the right
    col = [ln.index(w) for ln, w in zip(lines, ("Sodium", "Carbohydrate", "Fibre"))]
    assert col[0] == col[1] == col[2]                                                                         # words that sit above each other stay above each other


def test_block_text_reads_each_block_on_its_own():
    t = sl.block_text(sl.straighten(RAW))
    left, right = t.split("\n\n")
    assert "Total Fat 2.5g" in left and "Saturated Fat 0.5g" in left and "Sodium" not in left
    assert right.splitlines() == ["Sodium | 10mg", "Carbohydrate 39g", "Fibre 2g"]           # the wide gap on the first row is marked


def test_empty_scan_gives_empty_text():
    assert sl.layout_text([]) == "" and sl.block_text([]) == "" and sl.google_words({}) == []


def test_tilt_is_corrected():
    tilted = [(t, b, [(x * 0.97 - y * 0.24, x * 0.24 + y * 0.97) for x, y in pts]) for t, b, pts in RAW]      # about 14 degrees
    assert len(sl.layout_text(sl.straighten(tilted), columns=100).splitlines()) == 3
