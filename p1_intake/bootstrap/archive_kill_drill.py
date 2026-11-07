"""Archive kill drill, P9: cancel the archive job's notebook while it is archiving, then run it again.

The notebook uploads in batches and writes the archive manifest last, after Hugging Face reports the stored bytes. So a kill must leave
a manifest that names only files that are stored with the right bytes, and the re-run must archive the rest. This drill checks that
against a SCRATCH Hugging Face repo (the real archive already holds every file, so it cannot show it).

Safety: the drill repo name must end with '-drill' and be private (the helper and the notebook refuse otherwise); B2 is only read; the real
archive repo is only read (its manifest, for the expected sha256 of each file). The production archive job is not touched, and the script
refuses to start while it is running.

  python p1_intake/bootstrap/archive_kill_drill.py plan --env-file PATH [--files 6]
  python p1_intake/bootstrap/archive_kill_drill.py run  --env-file PATH [--files 6] [--fractions 0.2,0.3] [--full-seconds 66] [--branch main]
Environment: DATABRICKS_HOST, DATABRICKS_TOKEN (admin). Values are never printed. The notebooks read the archive token and the B2 read key
from the secret scope as the admin.

How it works: a baseline run (no kill) archives the chosen files into the drill repo and measures how long a full run takes. Then, per
fraction f, the repo is emptied, a run is started and CANCELLED at f x that duration, the repo is inspected, and the same run is started
again. A kill cannot be aimed exactly: each trial records which window it landed in ("before the first batch" is a void trial).
"""
import argparse
import base64
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "p2_lakehouse" / "bootstrap"))
import crash_test as ct  # noqa: E402  (client, submit, wait_terminal, run_output, load_env_file)

ARCHIVE_NB = "p1_intake/notebooks/archive_to_hf"
REAL_REPO = "Anonymous8392/packsense-archive"
DRILL_REPO = "Anonymous8392/packsense-archive-drill"

HELPER = '''# Databricks notebook source
# MAGIC %pip install -q huggingface_hub

# COMMAND ----------
import json
from huggingface_hub import CommitOperationAdd, CommitOperationDelete, HfApi, hf_hub_download
dbutils.widgets.text("mode", "inspect")
dbutils.widgets.text("real_repo", "")
dbutils.widgets.text("drill_repo", "")
dbutils.widgets.text("keys", "")
mode, real, drill = dbutils.widgets.get("mode"), dbutils.widgets.get("real_repo"), dbutils.widgets.get("drill_repo")
keys = [k for k in dbutils.widgets.get("keys").split(",") if k]
assert drill.endswith("-drill") and drill != real, "refusing to touch anything but the drill repo"
token = dbutils.secrets.get("packsense", "hf_archive_token")
api = HfApi(token=token)
assert api.repo_info(drill, repo_type="dataset").private, "the drill repo must be private"

def real_manifest():
    p = hf_hub_download(real, "archive/manifest.json", repo_type="dataset", token=token, local_dir="/tmp/hf_kill_real", force_download=True)
    return json.load(open(p))

def stored():
    out = {}
    try:
        for i in api.list_repo_tree(drill, path_in_repo="raw", recursive=True, repo_type="dataset", expand=True):
            if getattr(i, "size", None) is not None:
                out[i.path] = getattr(getattr(i, "lfs", None), "sha256", None)
    except Exception:
        pass
    return out

if mode == "reset":
    old = [p for p in api.list_repo_files(drill, repo_type="dataset")]
    empty = {"manifest_version": real_manifest()["manifest_version"], "files": {}}
    ops = [CommitOperationDelete(path_in_repo=p) for p in old if p != "archive/manifest.json"]
    ops.append(CommitOperationAdd(path_in_repo="archive/manifest.json", path_or_fileobj=json.dumps(empty, indent=1, sort_keys=True).encode()))
    api.create_commit(repo_id=drill, repo_type="dataset", operations=ops, commit_message="drill reset")
    dbutils.notebook.exit(json.dumps({"deleted": len(ops) - 1}))
elif mode == "inspect":
    try:
        m = json.load(open(hf_hub_download(drill, "archive/manifest.json", repo_type="dataset", token=token, local_dir="/tmp/hf_kill_drill", force_download=True)))
    except Exception:
        m = {"files": {}}
    rm = real_manifest()["files"]
    dbutils.notebook.exit(json.dumps({"manifest": {k: v.get("sha256") for k, v in m["files"].items()}, "stored": stored(),
                                      "real": {k: (rm.get(k) or {}).get("sha256") for k in keys}}))
'''


