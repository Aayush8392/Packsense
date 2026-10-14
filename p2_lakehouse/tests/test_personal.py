"""Hashing, scrubbing and the known-identity check.

Identities in these tests are the fixtures' stable placeholders (user_0001 ...), which stand in for real contributor
names; the strings being scrubbed use shapes that occur in real records (an email, an Aadhaar-shaped number, a PAN).
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from silver_lib import contract, personal  # noqa: E402

KEY = "test-key-not-a-secret-0000000000000000000000000000000000"
OTHER_KEY = "another-test-key-0000000000000000000000000000000000000"


def test_normalise_ignores_case_edges_and_width():
    assert personal.normalise("  User_0001 ") == "user_0001"
    assert personal.normalise("ＵＳＥＲ_0001") == "user_0001"


def test_hmac_is_64_hex_and_deterministic():
    h = personal.hmac_hex(KEY, "user_0001")
    assert len(h) == 64 and int(h, 16) >= 0
    assert h == personal.hmac_hex(KEY, "user_0001")


def test_hmac_depends_on_the_key_and_ignores_case():
    assert personal.hmac_hex(KEY, "user_0001") != personal.hmac_hex(OTHER_KEY, "user_0001")
    assert personal.hmac_hex(KEY, "User_0001") == personal.hmac_hex(KEY, "user_0001")
    assert personal.hmac_hex(KEY, "user_0001") != personal.hmac_hex(KEY, "user_0002")


def test_hash_value_shapes():
    assert personal.hash_value(KEY, None) is None
    assert personal.hash_value(KEY, "  ") is None
    assert personal.hash_value(KEY, 5) is None
    assert personal.hash_value(KEY, ["user_0001", "", "user_0002"]) == [
        personal.hmac_hex(KEY, "user_0001"), personal.hmac_hex(KEY, "user_0002")]
    assert personal.hash_value(KEY, []) == []


def patterns():
    return personal.compile_patterns(contract.load())


def test_scrub_removes_email_aadhaar_and_pan():
    text, n = personal.scrub("Write to redacted1@example.org or 2345 6789 0123, PAN ABCDE1234F.", patterns())
    assert "@" not in text and "2345" not in text and "ABCDE1234F" not in text
    assert n == 3 and text.count("[removed]") == 3


def test_scrub_leaves_barcodes_and_plain_text_alone():
    original = "Choco biscuits 250 g, EAN 8901234567890, 12.5% sugar"
    assert personal.scrub(original, patterns()) == (original, 0)


def known(*names):
    return {personal.hmac_hex(KEY, n): len(personal.normalise(n)) for n in names}


def test_whole_word_username_is_found_even_with_punctuation_and_case():
    k = known("user_0001")
    for text in ("photo by user_0001.", "Added by USER_0001, thanks", "user_0001"):
        hits, short = personal.find_known([text], KEY, k, {}, min_len=5)
        assert (hits, short) == (1, 0), text


def test_username_glued_into_a_longer_word_is_not_a_whole_word_hit():
    # the documented limit of the daily gate; the one-off substring audit measures this case
    k = known("user_0001")
    for text in ("byuser_0001", "user_0001x", "xuser_0001y"):
        assert personal.find_known([text], KEY, k, {}, min_len=5) == (0, 0), text


def test_short_names_are_counted_not_gated():
    k = known("bob", "bob12")
    assert personal.find_known(["by bob"], KEY, k, {}, min_len=5) == (0, 1)
    assert personal.find_known(["by bob12"], KEY, k, {}, min_len=5) == (1, 0)


def test_stoplist_word_is_ignored():
    k = known("honey")
    assert personal.find_known(["wild honey"], KEY, k, {}, min_len=5) == (1, 0)
    assert personal.find_known(["wild honey"], KEY, k, {}, min_len=5, stoplist=frozenset({"honey"})) == (0, 0)


def test_a_text_without_a_known_name_has_no_hit():
    assert personal.find_known(["Choco Crunch biscuits", "", None], KEY, known("user_0001"), {}, min_len=5) == (0, 0)


def test_known_identities_collects_names_and_phones_from_the_right_fields():
    record = {"creator": "user_0001", "editors_tags": ["user_0001", "user_0002"], "last_editor": None,
              "customer_service": "Call +91 98765 43210", "product_name": "Call +91 11111 22222"}
    users, phones = personal.known_identities(record, KEY, ["creator", "editors_tags", "last_editor"], ["customer_service"])
    assert set(users) == {personal.hmac_hex(KEY, "user_0001"), personal.hmac_hex(KEY, "user_0002")}
    assert list(phones.values()) == [12]          # 919876543210; product_name is not a phone-bearing field


def test_phone_copied_into_kept_text_is_found():
    _, phones = personal.known_identities({"customer_service": "+91 98765 43210"}, KEY, [], ["customer_service"])
    assert personal.find_known(["order on 98765 43210 or +91 98765 43210"], KEY, {}, phones, min_len=5)[0] >= 1
    assert personal.find_known(["call 12345 67890"], KEY, {}, phones, min_len=5) == (0, 0)


def test_candidates_include_the_word_without_edge_punctuation():
    assert set(personal.candidates("by user_0001.")) == {"by", "user_0001.", "user_0001"}
