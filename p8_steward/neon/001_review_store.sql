-- Review store (roadmap item 22, design E5): the queue, the agent's proposals, the human decisions and an append-only audit trail.
-- Statements are separated by a line holding only "-- go"; the runner (run_migrations.py) sends the whole file as ONE transaction.
-- Nothing here is a login role: the three group roles below cannot log in. The owner makes login roles in the Neon console and adds them as members.
--   review_steward   the agent: reads, inserts items and proposals. Cannot decide, update or delete.
--   review_reviewer  the human: reads, inserts decisions, moves an item's status with a version check. Cannot delete, cannot touch proposals or audit.
--   review_sync      the job that copies flags from gold and marks vanished ones superseded. Inserts items, moves status. Cannot delete.
-- The audit trail is written only by triggers (security definer), so no role holds INSERT on it, and a trigger refuses UPDATE and DELETE for everyone.
-- Grants are explicit and per table or column; nothing is granted table-wide and then revoked (a table-wide GRANT overrides a column REVOKE: design test C6).

create schema if not exists review;
-- go
create table if not exists review.schema_migrations (
    version text primary key,
    applied_at timestamptz not null default now()
);
-- go
create table review.items (
    flag_id text primary key,                         -- gold product_flag_spans.flag_id: hash of (code, severity, flag, first_seen_t)
    code text not null,
    severity text not null check (severity in ('error', 'warning', 'info')),
    flag text not null,
    first_seen_t bigint not null,
    status text not null default 'open' check (status in ('open', 'decided', 'superseded')),
    version integer not null default 1,               -- every status change must present the version it read
    created_at timestamptz not null default now()
);
-- go
create table review.proposals (
    proposal_id bigserial primary key,
    flag_id text not null references review.items (flag_id),
    proposed_by text not null default current_user,
    model text not null,
    prompt_hash text not null,
    evidence jsonb not null,                          -- the values the agent saw, snapshotted at proposal time
    proposal jsonb not null,
    created_at timestamptz not null default now()
);
-- go
create table review.decisions (
    decision_id bigserial primary key,
    flag_id text not null unique references review.items (flag_id),   -- one decision per item
    proposal_id bigint references review.proposals (proposal_id),
    decided_by text not null default current_user,
    decision text not null check (decision in ('accept', 'reject', 'edit')),
    note text,
    created_at timestamptz not null default now()
);
-- go
create table review.audit (
    audit_id bigserial primary key,
    at timestamptz not null default now(),
    actor text not null,
    action text not null,
    flag_id text,
    detail jsonb
);
-- go
create function review.refuse_audit_change() returns trigger language plpgsql as $$
begin
    raise exception 'review.audit is append-only';
end;
$$;
-- go
create trigger audit_no_update_delete before update or delete on review.audit
    for each row execute function review.refuse_audit_change();
-- go
create trigger audit_no_truncate before truncate on review.audit
    for each statement execute function review.refuse_audit_change();
-- go
create function review.write_audit() returns trigger language plpgsql security definer set search_path = review, pg_temp as $$
begin
    if tg_table_name = 'items' and tg_op = 'INSERT' then
        insert into review.audit (actor, action, flag_id, detail) values (current_user, 'item_added', new.flag_id, jsonb_build_object('severity', new.severity, 'flag', new.flag));
    elsif tg_table_name = 'items' and tg_op = 'UPDATE' then
        insert into review.audit (actor, action, flag_id, detail) values (current_user, 'item_status', new.flag_id, jsonb_build_object('from', old.status, 'to', new.status, 'version', new.version));
    elsif tg_table_name = 'proposals' then
        insert into review.audit (actor, action, flag_id, detail) values (current_user, 'proposal_added', new.flag_id, jsonb_build_object('proposal_id', new.proposal_id, 'model', new.model, 'prompt_hash', new.prompt_hash));
    elsif tg_table_name = 'decisions' then
        insert into review.audit (actor, action, flag_id, detail) values (current_user, 'decision_added', new.flag_id, jsonb_build_object('decision', new.decision, 'proposal_id', new.proposal_id));
    end if;
    return new;
end;
$$;
-- go
create trigger items_audit after insert or update on review.items for each row execute function review.write_audit();
-- go
create trigger proposals_audit after insert on review.proposals for each row execute function review.write_audit();
-- go
create trigger decisions_audit after insert on review.decisions for each row execute function review.write_audit();
-- go
-- A status change must raise the version by exactly one from the value the writer read; the writer's UPDATE carries "where version = <read>" and
-- this trigger refuses anything else (a second writer with a stale read updates zero rows; a writer that skips the check is refused here).
create function review.check_version() returns trigger language plpgsql as $$
begin
    if new.flag_id <> old.flag_id or new.code <> old.code or new.severity <> old.severity or new.flag <> old.flag or new.first_seen_t <> old.first_seen_t then
        raise exception 'only status and version of an item may change';
    end if;
    if new.version <> old.version + 1 then
        raise exception 'version must rise by one (read %, wrote %)', old.version, new.version;
    end if;
    return new;
end;
$$;
-- go
create trigger items_version before update on review.items for each row execute function review.check_version();
-- go
do $$
begin
    if not exists (select 1 from pg_roles where rolname = 'review_steward') then create role review_steward nologin; end if;
    if not exists (select 1 from pg_roles where rolname = 'review_reviewer') then create role review_reviewer nologin; end if;
    if not exists (select 1 from pg_roles where rolname = 'review_sync') then create role review_sync nologin; end if;
end;
$$;
-- go
revoke all on schema review from public;
-- go
revoke all on all tables in schema review from public;
-- go
revoke all on all sequences in schema review from public;
-- go
revoke all on all functions in schema review from public;
-- go
grant usage on schema review to review_steward, review_reviewer, review_sync;
-- go
grant select on review.items, review.proposals, review.decisions to review_steward, review_reviewer, review_sync;
-- go
grant insert on review.items to review_sync;
-- go
grant update (status, version) on review.items to review_sync, review_reviewer;
-- go
grant insert on review.proposals to review_steward;
-- go
grant usage on sequence review.proposals_proposal_id_seq to review_steward;
-- go
grant insert on review.decisions to review_reviewer;
-- go
grant usage on sequence review.decisions_decision_id_seq to review_reviewer;
-- go
-- the audit table is readable by the reviewer only (it holds who did what); no role can write it directly
grant select on review.audit to review_reviewer;
-- go
insert into review.schema_migrations (version) values ('001_review_store');
