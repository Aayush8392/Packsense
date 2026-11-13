"""Tests for the real readers (nightly/readers.py) with no network: the OFF fetch against fake answers, the error mapping, and that the model requests are the frozen ones."""
import sys
import urllib.error
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "bootstrap"))
import dev_ocr_reader as dr  # noqa: E402
import fetch_ocr_json as foj  # noqa: E402
import fetch_ocr_text as fo  # noqa: E402
import fetch_round2_photos as rp  # noqa: E402
import fix_test_agent as fa  # noqa: E402
import gateway as gw  # noqa: E402
import photo_method as pm  # noqa: E402
from nightly import readers as rd  # noqa: E402
from nightly.budget import TransientError  # noqa: E402

TEXT = "Nutrition facts per 100 g Energy 376 kJ / 90 kcal Fat 0.5 g Saturates 0.3 g Carbohydrate 8.9 g Sugars 6.5 g Protein 12.4 g Salt 0.06 g"
DISPLAY = {"en": "https://images.openfoodfacts.org/images/products/890/123/456/7890/nutrition_en.17.400.jpg"}
PRODUCT = {"product": {"code": "8901234567890", "selected_images": {"nutrition": {"display": DISPLAY}}, "images": {"nutrition_en": {"imgid": "5"}}}}
SCAN_URL = "https://images.openfoodfacts.org/images/products/890/123/456/7890/5.json"
GOOD = '{"basis": "per 100 g", "serving_size": null, "values_per_100": {"fat": 0.5}}'


class Http:
    """A fake OFF: url -> dict; every request is logged."""

    def __init__(self, answers):
        self.answers, self.urls = answers, []

    def __call__(self, url, sleep):
        self.urls.append(url)
        v = self.answers[url]
        if isinstance(v, Exception):
            raise v
        return v


def api(code="8901234567890"):
    return rd.API.format(code=code)


def readers(answers, monkeypatch, table=True):
    monkeypatch.setattr(rd.sl, "rows_text", lambda scan: TEXT if table else "")
    return rd.Readers(None, sleep=lambda s: None, http_json=Http(answers))


# ---------------------------------------------------------------- the OFF fetch
def test_the_scan_address_is_read_exactly_as_the_frozen_scan_fetcher_reads_it(monkeypatch):
    urls = []
    monkeypatch.setattr(fo, "get_json", lambda url: urls.append(url) or (PRODUCT if "api/v2" in url else {"responses": []}))
    foj.scan_json("8901234567890")
    assert urls[1] == SCAN_URL and rd.scan_address(PRODUCT["product"]) == ("890/123/456/7890", "5") and rd.SCAN.format(path="890/123/456/7890", imgid="5") == SCAN_URL


def test_a_full_fetch_makes_three_requests_and_returns_the_resized_photo(monkeypatch):
    http = {api(): PRODUCT, SCAN_URL: {"responses": ["x"]}}
    r = readers(http, monkeypatch)
    monkeypatch.setattr(rp, "download", lambda url, dest: dest.write_bytes(b"raw") or True)
    monkeypatch.setattr(rp, "resize", lambda src, dest: dest.write_bytes(b"small" + src.read_bytes()))
    got = r.fetch("8901234567890")
    assert got == {"has_photo": True, "ocr_text": TEXT, "photo": b"smallraw"} and r.http_json.urls == [api(), SCAN_URL]


def test_a_product_without_a_nutrition_photo_costs_one_request():
    r = rd.Readers(None, sleep=lambda s: None, http_json=Http({api(): {"product": {"code": "1"}}}))
    assert r.fetch("8901234567890") == {"has_photo": False, "ocr_text": "", "photo": None} and len(r.http_json.urls) == 1


def test_a_photo_without_a_table_in_its_scan_is_never_downloaded(monkeypatch):
    r = readers({api(): PRODUCT, SCAN_URL: {"responses": []}}, monkeypatch, table=False)
    monkeypatch.setattr(rp, "download", lambda url, dest: pytest.fail("downloaded"))
    assert r.fetch("8901234567890") == {"has_photo": True, "ocr_text": "", "photo": None}


def test_a_photo_that_will_not_download_is_a_transient_error_not_a_missing_photo(monkeypatch):
    r = readers({api(): PRODUCT, SCAN_URL: {"responses": ["x"]}}, monkeypatch)
    monkeypatch.setattr(rp, "download", lambda url, dest: False)
    with pytest.raises(TransientError):
        r.fetch("8901234567890")


def test_get_json_separates_a_real_404_from_a_block_or_an_outage(monkeypatch):
    def fake(exc):
        def _open(req, timeout):
            raise exc
        return _open

    for code, expect in ((404, {}), (429, TransientError), (403, TransientError), (503, TransientError)):
        monkeypatch.setattr(rd.urllib.request, "urlopen", fake(urllib.error.HTTPError("u", code, "m", {}, None)))
        if expect == {}:
            assert rd.get_json("https://x", sleep=lambda s: None) == {}
        else:
            with pytest.raises(TransientError):
                rd.get_json("https://x", sleep=lambda s: None)
    for exc in (urllib.error.URLError("down"), TimeoutError()):
        monkeypatch.setattr(rd.urllib.request, "urlopen", fake(exc))
        with pytest.raises(TransientError):
            rd.get_json("https://x", sleep=lambda s: None)


