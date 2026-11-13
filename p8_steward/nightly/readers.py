"""The real readers of the nightly job (A121 settled 2026-11-13): the OFF fetch and the two model readers, built from the FROZEN pieces and nothing else.

  fetch(code)                      3 OFF requests, 4 seconds apart: the product record (photo address and scan address), the scan JSON (rendered to table text by scan_layout.rows_text, first
                                   6,000 characters, as dr.scan_text does) and, only when the scan holds a table, the full photo resized to 1,600 px (fetch_round2_photos.download / resize)
  text_reader(code, text, prior)   the gateway call of fix_test_agent (role 'steward', the 'v3rows' prompt, the user message '<ocr>...</ocr>'); `prior` = the first entry, for the one JSON retry
  photo_reader(code, photo)        vision_variant_test.call on the resized photo

One request per reader call: the caller (night.py) counts every request and decides the one retry. Failures: a server error, a rate limit, a timeout or an OFF answer that is not a 404 are
TransientError (the queue retries the product on a later night); a genuine 404 or a product without a nutrition photo is a product fact. Differences from the frozen helpers, on purpose:
(1) OFF's old get_json returned {} on ANY HTTP error, so a 429 or 403 block would have looked like 'no product': here only a 404 does; (2) it exits the process on a network failure, here it raises;
(3) the gateway's provenance names the CONFIGURED model, so the transport is wrapped to keep the model the RESPONSE names, which is what the fail-closed model check needs.
"""
from __future__ import annotations

import gzip
import json
import re
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "p8_steward"))
sys.path.insert(0, str(ROOT / "p8_steward" / "bootstrap"))
import dev_ocr_reader as dr  # noqa: E402
import fetch_ocr_text as fo  # noqa: E402
import fetch_round2_photos as rp  # noqa: E402
import fix_test_agent as fa  # noqa: E402
import gateway as gw  # noqa: E402
import photo_method as pm  # noqa: E402
import scan_layout as sl  # noqa: E402
import vision_variant_test as vv  # noqa: E402
from nightly.budget import TransientError  # noqa: E402

AGENT = "packsense-nightly/1 (research)"
API = "https://world.openfoodfacts.org/api/v2/product/{code}.json?fields=code,selected_images,images"
SCAN = "https://images.openfoodfacts.org/images/products/{path}/{imgid}.json"


def get_json(url: str, sleep=time.sleep) -> dict:
    """One paced OFF request. {} only for a 404; every other failure raises TransientError."""
    sleep(fo.PACE)
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": AGENT}), timeout=60) as r:
            raw = r.read()
        if raw[:2] == bytes([0x1F, 0x8B]):
            raw = gzip.decompress(raw)
        return json.loads(raw)
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return {}
        raise TransientError(f"OFF answered HTTP {e.code}") from None
    except (urllib.error.URLError, TimeoutError, ValueError, OSError) as e:
        raise TransientError(f"OFF request failed: {type(e).__name__}") from None


def scan_address(product: dict) -> tuple[str, str] | None:
    """(image path, image id) of the scan, by the same reading of the product record as fetch_ocr_json.scan_json."""
    nut = ((product.get("selected_images") or {}).get("nutrition") or {}).get("display") or {}
    if not nut:
        return None
    _, url = sorted(nut.items())[0]
    m = re.search(r"/products/(.+)/nutrition_([a-z]+)\.\d+\.", url)
    imgid = ((product.get("images") or {}).get(f"nutrition_{m.group(2)}") or {}).get("imgid") if m else None
    return (m.group(1), imgid) if m and imgid else None


class Readers:
    def __init__(self, key: str | None, sleep=time.sleep, http_json=get_json):
        self.key, self.sleep, self.http_json = key, sleep, http_json
        fo.AGENT = AGENT                                   # fetch_round2_photos.download reads the user agent from here
        self.last_model: str | None = None
        self.gateway = None
        if key:
            steward = json.loads((ROOT / "p8_steward" / "gateway_config.json").read_text(encoding="utf-8"))["roles"]["steward"]
            cfg = {"endpoint": fa.GEMINI, "budget_share": 1.0, "roles": {"steward": {**steward, "model": pm.MODEL, "daily_tokens": 10_000_000, "max_output_tokens": 700}}}
            self.gateway = gw.Gateway(key, config=cfg, usage=gw.UsageLog(None), transport=self._transport)

    def _transport(self, endpoint: str, key: str, body: dict) -> dict:
        data = gw.http_transport(endpoint, key, body)
        self.last_model = data.get("model")
        return data

    # ---------------------------------------------------------------- OFF
    def fetch(self, code: str) -> dict:
        product = (self.http_json(API.format(code=code), self.sleep) or {}).get("product") or {}
        display = ((product.get("selected_images") or {}).get("nutrition") or {}).get("display") or {}
        if not display:
            return {"has_photo": False, "ocr_text": "", "photo": None}
        addr = scan_address(product)
        scan = self.http_json(SCAN.format(path=addr[0], imgid=addr[1]), self.sleep) if addr else {}
        text = sl.rows_text(scan)[:pm.TEXT_LIMIT] if scan else ""
        if not text or not _has_table(text):
            return {"has_photo": True, "ocr_text": text, "photo": None}           # no table: the photo is never needed, so it is never downloaded
        return {"has_photo": True, "ocr_text": text, "photo": self._photo(rp.full_address(display))}

    def _photo(self, url: str) -> bytes:
        self.sleep(fo.PACE)
        with tempfile.TemporaryDirectory() as d:
            raw, small = Path(d) / "raw.jpg", Path(d) / "small.jpg"
            if not rp.download(url, raw):
                raise TransientError("the photo did not download")
            rp.resize(raw, small)
            return small.read_bytes()

    # ---------------------------------------------------------------- the model
    def _map(self, e: gw.GatewayError) -> Exception:
        return TransientError(f"model request failed: {e.kind}") if e.kind in ("server", "rate_limited") else e

    def text_reader(self, code: str, text: str, prior: dict | None = None) -> dict:
        messages = [{"role": "system", "content": pm.text_system()}, {"role": "user", "content": f"<ocr>\n{text}\n</ocr>"}]
        if prior is not None:                                                        # the one retry for an unusable reply, as dr.retry_if_needed asks it
            messages += [{"role": "assistant", "content": (prior.get("answer") or "")[:2500]}, {"role": "user", "content": dr.RETRY_JSON}]
        self.last_model = None
        try:
            res = self.gateway.call("steward", messages)
        except gw.GatewayError as e:
            raise self._map(e) from None
        return {"answer": res["text"], "reading": dr.read_json(res["text"]), "tokens": res["provenance"]["total_tokens"], "finish": res["finish_reason"], "model": self.last_model}

    def photo_reader(self, code: str, photo: bytes) -> dict:
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "photo.jpg"
            p.write_bytes(photo)
            try:
                r = vv.call(self.key, p)
            except gw.GatewayError as e:
                raise self._map(e) from None
        return {**r, "reading": dr.read_json(r["answer"])}


def _has_table(text: str) -> bool:
    import answer_key_lib as akl
    return akl.text_has_table(text)


def make_readers(env: dict, need_model: bool = True) -> Readers:
    key = env.get("GEMINI_API_KEY") if need_model else None
    if need_model and not key:
        raise SystemExit("setup error: GEMINI_API_KEY is missing")
    return Readers(key)
