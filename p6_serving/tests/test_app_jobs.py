"""The app's list of pipeline jobs (src/data/jobs.json) stays in step with the collector that writes pipeline_health and with the bundles that schedule the jobs."""
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "p9_operations"))
import health_lib  # noqa: E402

JOBS = json.loads((ROOT / "p6_serving" / "app" / "src" / "data" / "jobs.json").read_text(encoding="utf-8"))

BUNDLE_FILES = [
    path
    for path in ROOT.rglob("*.yml")
    if not {".venv", "node_modules", ".git"} & set(path.parts) and ("resources" in path.parts or path.name == "databricks.yml")
]
VARIABLE = re.compile(r'^  (\w+):\n(?:    .*\n)*?    default: "([^"]*)"', re.M)
JOB_BLOCK = re.compile(r"^      name: (packsense-[\w-]+)\n((?:(?!^      name: ).*\n)*)", re.M)
CRON = re.compile(r'quartz_cron_expression: (?:"([^"]*)"|\$\{var\.(\w+)\})')


def test_the_app_lists_exactly_the_jobs_the_collector_reports():
    assert {job["name"] for job in JOBS} == set(health_lib.JOB_NAMES)
    assert len(JOBS) == len(health_lib.JOB_NAMES)


def test_every_job_has_a_known_cadence_and_only_the_daily_load_names_a_time():
    for job in JOBS:
        assert job["cadence"] in {"daily", "weekly", "monthly"}, job
    assert [job["name"] for job in JOBS if "at" in job] == ["packsense-bronze-load"]


def _bundle_crons():
    """Job name -> the cron its bundle schedules it with (a variable is replaced by its default value)."""
    defaults = {}
    for path in BUNDLE_FILES:
        defaults.update(dict(VARIABLE.findall(path.read_text(encoding="utf-8"))))
    crons = {}
    for path in BUNDLE_FILES:
        for name, body in JOB_BLOCK.findall(path.read_text(encoding="utf-8")):
            cron = CRON.search(body)
            if cron:
                crons[name] = cron.group(1) or defaults[cron.group(2)]
    return crons


def _cadence(cron):
    _, _, _, day_of_month, _, day_of_week = cron.split()
    if day_of_week not in {"*", "?"}:
        return "weekly"
    return "monthly" if day_of_month not in {"*", "?"} else "daily"


def test_every_job_is_scheduled_in_its_bundle_exactly_as_the_app_says():
    crons = _bundle_crons()
    for job in JOBS:
        assert job["name"] in crons, f"{job['name']} has no schedule in any bundle"
        assert crons[job["name"]] == job["cron"], job["name"]


def test_every_cadence_the_app_names_follows_from_the_schedule():
    for job in JOBS:
        assert _cadence(job["cron"]) == job["cadence"], job["name"]


def test_the_daily_load_time_the_app_names_is_the_time_in_its_cron():
    load = next(job for job in JOBS if job["name"] == "packsense-bronze-load")
    _, minute, hour, *_ = load["cron"].split()
    assert load["at"] == f"{int(hour):02d}:{int(minute):02d}"


def test_every_job_says_in_a_plain_sentence_what_it_is_for():
    for job in JOBS:
        assert len(job["purpose"]) > 20 and job["purpose"].endswith("."), job["name"]
