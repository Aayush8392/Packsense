"""One-time setup of the pipeline-health identity (an admin runs it; the ping URL is typed at a hidden prompt and never printed).

  python p9_operations/bootstrap/setup_health.py create-principal --env-file .env   makes `packsense-health` (Workspace access only), tries to grant the admin Use on it,
                                                                                    and writes its client id into the bundle files that carry the marker
  python p9_operations/bootstrap/setup_health.py create-schema --env-file .env      makes the schema workspace.packsense_health (the principal gets no CREATE SCHEMA, by design)
  python p9_operations/bootstrap/setup_health.py create-scope --env-file .env       makes the scope `packsense_health` (READ for the principal, MANAGE for the admin)
  python p9_operations/bootstrap/setup_health.py put-secret --name healthchecks_health_ping_url --env-file .env
  python p9_operations/bootstrap/setup_health.py grant-system --env-file .env       gives the principal SELECT on exactly two system tables (jobs, job_run_timeline)
  python p9_operations/bootstrap/setup_health.py list --env-file .env

The grants on workspace objects come from p5_governance/grants.yml (`apply_grants.py apply`). The system tables are outside the catalog that file manages, so
`grant-system` lists them here and the nightly policy job proves that the principal can read them and nothing else it should not. Environment (or the env file):
DATABRICKS_HOST, DATABRICKS_TOKEN (admin).
"""
import argparse
import getpass
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
NAME = "packsense-health"
SCOPE = "packsense_health"
SCHEMA = ("workspace", "packsense_health")
ALLOWED_SECRETS = ("healthchecks_health_ping_url",)
MARKER = "11111111-1111-1111-1111-111111111111"
MARKER_FILES = [
    "p9_operations/health/databricks.yml",
    "p9_operations/health/resources/health_job.yml",
    "p5_governance/policy/resources/policy_jobs.yml",
    "p5_governance/databricks.yml",
]
# The two system tables the collector reads, nothing wider: a catalog and two schemas need USE, the tables need SELECT.
SYSTEM_GRANTS = [
    ("catalog", "system", ["USE_CATALOG"]),
    ("schema", "system.lakeflow", ["USE_SCHEMA"]),
    ("table", "system.lakeflow.jobs", ["SELECT"]),
    ("table", "system.lakeflow.job_run_timeline", ["SELECT"]),
]
UUID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")


def patch_marker(text: str, client_id: str) -> str:
    """The text with every marker client id replaced by the real one (the client id is not a secret)."""
    if not UUID.match(client_id):
        raise ValueError("not a client id")
    return text.replace(MARKER, client_id)


def load_env_file(path: str) -> None:
    for raw in open(path, encoding="utf-8").read().splitlines():
        line = raw.split("#", 1)[0].strip()
        if line and "=" in line:
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip())


def client():
    from databricks.sdk import WorkspaceClient
    for name in ("DATABRICKS_HOST", "DATABRICKS_TOKEN"):
        if not os.environ.get(name, "").strip():
            sys.exit(f"missing environment variable: {name}")
    for name in ("DATABRICKS_CLIENT_ID", "DATABRICKS_CLIENT_SECRET"):
        os.environ.pop(name, None)
    return WorkspaceClient(host=os.environ["DATABRICKS_HOST"], token=os.environ["DATABRICKS_TOKEN"], auth_type="pat")


def find_principal(w):
    found = [sp for sp in w.service_principals.list(filter=f'displayName eq "{NAME}"')]
    return found[0] if found else None


def cmd_create_principal() -> int:
    w = client()
    sp = find_principal(w)
    if sp is None:
        from databricks.sdk.service.iam import ComplexValue
        sp = w.service_principals.create(display_name=NAME, active=True, entitlements=[ComplexValue(value="workspace-access")])
        print(f"created service principal {NAME}")
    else:
        print(f"service principal {NAME} already exists")
    client_id = sp.application_id
    me = w.current_user.me().user_name
    try:
        from databricks.sdk.service.iam import AccessControlRequest, PermissionLevel
        w.permissions.update(request_object_type="service-principals", request_object_id=str(sp.id),
                             access_control_list=[AccessControlRequest(user_name=me, permission_level=PermissionLevel.CAN_USE)])
        print("granted the admin Use on the principal (it can take a few minutes to apply)")
    except Exception as e:
        print(f"could not grant Use through the API ({type(e).__name__}): do it in Settings > Identity and access > Service principals > {NAME} > Permissions")
    for rel in MARKER_FILES:
        path = ROOT / rel
        text = path.read_text(encoding="utf-8")
        if MARKER in text:
            path.write_text(patch_marker(text, client_id), encoding="utf-8", newline="\n")
            print("client id written into", rel)
    print("client id:", client_id, "(not a secret)")
    return 0


