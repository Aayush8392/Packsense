"""Freshness tripwire: is the newest Open Food Facts delta file actually in the landing volume?

Independent of the capture job, so it also catches a capture that never ran or ran before OFF published.
Compares the newest file in OFF's index with the files in the Databricks landing volume.

Configuration comes from environment variables; values are never printed.
  DATABRICKS_HOST, DATABRICKS_PIPELINE_TOKEN
Exit codes: 0 fresh, 1 newest OFF delta missing from landing.
"""
import datetime as dt
import sys

from capture_deltas import NAME_RE, Landing, list_index


def main() -> int:
    names = list_index()
    if not names:
        print("OFF index lists no delta files")
        return 1
    newest = names[-1]
    have = Landing().names("deltas")
    ended = int(NAME_RE.match(newest).group(2))
    age_h = (dt.datetime.now(dt.timezone.utc).timestamp() - ended) / 3600
    print(f"newest OFF delta: {newest} (ends {age_h:.1f} h ago); {len(have)} files in landing")
    if newest in have:
        print("fresh: the newest OFF delta is in landing")
        return 0
    missing = [n for n in names if n not in have]
    print(f"STALE: {newest} is not in landing; {len(missing)} OFF delta file(s) missing in total")
    return 1


if __name__ == "__main__":
    sys.exit(main())
