"""The SQL comparison key of a brand (macros/brand_key.sql) against Python's, on real brand strings, and the accent table against its generator.

Python is the reference: lower-case, `&` as ` and `, NFKD with the combining marks removed, runs outside a-z and 0-9 as one space, a leading `the`, trailing legal words
(the same steps as `brand_key` in p7_triage_ml/analysis/brand_canon.py, where the rule was measured), then the plural step of dim_brand_canonical. The macro is rendered by
`dbt compile --inline` (the real DuckDB rendering) and run on a table of real Open Food Facts brand strings. A measured run over all 49,301 strings of the production catalogue
(2026-11-04) differed on exactly one, a vulgar-fraction character that NFKD turns into three characters and a one-to-one translate cannot: it is listed in KNOWN_DIFFERENCE.
`accent_table()` below is the generator of the translate table in the macro: run it and paste its output if the Unicode ranges ever change (the test compares).
Needs dbt and the DuckDB fixture build (skipped without them; the CI job `engines` has both).
"""
import re
import shutil
import subprocess
import unicodedata
from pathlib import Path

import duckdb
import pytest

P4 = Path(__file__).resolve().parents[1]
DB = P4 / "target" / "fixture.duckdb"
MACRO = P4 / "macros" / "brand_key.sql"
DBT = shutil.which("dbt") or str(P4.parent / ".venv-dbt" / "Scripts" / "dbt.exe")
pytestmark = pytest.mark.skipif(not DB.exists() or not Path(DBT).exists(), reason="dbt or the DuckDB fixture build is not available")

LEGAL = {"ltd", "limited", "pvt", "private", "inc", "incorporated", "llc", "gmbh", "sa", "sas", "spa", "srl", "bv", "ag", "co", "corp", "corporation", "company", "plc", "oy", "ab", "as", "nv", "sl", "sarl", "ltda", "kg"}
RANGES = ((0xA0, 0x24F), (0x1E00, 0x1EFF), (0x2070, 0x209F), (0xFF00, 0xFFEF), (0x1D400, 0x1D7FF))
KNOWN_DIFFERENCE = "autentico  (1⅕=140g=280cal)"

STRINGS = [   # all real first-brand strings of the catalogue (nothing invented): variants of one brand, accents, legal words, a leading 'the', scripts the key drops
    "trader joe's", "trader joes", "trader joe’s", "traderjoes", "cadbury's", "cadburys", "marks & spencer", "marks & spencers", "marks and spencer’s", "haldiram's", "haldiram s",
    "k-classic", "k classic", "k-classics", "the kroger co.", "kroger", "woolworth’s", "starbucks®", "pâturages", "páturages", "pâturage", "huercasa 5ª gama s.a.", "mª jose gamez garcia",
    "s.a.t. nº 9855 primaflor", "𝐑𝐚𝐚𝐤", "𝙠𝙚𝙡𝙡𝙤𝙜𝙨", "вкусвилл", "вкусвиилл", "מחלבת רמת הגולן", "αλφα-βητα", "3αλφα", "campofrío food group", "campofrio food group s.a.", "kahve dünyası",
    "müller x myprotein", "the", "ltd", "the 3 bakers", "the almond farmer", "bamboo house food co. ltd.", "bolero & co. ltd", "option+", "options", "!que viva espana!", "!que viva españa",
    "bergsträßer kaffeerösterei", "bohnen weiß", "aakeberg-skoglund pølsemakeri as", "arnold sørensen", "askim frukt- og bærpresseri", "attåtnæring", "ansław mushrooms & more",
    "cung đình", "(社福)せせらぎ会", "(주)푸디스", "nestlé", "nestle", "heinz", "baxters", "baxter’s", "1 -bite  foods", "205        magic wine orchil", "dr bear", "m&s bakery", "activus", "adrijus",
]


def accent_table() -> tuple[str, str]:
    frm, to = [], []
    for lo, hi in RANGES:
        for cp in range(lo, hi + 1):
            c = chr(cp)
            if c.lower() != c:
                continue
            base = "".join(ch for ch in unicodedata.normalize("NFKD", c) if not unicodedata.combining(ch))
            if len(base) == 1 and base != c and base.isascii() and base.isalnum():
                frm.append(c)
                to.append(base)
    return "".join(frm), "".join(to)


def py_key(raw: str) -> str:
    folded = unicodedata.normalize("NFKD", raw.lower().replace("&", " and "))
    words = re.sub(r"[^a-z0-9]+", " ", "".join(c for c in folded if not unicodedata.combining(c))).split()
    if words and words[0] == "the" and len(words) > 1:
        words = words[1:]
    while len(words) > 1 and words[-1] in LEGAL:
        words = words[:-1]
    return "".join(words)


def py_group_key(raw: str) -> str:
    k = py_key(raw)
    if not k:
        return raw
    return k[:-1] if len(k) >= 7 and k.endswith("s") else k


def rendered_sql() -> str:
    done = subprocess.run([DBT, "compile", "--target", "duckdb", "--profiles-dir", ".", "--inline",
                           "select raw, {{ brand_name_key('raw') }} as k1, {{ brand_name_stem_key(brand_name_key('raw')) }} as k2 from raw_strings"],
                          cwd=P4, capture_output=True, text=True, encoding="utf-8", env={**__import__("os").environ, "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"}, timeout=300)
    assert done.returncode == 0, done.stdout[-1500:] + done.stderr[-1500:]
    text = done.stdout + done.stderr
    start = text.index("select raw,")
    return text[start:].split("\n\n")[0].strip().strip('"')


def test_accent_table_in_the_macro_is_the_generated_one():
    frm, to = accent_table()
    assert f"'{frm}', '{to}'" in MACRO.read_text(encoding="utf-8")


def test_sql_key_equals_python_key_on_real_brand_strings():
    sql = rendered_sql()
    con = duckdb.connect()
    con.execute("create table raw_strings(raw varchar)")
    con.executemany("insert into raw_strings values (?)", [(s,) for s in STRINGS])
    rows = con.execute(sql).fetchall()
    assert len(rows) == len(STRINGS)
    for raw, k1, k2 in rows:
        assert k1 == py_key(raw), ("key", raw)
        group = (k2 if k1 else raw)               # the model falls back to the raw string when no key is left
        assert group == py_group_key(raw), ("group key", raw)


def test_known_difference_is_still_the_only_kind_we_do_not_cover():
    # NFKD turns the vulgar fraction into 1, a fraction slash and 5; a one-to-one translate cannot, so the SQL key keeps the digits of the rest only
    assert len(unicodedata.normalize("NFKD", "⅕")) == 3
    assert py_key(KNOWN_DIFFERENCE) != py_key(KNOWN_DIFFERENCE.replace("⅕", ""))
