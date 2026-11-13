"""The results dataset of the nightly job (A121 settled 2026-11-13): a PRIVATE Hugging Face dataset that holds the job's input, its state and its output.

  input/candidates.json   {"exported": date, "candidates": [{"code", "stored": {per-100 record}, "new": bool}]}   written by the Databricks export (until it exists: by hand)
  input/canary.json       {"canary": [{"code", "stored", "expected": {the saved right table}}]}                    the known-right canary products
  queue.json              the retry queue (queue_lib state)
  lines/current.json      {code: line}   every line that is still valid (its product is done as 'line' in the queue); the site build reads this file
  lines/<night>.json      [line, ...]    the lines added by that night's run (a second run of the same night adds to it, never replaces it)
  runs/<night>.json       the night's counts: stop reason, canary result, calls, silences by reason, errors, queue sizes (no product values)

One night is saved as ONE multi-file commit: either all of it lands or none of it. The backend is injected (`read(path) -> bytes | None`, `commit(files, message)`), so the tests use a
dict; `HfBackend` is the real one (huggingface_hub, imported only when used). A missing INPUT file is an error, never an empty night; a missing state file is a first night.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from nightly import queue_lib as ql  # noqa: E402

CANDIDATES, CANARY, QUEUE, CURRENT = "input/candidates.json", "input/canary.json", "queue.json", "lines/current.json"


class StoreError(Exception):
    pass


class HfBackend:
    """The real backend: one private dataset repo. Reads bypass the local cache, and a commit is one create_commit call (atomic on the Hub)."""

    def __init__(self, repo: str, token: str):
        from huggingface_hub import HfApi
        self.api, self.repo, self.token = HfApi(token=token), repo, token

    def read(self, path: str) -> bytes | None:
        import tempfile

        from huggingface_hub import hf_hub_download
        from huggingface_hub.errors import EntryNotFoundError
        with tempfile.TemporaryDirectory() as d:
            try:
                p = hf_hub_download(self.repo, path, repo_type="dataset", token=self.token, local_dir=d, force_download=True)
            except EntryNotFoundError:
                return None
            return Path(p).read_bytes()

    def commit(self, files: dict[str, bytes], message: str) -> None:
        from huggingface_hub import CommitOperationAdd
        ops = [CommitOperationAdd(path_in_repo=p, path_or_fileobj=b) for p, b in sorted(files.items())]
        self.api.create_commit(repo_id=self.repo, repo_type="dataset", operations=ops, commit_message=message)


def _dump(obj) -> bytes:
    return json.dumps(obj, ensure_ascii=False, indent=1, sort_keys=True).encode("utf-8")


class Store:
    def __init__(self, backend):
        self.b = backend

    def _json(self, path: str, required: bool):
        raw = self.b.read(path)
        if raw is None:
            if required:
                raise StoreError(f"missing input file {path}")
            return None
        try:
            return json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as e:
            raise StoreError(f"{path} is not valid JSON") from e

    def load_state(self) -> dict:
        s = self._json(QUEUE, required=False)
        if s is None:
            return ql.new_state()
        if not (isinstance(s, dict) and s.get("version") == 1 and isinstance(s.get("items"), dict) and isinstance(s.get("done"), dict)):
            raise StoreError("queue.json has an unknown shape")
        return s

    def load_candidates(self) -> list[dict]:
        doc = self._json(CANDIDATES, required=True)
        rows = doc.get("candidates") if isinstance(doc, dict) else None
        if not isinstance(rows, list) or not rows:
            raise StoreError("input/candidates.json holds no candidates")
        for r in rows:
            if not (isinstance(r, dict) and isinstance(r.get("code"), str) and isinstance(r.get("stored"), dict)):
                raise StoreError("a candidate has the wrong shape")
        return rows

    def load_canary(self) -> list[dict]:
        doc = self._json(CANARY, required=True)
        rows = doc.get("canary") if isinstance(doc, dict) else None
        if not isinstance(rows, list):
            raise StoreError("input/canary.json holds no canary list")
        for r in rows:
            if not (isinstance(r, dict) and isinstance(r.get("code"), str) and isinstance(r.get("stored"), dict) and isinstance(r.get("expected"), dict)):
                raise StoreError("a canary row has the wrong shape")
        return rows

    def save_night(self, night: str, state: dict, summary: dict) -> None:
        """One commit: queue, current lines, the night's added lines, the night's run record. A rerun of the same night adds to its lines file."""
        current = self._json(CURRENT, required=False) or {}
        added_path = f"lines/{night}.json"
        before = {ln["code"]: ln for ln in (self._json(added_path, required=False) or [])}
        for ln in summary.get("lines", []):
            current[ln["code"]] = ln
            before[ln["code"]] = ln
        valid = {c for c, d in state["done"].items() if d["outcome"] == "line"}
        current = {c: ln for c, ln in current.items() if c in valid}                     # a line whose product left the state or was requeued is no longer valid
        run = {k: v for k, v in summary.items() if k != "lines"}
        run["lines_added"] = len(summary.get("lines", []))
        self.b.commit({QUEUE: _dump(state), CURRENT: _dump(current), added_path: _dump(sorted(before.values(), key=lambda x: x["code"])), f"runs/{night}.json": _dump(run)},
                      f"night {night}: {run['lines_added']} lines, stopped: {summary.get('stopped')}")
