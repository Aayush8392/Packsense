"""One-time setup of the publish identity (an admin runs it; secret values are typed at a hidden prompt and never printed).

  python p6_serving/bootstrap/setup_publish.py create-principal --env-file .env     makes `packsense-publish` (Workspace access only), grants the admin Use on it,
                                                                                    and writes its client id into the four bundle files that carry the marker
  python p6_serving/bootstrap/setup_publish.py create-scope --env-file .env         makes the scope `packsense_publish` (READ for the principal, MANAGE for the admin)
  python p6_serving/bootstrap/setup_publish.py put-secret --name hf_site_token --env-file .env
  python p6_serving/bootstrap/setup_publish.py put-secret --name healthchecks_publish_ping_url --env-file .env
  python p6_serving/bootstrap/setup_publish.py list --env-file .env

The grants themselves come from p5_governance/grants.yml (`apply_grants.py apply`). Environment (or the env file): DATABRICKS_HOST, DATABRICKS_TOKEN (admin).
"""
import argparse
import getpass
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
NAME = "packsense-publish"
SCOPE = "packsense_publish"
ALLOWED_SECRETS = ("hf_site_token", "healthchecks_publish_ping_url")
MARKER = "00000000-0000-0000-0000-000000000000"
MARKER_FILES = [
    "p6_serving/databricks.yml",
    "p6_serving/resources/publish_job.yml",
    "p5_governance/policy/resources/policy_jobs.yml",
    "p5_governance/databricks.yml",
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


def cmd_list() -> int:
    w = client()
    print("secrets in the scope:", sorted(s.key for s in w.secrets.list_secrets(scope=SCOPE)))
    print("who can manage or read the scope:", [(a.principal, a.permission.value) for a in w.secrets.list_acls(scope=SCOPE)])
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("command", choices=["create-principal", "create-scope", "put-secret", "list"])
    ap.add_argument("--name")
    ap.add_argument("--replace", action="store_true")
    ap.add_argument("--env-file")
    args = ap.parse_args()
    if args.env_file:
        load_env_file(args.env_file)
    if args.command == "create-principal":
        return cmd_create_principal()
    if args.command == "create-scope":
        return cmd_create_scope()
    if args.command == "put-secret":
        if args.name not in ALLOWED_SECRETS:
            sys.exit(f"secret name must be one of {ALLOWED_SECRETS}")
        return cmd_put_secret(args.name, args.replace)
    return cmd_list()


if __name__ == "__main__":
    sys.exit(main())
