"""Delete-marker tripwire: has anything hidden an object in the capture bucket?

The capture key is upload-only, but an upload-only B2 key can still hide objects (a delete marker; test B1). Hidden
files are kept 30 days, so a hidden file is recoverable if someone notices in time. This job lists every object
version with a read-only key and fails on any delete marker the bucket's lifecycle rules did not create.

Expected markers (the lifecycle rules in infra/terraform/main.tf):
  tmp/  hidden after 7 days                -> always allowed
  raw/  hidden after 270 days of uploading -> allowed only if the key's earlier version is at least 269 days older
Anything else, including taxonomies/ (no lifecycle rule), is unexpected.

Configuration comes from environment variables; values are never printed.
  B2_S3_ENDPOINT, B2_BUCKET, B2_READ_KEY_ID, B2_READ_APPLICATION_KEY
  ALLOW_TMP_MARKERS=false switches off the tmp/ allowance (used by the deliberate-failure self-test)
  --make-test-marker (self-test only) also needs B2_UPLOAD_KEY_ID, B2_UPLOAD_APPLICATION_KEY: uploads one object
  under tmp/ and deletes it, which leaves a real delete marker.
Exit codes: 0 no unexpected markers, 1 unexpected marker found.
"""
import argparse
import datetime as dt
import os
import sys

import boto3
from botocore.config import Config

from capture_deltas import need

RAW_HIDE_AFTER_DAYS = 270
RAW_TOLERANCE_DAYS = 1


def client(key_id_var: str, key_var: str):
    endpoint = need("B2_S3_ENDPOINT")
    return boto3.client(
        "s3", endpoint_url=endpoint if endpoint.startswith("http") else "https://" + endpoint,
        aws_access_key_id=need(key_id_var), aws_secret_access_key=need(key_var),
        config=Config(signature_version="s3v4", retries={"max_attempts": 5, "mode": "standard"}),
    )


def unexpected_markers(markers: list[dict], versions: list[dict], allow_tmp: bool = True) -> list[dict]:
    """Delete markers the lifecycle rules would not have created.

    markers and versions are dicts with Key and LastModified (a datetime), as boto3 returns them.
    """
    min_age = dt.timedelta(days=RAW_HIDE_AFTER_DAYS - RAW_TOLERANCE_DAYS)
    bad = []
    for m in markers:
        key = m["Key"]
        if key.startswith("tmp/") and allow_tmp:
            continue
        if key.startswith("raw/"):
            earlier = [v["LastModified"] for v in versions if v["Key"] == key and v["LastModified"] <= m["LastModified"]]
            if earlier and m["LastModified"] - min(earlier) >= min_age:
                continue
        bad.append(m)
    return bad


def list_all(s3, bucket: str) -> tuple[list[dict], list[dict]]:
    versions, markers = [], []
    for page in s3.get_paginator("list_object_versions").paginate(Bucket=bucket):
        versions += page.get("Versions", [])
        markers += page.get("DeleteMarkers", [])
    return versions, markers


def make_test_marker(bucket: str) -> str:
    s3 = client("B2_UPLOAD_KEY_ID", "B2_UPLOAD_APPLICATION_KEY")
    key = "tmp/tripwire-selftest-" + dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    s3.put_object(Bucket=bucket, Key=key, Body=b"delete-marker tripwire self-test")
    s3.delete_object(Bucket=bucket, Key=key)
    print(f"self-test: uploaded and deleted {key} (leaves a delete marker under tmp/)")
    return key


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--make-test-marker", action="store_true", help="self-test: create a real marker under tmp/ first")
    args = ap.parse_args()
    bucket = need("B2_BUCKET")
    allow_tmp = os.environ.get("ALLOW_TMP_MARKERS", "true").strip().lower() != "false"
    if args.make_test_marker:
        make_test_marker(bucket)
    versions, markers = list_all(client("B2_READ_KEY_ID", "B2_READ_APPLICATION_KEY"), bucket)
    bad = unexpected_markers(markers, versions, allow_tmp)
    print(f"{len(versions)} object versions, {len(markers)} delete markers, {len(bad)} unexpected"
          f" (tmp/ allowance {'on' if allow_tmp else 'OFF'})")
    for m in bad:
        print(f"UNEXPECTED delete marker: {m['Key']} at {m['LastModified'].isoformat()}")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
