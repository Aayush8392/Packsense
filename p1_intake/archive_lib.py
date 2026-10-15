"""Archive job logic: copy every object in the B2 capture bucket to a private Hugging Face dataset repo, verified.

Plain Python with no network calls, so it is unit-tested on real key names and real manifest entries. The notebook
(p1_intake/notebooks/archive_to_hf.py) does the B2 and Hugging Face calls and uses these functions to decide what to
copy, to check each file, and to keep the archive manifest honest.

Rules:
  * what is archived: everything under raw/ and taxonomies/ (tmp/ is scratch and never archived);
  * a key is "done" only when it has an entry in archive/manifest.json, and that entry is written after the upload
    has been checked against what Hugging Face reports storing (so a crash leaves the key "not done" and the re-run
    uploads the same bytes again, which is harmless);
  * a delta file is checked against the sha256 the capture recorded in its manifest; a mismatch is never uploaded;
  * nothing is ever deleted from B2 by this job.
"""
import gzip
import hashlib
import io
import json
import re

ARCHIVE_PREFIXES = ("raw/", "taxonomies/")
MANIFEST_PATH = "archive/manifest.json"
MANIFEST_VERSION = 1
CAPTURE_MANIFEST_RE = re.compile(r"^raw/manifests/\d{8}T\d{6}Z\.json$")


def is_archivable(key: str) -> bool:
    """True for a real object under raw/ or taxonomies/ (not a folder placeholder, never tmp/)."""
    return key.startswith(ARCHIVE_PREFIXES) and not key.endswith("/")


def is_capture_manifest(key: str) -> bool:
    return bool(CAPTURE_MANIFEST_RE.match(key))


def new_manifest() -> dict:
    return {"manifest_version": MANIFEST_VERSION, "files": {}}


def load_manifest(raw: bytes | None) -> dict:
    """The archive manifest from its JSON bytes; None (no manifest yet) gives an empty one."""
    if raw is None:
        return new_manifest()
    manifest = json.loads(raw)
    if manifest.get("manifest_version") != MANIFEST_VERSION or not isinstance(manifest.get("files"), dict):
        raise ValueError("archive manifest has an unknown format")
    return manifest


def dump_manifest(manifest: dict) -> bytes:
    return json.dumps(manifest, indent=1, sort_keys=True).encode()


def plan(b2_objects: dict[str, int], manifest: dict) -> tuple[list[str], list[str]]:
    """(keys still to archive, keys whose size in B2 no longer matches the archived copy).

    b2_objects maps each B2 key to its size in bytes. A key B2 no longer lists is left alone (hidden after the
    lifecycle window: the archive copy is then the only one, which is the point). A size change on an archived key
    means a B2 object was overwritten; that is reported, and nothing is overwritten in the archive.
    """
    todo, changed = [], []
    for key in sorted(b2_objects):
        if not is_archivable(key):
            continue
        done = manifest["files"].get(key)
        if done is None:
            todo.append(key)
        elif done["bytes"] != b2_objects[key]:
            changed.append(key)
    return todo, changed


def expected_sha256(capture_manifests: list[dict]) -> dict[str, str]:
    """B2 key -> sha256 the capture recorded for it, from the capture manifests (a later entry wins)."""
    expected = {}
    for manifest in capture_manifests:
        for entry in manifest.get("files", []):
            expected[entry["b2_key"]] = entry["sha256"]
    return expected


def git_blob_sha1(data: bytes) -> str:
    """The id Hugging Face (git) gives a file stored without LFS."""
    return hashlib.sha1(b"blob %d\0" % len(data) + data).hexdigest()


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def etag_is_md5(etag: str) -> bool:
    """B2 returns an MD5 ETag for a plain upload; a multipart upload's ETag is not an MD5 and is not compared."""
    return bool(re.fullmatch(r"[0-9a-f]{32}", etag.strip('"')))


def gzip_is_whole(data: bytes) -> bool:
    """True if a .gz file decompresses to the end (a truncated download would not)."""
    try:
        with gzip.open(io.BytesIO(data), "rb") as g:
            while g.read(1 << 20):
                pass
        return True
    except (OSError, EOFError):
        return False


def check_download(key: str, data: bytes, size_in_b2: int, etag: str, expected: dict[str, str]) -> tuple[str | None, dict]:
    """(problem or None, facts to record) for a file just downloaded from B2.

    A problem means the file must not be archived. Facts: sha256, how it was checked.
    """
    sha = sha256_hex(data)
    facts = {"bytes": len(data), "sha256": sha, "checked_against": []}
    if len(data) != size_in_b2:
        return f"{key}: downloaded {len(data)} bytes but B2 lists {size_in_b2}", facts
    if etag_is_md5(etag):
        if hashlib.md5(data).hexdigest() != etag.strip('"'):
            return f"{key}: checksum differs from B2's ETag", facts
        facts["checked_against"].append("b2_etag_md5")
    if key.endswith(".gz"):
        if not gzip_is_whole(data):
            return f"{key}: gzip file is truncated or corrupt", facts
        facts["checked_against"].append("gzip_complete")
    if key in expected:
        if expected[key] != sha:
            return f"{key}: sha256 differs from the one the capture recorded", facts
        facts["checked_against"].append("capture_manifest_sha256")
    elif key.startswith("raw/deltas/"):
        facts["checked_against"].append("none_no_capture_manifest_entry")
    return None, facts


def hf_matches(facts: dict, data: bytes, lfs_sha256: str | None, blob_id: str | None) -> bool:
    """Does what Hugging Face reports storing equal what we sent? LFS files report sha256, others the git blob id."""
    if lfs_sha256:
        return lfs_sha256 == facts["sha256"]
    return blob_id is not None and blob_id == git_blob_sha1(data)


def record(manifest: dict, key: str, facts: dict, run_id: str, archived_at: str) -> None:
    manifest["files"][key] = {
        "bytes": facts["bytes"], "sha256": facts["sha256"], "checked_against": facts["checked_against"],
        "archived_at": archived_at, "job_run_id": run_id,
    }


def batches(items: list, size: int) -> list[list]:
    return [items[i:i + size] for i in range(0, len(items), size)]
