"""Compare the grants file with Unity Catalog and the secret scopes, and add what is missing. An admin runs it.

  python p5_governance/bootstrap/apply_grants.py plan  --env-file .env    # show the difference, change nothing
  python p5_governance/bootstrap/apply_grants.py apply --env-file .env    # add the missing grants and ACLs (never revokes)
  python p5_governance/bootstrap/apply_grants.py check --env-file .env    # exit 1 if anything is missing OR extra (drift)

Environment: DATABRICKS_HOST, DATABRICKS_TOKEN (admin); DATABRICKS_PIPELINE_TOKEN and DATABRICKS_ANALYST_TOKEN are optional (a role
whose token is missing or dead is skipped, and said so). Values are never printed. A grant that exists live and is not in the file is
EXTRA: it is listed and left alone, because revoking is the destructive direction and a human decides.
"""
import argparse
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
import grants_lib as gl  # noqa: E402
import grants_live as live  # noqa: E402


def load_env_file(path: str) -> None:
    for raw in open(path, encoding="utf-8").read().splitlines():
        line = raw.split("#", 1)[0].strip()
        if line and "=" in line:
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip())


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("mode", choices=["plan", "apply", "check"])
    ap.add_argument("--env-file")
    ap.add_argument("--grants", default=str(gl.DEFAULT_PATH))
    args = ap.parse_args(argv)
    if args.env_file:
        load_env_file(args.env_file)
    for name in ("DATABRICKS_HOST", "DATABRICKS_TOKEN"):
        if not os.environ.get(name):
            sys.exit(f"missing environment variable: {name}")

    from databricks.sdk import WorkspaceClient

    spec = gl.load_spec(args.grants)
    w = WorkspaceClient(host=os.environ["DATABRICKS_HOST"], token=os.environ["DATABRICKS_TOKEN"], auth_type="pat")
    ids, names = live.resolve_principals(w, spec)
    unresolved = [r for r, v in ids.items() if v is None]
    for r in unresolved:
        print(f"SKIPPED role {r}: could not be resolved (missing or dead token, or no such service principal); its grants are not checked")

    want_grants, _ = gl.expected_grants(spec, ids)
    want_acls = gl.expected_acls(spec, ids)
    have_grants, have_acls = live.read_live(w, spec)
    missing_g, extra_g = gl.diff(want_grants, have_grants)
    missing_a, extra_a = gl.diff(want_acls, have_acls)

    print(f"expected {len(want_grants)} grants and {len(want_acls)} scope ACLs; live {len(have_grants)} and {len(have_acls)}")
    for m in missing_g + missing_a:
        print("MISSING", live.pretty(m, names))
    for e in extra_g + extra_a:
        print("EXTRA  ", live.pretty(e, names), "(not in the file; left alone)")
    if not (missing_g or missing_a or extra_g or extra_a):
        print("live state equals the grants file")

    if args.mode == "apply" and (missing_g or missing_a):
        live.apply_missing(w, missing_g, missing_a)
        print(f"added {len(missing_g)} grants and {len(missing_a)} scope ACLs")
        return 0
    if args.mode == "check":
        return 1 if (missing_g or missing_a or extra_g or extra_a) else 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
