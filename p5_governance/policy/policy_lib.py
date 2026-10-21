"""Pure logic of the nightly policy tests: the checks file, how an attempt is judged, and the tie between the checks and grants.yml.

A policy test signs in as one identity and TRIES something. A `deny` check passes only when the attempt fails with a permission error; an
`allow` check passes only when it succeeds. Any other error (a typo, a missing table, a network problem) is an ERROR, not a pass: a test
that is "denied" for the wrong reason proves nothing. Nothing here prints a value: outcomes and short error classes only.
"""
from __future__ import annotations

import re
from pathlib import Path

import yaml

HERE = Path(__file__).resolve().parent
DEFAULT_CHECKS = HERE / "checks.yml"
PROBE = "_policy_probe"                      # every object a check creates carries this name, and is dropped again
ACTIONS = {"read_table", "create_table", "create_schema", "list_secrets", "upload_file", "create_volume", "get_catalog", "rows_only"}
NAME_RE = re.compile(r"^[A-Za-z0-9_]+(\.[A-Za-z0-9_]+){0,2}$")
DENIED = re.compile(r"INSUFFICIENT_PERMISSIONS|PERMISSION_DENIED|SQLSTATE:\s*42501|\bForbidden\b|\b403\b|\[Errno 13\] Permission denied")


class ChecksError(ValueError):
    pass


def is_denied(exc: BaseException) -> bool:
    """True only for a permission error. A NotFound, a syntax error or a timeout is NOT a denial."""
    return type(exc).__name__ in ("PermissionDenied", "Forbidden", "PermissionError") or bool(DENIED.search(str(exc)))


def load_checks(path: str | Path = DEFAULT_CHECKS) -> dict:
    spec = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    validate_checks(spec)
    return spec


def validate_checks(spec: dict) -> None:
    if not isinstance(spec, dict) or spec.get("version") != 1 or not spec.get("identities"):
        raise ChecksError("checks file: version must be 1 and identities are required")
    for ident, body in spec["identities"].items():
        checks = body.get("checks") or []
        kinds = {c.get("kind") for c in checks}
        if not {"deny", "allow"} <= kinds:
            raise ChecksError(f"{ident}: needs at least one deny check and one allow check (an allow check proves the identity works at all)")
        names = [c.get("name") for c in checks]
        if len(set(names)) != len(names) or not all(names):
            raise ChecksError(f"{ident}: check names must be present and unique")
        for c in checks:
            if c["kind"] not in ("deny", "allow") or c.get("action") not in ACTIONS:
                raise ChecksError(f"{ident}/{c.get('name')}: kind must be deny or allow and action one of {sorted(ACTIONS)}")
            for field in ("table", "schema", "scope", "volume", "catalog", "column"):
                if field in c and not NAME_RE.match(str(c[field])):
                    raise ChecksError(f"{ident}/{c['name']}: {field} is not a plain object name")
            need = {"read_table": "table", "create_table": "schema", "create_volume": "schema", "list_secrets": "scope",
                    "upload_file": "volume", "get_catalog": "catalog", "rows_only": "table"}.get(c["action"])
            if need and need not in c:
                raise ChecksError(f"{ident}/{c['name']}: action {c['action']} needs {need}")
            if c["action"] == "rows_only":
                if c["kind"] != "allow" or "column" not in c or not c.get("allowed"):
                    raise ChecksError(f"{ident}/{c['name']}: rows_only is an allow check with a column and a non-empty allowed list")


def evaluate(check: dict, attempt) -> dict:
    """Run one attempt (a zero-argument callable) and judge it. Returns {name, kind, status, detail}; status PASS, FAIL or ERROR."""
    out = {"name": check["name"], "kind": check["kind"]}
    try:
        result = attempt()
    except Exception as e:  # noqa: BLE001
        denied = is_denied(e)
        if check["kind"] == "deny" and denied:
            return {**out, "status": "PASS", "detail": "denied"}
        if check["kind"] == "allow" and denied:
            return {**out, "status": "FAIL", "detail": "denied, but this identity must be allowed"}
        return {**out, "status": "ERROR", "detail": f"{type(e).__name__}: {str(e)[:120]}".replace("\n", " ")}
    if check["kind"] == "deny":
        return {**out, "status": "FAIL", "detail": "ALLOWED, but this identity must be denied"}
    if check.get("action") == "rows_only":
        return {**out, **judge_rows(check, result)}
    return {**out, "status": "PASS", "detail": "allowed"}


