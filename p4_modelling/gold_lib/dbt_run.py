"""Plain helpers for the gold job notebook (kept out of the notebook so they can be unit-tested).

The notebook runs `dbt build` as the gold principal; this module decides the arguments, reads dbt's results and words the summary
that goes to the log and to healthchecks. Nothing here touches Databricks or reads a secret.
"""
import json

TARGETS = ("dev", "prod")
OK_STATUSES = {"success", "pass"}


def check_target(target: str) -> str:
    if target not in TARGETS:
        raise ValueError(f"dbt target must be one of {TARGETS}, got {target!r}")
    return target


def build_args(project_dir: str, target: str, silver_schema: str, target_path: str, log_path: str) -> list:
    """Arguments for `dbt build` (models and their tests in dependency order: a failed test stops what depends on it)."""
    check_target(target)
    return [
        "build",
        "--project-dir", project_dir,
        "--profiles-dir", project_dir,
        "--target", target,
        "--vars", json.dumps({"silver_schema": silver_schema}),
        "--target-path", target_path,
        "--log-path", log_path,
    ]


def summarise(results) -> dict:
    """results: (node name, status) pairs from dbt. A node counts as fine only when it succeeded or passed."""
    counts = {}
    bad = []
    for name, status in results:
        status = str(status).lower()
        counts[status] = counts.get(status, 0) + 1
        if status not in OK_STATUSES:
            bad.append(f"{name}={status}")
    return {"total": len(results), "counts": counts, "bad": sorted(bad), "ok": bool(results) and not bad}


def result_text(summary: dict) -> str:
    counts = ", ".join(f"{k} {v}" for k, v in sorted(summary["counts"].items())) or "nothing ran"
    text = f"dbt build: {summary['total']} nodes ({counts})"
    if summary["bad"]:
        text += "; not ok: " + ", ".join(summary["bad"][:10])
    return text


def freshness_text(files: int, newest_processed_at, newest_file) -> str:
    """What silver looked like when gold started. Informational: gold is a full rebuild, so stale silver gives an identical result."""
    if not files:
        return "silver manifest is empty"
    return f"silver: {files} files processed, newest {newest_file} at {newest_processed_at}"
