import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "bootstrap"))
import exploratory_model_run as emr  # noqa: E402
import freeze_method as fm  # noqa: E402


def test_the_reader_block_names_model_endpoint_and_runner_hash():
    b = fm.reader_block("gemini-3.5-flash-lite")
    assert b["model"] == "gemini-3.5-flash-lite"
    assert b["endpoint"] == emr.ENDPOINT                      # the frozen endpoint is the one the runner calls
    assert b["pause_between_calls_s"] == emr.PAUSE
    assert len(b["runner_sha256"]) == 64
    assert b["runner_sha256"] == fm.sha(Path(emr.__file__))   # a change of the runner changes the record


def test_the_reader_block_holds_no_secret_value():
    text = repr(fm.reader_block("gemini-3.5-flash-lite")).lower()
    assert "key_variable" in text and "(name only)" in text
    assert "bearer" not in text and "aiza" not in text        # no key shape


def test_a_record_without_a_reader_model_has_no_reader_key(tmp_path, monkeypatch):
    # the old 'test' freeze must keep its shape: reader keys appear only when a reader model is asked for
    monkeypatch.setattr(fm, "SET", tmp_path)
    (tmp_path / "answer_key_t_key.json").write_text('{"cards": {"1": {"usable": true}}}', encoding="utf-8")
    plain = fm.record("t", "v3rows")
    with_reader = fm.record("t", "v3rows", "gemini-3.5-flash-lite")
    assert "reader" not in plain and "family_rule" not in plain
    assert with_reader["reader"]["model"] == "gemini-3.5-flash-lite"
    assert {k: v for k, v in with_reader.items() if k not in ("reader", "family_rule")} == plain
    assert with_reader["family_rule"]["family_min_proposals"] == 15 and with_reader["family_rule"]["weights_information_only"]["B_salt_vs_sodium"] == 57
