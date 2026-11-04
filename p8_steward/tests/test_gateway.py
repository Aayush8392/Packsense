"""The gateway (item 22): refusals before sending, the rolling 24-hour budget, no retry on a quota answer, provenance, and the config. No network."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import gateway as gw  # noqa: E402

MESSAGES = [{"role": "user", "content": "hello " * 30}]


def fake(total=1000, calls=None):
    def transport(endpoint, key, body):
        if calls is not None:
            calls.append(body)
        return {"choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}], "usage": {"prompt_tokens": total - 100, "completion_tokens": 100, "total_tokens": total}}
    return transport


def test_the_committed_config_names_both_roles_with_their_own_models_and_no_fallback():
    cfg = gw.load_config()
    assert cfg["roles"]["steward"]["model"] != cfg["roles"]["narrator"]["model"]
    assert cfg["roles"]["steward"]["model"] == "qwen/qwen3.8-27b" and cfg["roles"]["narrator"]["model"] == "openai/gpt-oss-20b"
    assert all(r["fallbacks"] == [] for r in cfg["roles"].values())
    assert cfg["provider"] == "groq"
    assert "gpt-oss-120b" not in str(cfg) and "llama-3.3-70b" not in str(cfg)      # the Wardence models PackSense avoids


def test_a_call_returns_the_text_and_a_provenance_record_with_a_hash_not_the_prompt():
    calls = []
    g = gw.Gateway("k", transport=fake(calls=calls), clock=lambda: 1000.0)
    out = g.call("steward", MESSAGES)
    p = out["provenance"]
    assert out["text"] == "ok" and p["model"] == "qwen/qwen3.8-27b" and p["total_tokens"] == 1000 and p["at"] == 1000.0
    assert p["prompt_hash"] == gw.prompt_hash(MESSAGES) and len(p["prompt_hash"]) == 16
    assert "hello" not in str(p)
    assert calls[0]["model"] == "qwen/qwen3.8-27b" and calls[0]["max_completion_tokens"] == 700


def test_an_oversized_prompt_is_refused_before_anything_is_sent():
    calls = []
    g = gw.Gateway("k", transport=fake(calls=calls))
    with pytest.raises(gw.GatewayError) as e:
        g.call("steward", [{"role": "user", "content": "x" * 30000}])
    assert e.value.kind == "prompt_too_long" and calls == []


def test_the_rolling_budget_refuses_at_80_percent_and_forgets_after_24_hours():
    now = [0.0]
    usage = gw.UsageLog(clock=lambda: now[0])
    g = gw.Gateway("k", usage=usage, transport=fake(total=159500), clock=lambda: now[0])
    g.call("steward", MESSAGES)                                   # 159,500 used of the 160,000 allowed (80% of 200,000)
    calls = []
    g.transport = fake(calls=calls)
    with pytest.raises(gw.GatewayError) as e:
        g.call("steward", MESSAGES)                               # the estimate and the output allowance no longer fit
    assert e.value.kind == "budget" and calls == []               # refused before anything was sent
    other = g.call("narrator", MESSAGES)                          # the narrator's pool is separate
    assert other["provenance"]["model"] == "openai/gpt-oss-20b"
    now[0] += 86401                                               # the window moves on
    assert g.call("steward", MESSAGES)["text"] == "ok"


def test_a_quota_answer_raises_with_its_retry_after_and_is_not_retried():
    attempts = []

    def transport(endpoint, key, body):
        attempts.append(1)
        raise gw.GatewayError("rate_limited", "quota", "222")

    g = gw.Gateway("k", transport=transport)
    with pytest.raises(gw.GatewayError) as e:
        g.call("steward", MESSAGES)
    assert e.value.kind == "rate_limited" and e.value.retry_after == "222" and len(attempts) == 1
    assert g.usage.last_24h("qwen/qwen3.8-27b") == 0              # a failed call adds nothing to the log


def test_an_unknown_role_and_a_missing_key_are_config_errors(monkeypatch):
    with pytest.raises(gw.GatewayError) as e:
        gw.Gateway("k", transport=fake()).call("poet", MESSAGES)
    assert e.value.kind == "config"
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    with pytest.raises(gw.GatewayError):
        gw.read_key("GROQ_API_KEY")


def test_the_usage_log_survives_in_a_file(tmp_path):
    p = tmp_path / "usage.jsonl"
    a = gw.UsageLog(p, clock=lambda: 100.0)
    a.add("m", 500)
    b = gw.UsageLog(p, clock=lambda: 200.0)
    assert b.last_24h("m") == 500