def test_requests_are_paced_and_carry_the_nightly_user_agent(monkeypatch):
    slept = []
    sent = {}

    class Resp:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self):
            return b"{}"

    def fake_open(req, timeout):
        sent["ua"] = req.get_header("User-agent")
        return Resp()

    monkeypatch.setattr(rd.urllib.request, "urlopen", fake_open)
    rd.get_json("https://x", sleep=slept.append)
    assert slept == [fo.PACE] == [4.0] and sent["ua"] == "packsense-nightly/1 (research)"
    rd.Readers(None)
    assert fo.AGENT == rd.AGENT                                  # the photo download uses the same agent


# ---------------------------------------------------------------- the model readers are the frozen requests
def keyed(monkeypatch, response):
    sent = []

    def transport(endpoint, key, body):
        sent.append((endpoint, key, body))
        return response if not isinstance(response, Exception) else (_ for _ in ()).throw(response)

    monkeypatch.setattr(rd.gw, "http_transport", transport)
    return rd.Readers("k", sleep=lambda s: None), sent


def reply(text=GOOD, model=pm.MODEL):
    return {"model": model, "choices": [{"message": {"content": text}, "finish_reason": "stop"}], "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}}


def test_the_gateway_config_equals_the_one_the_frozen_runs_used(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "k")
    assert rd.Readers("k").gateway.cfg == fa.make_gateway(pm.MODEL, "no-such-env-file").cfg


def test_the_text_request_is_the_frozen_one_and_the_response_model_is_kept(monkeypatch):
    r, sent = keyed(monkeypatch, reply())
    e = r.text_reader("c", TEXT)
    endpoint, key, body = sent[0]
    assert endpoint == fa.GEMINI and key == "k" and body["model"] == pm.MODEL and body["max_completion_tokens"] == 700
    assert body["messages"] == [{"role": "system", "content": pm.text_system()}, {"role": "user", "content": f"<ocr>\n{TEXT}\n</ocr>"}]
    assert e["model"] == pm.MODEL and e["reading"] == dr.read_json(GOOD) and e["tokens"] == 15


def test_the_model_the_response_names_is_what_the_entry_carries_not_the_configured_one(monkeypatch):
    r, _ = keyed(monkeypatch, reply(model="gemini-something-else"))
    assert r.text_reader("c", TEXT)["model"] == "gemini-something-else"
    r2, _ = keyed(monkeypatch, {k: v for k, v in reply().items() if k != "model"})
    assert r2.text_reader("c", TEXT)["model"] is None                                     # no model named: the night's check will stop


def test_the_text_retry_adds_the_first_answer_and_the_frozen_retry_instruction(monkeypatch):
    r, sent = keyed(monkeypatch, reply())
    first = {"answer": "{cut " + "x" * 3000, "reading": None}
    r.text_reader("c", TEXT, first)
    m = sent[0][2]["messages"]
    assert len(m) == 4 and m[2] == {"role": "assistant", "content": first["answer"][:2500]} and m[3] == {"role": "user", "content": dr.RETRY_JSON}


def test_a_server_error_or_a_rate_limit_is_transient_and_other_gateway_errors_are_not(monkeypatch):
    for kind in ("server", "rate_limited"):
        r, _ = keyed(monkeypatch, gw.GatewayError(kind, "x"))
        with pytest.raises(TransientError):
            r.text_reader("c", TEXT)
    r, _ = keyed(monkeypatch, gw.GatewayError("config", "x"))
    with pytest.raises(gw.GatewayError):
        r.text_reader("c", TEXT)


def test_the_photo_reader_calls_the_frozen_vision_call_with_the_photo_bytes(monkeypatch):
    seen = {}

    def fake_call(key, path):
        seen["key"], seen["bytes"] = key, path.read_bytes()
        return {"answer": GOOD, "tokens": 9, "finish": "stop", "model": pm.MODEL}

    monkeypatch.setattr(rd.vv, "call", fake_call)
    e = rd.Readers("k").photo_reader("c", b"jpegbytes")
    assert seen == {"key": "k", "bytes": b"jpegbytes"} and e["reading"] == dr.read_json(GOOD) and e["model"] == pm.MODEL
    monkeypatch.setattr(rd.vv, "call", lambda key, path: (_ for _ in ()).throw(gw.GatewayError("server", "HTTP 503")))
    with pytest.raises(TransientError):
        rd.Readers("k").photo_reader("c", b"x")


def test_the_vision_request_body_is_the_frozen_one(monkeypatch):
    sent = []
    monkeypatch.setattr(rd.vv.gw, "http_transport", lambda endpoint, key, body, timeout=0: sent.append(body) or reply())
    rd.Readers("k").photo_reader("c", b"jpegbytes")
    body = sent[0]
    assert body["model"] == pm.MODEL and body["max_completion_tokens"] == 700 and body["temperature"] == 0.2 and body["messages"][0]["content"] == pm.photo_system()
    assert body["messages"][1]["content"][1]["image_url"]["url"].startswith("data:image/jpeg;base64,")


def test_make_readers_needs_the_key_only_when_a_model_is_used():
    assert rd.make_readers({}, need_model=False).key is None
    with pytest.raises(SystemExit):
        rd.make_readers({}, need_model=True)
    assert rd.make_readers({"GEMINI_API_KEY": "k"}).key == "k"


def test_the_resize_brings_the_long_side_to_1600_pixels(tmp_path):
    Image = pytest.importorskip("PIL.Image")
    src, dest = tmp_path / "a.jpg", tmp_path / "b.jpg"
    Image.new("RGB", (3000, 1000), "white").save(src)
    assert rp.resize(src, dest) == (1600, 533) and Image.open(dest).size == (1600, 533)
