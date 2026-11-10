import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import readonly_sql as r  # noqa: E402


def test_only_a_single_select_passes():
    assert r.is_read_only("select 1")
    assert r.is_read_only("  WITH a as (select 1) select * from a;")
    assert not r.is_read_only("delete from t")
    assert not r.is_read_only("select 1; drop table t")
    assert not r.is_read_only("insert into t select 1")
