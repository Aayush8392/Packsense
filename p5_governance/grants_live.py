"""The Databricks side of the grants file: resolve the principals, read the live grants, add what is missing. Needs an admin
WorkspaceClient. It only reads and adds; it never revokes."""
from __future__ import annotations

import os

import grants_lib as gl


def resolve_principals(w, spec: dict, environ=os.environ) -> tuple[dict[str, str | None], dict[str, str]]:
    """role -> the id Unity Catalog reports (application id for a service principal, user name for a user), None when it cannot be
    resolved; plus id -> role for printing. A user is the owner of the token in the environment variable."""
    from databricks.sdk import WorkspaceClient

    sp_by_name = {sp.display_name: sp.application_id for sp in w.service_principals.list()}
    ids: dict[str, str | None] = {}
    for role, p in spec["principals"].items():
        if p["kind"] == "service_principal":
            ids[role] = sp_by_name.get(p["name"])
        elif role == "admin":
            ids[role] = w.current_user.me().user_name
        else:
            token = environ.get(p["env"])
            try:
                ids[role] = WorkspaceClient(host=w.config.host, token=token, auth_type="pat").current_user.me().user_name if token else None
            except Exception:  # noqa: BLE001  a dead or expired token: the role is skipped, not fatal
                ids[role] = None
    return ids, {v: k for k, v in ids.items() if v}


def read_live(w, spec: dict) -> tuple[set, set]:
    """(grants, secret-scope ACLs) as sets in the same shape as grants_lib.expected_*. Reads the catalog, every schema and volume of
    it except the ignored schemas, and every table of the schemas the file lists."""
    catalog = spec["catalog"]
    ignore = set(spec.get("ignore_schemas") or [])
    listed_schemas = {s["name"].split(".")[1] for s in spec["securables"] if s["type"] == "schema"}
    live: set = set()

    def read(kind: str, full: str) -> None:
        for a in w.grants.get(securable_type=kind, full_name=full).privilege_assignments or []:
            live.update((kind, full, a.principal, p.value) for p in a.privileges)

    read("catalog", catalog)
    for sch in w.schemas.list(catalog_name=catalog):
        if sch.name in ignore:
            continue
        read("schema", f"{catalog}.{sch.name}")
        for v in w.volumes.list(catalog_name=catalog, schema_name=sch.name):
            read("volume", v.full_name)
        if sch.name in listed_schemas:
            for t in w.tables.list(catalog_name=catalog, schema_name=sch.name):
                read("table", t.full_name)
    acls = set()
    for scope in w.secrets.list_scopes():
        if scope.name in (spec.get("secret_scopes") or {}):
            acls.update((scope.name, a.principal, a.permission.value) for a in w.secrets.list_acls(scope=scope.name))
    return live, acls


def apply_missing(w, missing_grants: list, missing_acls: list) -> None:
    from databricks.sdk.service.catalog import PermissionsChange, Privilege
    from databricks.sdk.service.workspace import AclPermission

    by_object: dict[tuple, dict[str, list]] = {}
    for kind, name, pid, priv in missing_grants:
        by_object.setdefault((kind, name), {}).setdefault(pid, []).append(Privilege(priv))
    for (kind, name), per_principal in by_object.items():
        changes = [PermissionsChange(principal=pid, add=privs) for pid, privs in per_principal.items()]
        w.grants.update(securable_type=kind, full_name=name, changes=changes)
    for scope, pid, perm in missing_acls:
        w.secrets.put_acl(scope=scope, principal=pid, permission=AclPermission(perm))


def pretty(item: tuple, names: dict[str, str]) -> str:
    """One finding as a line; ids are replaced by the role name when known."""
    return " ".join(str(names.get(x, x)) for x in item)


def compare(w, spec: dict, environ=os.environ) -> dict:
    """The whole comparison in one call (used by the laptop script and by the nightly drift notebook): resolve the roles, read live
    state, diff. `clean` is False on any missing or extra grant AND when a role could not be resolved (drift cannot be judged for it)."""
    ids, names = resolve_principals(w, spec, environ)
    unresolved = sorted(r for r, v in ids.items() if v is None)
    want_g, _ = gl.expected_grants(spec, ids)
    want_a = gl.expected_acls(spec, ids)
    have_g, have_a = read_live(w, spec)
    missing_g, extra_g = gl.diff(want_g, have_g)
    missing_a, extra_a = gl.diff(want_a, have_a)
    return {"names": names, "unresolved": unresolved, "missing_g": missing_g, "extra_g": extra_g, "missing_a": missing_a,
            "extra_a": extra_a, "n_want": (len(want_g), len(want_a)), "n_have": (len(have_g), len(have_a)),
            "clean": not (unresolved or missing_g or extra_g or missing_a or extra_a)}


def describe(r: dict) -> str:
    """Counts and findings as text; ids are replaced by role names, no secret is involved."""
    lines = [f"expected {r['n_want'][0]} grants and {r['n_want'][1]} scope ACLs; live {r['n_have'][0]} and {r['n_have'][1]}"]
    lines += [f"SKIPPED role {x}: could not be resolved (dead token or missing service principal); its grants are not checked" for x in r["unresolved"]]
    lines += ["MISSING " + pretty(m, r["names"]) for m in r["missing_g"] + r["missing_a"]]
    lines += ["EXTRA   " + pretty(e, r["names"]) + " (not in the file; left alone)" for e in r["extra_g"] + r["extra_a"]]
    if r["clean"]:
        lines.append("live state equals the grants file")
    return "\n".join(lines)
