# Databricks notebook source
# Daily capture as the FIRST task of the bronze job (decision O1 + T2 + G1 after external review 02, 2026-10-18).
#
# Why here: the GitHub scheduler runs the capture 4 to 5 hours late, so each day's data was processed a day late. This task starts at
# 06:45 UTC, polls OFF's index every 5 minutes until today's file is listed (OFF publishes it between 06:19 and 06:33 UTC), and fails
# loudly if it is still missing at 07:45 UTC. The same capture code (p1_intake/capture_deltas.py and capture_taxonomies.py) runs here and on
# GitHub: the GitHub workflow stays as the independent second path, and both write to landing keyed by file name, so whichever comes first does
# the work and the other finds nothing to do.
#
# Order: wait for publication -> capture deltas (download, check, B2, landing, manifest) -> capture taxonomies -> assert that the newest OFF
# delta is in landing -> ONLY THEN the success ping (the manifest is already written by then). Any failure sends /fail and raises; bronze,
# silver, drift and taxonomy run afterwards anyway (run_if ALL_DONE). No automatic retry (disable_auto_optimization in the job): a
# failure must stay visible, and the GitHub path is the second chance.
# Secrets come from the secret scope (the B2 write-only capture key, the capture healthchecks ping URL); none is printed or passed as a parameter.

# COMMAND ----------
# MAGIC %pip install -q boto3 requests

# COMMAND ----------
import datetime as dt
import json
import os
import sys
import time

import requests

UTC = dt.timezone.utc


def find_p1_intake():
    """The folder that holds capture_deltas.py, wherever the deployed copy of this job lives."""
    starts = [os.getcwd()]
    try:
        nb = dbutils.notebook.entry_point.getDbutils().notebook().getContext().notebookPath().get()
        starts.insert(0, os.path.dirname(nb if nb.startswith("/Workspace") else "/Workspace" + nb))
    except Exception:
        pass
    for start in starts:
        p = start
        for _ in range(6):
            if os.path.isfile(os.path.join(p, "capture_deltas.py")):
                return p
            if os.path.isfile(os.path.join(p, "p1_intake", "capture_deltas.py")):
                return os.path.join(p, "p1_intake")
            p = os.path.dirname(p)
    raise RuntimeError("cannot find p1_intake/capture_deltas.py; looked from " + repr(starts))


sys.path.insert(0, find_p1_intake())

dbutils.widgets.text("run_id", "manual")
dbutils.widgets.text("landing", "/Volumes/workspace/packsense/landing")
dbutils.widgets.text("secret_scope", "packsense")
dbutils.widgets.text("b2_endpoint", "https://s3.eu-central-003.backblazeb2.com")   # not a secret (a repo variable)
dbutils.widgets.text("b2_bucket", "packsense-raw-aayush-8392")                      # not a secret (a repo variable)
dbutils.widgets.text("b2_prefix", "raw")                # a scratch proof sets "tmp/a2-test" so nothing lands under raw/
dbutils.widgets.text("upload_to_b2", "true")            # dev: "false" (the dev scope holds no B2 key)
dbutils.widgets.text("ping_healthchecks", "true")       # dev and tests: "false"
dbutils.widgets.text("taxonomies", "true")
dbutils.widgets.text("dry_run", "false")                # "true": list what would be captured, change nothing, no waiting, no pings
dbutils.widgets.text("max_files", "0")                  # tests: capture at most N files (0 = all)
dbutils.widgets.text("deadline_utc", "07:45")           # fail if today's file is still missing at this UTC time
dbutils.widgets.text("poll_seconds", "300")
dbutils.widgets.text("drill_fail", "false")             # failure drill: ping /fail and raise at once (bronze must still run)

RUN_ID = dbutils.widgets.get("run_id")
SCOPE = dbutils.widgets.get("secret_scope")
LANDING = dbutils.widgets.get("landing")
UPLOAD_B2 = dbutils.widgets.get("upload_to_b2").strip().lower() == "true"
PING = dbutils.widgets.get("ping_healthchecks").strip().lower() == "true"
TAXONOMIES = dbutils.widgets.get("taxonomies").strip().lower() == "true"
DRY_RUN = dbutils.widgets.get("dry_run").strip().lower() == "true"
DRILL_FAIL = dbutils.widgets.get("drill_fail").strip().lower() == "true"
MAX_FILES = int(dbutils.widgets.get("max_files") or 0)
POLL_SECONDS = int(dbutils.widgets.get("poll_seconds"))
HOUR, MINUTE = (int(x) for x in dbutils.widgets.get("deadline_utc").split(":"))

