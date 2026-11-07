"""Helper for the Terraform state drill workflow (.github/workflows/terraform-state-drill.yml).

The drill never touches the production state object (`packsense/github.tfstate`): it works on a scratch key, `packsense/drill.tfstate`, in the same
state bucket, and never runs `terraform apply`. Two recoveries are tried:
  A. state LOST: an empty scratch state plus the `import` blocks of infra/terraform/github must rebuild by importing the live objects, with nothing to
     add, change or destroy;
  B. state DAMAGED: the state bucket is versioned, so an earlier version of the production state object is copied into the scratch key (a read of
     production, a write of the scratch key) and a plan against it must add, change and destroy nothing.

  terraform_state_drill.py check-plan FILE --mode empty|restored [--imports 3]   judge a saved `terraform plan` output (exit 1 on a fail)
  terraform_state_drill.py restore-previous                                       copy the newest NON-latest version of the production state to the scratch key
  terraform_state_drill.py clear-scratch                                          delete every version of the scratch key (a denied delete is reported, not fatal)
Environment (restore-previous, clear-scratch): AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY (the state key), TF_STATE_BUCKET. Values are never printed.
"""
import argparse
import os
import re
import sys

PROD_KEY = "packsense/github.tfstate"
SCRATCH_KEY = "packsense/drill.tfstate"
ENDPOINT = "https://s3.eu-central-003.backblazeb2.com"
EXPECTED_IMPORTS = 3   # the two rulesets and the keep-alive deploy key

PLAN_RE = re.compile(r"Plan:\s+(?:(\d+) to import,\s+)?(\d+) to add,\s+(\d+) to change,\s+(\d+) to destroy")


# ---- pure logic (unit-tested) ------------------------------------------------------------------------------------------

def parse_plan(text: str) -> dict:
    m = PLAN_RE.search(text)
    if m:
        imp, add, chg, dst = (int(x or 0) for x in m.groups())
        return {"import": imp, "add": add, "change": chg, "destroy": dst, "no_changes": False}
    if re.search(r"No changes\.", text):
        return {"import": 0, "add": 0, "change": 0, "destroy": 0, "no_changes": True}
    raise ValueError("no plan summary found in the output")


def judge_empty_state(s: dict, imports: int = EXPECTED_IMPORTS) -> tuple:
    """A lost state must be rebuilt by the import blocks: every object imported, nothing to add, change or destroy."""
    if s["add"]:
        return False, f"{s['add']} object(s) would be CREATED although they already exist (state lost, and no import adopts them)"
    if s["change"] or s["destroy"]:
        return False, f"{s['change']} to change, {s['destroy']} to destroy"
    if s["import"] != imports:
        return False, f"{s['import']} imported, expected {imports}"
    return True, f"{s['import']} imported, nothing to add, change or destroy"


def judge_restored_state(s: dict) -> tuple:
    """A restored earlier state may still need to import something, but it must not add, change or destroy anything."""
    if s["add"] or s["change"] or s["destroy"]:
        return False, f"{s['add']} to add, {s['change']} to change, {s['destroy']} to destroy"
    return True, "no changes" if s.get("no_changes") else f"nothing to add, change or destroy ({s['import']} still to import)"


def pick_previous_version(versions: list) -> dict:
    earlier = [v for v in versions if not v.get("IsLatest")]
    if not earlier:
        raise ValueError("no earlier version of the state object exists")
    return max(earlier, key=lambda v: v["LastModified"])


def scratch_key_ok(key: str, prod_key: str = PROD_KEY) -> bool:
    """The scratch key must be under the project prefix, named like a drill, and never a production state key."""
    return key.startswith("packsense/drill") and key != prod_key and key != "packsense/terraform.tfstate"


# ---- S3 side (B2's S3-compatible API) ----------------------------------------------------------------------------------

def client():
    import boto3
    from botocore.config import Config
    for name in ("AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "TF_STATE_BUCKET"):
        if not os.environ.get(name):
            sys.exit(f"missing environment variable: {name}")
    return boto3.client("s3", endpoint_url=ENDPOINT, region_name="eu-central-003", config=Config(signature_version="s3v4", s3={"addressing_style": "path"}))


def versions_of(s3, bucket: str, key: str) -> list:
    out = []
    for page in s3.get_paginator("list_object_versions").paginate(Bucket=bucket, Prefix=key):
        out += [v for v in page.get("Versions", []) if v["Key"] == key]
    return out


def cmd_restore_previous(args) -> int:
    assert scratch_key_ok(SCRATCH_KEY), "the scratch key is not safe"
    s3, bucket = client(), os.environ["TF_STATE_BUCKET"]
    vs = versions_of(s3, bucket, PROD_KEY)
    print(f"the production state object has {len(vs)} version(s)")
    prev = pick_previous_version(vs)
    print(f"copying the newest earlier version (written {prev['LastModified'].isoformat()}, {prev['Size']} bytes) to the scratch key")
    body = s3.get_object(Bucket=bucket, Key=PROD_KEY, VersionId=prev["VersionId"])["Body"].read()
    s3.put_object(Bucket=bucket, Key=SCRATCH_KEY, Body=body)
    return 0


def cmd_clear_scratch(args) -> int:
    assert scratch_key_ok(SCRATCH_KEY), "the scratch key is not safe"
    s3, bucket = client(), os.environ["TF_STATE_BUCKET"]
    vs = versions_of(s3, bucket, SCRATCH_KEY)
    done = 0
    for v in vs:
        try:
            s3.delete_object(Bucket=bucket, Key=SCRATCH_KEY, VersionId=v["VersionId"])
            done += 1
        except Exception as e:
            print(f"could not delete a version of the scratch key ({type(e).__name__}); it stays as a small unused file")
            break
    print(f"scratch key: {done} of {len(vs)} version(s) deleted")
    return 0


def cmd_check_plan(args) -> int:
    text = open(args.file, encoding="utf-8", errors="replace").read()
    s = parse_plan(text)
    ok, why = judge_empty_state(s, args.imports) if args.mode == "empty" else judge_restored_state(s)
    line = f"{'PASS' if ok else 'FAIL'} ({args.mode}): {why}"
    print(line)
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as fh:
            fh.write(f"- {line}\n")
    return 0 if ok else 1


def main() -> int:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="command", required=True)
    c = sub.add_parser("check-plan")
    c.add_argument("file")
    c.add_argument("--mode", choices=["empty", "restored"], required=True)
    c.add_argument("--imports", type=int, default=EXPECTED_IMPORTS)
    sub.add_parser("restore-previous")
    sub.add_parser("clear-scratch")
    args = ap.parse_args()
    return {"check-plan": cmd_check_plan, "restore-previous": cmd_restore_previous, "clear-scratch": cmd_clear_scratch}[args.command](args)


if __name__ == "__main__":
    sys.exit(main())
