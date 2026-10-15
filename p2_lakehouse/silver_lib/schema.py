"""Table definitions for the silver layer, built from the contract so the tables and the contract cannot drift apart.

silver_product_versions is generated from contracts/silver.yml. The small bookkeeping tables (quarantine, manifest, run
stats, field log) have fixed definitions here; tests check both against the contract.
"""
import re

TYPE_WORDS = re.compile(r"\b(string|int|bigint|double|boolean|timestamp|array|map|struct)\b")


def spark_type(contract_type: str) -> str:
    """'array<struct<value:double,unit:string>>' -> 'ARRAY<STRUCT<value:DOUBLE,unit:STRING>>'"""
    return TYPE_WORDS.sub(lambda m: m.group(1).upper(), contract_type.replace(" ", ""))


def silver_table_sql(contract: dict) -> str:
    cols = ",\n  ".join(
        f"{c['name']} {spark_type(c['type'])}" + ("" if c["nullable"] else " NOT NULL") for c in contract["columns"])
    return f"CREATE TABLE IF NOT EXISTS {contract['table']} (\n  {cols}\n) USING DELTA"


def quarantine_table_sql(contract: dict) -> str:
    return f"""CREATE TABLE IF NOT EXISTS {contract['quarantine_table']} (
  code STRING,
  last_modified_t BIGINT,
  reason STRING NOT NULL,
  payload STRING,
  source_file STRING NOT NULL,
  file_sha256 STRING NOT NULL,
  record_sha256 STRING NOT NULL,
  bronze_ingested_at TIMESTAMP,
  quarantined_at TIMESTAMP NOT NULL,
  job_run_id STRING NOT NULL,
  resolved_by_run STRING
) USING DELTA"""


def manifest_table_sql(contract: dict) -> str:
    return f"""CREATE TABLE IF NOT EXISTS {contract['manifest_table']} (
  file_name STRING NOT NULL,
  file_sha256 STRING NOT NULL,
  rows_in BIGINT NOT NULL,
  rows_silver BIGINT NOT NULL,
  rows_quarantine BIGINT NOT NULL,
  processed_at TIMESTAMP NOT NULL,
  job_run_id STRING NOT NULL
) USING DELTA"""


def stats_table_sql(contract: dict) -> str:
    return f"""CREATE TABLE IF NOT EXISTS {contract['stats_table']} (
  job_run_id STRING NOT NULL,
  processed_at TIMESTAMP NOT NULL,
  contract_version INT NOT NULL,
  files BIGINT NOT NULL,
  rows_in BIGINT NOT NULL,
  rows_silver BIGINT NOT NULL,
  rows_quarantine BIGINT NOT NULL,
  quarantine_by_reason MAP<STRING,BIGINT>,
  coerce_failures MAP<STRING,BIGINT>,
  nutrition_format MAP<STRING,BIGINT>,
  tags_dropped MAP<STRING,BIGINT>,
  patterns_scrubbed BIGINT,
  own_handles_redacted BIGINT,
  nutrient_entries_dropped BIGINT,
  enums_nulled BIGINT,
  top_level_fields_seen BIGINT
) USING DELTA"""


def field_log_table_sql(contract: dict) -> str:
    return f"""CREATE TABLE IF NOT EXISTS {contract['field_log_table']} (
  job_run_id STRING NOT NULL,
  processed_at TIMESTAMP NOT NULL,
  field STRING NOT NULL,
  products BIGINT NOT NULL
) USING DELTA"""


def drift_report_table(contract: dict) -> str:
    """Name of the drift report table: next to the silver table, so a relocated contract moves it too."""
    return contract["table"].rsplit(".", 1)[0] + ".silver_drift_report"


def drift_report_table_sql(contract: dict) -> str:
    return f"""CREATE TABLE IF NOT EXISTS {drift_report_table(contract)} (
  evaluated_at TIMESTAMP NOT NULL,
  drift_run_id STRING NOT NULL,
  subject_kind STRING NOT NULL,
  subject STRING NOT NULL,
  check_name STRING NOT NULL,
  level STRING NOT NULL,
  observed DOUBLE,
  baseline_low DOUBLE,
  baseline_high DOUBLE,
  detail STRING
) USING DELTA"""


def struct_ddl(contract: dict) -> str:
    """Column list for spark.createDataFrame(rows, schema=...): the table's columns without NOT NULL."""
    return ", ".join(f"{c['name']} {spark_type(c['type'])}" for c in contract["columns"])


def all_table_sql(contract: dict) -> list[str]:
    return [silver_table_sql(contract), quarantine_table_sql(contract), manifest_table_sql(contract),
            stats_table_sql(contract), field_log_table_sql(contract)]
