"""Test helper: insert many rows into a DuckDB table in a few statements.

One parameterised `con.execute("insert ... values (?, ...)", row)` per row costs about 18 ms, because the DuckDB Python layer probes for importable modules on every call (about 120,000 `stat`
calls for 1,000 rows, 17 s on Windows); one multi-row VALUES statement takes 0.07 s for 771 rows (measured 2026-11-13; the same cause as the 2026-11-04 Parquet fix in test_snapshot_lib.py).
The rows are test data from real fixtures: values are rendered as SQL literals (strings quoted, lists as arrays, None as NULL).
"""


class Raw(str):
    """A SQL fragment that lit() leaves as it is (for example DATE '2026-10-19')."""


def lit(v):
    if isinstance(v, Raw):
        return str(v)
    if v is None:
        return "NULL"
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float)):
        return repr(v)
    if isinstance(v, str):
        return "'" + v.replace("'", "''") + "'"
    if isinstance(v, (list, tuple)):
        return "[" + ", ".join(lit(x) for x in v) + "]"
    raise TypeError(f"no SQL literal for {type(v).__name__}")


def insert_rows(con, table, rows, chunk=500):
    """INSERT the rows (each a list of values, in column order) in statements of at most `chunk` rows."""
    for i in range(0, len(rows), chunk):
        con.execute(f"insert into {table} values " + ", ".join("(" + ", ".join(lit(x) for x in row) + ")" for row in rows[i:i + chunk]))
