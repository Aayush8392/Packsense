"""The review store (item 22, design test 5): static checks on the migration, and role checks on the live Neon database.

The live checks run only where NEON_DATABASE_URL is set (the laptop, never a pull-request workflow) and leave nothing behind: every check is ONE
transaction that ends in a deliberate division by zero, so Neon rolls everything back. A check therefore has two possible outcomes that matter:
  - the action is DENIED: the server stops at it with a permission error (42501) or the rule's own error;
  - the action is ALLOWED: every statement runs and the transaction stops only at the deliberate failure (22012).
The roles are group roles with no login; the checks switch to them with SET LOCAL ROLE, so no password is involved.
"""
from __future__ import annotations

import os
import re
import sys
from pathlib import Path

import pytest

NEON = Path(__file__).resolve().parents[1] / "neon"
sys.path.insert(0, str(NEON))
import neon_http  # noqa: E402
import run_migrations  # noqa: E402

SQL = (NEON / "001_review_store.sql").read_text(encoding="utf-8")


def test_the_migration_splits_into_statements_and_ends_by_recording_itself():
    statements = run_migrations.split_statements(SQL)
    assert len(statements) > 20
    assert "insert into review.schema_migrations" in statements[-1]


def test_no_grant_is_table_wide_or_to_public_and_no_role_can_log_in():
    grants = [s for s in re.split(r";\s*\n", SQL) if re.search(r"^\s*grant\b", s, re.IGNORECASE | re.MULTILINE)]
    assert grants
    for g in grants:
        assert "all tables" not in g.lower() and "all privileges" not in g.lower() and " public" not in g.lower(), g
        assert not re.search(r"\bdelete\b|\btruncate\b", g, re.IGNORECASE), g
    for create in re.findall(r"create role \w+ ([^;]*);", SQL, re.IGNORECASE):
        assert create.strip().lower() == "nologin"


def test_url_reader_refuses_a_value_that_is_not_a_postgres_url(monkeypatch):
    monkeypatch.setenv("NEON_DATABASE_URL", "not-a-url")
    with pytest.raises(ValueError):
        neon_http.read_url()


ROOT = Path(__file__).resolve().parents[2]
try:
    URL = neon_http.read_url(str(ROOT / ".env") if os.environ.get("PACKSENSE_NEON_ENV_FILE") == "1" else None)
except ValueError:
    URL = None
live = pytest.mark.skipif(URL is None, reason="NEON_DATABASE_URL is not set (live role checks run on the laptop only)")

FLAG = "test_flag_0001"
ITEM = f"insert into review.items (flag_id, code, severity, flag, first_seen_t) values ('{FLAG}', '1', 'error', 'en:test', 1)"
PROPOSAL = f"insert into review.proposals (flag_id, model, prompt_hash, evidence, proposal) values ('{FLAG}', 'm', 'h', '{{}}', '{{}}')"
DECISION = f"insert into review.decisions (flag_id, decision) values ('{FLAG}', 'accept')"
END = "select 1 / 0"          # the deliberate failure that rolls the transaction back
ROLLED_BACK = "22012"


def outcome(role: str | None, *statements: str, setup: tuple[str, ...] = ()) -> str:
    """Run setup (as the owner), then the statements as `role`, then the deliberate failure. Returns 'allowed' or the server's error."""
    batch = [*setup, *([f"set local role {role}"] if role else []), *statements, END]
    try:
        neon_http.run(URL, batch)
    except neon_http.NeonError as e:
        return "allowed" if e.code == ROLLED_BACK else f"{e.code}: {e.message}"
    raise AssertionError("the deliberate failure did not happen")


def denied(result: str) -> bool:
    """A permission error on the ACTION. A refused role switch is a test setup fault, never a denial (it would let every check pass for the wrong reason)."""
    assert "set role" not in result, result
    return result.startswith("42501")


@live
def test_the_steward_can_add_a_proposal_but_cannot_decide_change_or_delete():
    assert outcome("review_steward", PROPOSAL, setup=(ITEM,)) == "allowed"
    for statement in (DECISION, "update review.items set status = 'decided', version = 2", f"delete from review.items where flag_id = '{FLAG}'",
                      f"delete from review.proposals where flag_id = '{FLAG}'", "insert into review.audit (actor, action) values ('x', 'y')", ITEM.replace(FLAG, FLAG + "b")):
        assert denied(outcome("review_steward", statement, setup=(ITEM,))), statement


@live
def test_the_reviewer_can_decide_and_move_status_but_cannot_delete_or_edit_the_trail():
    assert outcome("review_reviewer", DECISION, setup=(ITEM,)) == "allowed"
    assert outcome("review_reviewer", "update review.items set status = 'decided', version = 2", setup=(ITEM,)) == "allowed"
    for statement in (f"delete from review.decisions where flag_id = '{FLAG}'", PROPOSAL, "update review.audit set action = 'x'", "delete from review.audit",
                      "insert into review.audit (actor, action) values ('x', 'y')", "update review.items set flag = 'en:other'"):
        assert denied(outcome("review_reviewer", statement, setup=(ITEM, PROPOSAL, DECISION))), statement


@live
def test_the_sync_role_adds_items_and_marks_them_but_cannot_decide_or_delete():
    assert outcome("review_sync", ITEM) == "allowed"
    assert outcome("review_sync", "update review.items set status = 'superseded', version = 2", setup=(ITEM,)) == "allowed"
    for statement in (DECISION, PROPOSAL, f"delete from review.items where flag_id = '{FLAG}'"):
        assert denied(outcome("review_sync", statement, setup=(ITEM,))), statement


@live
def test_one_decision_per_item_and_the_version_must_rise_by_one():
    assert outcome(None, DECISION, DECISION, setup=(ITEM,)).startswith("23505")
    assert "version must rise by one" in outcome("review_reviewer", "update review.items set status = 'decided', version = 5", setup=(ITEM,))
    assert "version must rise by one" in outcome("review_reviewer", "update review.items set status = 'decided'", setup=(ITEM,))


@live
def test_the_trail_is_written_by_triggers_and_cannot_be_changed_by_anyone():
    check = (f"do $$ begin if (select count(*) from review.audit where flag_id = '{FLAG}') <> 3 then raise exception 'audit rows missing'; end if; end $$")
    assert outcome(None, PROPOSAL, DECISION, check, setup=(ITEM,)) == "allowed"
    assert "append-only" in outcome(None, "update review.audit set action = 'x'", setup=(ITEM,))
    assert "append-only" in outcome(None, "delete from review.audit", setup=(ITEM,))
    assert "append-only" in outcome(None, "truncate review.audit", setup=(ITEM,))


@live
def test_a_planted_wrong_grant_is_seen_by_the_denial_check():
    """The checker is only evidence if it can go red: grant DELETE to the steward inside the rolled-back transaction and the denial check must fail."""
    result = outcome("review_steward", f"delete from review.items where flag_id = '{FLAG}'", setup=(ITEM, "grant delete on review.items to review_steward"))
    assert result == "allowed" and not denied(result)
