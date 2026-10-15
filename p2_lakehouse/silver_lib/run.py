"""Processes one batch of bronze rows (normally one landed file) into silver rows, quarantine rows and bookkeeping.

Pure Python, no Spark: the notebook reads the rows, calls process_batch, and writes the results, so everything that
decides what happens to a record is tested here against real records. Each record is handled on its own (nothing depends
on the other rows of the batch or on earlier files), so the order of files cannot change a result.
"""
import hashlib
from collections import Counter
from dataclasses import dataclass, field

from . import transform


@dataclass
class BatchResult:
    rows_in: int = 0
    silver: list = field(default_factory=list)          # dicts keyed by silver column name
    quarantine: list = field(default_factory=list)      # dicts keyed by silver_quarantine column name
    reasons: Counter = field(default_factory=Counter)
    coerce_failures: Counter = field(default_factory=Counter)
    nutrition_format: Counter = field(default_factory=Counter)
    tags_dropped: Counter = field(default_factory=Counter)
    scrubbed: int = 0
    own_handles_redacted: int = 0
    nutrient_entries_dropped: int = 0
    enums_nulled: int = 0

    def balanced(self) -> bool:
        """The hand-off check: every row in is either in silver or in quarantine, nothing lost, nothing doubled."""
        return self.rows_in == len(self.silver) + len(self.quarantine)


def process_batch(rows: list, ctx: transform.Context, run_id: str, processed_at) -> BatchResult:
    """rows: dicts with code, last_modified_t, raw_json, source_file, file_sha256, ingested_at (the bronze columns)."""
    out = BatchResult(rows_in=len(rows))
    for r in rows:
        lineage = {"source_file": r["source_file"], "file_sha256": r["file_sha256"], "bronze_ingested_at": r["ingested_at"],
                   "silver_processed_at": processed_at, "job_run_id": run_id}
        res = transform.process(r["raw_json"], ctx, lineage)
        out.coerce_failures.update(res.coerce_failures)
        out.tags_dropped.update(res.tags_dropped)
        out.scrubbed += res.scrubbed
        out.own_handles_redacted += res.own_handles_redacted
        out.nutrient_entries_dropped += res.nutrient_entries_dropped
        out.enums_nulled += res.enums_nulled
        if res.kind == "silver":
            out.silver.append(res.row)
            out.nutrition_format[res.row["nutrition_format"]] += 1
        else:
            out.reasons[res.reason] += 1
            out.quarantine.append({
                "code": res.code if res.code is not None else r.get("code"),
                "last_modified_t": res.last_modified_t if res.last_modified_t is not None else r.get("last_modified_t"),
                "reason": res.reason, "payload": res.payload,
                "source_file": r["source_file"], "file_sha256": r["file_sha256"],
                "record_sha256": hashlib.sha256(r["raw_json"].encode("utf-8")).hexdigest(),
                "bronze_ingested_at": r["ingested_at"], "quarantined_at": processed_at, "job_run_id": run_id,
                "resolved_by_run": None})
    return out
