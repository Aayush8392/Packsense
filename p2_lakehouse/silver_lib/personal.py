"""Personal-data and value handling for silver, all stateless (a record in, a value out; no global lists, no tables).

hashing        contributor identity fields -> HMAC codes (they never leave silver)
scrub          patterns with a clear shape (email, URL, social link, @handle, obfuscated email, Aadhaar, PAN, GSTIN)
own handles    replace the record's OWN contributor names (whole word, 8+ characters) in a text
fingerprint    a change detector for text we do not keep
parsing        quantity and serving size text -> number and unit
shape checks   tags, nutrient keys and enum strings must come from a small closed vocabulary
"""
import hashlib
import hmac
import re
import unicodedata

NUM = r"\d+(?:\.\d+)?"
MAX_AMOUNT = 1_000_000


def normalise(value: str) -> str:
    return unicodedata.normalize("NFKC", value).strip().lower()


# ---- contributor identities -------------------------------------------------------------------------------------------

def hmac_hex(key: str, value: str) -> str:
    return hmac.new(key.encode(), normalise(value).encode(), hashlib.sha256).hexdigest()


def hash_value(key: str, value):
    """A username string -> HMAC; a list of usernames -> list of HMACs; empty or missing -> None."""
    if isinstance(value, str):
        return hmac_hex(key, value) if value.strip() else None
    if isinstance(value, list):
        return [hmac_hex(key, v) for v in value if isinstance(v, str) and v.strip()]
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


# ---- the record's own handles -------------------------------------------------------------------------------------------

def own_handles(record: dict, fields: list[str], min_length: int) -> set[str]:
    """Normalised names of this record's own contributors that are long enough to redact."""
    return {n for n in (normalise(v) for v in personal_values(record, fields)) if len(n) >= min_length}


def handle_regex(handles):
    """One whole-word, case-insensitive pattern for a set of names; None when there are none.

    A name is a whole word when no letter, digit or underscore touches it, and no dot or hyphen that itself touches a letter
    or digit (so "photo by name." counts, "name.com", "www.name" and "name-bakery" do not). Usernames use only letters,
    digits, underscore, dot and hyphen: verified on all 75,749 names in bronze."""
    names = sorted({h for h in handles if h}, key=len, reverse=True)
    if not names:
        return None
    return re.compile(r"(?<!\w)(?<!\w[.\-])(?:" + "|".join(re.escape(n) for n in names) + r")(?!\w)(?![.\-]\w)", re.IGNORECASE)


def redact_handles(text: str, handles, sentinel: str) -> tuple[str, int]:
    rx = handle_regex(handles)
    if rx is None or not text:
        return text, 0
    return rx.subn(sentinel, text)


# ---- patterns with a clear shape ----------------------------------------------------------------------------------------

SCRUB_ORDER = ("email", "obfuscated_email", "social_link", "url", "at_handle", "aadhaar", "gstin", "pan")


def compile_patterns(contract: dict) -> dict:
    s = contract["scrub"]
    out = {name: re.compile(s[name]) for name in SCRUB_ORDER}
    out["replacement"] = s["replacement"]
    return out


def scrub(text: str, patterns: dict) -> tuple[str, int]:
    """Replace every pattern with the contract's replacement; returns the new text and how many substitutions were made."""
    n_total = 0
    for name in SCRUB_ORDER:
        text, n = patterns[name].subn(patterns["replacement"], text)
        n_total += n
    return text, n_total


def has_pattern(text: str, patterns: dict) -> bool:
    return any(patterns[n].search(text) for n in SCRUB_ORDER)


# ---- fingerprint of text we do not keep ---------------------------------------------------------------------------------

def fingerprint(text) -> str | None:
    """SHA-256 of the normalised text (NFKC, lower case, one space between words); None when there is no text."""
    if not isinstance(text, str):
        return None
    t = " ".join(unicodedata.normalize("NFKC", text).lower().split())
    return hashlib.sha256(t.encode("utf-8")).hexdigest() if t else None


# ---- quantity and serving size text -> number and unit -------------------------------------------------------------------

def _clean(s: str) -> str:
    t = s.strip().lower()
    t = re.sub(r"(?<=\d),(?=\d)", ".", t)            # decimal comma
    t = re.sub(r"\([^)]*\)", " ", t)                   # a bracketed alternative such as (8.8 oz)
    t = re.sub(r"\s*=.*$", "", t)                      # "6 x 50 g = 300 g" keeps the part before the sign
    t = re.sub(r"[\s.,;:]+$", "", t)                   # trailing punctuation
    t = re.sub(r"\s*[e℮]$", "", t)                # the estimated-quantity mark after the unit
    return " ".join(t.split())


def _unit_alternation(units: dict) -> str:
    return "|".join(re.escape(u) for u in sorted(units, key=len, reverse=True))


def parse_quantity(value, units: dict):
    """'6 x 33 cl' -> (33.0, 'cl', 6); '250 g' -> (250.0, 'g', None); anything else -> (None, None, None)."""
    if not isinstance(value, str) or not value.strip():
        return None, None, None
    t = _clean(value)
    u = _unit_alternation(units)
    for pattern, order in (
        (rf"^(\d+)\s*[x×*]\s*({NUM})\s*({u})$", "mult_amount"),     # 6 x 33 cl
        (rf"^({NUM})\s*({u})\s*[x×*]\s*(\d+)$", "amount_mult"),     # 250 g x 4
        (rf"^({NUM})\s*({u})(?:\s*/\s*{NUM}\s*(?:{u}))?$", "single"),    # 250 g, or 250 g / 250 ml (the first part)
    ):
        m = re.match(pattern, t)
        if not m:
            continue
        if order == "mult_amount":
            mult, amount, unit = int(m.group(1)), float(m.group(2)), m.group(3)
        elif order == "amount_mult":
            amount, unit, mult = float(m.group(1)), m.group(2), int(m.group(3))
        else:
            amount, unit, mult = float(m.group(1)), m.group(2), None
        if 0 < amount < MAX_AMOUNT and (mult is None or 0 < mult < 1000):
            return amount, units[unit], mult
    return None, None, None


def parse_serving(value, units: dict):
    """The first amount in grams or millilitres anywhere in the value: '1 cup (240 ml)' -> (240.0, 'ml')."""
    if not isinstance(value, str) or not value.strip():
        return None, None
    t = re.sub(r"(?<=\d),(?=\d)", ".", value.strip().lower())
    allowed = {k: v for k, v in units.items() if v in ("g", "ml")}
    m = re.search(rf"(?<![\w.])({NUM})\s*({_unit_alternation(allowed)})(?![\w])", t)
    if not m:
        return None, None
    amount = float(m.group(1))
    return (amount, allowed[m.group(2)]) if 0 < amount < MAX_AMOUNT else (None, None)


# ---- shape checks -------------------------------------------------------------------------------------------------------

def compile_shapes(contract: dict) -> dict:
    return {name: re.compile(rx) for name, rx in contract["shape"].items()}


def shape_ok(value, rx) -> bool:
    return isinstance(value, str) and rx.match(value) is not None
