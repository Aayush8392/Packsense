"""Tests for the grants file and its logic: the real file validates, the diff reports a planted missing and a planted extra grant,
the README block is the generated one, nothing else in the repo keeps a second copy of the grants, and every schema, volume and
secret scope the bundles name is covered by the file."""
import copy
import re
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "p5_governance"))
import grants_lib as gl  # noqa: E402

SPEC = gl.load_spec()
IDS = {r: f"id-{r}" for r in SPEC["principals"]}


def test_the_real_file_validates_and_resolves_every_role():
    want, skipped = gl.expected_grants(SPEC, IDS)
    assert want and not skipped
    assert gl.expected_acls(SPEC, IDS)


def test_a_missing_grant_and_an_extra_grant_are_both_reported():
    want, _ = gl.expected_grants(SPEC, IDS)
    live = set(want)
    planted_missing = ("table", "workspace.packsense_silver.silver_manifest", "id-packsense-gold", "SELECT")
    live.discard(planted_missing)
    planted_extra = ("schema", "workspace.packsense_bronze", "id-packsense-gold", "SELECT")      # gold must never read bronze
    live.add(planted_extra)
    missing, extra = gl.diff(want, live)
    assert missing == [planted_missing]
    assert extra == [planted_extra]


def test_an_identical_state_has_no_difference():
    want, _ = gl.expected_grants(SPEC, IDS)
    assert gl.diff(want, set(want)) == ([], [])


def test_a_role_that_cannot_be_resolved_is_skipped_not_guessed():
    ids = dict(IDS, analyst=None)
    want, skipped = gl.expected_grants(SPEC, ids)
    assert skipped == ["analyst"]
    assert not any(p is None for _, _, p, _ in want)


@pytest.mark.parametrize("mutate, message", [
    (lambda s: s["securables"][0]["grants"].update({"nobody": ["USE_CATALOG"]}), "unknown principal"),
    (lambda s: s["securables"][0]["grants"].update({"admin": ["WRITE_VOLUME"]}), "not allowed on a catalog"),
    (lambda s: s["securables"].append(copy.deepcopy(s["securables"][0])), "listed twice"),
    (lambda s: s["securables"].append({"type": "schema", "name": "other.packsense", "grants": {}}), "full name inside catalog"),
    (lambda s: s["secret_scopes"]["packsense"].update({"admin": "ROOT"}), "permission must be"),
])
def test_a_bad_file_is_refused(mutate, message):
    bad = copy.deepcopy(SPEC)
    mutate(bad)
    with pytest.raises(gl.SpecError, match=message):
        gl.validate(bad)


def test_gold_principals_have_no_access_to_bronze_or_the_main_scope():
    """The single-writer rule in the file itself: a gold principal never appears on a bronze object or the bronze scope."""
    for s in SPEC["securables"]:
        if "bronze" in s["name"] or s["name"] in ("workspace.packsense", "workspace.packsense.landing"):
            assert not {r for r in s.get("grants", {}) if "gold" in r}, s["name"]
    for scope in ("packsense", "packsense_dev"):
        assert not {r for r in SPEC["secret_scopes"][scope] if "gold" in r}


def test_gold_principals_read_exactly_the_three_silver_tables():
    tables = {r: set() for r in ("packsense-gold", "packsense-gold-dev")}
    for s in SPEC["securables"]:
        if s["type"] == "table":
            for r in s["grants"]:
                if r in tables:                      # the analyst's table grants (P5 step 4) are checked in test_policies.py
                    tables[r].add(s["name"].split(".")[-1])
    assert tables["packsense-gold"] == tables["packsense-gold-dev"] == {"silver_product_versions", "silver_manifest", "silver_taxonomy_tag"}


def test_the_readme_block_is_the_generated_one():
    readme = (ROOT / "p5_governance" / "README.md").read_text(encoding="utf-8")
    m = re.search(r"<!-- grants:begin -->\n```sql\n(.*?)\n```\n<!-- grants:end -->", readme, re.S)
    assert m, "README.md has no generated grants block"
    assert m.group(1) == gl.render_sql(SPEC), "the README grants block is stale: regenerate it from grants.yml (python p5_governance/bootstrap/render_readme_block.py)"


def test_no_other_readme_keeps_a_second_copy_of_the_grants():
    for rel in ("p3_delivery/README.md", "p4_modelling/README.md"):
        text = (ROOT / rel).read_text(encoding="utf-8")
        assert not re.search(r"^GRANT .* TO `<principal>`", text, re.M), f"{rel} still carries its own GRANT block: point it at p5_governance"


def _bundle_names():
    """Schemas, volumes and secret scopes named by the bundle files (variables with defaults and per-target values)."""
    text = ""
    for rel in ("databricks.yml", "p4_modelling/databricks.yml"):
        text += (ROOT / rel).read_text(encoding="utf-8") + "\n"
    schemas = set(re.findall(r"workspace\.(packsense\w*)", text))
    schemas |= set(re.findall(r"(?:bronze_schema|silver_schema|gold_schema):\s*(?:default:\s*)?(?:workspace\.)?(packsense\w*)", text))
    scopes = set(re.findall(r"secret_scope:\s*(?:default:\s*)?(packsense\w*)", text))
    return schemas, scopes


def test_every_schema_and_scope_the_bundles_name_is_in_the_grants_file():
    schemas, scopes = _bundle_names()
    listed = {s["name"].split(".")[1] for s in SPEC["securables"] if s["type"] == "schema"}
    # the dev landing volume's schema is `packsense_dev`; both landing schemas are listed above
    assert schemas <= listed, f"schemas used by a bundle but not in grants.yml: {sorted(schemas - listed)}"
    assert scopes <= set(SPEC["secret_scopes"]), f"scopes used by a bundle but not in grants.yml: {sorted(scopes - set(SPEC['secret_scopes']))}"


def test_the_yaml_is_plain_data():
    yaml.safe_load((ROOT / "p5_governance" / "grants.yml").read_text(encoding="utf-8"))
