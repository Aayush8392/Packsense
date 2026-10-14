"""Personal-data handling for silver: normalising, HMAC, scrubbing and the known-identity checks.

Plain usernames are never stored outside bronze. The "known identities" are kept as HMACs, and a text is checked by
hashing its words the same way and looking the hashes up.
"""
import hashlib
import hmac
import re
import unicodedata

# a word as a username is written: letters, digits, underscore, dot, hyphen
TOKEN_RE = re.compile(r"[\w.\-]+", re.UNICODE)
# Deliberately liberal: any run of digits with spaces, dots, dashes or brackets, reduced to its digits (8 to 15 of them).
# It over-matches (dates, codes), which is harmless: a hit needs the digits' HMAC to be in the known-phone set, and that
# set holds only numbers found in the phone-bearing dropped fields. The narrower pattern used in the first privacy scan
# missed Indian-style numbers such as "+91 98765 43210" (found by a test).
PHONE_RE = re.compile(r"(?<![\w.])\+?\(?\d[\d ().\-]{5,17}\d(?!\w)")
SHORT_MIN = 3   # default for report_min; the contract sets it (report_min_username_length)


def normalise(value: str) -> str:
    return unicodedata.normalize("NFKC", value).strip().lower()


def hmac_hex(key: str, value: str, prefix: str = "") -> str:
    return hmac.new(key.encode(), (prefix + normalise(value)).encode(), hashlib.sha256).hexdigest()


def hash_value(key: str, value):
    """A username string -> HMAC; a list of usernames -> list of HMACs; empty or missing -> None."""
    if isinstance(value, str):
        return hmac_hex(key, value) if value.strip() else None
    if isinstance(value, list):
        out = [hmac_hex(key, v) for v in value if isinstance(v, str) and v.strip()]
        return out
    return None


def personal_values(record: dict, fields: list[str]) -> list[str]:
    """Every non-empty string in the raw personal fields of one record."""
    out = []
    for f in fields:
        v = record.get(f)
        for x in (v if isinstance(v, list) else [v]):
            if isinstance(x, str) and x.strip():
                out.append(x)
    return out


def phone_digits(text: str) -> list[str]:
    """Phone-number-like sequences in a text, reduced to digits (8 to 15 of them)."""
    found = []
    for m in PHONE_RE.finditer(text):
        d = re.sub(r"\D", "", m.group(0))
        if 8 <= len(d) <= 15:
            found.append(d)
    return found


def known_identities(record: dict, key: str, personal_fields: list[str], phone_prefixes: list[str]):
    """HMACs of the contributor names and of the phone numbers found in the phone-bearing fields of one record.

    Returns two dicts: {hmac: name length} for usernames and {hmac: digit count} for phones.
    """
    users = {}
    for v in personal_values(record, personal_fields):
        users[hmac_hex(key, v)] = len(normalise(v))
    phones = {}
    for k, v in record.items():
        if isinstance(v, str) and any(k.startswith(p) for p in phone_prefixes):
            for d in phone_digits(v):
                phones[hmac_hex(key, d, prefix="phone:")] = len(d)
    return users, phones


def candidates(text: str):
    """Words of a text as a username could appear in it: each token, and the token without edge punctuation."""
    for t in TOKEN_RE.findall(text):
        yield t
        s = t.strip("._-")
        if s and s != t:
            yield s


def load_stoplist(path) -> frozenset:
    """Ordinary words that are also usernames: one per line, # comments and blank lines ignored, normalised."""
    words = set()
    for line in open(path, encoding="utf-8").read().splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            words.add(normalise(line))
    return frozenset(words)


def find_known(texts: list[str], key: str, known_users, known_phones, min_len: int, stoplist=frozenset(),
               exempt=frozenset(), report_min: int = SHORT_MIN):
    """Search texts for known usernames (whole words) and phone numbers.

    Returns (hits, short_hits, exempt_hits):
      hits         usernames of min_len or more, and phone numbers: a reason to quarantine the row
      short_hits   usernames of report_min to min_len-1 characters: counted, never a reason to quarantine
      exempt_hits  usernames whose HMAC is in `exempt` (the product's own contributors, for columns the contract exempts)
    """
    hits, short_hits, exempt_hits = 0, 0, 0
    for text in texts:
        if not text:
            continue
        seen = set()
        for c in candidates(text):
            n = normalise(c)
            if n in seen or len(n) < report_min or n in stoplist:
                continue
            seen.add(n)
            h = hmac_hex(key, n)
            if h in known_users:
                if h in exempt:
                    exempt_hits += 1
                elif len(n) >= min_len:
                    hits += 1
                else:
                    short_hits += 1
        for d in phone_digits(text):
            if hmac_hex(key, d, prefix="phone:") in known_phones:
                hits += 1
    return hits, short_hits, exempt_hits


def scrub(text: str, patterns: dict) -> tuple[str, int]:
    """Replace email, Aadhaar and PAN patterns. patterns holds the three compiled regexes and the replacement."""
    n_total = 0
    for name in ("email", "aadhaar", "pan"):
        text, n = patterns[name].subn(patterns["replacement"], text)
        n_total += n
    return text, n_total


def compile_patterns(contract: dict) -> dict:
    s = contract["scrub"]
    return {"email": re.compile(s["email"]), "aadhaar": re.compile(s["aadhaar"]), "pan": re.compile(s["pan"]),
            "replacement": s["replacement"]}


def has_pattern(text: str, patterns: dict) -> bool:
    return any(patterns[n].search(text) for n in ("email", "aadhaar", "pan"))
