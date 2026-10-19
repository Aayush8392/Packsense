"""How each action is carried out: as SQL and dbutils inside a job that runs as the identity (notebook runner), or through the Databricks
SDK with the identity's own token (sdk runner). Only the builders of SQL and paths are pure; the two classes are thin adapters tested with fakes."""
from __future__ import annotations

import io
import os

from policy_lib import PROBE

CATALOG = "workspace"
WAREHOUSE = "c9e35ecf0a03295d"       # the Serverless Starter 2X-Small (an address, not a secret); only rows_only checks use it
PROBE_SCHEMA = f"{CATALOG}.{PROBE}_schema"
PROBE_FILE = f"{PROBE}.txt"


def volume_path(volume: str) -> str:
    cat, sch, vol = volume.split(".")
    return f"/Volumes/{cat}/{sch}/{vol}/{PROBE_FILE}"


def sql_attempt(check: dict) -> str:
    a = check["action"]
    if a == "read_table":
        return f"SELECT 1 FROM {check['table']} LIMIT 1"
    if a == "create_table":
        return f"CREATE OR REPLACE TABLE {check['schema']}.{PROBE} AS SELECT 1 AS x"
    if a == "create_schema":
        return f"CREATE SCHEMA {PROBE_SCHEMA}"
    if a == "create_volume":
        return f"CREATE VOLUME {check['schema']}.{PROBE}"
    raise ValueError(f"{a} has no SQL form")


def sql_cleanup(check: dict) -> str | None:
    a = check["action"]
    if a == "create_table":
        return f"DROP TABLE IF EXISTS {check['schema']}.{PROBE}"
    if a == "create_schema":
        return f"DROP SCHEMA IF EXISTS {PROBE_SCHEMA}"
    if a == "create_volume":
        return f"DROP VOLUME IF EXISTS {check['schema']}.{PROBE}"
    return None


class NotebookRunner:
    """Runs inside a job whose identity is the one under test. `spark` and `dbutils` are the notebook's."""

    def __init__(self, spark, dbutils):
        self.spark, self.dbutils = spark, dbutils

    def whoami(self) -> str:
        return self.spark.sql("SELECT current_user()").collect()[0][0]

    def attempt_for(self, check):
        a = check["action"]
        if a == "list_secrets":
            return lambda: self.dbutils.secrets.list(check["scope"])
        if a == "upload_file":
            def up():
                path = volume_path(check["volume"])
                with open(path, "w", encoding="utf-8") as f:
                    f.write("policy probe")
            return up
        return lambda: self.spark.sql(sql_attempt(check)).collect()

    def cleanup_for(self, check):
        if check["action"] == "upload_file":
            return lambda: os.remove(volume_path(check["volume"]))
        stmt = sql_cleanup(check)
        return (lambda: self.spark.sql(stmt).collect()) if stmt else (lambda: None)


class SdkRunner:
    """Uses a WorkspaceClient signed in with the identity's own token (no warehouse needed: the Unity Catalog and Files APIs enforce the same rights)."""

    def __init__(self, w):
        self.w = w

    def whoami(self) -> str:
        return self.w.current_user.me().user_name

    def distinct_values(self, table: str, column: str) -> list[str]:
        """The distinct values of one column as this identity sees them (the row filter applies). Needs the identity to use the SQL warehouse."""
        import time
        r = self.w.statement_execution.execute_statement(
            warehouse_id=WAREHOUSE, statement=f"SELECT DISTINCT {column} FROM {table}", wait_timeout="50s")
        while r.status.state.value in ("PENDING", "RUNNING"):
            time.sleep(2)
            r = self.w.statement_execution.get_statement(r.statement_id)
        if r.status.state.value != "SUCCEEDED":
            raise RuntimeError(f"{r.status.state.value}: {r.status.error}")
        return [row[0] for row in (r.result.data_array or [])] if r.result else []

    def attempt_for(self, check):
        a, w = check["action"], self.w
        if a == "get_catalog":
            return lambda: w.catalogs.get(name=check["catalog"])
        if a == "read_table":
            return lambda: w.tables.get(full_name=check["table"])
        if a == "list_secrets":
            return lambda: list(w.secrets.list_secrets(scope=check["scope"]))
        if a == "rows_only":
            return lambda: self.distinct_values(check["table"], check["column"])
        if a == "upload_file":
            return lambda: w.files.upload(volume_path(check["volume"]), io.BytesIO(b"policy probe"), overwrite=True)
        if a == "create_volume":
            from databricks.sdk.service.catalog import VolumeType
            cat, sch = check["schema"].split(".")
            return lambda: w.volumes.create(catalog_name=cat, schema_name=sch, name=PROBE, volume_type=VolumeType.MANAGED)
        raise ValueError(f"{a} is not available through the SDK runner")

    def cleanup_for(self, check):
        a, w = check["action"], self.w
        if a == "upload_file":
            return lambda: w.files.delete(volume_path(check["volume"]))
        if a == "create_volume":
            return lambda: w.volumes.delete(name=f"{check['schema']}.{PROBE}")
        return lambda: None
