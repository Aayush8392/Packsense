"""India seed from OFF's full dump: the pure logic (no network, no Spark), unit-tested on real records.

The dump is one gzip stream that was copied to the private archive as 1 GiB byte ranges ("parts", dump/part-NNNN.bin). A part
boundary can fall anywhere: inside a gzip block, inside a line. So the parts must be decompressed in order as ONE stream, and a
line belongs to the part in which it is completed. The notebook (notebooks/seed_dump_load.py) downloads the parts, checks each
against the sha256 in the archive manifest, and uses this module to turn the stream into India records.

India = `countries_tags` contains `en:india` (decided 2026-10-15). A cheap byte search for `en:india` comes first; it also
matches other fields (2,434 of 27,229 prefiltered lines in the real dump), so every hit is parsed and `countries_tags` checked.
"""
import json
import zlib

INDIA_TAG = "en:india"
_NEEDLE = INDIA_TAG.encode()


def india_record(line: bytes) -> dict | None:
    """A bronze-shaped record for an India product line, or None (not India, or not a JSON object)."""
    if _NEEDLE not in line:
        return None
    try:
        o = json.loads(line)
    except ValueError:
        return None
    if not isinstance(o, dict) or INDIA_TAG not in (o.get("countries_tags") or []):
        return None
    code, lmt = o.get("code"), o.get("last_modified_t")
    return {
        "code": str(code) if isinstance(code, (str, int)) and not isinstance(code, bool) else None,
        "last_modified_t": lmt if isinstance(lmt, int) and not isinstance(lmt, bool) else None,
        "raw_json": line.decode("utf-8"),
    }


class DumpStream:
    """Decompresses the parts of the dump in order and hands out complete lines.

    The bytes after the last newline are carried into the next chunk, so a line that straddles two parts is returned once, with
    the part where it ends. Several gzip members in a row are accepted.
    """

    def __init__(self):
        self._d = zlib.decompressobj(31)
        self._fed = False        # has the current member received any bytes?
        self._tail = b""

    def _decompress(self, chunk: bytes) -> bytes:
        out = []
        while chunk:
            out.append(self._d.decompress(chunk))
            self._fed = True
            if not self._d.eof:
                break
            chunk = self._d.unused_data      # the member ended: whatever follows starts a new one
            self._d, self._fed = zlib.decompressobj(31), False
        return b"".join(out)

    def feed(self, chunk: bytes, keep_lines: bool = True) -> list[bytes]:
        """Complete non-empty lines made available by this chunk (keep_lines=False only advances the stream)."""
        data = self._tail + self._decompress(chunk)
        cut = data.rfind(b"\n")
        if cut < 0:
            self._tail = data
            return []
        self._tail = data[cut + 1:]
        return [x for x in data[:cut].split(b"\n") if x.strip()] if keep_lines else []

    def finish(self) -> list[bytes]:
        """The last line, if the dump does not end with a newline."""
        data, self._tail = self._tail, b""
        return [data] if data.strip() else []

    @property
    def complete(self) -> bool:
        """True if the stream ended cleanly: a truncated download leaves a member open."""
        return self._d.eof or not self._fed


def scan_chunks(stream: DumpStream, chunks, collect: bool = True) -> tuple[list[dict], int]:
    """(India records, lines seen) for the lines completed while these chunks were fed."""
    records, lines = [], 0
    for chunk in chunks:
        for line in stream.feed(chunk, keep_lines=collect):
            lines += 1
            rec = india_record(line)
            if rec:
                records.append(rec)
    return records, lines


def source_file_name(dump_date: str, part_key: str) -> str:
    """The bronze source_file of the India lines completed in one part: seed-dump:2026-10-13:part-0004."""
    return f"seed-dump:{dump_date}:part-{part_key}"


def plan_parts(archive_manifest: dict, done: set[str], dump_date: str) -> list[dict]:
    """The parts in stream order, each with its expected size and sha256, and whether the stage already holds it."""
    parts = []
    for key in sorted(archive_manifest["parts"]):
        p = archive_manifest["parts"][key]
        name = source_file_name(dump_date, key)
        parts.append({"key": key, "source_file": name, "bytes": p["bytes"], "sha256": p["sha256"], "done": name in done})
    return parts


def verify_part(part: dict, size: int, sha256: str) -> str | None:
    """A problem description if the downloaded part is not the part the archive manifest describes."""
    if size != part["bytes"]:
        return f"part {part['key']}: {size} bytes downloaded, the archive manifest says {part['bytes']}"
    if sha256 != part["sha256"]:
        return f"part {part['key']}: sha256 differs from the archive manifest"
    return None


def stage_tuple(rec: dict, source_file: str, file_sha256: str, ingested_at) -> tuple:
    """A row of bronze_delta_raw: code, last_modified_t, source_file, file_sha256, ingested_at, raw_json."""
    return (rec["code"], rec["last_modified_t"], source_file, file_sha256, ingested_at, rec["raw_json"])
