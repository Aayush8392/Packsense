"""Tests for the nightly entry point (nightly/run_nightly.py): setup errors, the three modes, exit codes, counts-only output, red nights still written."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "bootstrap"))
import photo_method as pm  # noqa: E402
from nightly import budget as bd  # noqa: E402
from nightly import run_nightly as rn  # noqa: E402
from nightly import night as nt_module  # noqa: E402
from nightly import store as st  # noqa: E402

TEXT = "Nutrition facts per 100 g Energy 376 kJ / 90 kcal Fat 0.5 g Saturates 0.3 g Carbohydrate 8.9 g Sugars 6.5 g Protein 12.4 g Salt 0.06 g"
VALUES = {"energy_kcal": 90, "energy_kj": 376, "fat": 0.5, "saturated_fat": 0.3, "carbohydrates": 8.9, "sugars": 6.5, "proteins": 12.4, "salt": 0.06}
STORED = {k: float(v) for k, v in VALUES.items()}
ENV = {"HF_NIGHTLY_REPO": "owner/real", "HF_NIGHTLY_SCRATCH_REPO": "owner/scratch", "HF_NIGHTLY_WRITE_TOKEN": "t", "GEMINI_API_KEY": "k"}


class Backend:
    def __init__(self, files=None):
        self.files, self.commits, self.repo = dict(files or {}), [], None

    def read(self, path):
        return self.files.get(path)

    def commit(self, files, message):
        self.commits.append(message)
        self.files.update(files)


def inputs(n=3, canary=3, exported="2026-11-13"):
    cands = [{"code": f"3000000{i}", "stored": STORED, "new": i == 0} for i in range(n)]
    can = [{"code": f"2000000{i}", "stored": STORED, "expected": VALUES} for i in range(canary)]
    return {st.CANDIDATES: json.dumps({"exported": exported, "candidates": cands}).encode(), st.CANARY: json.dumps({"canary": can}).encode()}


def entry(values=VALUES, model=pm.MODEL):
    return {"reading": {"basis": "per 100 g", "serving_size": None, "values_per_100": dict(values)}, "model": model}


class Readers:
    def __init__(self, fail_fetch=False, model=pm.MODEL, photo=True):
        self.fail_fetch, self.model, self.photo, self.calls = fail_fetch, model, photo, 0

    def fetch(self, code):
        if self.fail_fetch:
            raise ConnectionError("refused")
        return {"has_photo": self.photo, "ocr_text": TEXT, "photo": b"x" if self.photo else None}

    def text_reader(self, code, text, prior=None):
        self.calls += 1
        return entry(model=self.model)

    def photo_reader(self, code, photo):
        self.calls += 1
        return entry(model=self.model)


def go(mode, backend, readers, out, env=ENV, freeze=lambda: [], **kw):
    return rn.run(mode, env, "2026-11-13", backend_factory=lambda repo, tok: backend, readers_factory=lambda e, need: readers, freeze_problems=freeze,
                  budget_factory=lambda **b: bd.Budget(sleep=lambda s: None, **b), out=out.append, **kw)


def test_a_missing_variable_is_a_setup_error_named_without_values():
    out = []
    assert go("real", Backend(inputs()), Readers(), out, env={"HF_NIGHTLY_REPO": "x"}) == 2
    assert out == ["setup error: missing HF_NIGHTLY_WRITE_TOKEN, GEMINI_API_KEY"]
    out = []
    assert go("fetch-only", Backend(inputs()), Readers(), out, env={"HF_NIGHTLY_REPO": "x", "HF_NIGHTLY_WRITE_TOKEN": "t"}) == 0          # no model key needed


def test_a_missing_input_file_is_an_input_error_and_nothing_is_written():
    b, out = Backend({st.CANDIDATES: inputs()[st.CANDIDATES]}), []
    assert go("real", b, Readers(), out) == 2 and out == ["input error: missing input file input/canary.json"] and b.commits == []


def test_fetch_only_counts_fetches_and_writes_nothing_and_calls_no_model():
    b, r, out = Backend(inputs(n=5)), Readers(), []
    assert go("fetch-only", b, r, out, limit=4) == 0
    assert b.commits == [] and r.calls == 0 and out[0].startswith("fetch-only: 4 products, 4 fetched, errors none, with a photo 4, with a table in the scan 4")


def test_fetch_only_goes_red_on_any_failed_fetch_and_counts_the_kind():
    out = []
    assert go("fetch-only", Backend(inputs()), Readers(fail_fetch=True), out) == 1 and "errors {'ConnectionError': 3}" in out[0]


def test_a_real_night_writes_one_commit_and_prints_counts_only():
    b, out = Backend(inputs()), []
    assert go("real", b, Readers(), out) == 0
    assert len(b.commits) == 1 and "3 lines" in b.commits[0]
    assert "stopped None" in out[0] and "lines 3" in out[0] and "canary 3/3" in out[0] and "3000000" not in out[0] and "2000000" not in out[0]
    assert sorted(json.loads(b.files[st.CURRENT])) == ["30000000", "30000001", "30000002"]


def test_the_call_ceiling_is_a_normal_end_and_the_cap_comes_from_the_argument():
    b, out = Backend(inputs(n=10)), []
    assert go("real", b, Readers(), out, max_calls=6 + 4) == 0 and "stopped call_ceiling" in out[0] and "lines 2" in out[0]


def test_red_stops_exit_1_and_still_write_the_run_record():
    b, out = Backend(inputs()), []
    assert go("real", b, Readers(), out, freeze=lambda: ["p8_steward/guard_v2.py"]) == 1 and "stopped freeze_broken" in out[0]
    assert len(b.commits) == 1 and json.loads(b.files["runs/2026-11-13.json"])["stopped"] == "freeze_broken"
    b, out = Backend(inputs()), []
    assert go("real", b, Readers(model="gemini-other"), out) == 1 and "stopped model_mismatch" in out[0]


def test_scratch_mode_reads_the_scratch_variable_not_the_real_one():
    seen = []
    rn.run("scratch", ENV, "n", backend_factory=lambda repo, tok: seen.append(repo) or Backend(inputs()), readers_factory=lambda e, need: Readers(),
           freeze_problems=lambda: [], budget_factory=lambda **b: bd.Budget(sleep=lambda s: None, **b), out=lambda s: None)
    assert seen == ["owner/scratch"]


# ---------------------------------------------------------------- hardening (2026-11-13)
class FlakyBackend(Backend):
    """Every commit fails (fail_from=0) or only the ones from the n-th on."""

    def __init__(self, files=None, fail_from=0):
        super().__init__(files)
        self.n, self.fail_from = 0, fail_from

    def commit(self, files, message):
        self.n += 1
        if self.n > self.fail_from:
            raise st.StoreError("saving to the results dataset failed after 3 tries (ConnectionError)")
        super().commit(files, message)


def test_a_real_night_refuses_a_stale_export_but_scratch_and_fetch_only_do_not():
    old = inputs(exported="2026-11-01")
    out = []
    assert go("real", Backend(old), Readers(), out) == 2 and "export is 12 days old" in out[0]
    assert go("scratch", Backend(old), Readers(), []) == 0
    assert go("fetch-only", Backend(old), Readers(), []) == 0


def test_a_failed_final_save_is_exit_3_with_the_loss_stated_and_no_values_printed():
    b, out = FlakyBackend(inputs()), []
    assert go("real", b, Readers(), out) == 3
    assert out[0].startswith("save error: saving to the results dataset failed after 3 tries (ConnectionError); this night's 3 lines") and "3000000" not in out[0]


def test_checkpoints_save_progress_during_the_night_and_a_failed_checkpoint_does_not_stop_it(monkeypatch):
    monkeypatch.setattr(nt_module, "CHECKPOINT_EVERY", 2)
    b, out = Backend(inputs(n=7)), []
    assert go("real", b, Readers(), out) == 0
    assert len(b.commits) == 4 and "checkpoints 3 (failed 0)" in out[0]                      # 7 products: checkpoints after 2, 4 and 6, then the final save
    b2, out2 = FlakyBackend(inputs(n=7), fail_from=0), []
    assert go("real", b2, Readers(), out2) == 3 and b2.n == 4                               # every save fails: three checkpoints and the final one were tried


def test_an_off_outage_is_a_red_night_that_still_writes_its_record_and_charges_nobody():
    class OffDown(Readers):
        def fetch(self, code):
            if code.startswith("2"):
                return super().fetch(code)
            raise rn.nt.TransientError("OFF answered HTTP 503")

    b, out = Backend(inputs(n=9)), []
    assert go("real", b, OffDown(), out) == 1 and "stopped off_unavailable" in out[0]
    assert json.loads(b.files["queue.json"])["done"] == {} and all(i["attempts"] == 0 for i in json.loads(b.files["queue.json"])["items"].values())


def test_the_summary_counts_invalid_candidates_without_naming_them():
    files = inputs(n=40)
    doc = json.loads(files[st.CANDIDATES])
    doc["candidates"].append({"code": "30000099", "stored": {"fat": "abc"}, "new": False})
    files[st.CANDIDATES] = json.dumps(doc).encode()
    out = []
    assert go("real", Backend(files), Readers(), out) == 0 and "invalid candidates 1" in out[0] and "30000099" not in out[0]
