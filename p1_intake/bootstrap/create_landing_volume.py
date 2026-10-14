"""One-time setup: the Unity Catalog schema and managed volume that receive the daily capture, plus the pipeline user's grants.

Creates workspace.packsense and the managed volume workspace.packsense.landing, then grants the pipeline user the least
privilege the Files API needs (USE on the catalog and schema, READ+WRITE on the volume; a write-only grant cannot upload).
This is later brought under Terraform; until then it documents exactly what exists.

Needs an admin token and the pipeline user's token in the environment (or in an --env-file). Values are never printed.
  pip install databricks-sdk
  python p1_intake/bootstrap/create_landing_volume.py [--env-file PATH]
Environment: DATABRICKS_HOST, DATABRICKS_TOKEN (admin), DATABRICKS_PIPELINE_TOKEN
"""
import argparse
import os
import sys

CATALOG, SCHEMA, VOLUME = "workspace", "packsense", "landing"


def load_env_file(path: str) -> None:
    for raw in open(path, encoding="utf-8").read().splitlines():
        line = raw.split("#", 1)[0].strip()
        if line and "=" in line:
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip())


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--env-file")
    args = ap.parse_args()
    if args.env_file:
        load_env_file(args.env_file)
    for name in ("DATABRICKS_HOST", "DATABRICKS_TOKEN", "DATABRICKS_PIPELINE_TOKEN"):
        if not os.environ.get(name):
            sys.exit(f"missing environment variable: {name}")

    from databricks.sdk import WorkspaceClient
    from databricks.sdk.errors import ResourceAlreadyExists
    from databricks.sdk.service.catalog import PermissionsChange, Privilege, VolumeType

    host, admin_token = os.environ["DATABRICKS_HOST"], os.environ["DATABRICKS_TOKEN"]
    admin = WorkspaceClient(host=host, token=admin_token)
    pipeline_user = WorkspaceClient(host=host, token=os.environ["DATABRICKS_PIPELINE_TOKEN"]).current_user.me().user_name

    try:
        admin.schemas.create(name=SCHEMA, catalog_name=CATALOG, comment="PackSense lakehouse")
        print(f"created schema {CATALOG}.{SCHEMA}")
    except ResourceAlreadyExists:
        print(f"schema {CATALOG}.{SCHEMA} already exists")
    try:
        admin.volumes.create(catalog_name=CATALOG, schema_name=SCHEMA, name=VOLUME, volume_type=VolumeType.MANAGED,
                             comment="Daily capture landing zone (raw OFF delta files and manifests)")
        print(f"created volume {CATALOG}.{SCHEMA}.{VOLUME}")
    except ResourceAlreadyExists:
        print(f"volume {CATALOG}.{SCHEMA}.{VOLUME} already exists")

    for kind, name, privileges in (
        ("catalog", CATALOG, [Privilege.USE_CATALOG]),
        ("schema", f"{CATALOG}.{SCHEMA}", [Privilege.USE_SCHEMA]),
        ("volume", f"{CATALOG}.{SCHEMA}.{VOLUME}", [Privilege.READ_VOLUME, Privilege.WRITE_VOLUME]),
    ):
        admin.grants.update(securable_type=kind, full_name=name, changes=[PermissionsChange(principal=pipeline_user, add=privileges)])
        print(f"granted {[p.value for p in privileges]} on {name} to the pipeline user")
    return 0


if __name__ == "__main__":
    sys.exit(main())
