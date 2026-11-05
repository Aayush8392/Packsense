"""Serves the review-set photos to Label Studio while the owner labels (local only, read only, one folder).

  .venv\Scripts\python.exe -I p8_steward\bootstrap\serve_photos.py            serves output/review_set/photos on http://127.0.0.1:8090 until Ctrl+C

Why: embedding every photo in its task (about 750 KB each) made a page of the Data Manager 22 MB and Label Studio's SQLite database ('database is locked', submits refused, 'runtime error')
on 2026-11-05. With this server a task carries a plain address and weighs about 1 KB. It binds to 127.0.0.1 only, serves nothing but that folder, and allows only GET.
"""
from __future__ import annotations

import functools
import http.server
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PHOTOS = ROOT / "output" / "review_set" / "photos"
HOST, PORT = "127.0.0.1", 8090


class Handler(http.server.SimpleHTTPRequestHandler):
    def end_headers(self):
        self.send_header("Access-Control-Allow-Origin", "*")           # the image is shown by a page on another local port
        self.send_header("Cache-Control", "max-age=3600")
        super().end_headers()

    def log_message(self, format, *args):                             # under pythonw (no console) sys.stderr is None and the default log line would crash every request
        return

    def do_POST(self):
        self.send_error(405)

    do_PUT = do_DELETE = do_PATCH = do_POST

    def list_directory(self, path):
        self.send_error(404)                                            # no folder listing
        return None


def main() -> None:
    if not PHOTOS.is_dir():
        sys.exit(f"{PHOTOS} does not exist: run fetch_part_assets.py first")
    server = http.server.ThreadingHTTPServer((HOST, PORT), functools.partial(Handler, directory=str(PHOTOS)))
    print(f"serving {PHOTOS} on http://{HOST}:{PORT} (Ctrl+C to stop)", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
