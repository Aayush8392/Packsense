"""Pure logic for the grants file: load and validate it, turn it into the set of grants it expects, diff that against what is live,
and render the SQL block the READMEs show. No Databricks calls here (see grants_live.py), so everything is testable offline.
"""
from __future__ import annotations

from pathlib import Path

import yaml

SECURABLE_TYPES = ("catalog", "schema", "volume", "table")
PRIVILEGES = {
    "catalog": {"USE_CATALOG", "USE_SCHEMA", "CREATE_SCHEMA", "SELECT", "MODIFY", "CREATE_TABLE"},
    "schema": {"USE_SCHEMA", "CREATE_TABLE", "SELECT", "MODIFY", "CREATE_VOLUME", "EXECUTE", "READ_VOLUME", "WRITE_VOLUME"},
    "volume": {"READ_VOLUME", "WRITE_VOLUME"},
    "table": {"SELECT", "MODIFY"},
}
SCOPE_PERMISSIONS = {"READ", "WRITE", "MANAGE"}
PRINCIPAL_KINDS = {"service_principal", "user_from_token"}
DEFAULT_PATH = Path(__file__).resolve().parent / "grants.yml"


class SpecError(ValueError):
    pass


def load_spec(path: str | Path = DEFAULT_PATH) -> dict:
    spec = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    validate(spec)
    return spec


def validate(spec: dict) -> None:
    if not isinstance(spec, dict) or spec.get("version") != 1:
        raise SpecError("grants file: version must be 1")
    roles = spec.get("principals") or {}
    for role, p in roles.items():
        if p.get("kind") not in PRINCIPAL_KINDS:
            raise SpecError(f"principal {role}: kind must be one of {sorted(PRINCIPAL_KINDS)}")
        if p["kind"] == "service_principal" and not p.get("name"):
            raise SpecError(f"principal {role}: a service principal needs a name")
        if p["kind"] == "user_from_token" and not p.get("env"):
            raise SpecError(f"principal {role}: a user needs the environment variable of its token")
    seen = set()
    catalog = spec.get("catalog")
    if not catalog:
        raise SpecError("grants file: catalog is required")
    for s in spec.get("securables") or []:
        kind, name = s.get("type"), s.get("name")
        if kind not in SECURABLE_TYPES:
            raise SpecError(f"securable {name}: type must be one of {SECURABLE_TYPES}")
        if (kind, name) in seen:
            raise SpecError(f"securable {kind} {name} is listed twice")
        seen.add((kind, name))
        depth = {"catalog": 1, "schema": 2, "volume": 3, "table": 3}[kind]
        if name.count(".") + 1 != depth or not name.startswith(catalog):
            raise SpecError(f"securable {kind} {name}: the name must be a full name inside catalog {catalog}")
        for role, privs in (s.get("grants") or {}).items():
            if role not in roles:
                raise SpecError(f"securable {name}: unknown principal {role}")
            bad = set(privs) - PRIVILEGES[kind]
            if bad:
                raise SpecError(f"securable {name}, {role}: privileges not allowed on a {kind}: {sorted(bad)}")
    for role, tables in (spec.get("system_grants") or {}).items():
        if role not in roles:
            raise SpecError(f"system_grants: unknown principal {role}")
        if not all(isinstance(t, str) and t.startswith("system.") and t.count(".") == 2 for t in tables):
            raise SpecError(f"system_grants {role}: each entry must be a full system table name (system.<schema>.<table>)")
    for scope, acls in (spec.get("secret_scopes") or {}).items():
        for role, perm in acls.items():
            if role not in roles:
                raise SpecError(f"secret scope {scope}: unknown principal {role}")
            if perm not in SCOPE_PERMISSIONS:
                raise SpecError(f"secret scope {scope}, {role}: permission must be one of {sorted(SCOPE_PERMISSIONS)}")


def expected_grants(spec: dict, ids: dict[str, str | None]) -> tuple[set, list[str]]:
    """The set of (type, name, principal id, privilege) the file expects, and the roles skipped because they could not be resolved."""
    out, skipped = set(), []
    for s in spec.get("securables") or []:
        for role, privs in (s.get("grants") or {}).items():
            pid = ids.get(role)
            if pid is None:
                if role not in skipped:
                    skipped.append(role)
                continue
            out.update((s["type"], s["name"], pid, p) for p in privs)
    return out, skipped


def expected_acls(spec: dict, ids: dict[str, str | None]) -> set:
    out = set()
    for scope, acls in (spec.get("secret_scopes") or {}).items():
        for role, perm in acls.items():
            if ids.get(role) is not None:
                out.add((scope, ids[role], perm))
    return out


def diff(expected: set, live: set) -> tuple[list, list]:
    """(missing, extra), each sorted: missing = expected and not live; extra = live and not expected."""
    return sorted(expected - live), sorted(live - expected)


def render_sql(spec: dict) -> str:
    """The grants as SQL with the role name in backticks, for the READMEs. Generated: do not edit by hand."""
    lines = []
    for s in spec.get("securables") or []:
        for role, privs in (s.get("grants") or {}).items():
            names = ", ".join(p.replace("_", " ") for p in privs)
            lines.append(f"GRANT {names} ON {s['type'].upper()} {s['name']} TO `{role}`;")
    for scope, acls in (spec.get("secret_scopes") or {}).items():
        for role, perm in acls.items():
            lines.append(f"-- secret scope {scope}: {perm} for `{role}`")
    return "\n".join(lines)


def names_in_spec(spec: dict) -> dict[str, set[str]]:
    """The schemas, volumes and scopes the file mentions (used by the coverage test)."""
    out = {"schema": set(), "volume": set(), "scope": set(spec.get("secret_scopes") or {})}
    for s in spec.get("securables") or []:
        if s["type"] in out:
            out[s["type"]].add(s["name"])
    return out