# COMMAND ----------
ping_url = dbutils.secrets.get(SCOPE, "healthchecks_capture_ping_url") if (PING and not DRY_RUN) else None


def ping(suffix="", body=None):
    """Best effort: a failing ping must never fail the capture. The URL is never printed."""
    if not ping_url:
        return
    try:
        requests.post(ping_url + suffix, data=(body or "")[:1000].encode("utf-8"), timeout=10)
    except Exception as e:
        print("healthchecks ping failed:", type(e).__name__)


ping("/start")
try:
    if DRILL_FAIL:
        raise RuntimeError("failure drill: capture stopped on purpose (drill_fail=true)")

    os.environ["LANDING_ROOT"] = LANDING
    os.environ["B2_S3_ENDPOINT"] = dbutils.widgets.get("b2_endpoint")
    os.environ["B2_BUCKET"] = dbutils.widgets.get("b2_bucket")
    os.environ["B2_PREFIX"] = dbutils.widgets.get("b2_prefix")
    if UPLOAD_B2 and not DRY_RUN:
        os.environ["B2_UPLOAD_KEY_ID"] = dbutils.secrets.get(SCOPE, "b2_capture_key_id")
        os.environ["B2_UPLOAD_APPLICATION_KEY"] = dbutils.secrets.get(SCOPE, "b2_capture_application_key")

    import capture_deltas as cd  # noqa: E402  (after the environment is set; it reads it when it runs)
    import capture_taxonomies as ct  # noqa: E402

    flags = (["--dry-run"] if DRY_RUN else []) + ([] if UPLOAD_B2 else ["--no-b2"])
    published_polls = 0
    if not DRY_RUN:
        now = dt.datetime.now(UTC)
        deadline = now.replace(hour=HOUR, minute=MINUTE, second=0, microsecond=0)
        published, published_polls, names = cd.wait_for_publication(
            cd.list_index, lambda: dt.datetime.now(UTC), time.sleep, deadline, POLL_SECONDS)
        print(f"OFF index read {published_polls} time(s); today's file listed: {published}; newest: {names[-1] if names else None}")
        if not published:
            raise RuntimeError(f"OFF had not published today's delta file by {HOUR:02d}:{MINUTE:02d} UTC")

    code = cd.main(flags + (["--max-files", str(MAX_FILES)] if MAX_FILES else []))
    if code != 0:
        raise RuntimeError(f"delta capture ended with code {code}")
    taxonomy_problem = None
    if TAXONOMIES:
        # A taxonomy that fails to download must not fail the capture: the delta (the time-critical part) is already landed, taxonomies
        # change rarely, and the next run (and the GitHub second path at 10:00 UTC) fetches any that were missed. The problem stays
        # visible in the ping text and the notebook result. (2026-10-19: origins_adjectives failed once and turned the check red.)
        try:
            code = ct.main(flags)
            if code != 0:
                taxonomy_problem = f"taxonomy capture ended with code {code}"
        except (Exception, SystemExit) as e:
            taxonomy_problem = f"taxonomy capture raised {type(e).__name__}: {str(e)[:100]}"
        if taxonomy_problem:
            print("WARNING:", taxonomy_problem)

    summary = {"run_id": RUN_ID, "dry_run": DRY_RUN, "polls": published_polls}
    if taxonomy_problem:
        summary["taxonomy_problem"] = taxonomy_problem
    if not DRY_RUN:
        # The freshness assertion: the newest file OFF lists must now be in landing.
        names = cd.list_index()
        landing = cd.make_landing()
        if not names or names[-1] not in landing.names("deltas"):
            raise RuntimeError("freshness assertion failed: the newest OFF delta file is not in landing")
        manifests = sorted(landing.names("manifests"))
        if manifests:
            summary["lateness_minutes"] = cd.lateness_minutes(json.loads(landing.get(f"manifests/{manifests[-1]}")))
        summary["newest_delta"] = names[-1]
    print(json.dumps(summary))
    ping("", json.dumps(summary))   # only now: the manifest is written and the newest file is in landing
except (Exception, SystemExit) as e:
    # the message is cut short: it must never carry more than the type and a short reason into the logs or the ping
    ping("/fail", f"capture failed: {type(e).__name__}: {str(e)[:200]}")
    raise

# COMMAND ----------
# Outside the try block on purpose: exit() may work by raising, and that must not be reported as a failure.
dbutils.notebook.exit(json.dumps(summary))
