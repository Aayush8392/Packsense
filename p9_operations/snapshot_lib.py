"""Flag history from OFF's dated Hugging Face snapshots (P9 operations; roadmap Phase A).

Why this exists: the flag-fix label needs to know when a flag was on a product and when it went away, and our own daily deltas only start on
30 Sep and rarely show a product before its fix. OFF's dataset `openfoodfacts/product-database` is rebuilt about twice a day and every build
is a git commit, so a dated snapshot of the whole catalogue can be read back for about a year. We read a small number of columns of a weekly
snapshot with DuckDB, compare consecutive snapshots and keep only the CHANGES (flag appeared or disappeared, product left), never the snapshots.

What is measured (2026-10-20, three snapshots 1, 10 and 19 Oct): one snapshot costs about 310 MB for these columns and about 190 s on
Databricks; the Hugging Face resolver allows 3,000 requests per 5 minutes, so the signed CDN address is resolved once and read directly.
What is not known: Databricks Free Edition publishes no storage or daily compute cap, so every run is bounded on our side (byte guard per
snapshot, a cap on pairs per run, a rolling retention of the event tables).

Everything here is plain Python except `compute_pair`, which takes a DuckDB connection; the notebook does the network and Delta work.
"""
from __future__ import annotations

import datetime as dt
import json
import re
import sys
import threading
import urllib.error
import urllib.request

REPO = "openfoodfacts/product-database"
UA = {"User-Agent": "packsense-snapshots/0.1 (portfolio project)"}
# (column alias in the loaded table, severity name, column in OFF's Parquet)
SEVERITIES = (
    ("e", "error", "data_quality_errors_tags"),
    ("w", "warning", "data_quality_warnings_tags"),
    ("i", "info", "data_quality_info_tags"),
)
BYTE_GUARD = 1_000_000_000      # one snapshot is ~310 MB for these columns; a read that passes 1 GB is stopped
RETENTION_MONTHS = 13           # flag events older than this (by the newer snapshot's date) are deleted at the end of a run

DEFAULT_SCHEMA = "workspace.packsense_snapshots"
TABLES = ("snapshot_flag_events", "snapshot_open_counts", "snapshot_presence_events", "snapshot_manifest")


# --- the flag family -----------------------------------------------------------------------------------------------------------------------
# OFF writes one check under several tags: a plain tag (`en:nutrition-value-total-over-105`) and one per nutrition source and basis
# (`en:nutrition-packaging-as-sold-100g-value-total-over-105`). A product that moves from the plain tag to the source tag has not been
# fixed, so the label is built on the FAMILY, the tag with the source and basis stripped. Measured 2026-10-20: 176 of 215 'gone but still
# violating' error cases were exactly this move.

# The per-source tags seen on 2026-10-20 (1,538 distinct tags in two snapshots): source `packaging` or `manufacturer`, `as-sold` or (without `as-`)
# `prepared`, basis `100g`, `100ml`, `serving`, `100kj`, `100-` or `100mmol-l`.
_SOURCE_TAG = re.compile(r"^nutrition-[a-z0-9]+-(?:as-)?(?:sold|prepared)-(?:serving|100[a-z]*(?:-l)?-?)-")
_LEFTOVER = re.compile(r"(?:^|-)(?:as-)?(?:sold|prepared)-(?:serving|100)")


def family_key(tag: str) -> str:
    """`en:nutrition-packaging-as-sold-100g-value-total-over-105` and `en:nutrition-value-total-over-105` both give `value-total-over-105`;
    a tag with no such prefix keeps its text (without the language prefix)."""
    body = tag.split(":", 1)[1] if ":" in tag else tag
    stripped = _SOURCE_TAG.sub("", body, count=1)
    if stripped != body:
        return stripped
    return body[len("nutrition-"):] if body.startswith("nutrition-") else body


def looks_unparsed(tag: str) -> bool:
    """True when the family still carries a source/basis marker: OFF added a source or basis this module does not know. Such a tag would be
    mistaken for its own family, so the notebook counts them and a test asserts there are none among the real tags."""
    return bool(_LEFTOVER.search(family_key(tag)))


# --- which snapshots ----------------------------------------------------------------------------------------------------------------------

