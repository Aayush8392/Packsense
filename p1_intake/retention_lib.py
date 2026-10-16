"""Landing-volume retention: which landed delta files may be deleted. Plain Python with no I/O, so it is unit-tested on real file names;
the notebook (notebooks/landing_retention.py) reads the two manifests, lists the volume, calls `plan` and deletes what it says.

Why: landing holds a copy of every delta file (about 30 MB a day) next to the two verified copies (B2 for 270 days, the Hugging Face
archive). It needs a rule so it does not grow without end. A delta file is deleted only if ALL of these hold:
  1. it is older than RETENTION_DAYS, by the end time in its own name (not by file dates), which is far beyond the ~14 days OFF keeps
     listed: the capture decides what to fetch from what is in landing, so a file OFF still lists must never be deleted;
  2. bronze loaded it: bronze_manifest has the file with a sha256;
  3. the Hugging Face archive holds it with the SAME sha256 (the independent verified copy), so a deletion never depends on one
     system's say-so and an archive outage stops deletions instead of risking data.
Never touched: manifests, taxonomy snapshots, and anything whose name is not an OFF delta file. At most MAX_DELETIONS per run (about one
file expires a day, so more would mean a bug); the rest wait for the next run.
"""
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone

NAME_RE = re.compile(r"^openfoodfacts_products_(\d+)_(\d+)\.json\.gz$")     # the same pattern the capture uses
ARCHIVE_PREFIX = "raw/deltas/"
RETENTION_DAYS = 30
MAX_DELETIONS = 20

YOUNG, NOT_IN_BRONZE, NOT_ARCHIVED, DISAGREE, NOT_A_DELTA = (
    "younger_than_retention", "not_loaded_in_bronze", "not_in_archive", "bronze_and_archive_disagree", "not_a_delta_file")


@dataclass
class Plan:
    delete: list = field(default_factory=list)        # names to delete now, oldest first
    deferred: list = field(default_factory=list)      # eligible but over the per-run cap
    kept: dict = field(default_factory=dict)          # name -> reason it stays


def end_time(name: str) -> datetime | None:
    """The end of the delta's time range (seconds since the epoch in the second number of its name), UTC; None if not a delta name."""
    m = NAME_RE.match(name)
    return datetime.fromtimestamp(int(m.group(2)), tz=timezone.utc) if m else None


def age_days(name: str, now: datetime) -> float | None:
    t = end_time(name)
    return None if t is None else (now - t).total_seconds() / 86400


def archive_shas(archive_files: dict) -> dict[str, str]:
    """{delta file name: sha256} from the archive manifest's files (keys such as raw/deltas/<name>)."""
    return {k[len(ARCHIVE_PREFIX):]: v["sha256"] for k, v in archive_files.items() if k.startswith(ARCHIVE_PREFIX) and "sha256" in v}


def plan(landed, bronze: dict[str, str], archive: dict[str, str], now: datetime, retention_days: int = RETENTION_DAYS,
         max_deletions: int = MAX_DELETIONS) -> Plan:
    """landed: file names in landing/deltas. bronze and archive: {file name: sha256}. now: timezone-aware."""
    out = Plan()
    eligible = []
    for name in sorted(landed):
        age = age_days(name, now)
        if age is None:
            out.kept[name] = NOT_A_DELTA
        elif age <= retention_days:
            out.kept[name] = YOUNG
        elif name not in bronze:
            out.kept[name] = NOT_IN_BRONZE
        elif name not in archive:
            out.kept[name] = NOT_ARCHIVED
        elif bronze[name] != archive[name]:
            out.kept[name] = DISAGREE
        else:
            eligible.append(name)
    eligible.sort(key=lambda n: end_time(n))           # oldest first
    out.delete, out.deferred = eligible[:max_deletions], eligible[max_deletions:]
    for n in out.deferred:
        out.kept[n] = "over_the_per_run_cap"
    return out