# ---- pure logic (unit-tested) ------------------------------------------------------------------------------------------

def pick_smallest(sizes: dict, n: int) -> list:
    """B2 keys of the n smallest delta files in landing (smallest B2 download for the drill)."""
    names = sorted((k for k in sizes if k.startswith("openfoodfacts_products_") and k.endswith(".json.gz")), key=lambda k: (sizes[k], k))
    if len(names) < n:
        raise ValueError(f"need {n} delta files, found {len(names)}")
    return ["raw/deltas/" + k for k in names[:n]]


def cancel_after(full_seconds: float, fraction: float) -> float:
    if full_seconds <= 0 or not 0 < fraction < 1:
        raise ValueError("need a measured full run and a fraction between 0 and 1")
    return full_seconds * fraction


def window(recorded: set, stored: set, all_keys: set) -> str:
    """Where a killed run stopped, from the manifest (recorded) and the repo (stored)."""
    if not recorded and not stored:
        return "before the first batch"
    if stored - recorded:
        return "after an upload, before its manifest write (the risky window)"
    if recorded >= all_keys:
        return "after the last manifest write (nothing left to do)"
    return "between batches"


def counts_as_kill(win: str) -> bool:
    """Only a cancel that landed while the run was still archiving tests anything: before the first batch and after the last manifest write do not."""
    return win == "between batches" or "risky window" in win


def overall_verdict(results: list) -> str:
    """FAIL on any problem anywhere; INCONCLUSIVE when no cancel landed mid-run; PASS only with at least one real kill and no problems."""
    if not results:
        return "FAIL (no runs)"
    bad = [x for x in results if x.get("problems") or x.get("state_problems") or x.get("final_problems")]
    if bad:
        return f"FAIL ({len(bad)} run(s) with problems)"
    trials = [x for x in results if x.get("trial") != "baseline"]
    real = [x for x in trials if counts_as_kill(x.get("window", ""))]
    if not real:
        return f"INCONCLUSIVE (0 of {len(trials)} cancels landed mid-run: each came after the run had finished archiving or before it started)"
    return f"PASS ({len(real)} of {len(trials)} cancels landed mid-run, no problems)"


def state_problems(manifest: dict, stored: dict, real: dict) -> list:
    """After a kill: every file the manifest records must be stored with the real bytes and recorded with the real hash.
    Files stored but not recorded are allowed (the re-run uploads them again)."""
    problems = []
    for k, sha in manifest.items():
        if real.get(k) and sha != real[k]:
            problems.append(f"{k}: the manifest records a hash that is not the real file's")
        if k not in stored:
            problems.append(f"{k}: recorded but not stored in the repo")
        elif real.get(k) and stored[k] != real[k]:
            problems.append(f"{k}: stored with different bytes than the real archive")
    return problems


def final_problems(all_keys: list, manifest: dict, stored: dict, real: dict) -> list:
    """After the re-run: all chosen files recorded and stored with the real bytes, and nothing else in the repo."""
    problems = state_problems(manifest, stored, real)
    problems += [f"{k}: not recorded after the re-run" for k in all_keys if k not in manifest]
    problems += [f"{k}: not stored after the re-run" for k in all_keys if k not in stored]
    problems += [f"{k}: stored outside the chosen set" for k in stored if k not in set(all_keys)]
    return problems


# ---- Databricks side ---------------------------------------------------------------------------------------------------

def landing_sizes(w) -> dict:
    return {i.name: i.file_size for i in w.files.list_directory_contents(f"{ct.LANDING}/deltas") if not i.is_directory}


def refuse_if_archive_job_active(w):
    active = [r for r in w.jobs.list_runs(active_only=True) if (r.run_name or "") == "packsense-archive"]
    if active:
        sys.exit("the production archive job is running: wait for it, then start the drill")


