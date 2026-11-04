-- The migrating owner becomes a member of the three group roles, so the role checks (tests/test_review_store.py) can switch to each with SET LOCAL ROLE
-- and prove what it may and may not do, with no password involved. Postgres does not give the creator of a role membership in it by default (found 2026-11-04:
-- "permission denied to set role" made every denial check pass for the wrong reason, which the test helper now refuses to count).
do $$
begin
    execute format('grant review_steward, review_reviewer, review_sync to %I', current_user);
end;
$$;
-- go
insert into review.schema_migrations (version) values ('002_owner_membership');
