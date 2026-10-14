"""Delete-marker classification.

Key names are real ones from this project (OFF delta file names and a real taxonomy snapshot path); the dates are the
real capture time of the first run. A synthetic marker is not needed: the end-to-end proof is the workflow's
self-test, which creates a real delete marker in the real bucket.
"""
import datetime as dt
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from check_delete_markers import unexpected_markers  # noqa: E402

UTC = dt.timezone.utc
RAW = "raw/openfoodfacts_products_1791094877_1791181482.json.gz"
TAX = "taxonomies/data_quality/1760000000_0123456789ab.json.gz"
UPLOADED = dt.datetime(2026, 10, 13, 21, 19, tzinfo=UTC)


def marker(key, when):
    return {"Key": key, "LastModified": when}


def version(key, when):
    return {"Key": key, "LastModified": when}


def test_no_markers_is_fine():
    assert unexpected_markers([], [version(RAW, UPLOADED)]) == []


def test_tmp_marker_is_allowed():
    m = marker("tmp/tripwire-selftest-20261015T060000Z", UPLOADED)
    assert unexpected_markers([m], []) == []


def test_tmp_marker_flagged_when_allowance_off():
    m = marker("tmp/tripwire-selftest-20261015T060000Z", UPLOADED)
    assert unexpected_markers([m], [], allow_tmp=False) == [m]


def test_raw_marker_the_day_after_upload_is_unexpected():
    m = marker(RAW, UPLOADED + dt.timedelta(days=1))
    assert unexpected_markers([m], [version(RAW, UPLOADED)]) == [m]


def test_raw_marker_after_270_days_is_the_lifecycle_rule():
    m = marker(RAW, UPLOADED + dt.timedelta(days=270))
    assert unexpected_markers([m], [version(RAW, UPLOADED)]) == []


def test_raw_marker_with_no_earlier_version_is_unexpected():
    m = marker(RAW, UPLOADED + dt.timedelta(days=300))
    assert unexpected_markers([m], []) == [m]


def test_marker_outside_raw_and_tmp_is_unexpected():
    m = marker(TAX, UPLOADED + dt.timedelta(days=400))
    assert unexpected_markers([m], [version(TAX, UPLOADED)]) == [m]
