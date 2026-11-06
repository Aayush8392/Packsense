import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "bootstrap"))
import report_sealed_test as rs  # noqa: E402


def row(action, stored_right=True, proposal_right=None, height=25.0):
    return {"code": "x", "action": action, "stored_right": stored_right, "proposal_right": proposal_right, "height": height}


def test_wilson_known_values():
    lo, hi = rs.wilson(46, 50)
    assert round(lo, 3) == 0.812 and round(hi, 3) == 0.968      # 46 of 50 passes the bar (lower bound at least 0.80)
    lo45, _ = rs.wilson(45, 50)
    assert lo45 < 0.80          # 45 of 50 does not pass
    assert rs.wilson(0, 0) == (0.0, 0.0)


def test_a2026_examples_of_the_bar():
    def run(right, n):
        return rs.summarise([row("change to reading", False, i < right) for i in range(n)])["bar"]
    assert run(46, 50) == "PASS"
    assert run(45, 50) == "FAIL"             # 90% point, lower bound under 80%
    assert run(37, 40) == "PASS"
    assert run(36, 40) == "FAIL"
    assert run(30, 30).startswith("INCONCLUSIVE")


def test_band_edges():
    assert rs.band_of(14.9) == "under 15 px" and rs.band_of(15) == "15 to 20 px" and rs.band_of(49.9) == "30 to 50 px" and rs.band_of(50) == "50 px and up"
    assert rs.band_of(None) == "no word height"


def test_planted_violations_are_counted():
    rows = [row("change to reading", False, True)] * 3 + [row("change to reading", False, False)] + [row("no change", True)] * 2 + [row("no change", False)] + [row("abstain (x)")] * 4
    s = rs.summarise(rows)
    assert (s["proposals"]["k"], s["proposals"]["n"]) == (3, 4)
    assert (s["match_verdicts"]["k"], s["match_verdicts"]["n"]) == (2, 3)
    assert s["silent_misses"]["k"] == 1 and s["abstentions"]["k"] == 4 and s["coverage"]["k"] == 7 and s["cards"] == 11


def test_band_switch_needs_15_and_lower_bound():
    few = rs.summarise([row("fill in", False, True, 40.0)] * 14)["bands"]["30 to 50 px"]
    assert few["switched_on"] is False
    enough = rs.summarise([row("fill in", False, True, 40.0)] * 20)["bands"]["30 to 50 px"]
    assert enough["switched_on"] is True
    weak = rs.summarise([row("fill in", False, i < 14, 40.0) for i in range(20)])["bands"]["30 to 50 px"]
    assert weak["switched_on"] is False
