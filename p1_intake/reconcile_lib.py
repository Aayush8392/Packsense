"""B2 reconciliation: does the capture bucket hold exactly what our records say it should? Plain Python with no I/O, so it is unit-tested on
real key shapes; the notebook (notebooks/b2_reconcile.py) lists B2, reads the manifests and calls `reconcile`.

Every upload was checked when it happened (capture: checksums; archive: downloaded and compared), so this audit looks for what changes
afterwards: an object that disappeared or was overwritten, an object nobody recorded, an archive that fell behind. Listing only: B2 is
never downloaded from (that is what the free daily download cap limits). It checks existence and size, not content.

Checks (each finding has a code):
  B2_MISSING             a delta file, manifest, log or taxonomy snapshot our records name is not in B2
  SIZE_MISMATCH          its size in B2 differs from the recorded size, or from the copy in landing
  UNEXPECTED_OBJECT      an object under raw/ or taxonomies/ that no record explains (something wrote with the upload key unrecorded)
  NOT_ARCHIVED           a B2 object older than ARCHIVE_GRACE_HOURS has no entry in the Hugging Face archive manifest
  ARCHIVE_SIZE_MISMATCH  the archive manifest records a different size than B2 holds
  ARCHIVE_ONLY_TOO_SOON  an archived key is no longer listed in B2 although it was archived less than RAW_HIDE_AFTER_DAYS ago (hidden?)
  LANDING_NOT_IN_B2      a delta file in landing has no object in B2
"""
from dataclasses import dataclass
from datetime import datetime, timedelta

ARCHIVE_GRACE_HOURS = 36        # a file captured after the last archive run is not a finding yet
RAW_HIDE_AFTER_DAYS = 270       # the lifecycle rule: raw/ objects are hidden after this long, so the archive may outlive them


@dataclass(frozen=True)
class Finding:
    code: str
    key: str
    detail: str


def expected_objects(capture_manifests: dict, tax_logs: dict) -> dict[str, int | None]:
    """B2 key -> recorded size (None where no size is recorded) for everything the records say B2 holds, except the manifests/logs themselves."""
    out: dict[str, int | None] = {}
    for manifest in capture_manifests.values():
        for e in manifest.get("files", []):
            out[e["b2_key"]] = e["bytes"]
    for log in tax_logs.values():
        for e in log.get("entries", []):
            out[f"taxonomies/{e['snapshot']}"] = None        # the log records the uncompressed size; the stored size comes from landing
    return out


def reconcile(b2: dict, capture_manifests: dict, manifest_sizes: dict, tax_logs: dict, log_sizes: dict, snapshot_sizes: dict,
              landing_deltas: dict, archive_files: dict, now: datetime) -> list[Finding]:
    """b2: key -> {"size", "modified"} (current versions under raw/ and taxonomies/). capture_manifests: stamp -> parsed manifest;
    manifest_sizes: stamp -> bytes of its landing copy. tax_logs / log_sizes: the same for taxonomy logs. snapshot_sizes: snapshot key ->
    bytes of the landing copy (missing if absent from landing). landing_deltas: file name -> bytes. archive_files: the archive manifest's
    "files" (key -> {"bytes", "archived_at"}). now: timezone-aware."""
    out: list[Finding] = []
    explained: set[str] = set()

    def check(key: str, recorded: int | None, what: str) -> None:
        explained.add(key)
        if key not in b2:
            out.append(Finding("B2_MISSING", key, f"{what} is not in B2"))
        elif recorded is not None and b2[key]["size"] != recorded:
            out.append(Finding("SIZE_MISMATCH", key, f"{what}: B2 holds {b2[key]['size']} bytes, expected {recorded}"))

    for key, size in expected_objects(capture_manifests, {}).items():
        check(key, size, "a delta file the capture recorded")
    for stamp, size in manifest_sizes.items():
        check(f"raw/manifests/{stamp}.json", size, "a capture manifest")
    for stamp, size in log_sizes.items():
        check(f"taxonomies/_log/{stamp}.json", size, "a taxonomy log")
    for key in expected_objects({}, tax_logs):
        check(key, snapshot_sizes.get(key[len("taxonomies/"):]), "a taxonomy snapshot")
    for name, size in landing_deltas.items():
        key = f"raw/deltas/{name}"
        if key not in b2:
            out.append(Finding("LANDING_NOT_IN_B2", key, "a delta file in landing has no object in B2"))
        elif b2[key]["size"] != size:
            out.append(Finding("SIZE_MISMATCH", key, f"landing holds {size} bytes, B2 holds {b2[key]['size']}"))

    for key in sorted(b2):
        if key not in explained and not key.endswith("/"):
            out.append(Finding("UNEXPECTED_OBJECT", key, "no capture manifest, taxonomy log or manifest file records this object"))

    grace = timedelta(hours=ARCHIVE_GRACE_HOURS)
    for key, info in sorted(b2.items()):
        if key.endswith("/"):
            continue
        a = archive_files.get(key)
        if a is None:
            if now - info["modified"] > grace:
                out.append(Finding("NOT_ARCHIVED", key, f"older than {ARCHIVE_GRACE_HOURS} h and not in the archive manifest"))
        elif a["bytes"] != info["size"]:
            out.append(Finding("ARCHIVE_SIZE_MISMATCH", key, f"archive records {a['bytes']} bytes, B2 holds {info['size']}"))
    for key, a in sorted(archive_files.items()):
        if key not in b2 and (now - datetime.fromisoformat(a["archived_at"])) < timedelta(days=RAW_HIDE_AFTER_DAYS):
            out.append(Finding("ARCHIVE_ONLY_TOO_SOON", key, "archived but no longer listed in B2, before the lifecycle window"))
    return out


def summary(findings: list[Finding], limit: int = 6) -> str:
    """One short line for the healthchecks ping body (the full detail is in the run output)."""
    counts: dict[str, int] = {}
    for f in findings:
        counts[f.code] = counts.get(f.code, 0) + 1
    head = "b2 reconcile: " + (", ".join(f"{n} {c}" for c, n in sorted(counts.items())) if counts else "no findings")
    shown = [f"{f.code} {f.key}" for f in findings[:limit]]
    return (head + ("; " + " | ".join(shown) if shown else ""))[:1000]