def cmd_plan(w, args):
    sizes = landing_sizes(w)
    keys = pick_smallest(sizes, args.files)
    mb = sum(sizes[k.split("/")[-1]] for k in keys) / 1e6
    print(f"{len(keys)} smallest delta files, {mb:.0f} MB:")
    for k in keys:
        print("  ", k, f"{sizes[k.split('/')[-1]] / 1e6:.1f} MB")
    print(f"B2 download estimate: baseline {mb:.0f} MB + per trial up to {2 * mb:.0f} MB (a partial run, then the rest) "
          f"= {mb + 2 * mb * 2:.0f} MB for 2 trials, against B2's 1 GB free daily download (other users of B2 today: the daily archive run, about one new file)")


def helper_step(w, nb, label, mode, keys, log):
    params = {"mode": mode, "real_repo": REAL_REPO, "drill_repo": DRILL_REPO, "keys": ",".join(keys)}
    waiter = ct.submit(w, f"packsense-archive-drill-{label}", nb, params, workspace=True)
    res, r = ct.wait_terminal(w, waiter.run_id)
    text, err = ct.run_output(w, r)
    log.append({"label": label, "run_id": waiter.run_id, "result": res})
    if res != "SUCCESS":
        raise RuntimeError(f"helper {label} ended {res}: {err}")
    return json.loads(text)


def archive_params(keys, run_id):
    return {"run_id": run_id, "secret_scope": "packsense", "hf_repo": DRILL_REPO, "batch_size": "1", "ping_healthchecks": "false",
            "only_keys": ",".join(keys), "dry_run": "false"}


def seconds_of(r) -> float:
    return ((r.end_time or 0) - (r.start_time or 0)) / 1000


