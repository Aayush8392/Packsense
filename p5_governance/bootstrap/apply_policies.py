"""Compare the policies file (row filters, masks, who sees what) with Unity Catalog, and apply it. An admin runs it.

  python p5_governance/bootstrap/apply_policies.py plan  --env-file .env     # show the difference, change nothing
  python p5_governance/bootstrap/apply_policies.py apply --env-file .env --only dev|prod|all
  python p5_governance/bootstrap/apply_policies.py check --env-file .env     # exit 1 on any difference (the nightly drift notebook does the same)

`apply` creates schema workspace.packsense_policy, the access table, the three functions, then attaches the filters and masks of the chosen
environment (default: dev: a mask on production silver is a production change, so prod is always asked for by name). A mask is attached only
AFTER the access rows exist. Run it again after a table swap (a rename or a drop loses filters and masks like it loses grants).
Environment: DATABRICKS_HOST, DATABRICKS_TOKEN (admin); DATABRICKS_PIPELINE_TOKEN and DATABRICKS_ANALYST_TOKEN to resolve those roles. Values are never printed.
"""
import argparse
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
import grants_lib as gl  # noqa: E402
import policies_lib as pol  # noqa: E402
import policies_live as live  # noqa: E402


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
    ap.add_argument("--only", choices=["dev", "prod", "all"], default="dev")
    ap.add_argument("--no-masks", action="store_true", help="attach row filters only (a mask on production silver waits for a clean scheduled run)")
    ap.add_argument("--policies", default=str(pol.DEFAULT_PATH))
    args = ap.parse_args(argv)
    if args.env_file:
        load_env_file(args.env_file)
    for name in ("DATABRICKS_HOST", "DATABRICKS_TOKEN"):
        if not os.environ.get(name):
            sys.exit(f"missing environment variable: {name}")

    from databricks.sdk import WorkspaceClient

    grants_spec = gl.load_spec()
    spec = pol.load_spec(args.policies)
    pol.validate(spec, set(grants_spec["principals"]))
    w = WorkspaceClient(host=os.environ["DATABRICKS_HOST"], token=os.environ["DATABRICKS_TOKEN"], auth_type="pat")
    if args.mode == "apply":
        for s in live.apply(w, spec, grants_spec, only=args.only, masks=not args.no_masks):
            print("ran:", s if len(s) < 200 else s[:200] + " ...")
    r = live.compare(w, spec, grants_spec)
    print(live.describe(r))
    if args.mode == "check":
        return 0 if r["clean"] else 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