def judge_rows(check: dict, values) -> dict:
    """A rows_only check reads the DISTINCT values of one column through a row filter. It passes only when the identity sees at least one row
    and every value is in the allowed list: seeing nothing means the filter or the access table is broken (fail closed is not a pass either),
    seeing another market means the filter is gone or wrong. Only counts are reported, never the values."""
    got = {v for v in (values or [])}
    allowed = set(check["allowed"])
    if not got:
        return {"status": "FAIL", "detail": "reads the table but sees no rows (the filter or the access table is broken)"}
    outside = got - allowed
    if outside:
        return {"status": "FAIL", "detail": f"sees {len(outside)} value(s) outside its allowed set: the row filter is missing or wrong"}
    return {"status": "PASS", "detail": f"sees only its allowed set ({len(got)} value(s))"}


def run_checks(checks: list[dict], attempt_for, cleanup_for=None) -> list[dict]:
    """attempt_for(check) -> zero-argument callable; cleanup_for(check) -> zero-argument callable run afterwards whatever happened
    (a check that unexpectedly created something must not leave it behind)."""
    results = []
    for c in checks:
        results.append(evaluate(c, attempt_for(c)))
        if cleanup_for is not None:
            try:
                cleanup_for(c)()
            except Exception:  # noqa: BLE001  a cleanup of something that was never created fails harmlessly
                pass
    return results


def summarise(identity: str, results: list[dict]) -> tuple[bool, str]:
    bad = [r for r in results if r["status"] != "PASS"]
    head = f"{identity}: {len(results) - len(bad)}/{len(results)} checks passed"
    lines = [head] + [f"  {r['status']} {r['kind']} {r['name']}: {r['detail']}" for r in bad]
    return not bad, "\n".join(lines)


# --- the tie between the checks and grants.yml -------------------------------------------------------------------------------

def expected_allowed(role: str, check: dict, grants_spec: dict) -> bool:
    """Would grants.yml let this role do what the check tries? The checks file must agree with the grants file in BOTH directions."""
    have: dict[tuple[str, str], set[str]] = {}
    for s in grants_spec["securables"]:
        have[(s["type"], s["name"])] = set((s.get("grants") or {}).get(role, []))
    cat = grants_spec["catalog"]

    def has(kind: str, name: str, priv: str) -> bool:
        return priv in have.get((kind, name), set())

    def schema_of(full: str) -> str:
        return ".".join(full.split(".")[:2])

    a = check["action"]
    if a in ("read_table", "rows_only"):
        t = check["table"]
        if t.startswith("system."):         # Databricks' own system tables are outside the managed catalog: grants.yml lists them under `system_grants`
            return t in (grants_spec.get("system_grants") or {}).get(role, [])
        s = schema_of(t)
        return has("catalog", cat, "USE_CATALOG") and has("schema", s, "USE_SCHEMA") and (has("table", t, "SELECT") or has("schema", s, "SELECT"))
    if a == "create_table":
        s = check["schema"]
        return has("catalog", cat, "USE_CATALOG") and has("schema", s, "USE_SCHEMA") and has("schema", s, "CREATE_TABLE")
    if a == "create_volume":
        s = check["schema"]
        return has("schema", s, "USE_SCHEMA") and has("schema", s, "CREATE_VOLUME")
    if a == "create_schema":
        return has("catalog", cat, "CREATE_SCHEMA")
    if a == "get_catalog":
        return has("catalog", cat, "USE_CATALOG")
    if a == "upload_file":
        v = check["volume"]
        s = schema_of(v)
        return has("schema", s, "USE_SCHEMA") and has("volume", v, "WRITE_VOLUME")
    if a == "list_secrets":
        return role in (grants_spec.get("secret_scopes") or {}).get(check["scope"], {})
    raise ChecksError(f"unknown action {a}")