def cmd_run(w, args):
    refuse_if_archive_job_active(w)
    sizes = landing_sizes(w)
    keys = pick_smallest(sizes, args.files)
    fractions = [float(x) for x in args.fractions.split(",") if x]
    nb = ct.helper_notebook_path(w).replace("crash_test_copy", "archive_kill_drill_helper")
    log, results, active = [], [], []
    before = {"real": {}}
    try:
        from databricks.sdk.service.workspace import ImportFormat, Language
        w.workspace.import_(path=nb, content=base64.b64encode(HELPER.encode()).decode(), format=ImportFormat.SOURCE,
                            language=Language.PYTHON, overwrite=True)
        before = helper_step(w, nb, "inspect-real-before", "inspect", keys, log)
        print("drill repo reset:", helper_step(w, nb, "reset-0", "reset", keys, log), flush=True)

        full = args.full_seconds
        if full is None:
            # baseline: a full run, no kill; measures the duration the kill times are fractions of
            waiter = ct.submit(w, "packsense-archive-drill-baseline", ARCHIVE_NB, archive_params(keys, "kill-drill-base"), args.branch)
            active.append(waiter.run_id)
            res, r = ct.wait_terminal(w, waiter.run_id)
            text, err = ct.run_output(w, r)
            full = seconds_of(r)
            log.append({"label": "baseline", "run_id": waiter.run_id, "result": res, "seconds": full})
            st = helper_step(w, nb, "inspect-baseline", "inspect", keys, log)
            probs = final_problems(keys, st["manifest"], st["stored"], st["real"]) if res == "SUCCESS" else [f"baseline run ended {res}: {err}"]
            print(f"baseline: {res} in {full:.0f} s {text[:160]} -> problems: {probs or 'none'}", flush=True)
            results.append({"trial": "baseline", "problems": probs})
            if res != "SUCCESS":
                return 1

        for i, f in enumerate(fractions, 1):
            helper_step(w, nb, f"reset-{i}", "reset", keys, log)
            waiter = ct.submit(w, f"packsense-archive-drill-kill-{i}", ARCHIVE_NB, archive_params(keys, f"kill-drill-{i}"), args.branch)
            active.append(waiter.run_id)
            target = cancel_after(full, f)
            cancelled_at = None
            while True:
                life, _, r = ct.run_state(w, waiter.run_id)
                if life in ct.TERMINAL:
                    break
                started = (r.start_time or 0) / 1000
                if started and time.time() - started >= target:
                    cancelled_at = time.time() - started
                    w.jobs.cancel_run(waiter.run_id)
                    break
                time.sleep(1)
            kres, kr = ct.wait_terminal(w, waiter.run_id, 10)
            log.append({"label": f"kill-{i}", "run_id": waiter.run_id, "result": kres, "seconds": seconds_of(kr)})
            time.sleep(8)   # let any in-flight write settle before looking
            st = helper_step(w, nb, f"inspect-kill-{i}", "inspect", keys, log)
            win = window(set(st["manifest"]), set(st["stored"]), set(keys))
            sp = state_problems(st["manifest"], st["stored"], st["real"])
            lag = f"{seconds_of(kr) - cancelled_at:.0f} s" if cancelled_at is not None else "n/a"
            print(f"trial {i}: cancel sent at {target:.0f} s of a {full:.0f} s run, it took effect {lag} later (run ended {kres}); recorded {len(st['manifest'])}, stored {len(st['stored'])} of {len(keys)}"
                  f" -> window: {win}; state problems: {sp or 'none'}", flush=True)
            rw = ct.submit(w, f"packsense-archive-drill-recover-{i}", ARCHIVE_NB, archive_params(keys, f"kill-drill-{i}-recover"), args.branch)
            active.append(rw.run_id)
            rres, rr = ct.wait_terminal(w, rw.run_id)
            rtext, rerr = ct.run_output(w, rr)
            log.append({"label": f"recover-{i}", "run_id": rw.run_id, "result": rres, "seconds": seconds_of(rr)})
            st2 = helper_step(w, nb, f"inspect-recover-{i}", "inspect", keys, log)
            fp = final_problems(keys, st2["manifest"], st2["stored"], st2["real"]) if rres == "SUCCESS" else [f"re-run ended {rres}: {rerr}"]
            print(f"   re-run: {rres} in {seconds_of(rr):.0f} s {rtext[:160]} -> problems: {fp or 'none'}", flush=True)
            results.append({"trial": i, "fraction": f, "killed_run": kres, "window": win, "state_problems": sp, "final_problems": fp})
        return 0
    finally:
        for rid in active:
            try:
                life, _, _ = ct.run_state(w, rid)
                if life not in ct.TERMINAL:
                    w.jobs.cancel_run(rid)
            except Exception:
                pass
        try:
            helper_step(w, nb, "reset-end", "reset", keys, log)
            after = helper_step(w, nb, "inspect-real-after", "inspect", keys, log)
            print("real archive manifest entries for the chosen files, before and after:",
                  sum(1 for v in before["real"].values() if v), "->", sum(1 for v in after["real"].values() if v), "(the real archive is only read)")
        except Exception as e:
            print("final reset failed:", type(e).__name__, "(empty the drill repo by hand)")
        try:
            w.workspace.delete(nb)
        except Exception as e:
            print("helper notebook not deleted:", type(e).__name__)
        print("RESULTS:", json.dumps(results))
        print("VERDICT:", overall_verdict(results))
        print("COST: notebook seconds per run:", {x["label"]: round(x.get("seconds", 0)) for x in log if x.get("seconds")}, "; run ids saved for `usage`")
        (Path(ct.tempfile.gettempdir()) / "packsense_archive_kill_drill.json").write_text(json.dumps({"runs": log, "results": results}, indent=1), encoding="utf-8")


def cmd_usage(w, args):
    p = Path(ct.tempfile.gettempdir()) / "packsense_archive_kill_drill.json"
    if not p.exists():
        sys.exit(f"no state file {p}: run the drill first")
    ids = ",".join(str(x["run_id"]) for x in json.loads(p.read_text(encoding="utf-8"))["runs"])
    q = ct.Sql(w)
    print("DBU of the drill's runs:", q.run(f"SELECT sku_name, round(sum(usage_quantity), 3) FROM system.billing.usage WHERE usage_metadata.job_run_id IN ({ids}) GROUP BY sku_name") or "no rows yet")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("command", choices=["plan", "run", "usage"])
    ap.add_argument("--env-file", required=True)
    ap.add_argument("--files", type=int, default=6)
    ap.add_argument("--fractions", default="0.2,0.3", help="kill times as fractions of the measured full run (a cancel takes 20 to 35 s to take effect)")
    ap.add_argument("--full-seconds", type=float, default=None, help="reuse a measured full-run duration and skip the baseline run (saves one 120 MB B2 download)")
    ap.add_argument("--branch", default="main")
    args = ap.parse_args()
    ct.load_env_file(args.env_file)
    w = ct.client()
    return {"plan": cmd_plan, "run": cmd_run, "usage": cmd_usage}[args.command](w, args) or 0


if __name__ == "__main__":
    sys.exit(main())