class Snapshot:
    __slots__ = ("sha", "date")

    def __init__(self, sha: str, date: dt.datetime):
        self.sha, self.date = sha, date

    def __repr__(self):
        return f"Snapshot({self.sha[:8]}, {self.date.isoformat()})"

    def __eq__(self, other):
        return isinstance(other, Snapshot) and (self.sha, self.date) == (other.sha, other.date)


def parse_commit_date(text: str) -> dt.datetime:
    return dt.datetime.fromisoformat(text.replace("Z", "+00:00"))


def weekly_targets(now: dt.datetime, weeks: int) -> list[dt.datetime]:
    """Monday 00:00 UTC of the current week and of each of the `weeks` weeks before it, oldest first. Anchored to Mondays so that a rerun
    on any day picks the same snapshots (and therefore the same pair ids)."""
    now = now.astimezone(dt.timezone.utc)
    monday = (now - dt.timedelta(days=now.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)
    return [monday - dt.timedelta(weeks=k) for k in range(weeks, -1, -1)]


def pick_snapshots(commits: list[dict], targets: list[dt.datetime]) -> list[Snapshot]:
    """For every target time the newest commit made at or before it. A target older than the oldest commit is skipped; neighbours that pick the
    same commit are kept once. `commits` are Hugging Face's commit records ({'id', 'date'}), in any order."""
    dated = sorted(((parse_commit_date(c["date"]), c["id"]) for c in commits), reverse=True)
    out: list[Snapshot] = []
    for target in targets:
        for date, sha in dated:
            if date <= target:
                if not out or out[-1].sha != sha:
                    out.append(Snapshot(sha, date))
                break
    return out


def pair_id(a: Snapshot, b: Snapshot) -> str:
    return f"{a.sha[:12]}_{b.sha[:12]}"


def pairs_to_do(snapshots: list[Snapshot], done: set[str], max_pairs: int) -> list[tuple[Snapshot, Snapshot]]:
    """Consecutive pairs (oldest first) whose id is not in `done`, at most `max_pairs`."""
    out = []
    for a, b in zip(snapshots, snapshots[1:]):
        if pair_id(a, b) not in done:
            out.append((a, b))
        if len(out) >= max_pairs:
            break
    return out


def retention_cutoff(now: dt.datetime, months: int = RETENTION_MONTHS) -> dt.date:
    """The date `months` calendar months before `now` (the day clipped to the month's length); events with a newer-snapshot date before it go."""
    y, m = now.year, now.month - months
    while m <= 0:
        y, m = y - 1, m + 12
    last = (dt.date(y + (m == 12), m % 12 + 1, 1) - dt.timedelta(days=1)).day
    return dt.date(y, m, min(now.day, last))


# --- the network --------------------------------------------------------------------------------------------------------------------------

class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def fetch_commits(pages: int = 4, opener=urllib.request.urlopen) -> list[dict]:
    """Hugging Face's commit list for the dataset, newest first, 50 per page (about two commits a day: 4 pages are about 100 days)."""
    out: list[dict] = []
    for p in range(pages):
        req = urllib.request.Request(f"https://huggingface.co/api/datasets/{REPO}/commits/main?p={p}&limit=50", headers=UA)
        got = json.load(opener(req))
        out += got
        if len(got) < 50:
            break
    return out


def resolve_cdn(sha: str, build_opener=urllib.request.build_opener) -> str:
    """One request to Hugging Face's resolver for `food.parquet` at a commit; returns the signed CDN address it redirects to. Reading that
    address directly spends none of the resolver's quota (3,000 requests per 5 minutes, measured) on the thousands of range reads."""
    url = f"https://huggingface.co/datasets/{REPO}/resolve/{sha}/food.parquet"
    try:
        build_opener(_NoRedirect).open(urllib.request.Request(url, method="HEAD", headers=UA))
    except urllib.error.HTTPError as e:
        if e.code == 302 and e.headers.get("location"):
            return e.headers["location"]
        raise
    return url


class ByteGuard:
    """Stops a read that downloads more than `limit` bytes: a watcher thread compares the machine's received bytes with the count at the start
    and calls `interrupt` once. Used around every snapshot load, because Databricks Free Edition publishes no limit of its own."""

    def __init__(self, read_rx, limit: int, interrupt, poll: float = 1.0):
        self.read_rx, self.limit, self.interrupt, self.poll = read_rx, limit, interrupt, poll
        self.tripped = False
        self._done = threading.Event()
        self._start = 0
        self._thread: threading.Thread | None = None

    def __enter__(self):
        self._start = self.read_rx()
        self._thread = threading.Thread(target=self._watch, daemon=True)
        self._thread.start()
        return self

    def _watch(self):
        while not self._done.wait(self.poll):
            if self.read_rx() - self._start > self.limit:
                self.tripped = True
                self.interrupt()
                return

    def __exit__(self, *exc):
        self._done.set()
        if self._thread:
            self._thread.join(timeout=5)
        return False

    def received(self) -> int:
        return self.read_rx() - self._start


def read_rx_bytes(path: str = "/proc/net/dev") -> int:
    """Bytes received on every interface except loopback (Linux: the Databricks driver)."""
    total = 0
    with open(path) as fh:
        for line in fh.read().splitlines()[2:]:
            name, rest = line.split(":", 1)
            if name.strip() != "lo":
                total += int(rest.split()[0])
    return total


# --- tables -------------------------------------------------------------------------------------------------------------------------------

def ddl(schema: str) -> dict[str, str]:
    """CREATE TABLE statements, keyed by table name. `schema` is `catalog.schema`."""
    return {
        "snapshot_flag_events": f"""CREATE TABLE IF NOT EXISTS {schema}.snapshot_flag_events (
            pair_id STRING, date_from DATE, date_to DATE, code STRING, severity STRING, flag STRING, family STRING, event STRING,
            family_remains BOOLEAN, edited BOOLEAN, lm_from BIGINT, lm_to BIGINT) USING DELTA""",
        "snapshot_open_counts": f"""CREATE TABLE IF NOT EXISTS {schema}.snapshot_open_counts (
            snapshot_sha STRING, snapshot_date DATE, severity STRING, flag STRING, family STRING, open_pairs BIGINT) USING DELTA""",
        "snapshot_presence_events": f"""CREATE TABLE IF NOT EXISTS {schema}.snapshot_presence_events (
            pair_id STRING, date_from DATE, date_to DATE, code STRING, event STRING, lm_from BIGINT) USING DELTA""",
        "snapshot_manifest": f"""CREATE TABLE IF NOT EXISTS {schema}.snapshot_manifest (
            pair_id STRING, snapshot_from STRING, snapshot_to STRING, date_from DATE, date_to DATE, rows_from BIGINT, rows_to BIGINT,
            in_both BIGINT, left_count BIGINT, entered_count BIGINT, edited_count BIGINT, flag_events BIGINT,
            rx_mb BIGINT, seconds DOUBLE, job_run_id STRING, finished_at TIMESTAMP) USING DELTA""",
    }


def ddl_columns(sql: str) -> list[str]:
    body = sql[sql.index("(") + 1: sql.rindex(")")]
    return [p.split()[0] for p in body.split(",") if p.strip()]


# --- loading and comparing (DuckDB) -------------------------------------------------------------------------------------------------------

def load_sql(table: str, url: str) -> str:
    """Create `table` from one snapshot: only the columns that matter, one row per barcode (OFF's Parquet has about 60 duplicates)."""
    cols = ", ".join(f"{c} as {a}" for a, _, c in SEVERITIES)
    return (f"create table {table} as select code, last_modified_t as lm, {cols} from read_parquet('{url}') "
            f"qualify row_number() over (partition by code order by last_modified_t desc) = 1")


def open_counts(con, table: str) -> list[tuple[str, str, int]]:
    """(severity, tag, number of products carrying it) for one loaded snapshot. A tag listed twice on one product counts once (OFF's lists
    can repeat a tag: seen on 2026-10-20 in `en:nutri-score-grade-from-label-does-not-match-calculated-grade`)."""
    rows = []
    for alias, sev, _ in SEVERITIES:
        for tag, n in con.execute(f"select tag, count(*) from (select unnest(list_distinct({alias})) as tag from {table}) group by 1").fetchall():
            rows.append((sev, tag, n))
    return rows


def compute_pair(con, prev: str = "p", cur: str = "n") -> dict:
    """Compare two loaded snapshots. Returns
      stats     counts for the manifest;
      events    one dict per tag that disappeared from or appeared on a product present in both snapshots;
      left      products in `prev` and not in `cur` (deletion candidates).
    A NULL tag list (a product OFF lists with no flags at all) counts as an empty list: without that, `list_contains(NULL, x)` is NULL and every
    tag that appeared on such a product was silently dropped (found 2026-10-20 by an independent recount: 372 warning and 561 info events).
    For a disappeared tag `family_remains` is True when the product still carries ANOTHER tag of the same family in `cur` (a rename, not a fix);
    for an appeared tag it is True when the product already carried that family in `prev`. `edited` is whether last_modified_t changed."""
    def q(sql):
        return con.execute(sql).fetchall()

    # Memory: the 2026-10-20 production run was killed (out of memory) after 7 pairs. The first version copied BOTH snapshots' flag lists into a joined
    # temp table for every pair. Now the join is read twice but only counts come out of the first pass and only the products that changed (tens of
    # thousands, not 4.7 million) are kept in `_d`.
    joined = f"from {prev} p join {cur} c on p.code = c.code"
    in_both, edited = q(f"select count(*), count(*) filter (where p.lm <> c.lm) {joined}")[0]
    con.execute("create or replace temp table _d as select p.code, p.lm as lm_from, c.lm as lm_to, "
                + ", ".join(f"coalesce(p.{a}, []::varchar[]) as {a}_p, coalesce(c.{a}, []::varchar[]) as {a}_c" for a, _, _ in SEVERITIES)
                + f" {joined} where p.lm <> c.lm or "
                + " or ".join(f"coalesce(p.{a}, []::varchar[]) <> coalesce(c.{a}, []::varchar[])" for a, _, _ in SEVERITIES))
    stats = {
        "rows_from": q(f"select count(*) from {prev}")[0][0],
        "rows_to": q(f"select count(*) from {cur}")[0][0],
        "in_both": in_both,
        "edited_count": edited,
    }
    left = [(code, lm) for code, lm in q(f"select code, lm from {prev} where code not in (select code from {cur}) order by code")]
    stats["left_count"] = len(left)
    stats["entered_count"] = q(f"select count(*) from {cur} where code not in (select code from {prev})")[0][0]

    events = []
    for alias, sev, _ in SEVERITIES:
        for event, a, b in (("disappeared", f"{alias}_p", f"{alias}_c"), ("appeared", f"{alias}_c", f"{alias}_p")):
            rows = q(f"select code, lm_from, lm_to, tag, {b} as other from (select code, lm_from, lm_to, {b}, "
                     f"unnest(list_distinct(list_filter({a}, x -> not list_contains({b}, x)))) as tag from _d)")
            # the tags the product carries on the OTHER side, as family sets, to tell a rename from a real change
            for code, lm_from, lm_to, tag, other in rows:
                fam = family_key(tag)
                remains = any(family_key(t) == fam for t in (other or []))
                events.append({"code": code, "severity": sev, "flag": tag, "family": fam, "event": event, "family_remains": remains,
                               "edited": lm_from != lm_to, "lm_from": lm_from, "lm_to": lm_to})
    stats["flag_events"] = len(events)
    con.execute("drop table if exists _d")
    return {"stats": stats, "events": events, "left": left}


# --- watching a long run ------------------------------------------------------------------------------------------------------------------
# Added after the 2026-10-20 production run: it was killed (out of memory) after 117 minutes with 7 of 12 pairs written, the time per pair rising
# from 554 s to 1,355 s, and nothing in the run said so until it died. Every pair now logs its memory and seconds and the run stops by itself, with
# its progress saved, as soon as either runs away.

def process_rss_mb(path: str = "/proc/self/status") -> float:
    """Resident memory of this process in MB (Linux)."""
    with open(path) as fh:
        for line in fh:
            if line.startswith("VmRSS:"):
                return int(line.split()[1]) / 1024
    raise RuntimeError("VmRSS not found in " + path)


def mem_total_mb(path: str = "/proc/meminfo") -> float:
    """Total memory of the machine in MB, or of the cgroup limit when that is lower (a container sees the host's memory in /proc/meminfo)."""
    with open(path) as fh:
        for line in fh:
            if line.startswith("MemTotal:"):
                return int(line.split()[1]) / 1024
    raise RuntimeError("MemTotal not found in " + path)


def should_stop(seconds_history: list[float], rss_mb: float, total_mb: float, rss_fraction: float = 0.6, slowdown: float = 2.0, min_history: int = 3):
    """(stop, reason) after a finished pair. Stop when the process holds more than `rss_fraction` of the machine's memory, or when the last pair
    took more than `slowdown` times the median of the earlier ones (needs `min_history` earlier pairs)."""
    if total_mb and rss_mb > rss_fraction * total_mb:
        return True, f"memory {rss_mb:.0f} MB is over {rss_fraction:.0%} of {total_mb:.0f} MB"
    if len(seconds_history) > min_history:
        earlier = sorted(seconds_history[:-1])
        median = earlier[len(earlier) // 2]
        if seconds_history[-1] > slowdown * median:
            return True, f"the last pair took {seconds_history[-1]:.0f} s, over {slowdown:g} x the median {median:.0f} s of the earlier ones"
    return False, ""


# --- one pair in its own process ----------------------------------------------------------------------------------------------------------
# The notebook runs every pair in a separate Python process (`python snapshot_lib.py worker <spec.json>`): when the process ends, all its memory
# goes back to the machine, so one pair can never inherit what the one before it left behind, and a pair that is killed for memory takes down only
# itself (the notebook sees the exit code, keeps the pairs already written and reports). A snapshot read from the network is also written to a local
# Parquet file (`cache`), so the next pair, whose older snapshot is this one, reads it from disk instead of downloading it again.

def _load_side(con, table: str, side: dict, byte_guard: int) -> int:
    """Create `table` from one side of a pair: a local Parquet file when `local` is set, otherwise the snapshot over the network (then copied to
    `cache` when given). Returns the bytes received from the network."""
    local = side.get("local")
    if local:
        con.execute(f"create table {table} as select * from read_parquet('{local}')")
        return 0
    try:
        with ByteGuard(read_rx_bytes, byte_guard, con.interrupt) as guard:
            con.execute(load_sql(table, resolve_cdn(side["sha"])))
    except Exception:
        # the guard's interrupt makes DuckDB raise before the check below: name the cause and the bytes seen (found 2026-10-26, a bare 'Interrupted!')
        if guard.tripped:
            raise RuntimeError(f"byte guard: reading snapshot {side['sha'][:8]} passed {byte_guard / 1e6:.0f} MB "
                               f"({guard.received() / 1e6:.0f} MB received by the machine); stopped") from None
        raise
    if guard.tripped:
        raise RuntimeError(f"byte guard: reading snapshot {side['sha'][:8]} passed {byte_guard / 1e6:.0f} MB; stopped")
    if side.get("cache"):
        con.execute(f"copy {table} to '{side['cache']}' (format parquet, compression zstd)")
    return guard.received()


def peak_rss_mb() -> float | None:
    """Highest resident memory this process has reached, in MB (None where the platform has no `resource` module)."""
    try:
        import resource
        return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024      # Linux reports kilobytes
    except ImportError:
        return None


def run_worker(spec: dict) -> dict:
    """Compare one pair. spec: prev and cur ({sha, local?, cache?}), out (path of the result JSON), memory_limit_mb, temp_dir, threads,
    byte_guard, count_prev / count_cur (whether to compute the open-flag counts of that side). Returns and writes the result."""
    import time

    import duckdb
    t0 = time.time()
    con = duckdb.connect()
    if not (spec["prev"].get("local") and spec["cur"].get("local")):
        con.execute("INSTALL httpfs; LOAD httpfs;")
    con.execute(f"SET threads={int(spec.get('threads', 8))}")
    con.execute("SET allow_asterisks_in_http_paths = true")           # the signed CDN address has a '*' in its query string
    if spec.get("memory_limit_mb"):
        con.execute(f"SET memory_limit='{int(spec['memory_limit_mb'])}MB'")
    if spec.get("temp_dir"):
        con.execute(f"SET temp_directory='{spec['temp_dir']}'")
    guard = int(spec.get("byte_guard", BYTE_GUARD))
    rx = _load_side(con, "p", spec["prev"], guard) + _load_side(con, "n", spec["cur"], guard)
    res = compute_pair(con, "p", "n")
    res["open_counts"] = {"prev": open_counts(con, "p") if spec.get("count_prev") else None,
                          "cur": open_counts(con, "n") if spec.get("count_cur") else None}
    res["rx_bytes"] = rx
    res["seconds"] = round(time.time() - t0, 1)
    res["peak_rss_mb"] = peak_rss_mb()
    with open(spec["out"], "w", encoding="utf-8") as fh:
        json.dump(res, fh)
    return res


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "worker":
        with open(sys.argv[2], encoding="utf-8") as fh:
            run_worker(json.load(fh))
    else:
        raise SystemExit("usage: python snapshot_lib.py worker <spec.json>")