def cmd_create_schema() -> int:
    """The schema AND the table are made by the admin, so the collector needs no CREATE SCHEMA and no CREATE TABLE (only USE_SCHEMA, SELECT, MODIFY)."""
    w = client()
    catalog, schema = SCHEMA
    try:
        w.schemas.create(name=schema, catalog_name=catalog)
        print(f"schema {catalog}.{schema} created")
    except Exception as e:
        print(f"create schema: {str(e)[:120]}")
    sys.path.insert(0, str(ROOT / "p9_operations"))
    import health_lib
    warehouse = os.environ.get("DBT_HTTP_PATH", "/sql/1.0/warehouses/c9e35ecf0a03295d").rstrip("/").split("/")[-1]   # the Serverless Starter 2X-Small: an address, not a secret
    r = w.statement_execution.execute_statement(warehouse_id=warehouse, statement=health_lib.ddl(), wait_timeout="50s")
    print(f"create table {health_lib.FULL_TABLE}: {r.status.state.value}")
    print("schemas of the catalog:", sorted(s.name for s in w.schemas.list(catalog_name=catalog) if s.name.startswith("packsense")))
    return 0


def cmd_create_scope() -> int:
    w = client()
    sp = find_principal(w)
    if sp is None:
        sys.exit(f"run create-principal first: no service principal named {NAME}")
    try:
        w.secrets.create_scope(scope=SCOPE)
        print(f"scope '{SCOPE}' created")
    except Exception as e:
        print(f"create_scope: {str(e)[:100]}")
    from databricks.sdk.service.workspace import AclPermission
    w.secrets.put_acl(scope=SCOPE, principal=sp.application_id, permission=AclPermission.READ)
    print("who can manage or read the scope:", [(a.principal, a.permission.value) for a in w.secrets.list_acls(scope=SCOPE)])
    return 0


def cmd_put_secret(name: str, replace: bool) -> int:
    w = client()
    exists = any(s.key == name for s in w.secrets.list_secrets(scope=SCOPE))
    if exists and not replace:
        sys.exit(f"'{name}' already exists in scope '{SCOPE}': nothing changed (use --replace to overwrite it)")
    value = getpass.getpass(f"value for '{name}' (hidden, not echoed): ").strip()
    if not value:
        sys.exit("empty value: nothing stored")
    w.secrets.put_secret(scope=SCOPE, key=name, string_value=value)
    del value
    print(f"stored '{name}' in scope '{SCOPE}' ({'replaced' if exists else 'new'}); the value was not printed")
    return 0


def cmd_grant_system() -> int:
    """Add the system-table grants one object at a time and report each, so a refusal (Free Edition may not allow it) names the object it stopped at."""
    from databricks.sdk.service.catalog import PermissionsChange, Privilege, SecurableType
    w = client()
    sp = find_principal(w)
    if sp is None:
        sys.exit(f"run create-principal first: no service principal named {NAME}")
    failed = 0
    for kind, full, privs in SYSTEM_GRANTS:
        try:
            w.grants.update(securable_type=SecurableType(kind), full_name=full,
                            changes=[PermissionsChange(principal=sp.application_id, add=[Privilege(p) for p in privs])])
            print(f"granted {','.join(privs)} on {kind} {full}")
        except Exception as e:
            failed += 1
            print(f"REFUSED {','.join(privs)} on {kind} {full}: {type(e).__name__}: {str(e)[:200]}")
    return 1 if failed else 0


def cmd_list() -> int:
    w = client()
    print("secrets in the scope:", sorted(s.key for s in w.secrets.list_secrets(scope=SCOPE)))
    print("who can manage or read the scope:", [(a.principal, a.permission.value) for a in w.secrets.list_acls(scope=SCOPE)])
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("command", choices=["create-principal", "create-schema", "create-scope", "put-secret", "grant-system", "list"])
    ap.add_argument("--name")
    ap.add_argument("--replace", action="store_true")
    ap.add_argument("--env-file")
    args = ap.parse_args()
    if args.env_file:
        load_env_file(args.env_file)
    if args.command == "create-principal":
        return cmd_create_principal()
    if args.command == "create-schema":
        return cmd_create_schema()
    if args.command == "create-scope":
        return cmd_create_scope()
    if args.command == "put-secret":
        if args.name not in ALLOWED_SECRETS:
            sys.exit(f"secret name must be one of {ALLOWED_SECRETS}")
        return cmd_put_secret(args.name, args.replace)
    if args.command == "grant-system":
        return cmd_grant_system()
    return cmd_list()


if __name__ == "__main__":
    sys.exit(main())
