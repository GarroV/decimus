-- Исправления по находкам принятой проверки: #2408, #2409.
-- Состояния исправлений и неизменяемый журнал решений проверяющего.
alter table inspection_followup
    add column finding_id uuid references findings (id),
    add column preview_path text;
create index inspection_followup_by_finding
    on inspection_followup (finding_id, created_at desc, id desc)
    where finding_id is not null;

create table inspection_remediation (
    finding_id uuid primary key references findings (id),
    inspection_id uuid not null references inspections (id),
    status text not null default 'open' check (status in ('open', 'submitted', 'confirmed')),
    revision integer not null default 1 check (revision > 0)
);
create table inspection_remediation_events (
    id bigint generated always as identity primary key,
    finding_id uuid not null references inspection_remediation (finding_id),
    revision integer not null,
    kind text not null check (kind in ('evidence', 'submitted', 'confirmed', 'returned', 'reopened')),
    actor text not null check (length(btrim(actor)) between 1 and 200),
    reason text not null default '' check (length(reason) <= 5000),
    created_at timestamptz not null default clock_timestamp(),
    unique (finding_id, revision)
);
comment on table inspection_remediation is 'Состояние исправления находки; отсутствие строки означает открытый пункт.';
comment on table inspection_remediation_events is 'Неизменяемая история материалов, передачи, подтверждений и возвратов исправления.';

-- Блокировка одного пункта общая для доказательств и решений проверяющего.
-- Замороженный отчёт не обновляется, его блокирует только узкая функция владельца.
create function inspection_remediation_lock(inspection uuid, finding uuid) returns void
    language plpgsql security definer
    set search_path = pg_catalog, public, pg_temp
as $$
declare parent inspections%rowtype;
begin
    perform pg_advisory_xact_lock(hashtextextended(finding::text, 136));
    select * into parent from inspections where id = inspection for share;
    if not found or parent.status <> 'finalized' or parent.retracted_at is not null
       or not decimus_space_reads(parent.tenant_code, parent.unit_id)
       or not exists (select 1 from findings f where f.id = finding
                      and f.inspection_id = inspection and f.level in ('D1', 'D2', 'D3')) then
        raise exception 'repair item is unavailable' using errcode = 'check_violation';
    end if;
end
$$;
revoke all on function inspection_remediation_lock(uuid, uuid) from public;
grant execute on function inspection_remediation_lock(uuid, uuid) to dodo_audit_app, dodo_audit_admin;

create function inspection_remediation_guard() returns trigger
    language plpgsql
    set search_path = pg_catalog, public, pg_temp
as $$
declare
    reviewer boolean := pg_has_role(current_user, 'dodo_audit_admin', 'member');
    who text := btrim(coalesce(current_setting('decimus.remediation_actor', true), ''));
    reason text := btrim(coalesce(current_setting('decimus.remediation_reason', true), ''));
begin
    perform inspection_remediation_lock(new.inspection_id, new.finding_id);
    if length(who) not between 1 and 200 then
        raise exception 'repair actor required' using errcode = 'check_violation';
    end if;
    if tg_op = 'INSERT' then
        if new.status <> 'open' or new.revision <> 1 then
            raise exception 'repair starts open' using errcode = 'check_violation';
        end if;
        return new;
    end if;
    if new.finding_id <> old.finding_id or new.inspection_id <> old.inspection_id
       or new.revision <> old.revision + 1 then
        raise exception 'invalid repair revision' using errcode = 'check_violation';
    end if;
    if new.status = old.status then
        if not reviewer or old.status = 'confirmed' then
            raise exception 'materials cannot change a closed repair' using errcode = 'insufficient_privilege';
        end if;
    elsif old.status = 'open' and new.status = 'submitted' then
        if not exists (select 1 from inspection_followup e where e.finding_id = new.finding_id) then
            raise exception 'repair evidence required' using errcode = 'check_violation';
        end if;
    elsif reviewer and old.status = 'submitted' and new.status = 'confirmed' then
        null;
    elsif reviewer and new.status = 'open' and old.status in ('submitted', 'confirmed') then
        if length(reason) not between 1 and 5000 then
            raise exception 'repair return reason required' using errcode = 'check_violation';
        end if;
    else
        raise exception 'repair transition refused' using errcode = 'insufficient_privilege';
    end if;
    return new;
end
$$;
create trigger inspection_remediation_guard before insert or update on inspection_remediation
    for each row execute function inspection_remediation_guard();

create function inspection_remediation_history() returns trigger
    language plpgsql security definer
    set search_path = pg_catalog, public, pg_temp
as $$
declare event_kind text;
begin
    event_kind := case
        when tg_op = 'INSERT' then 'evidence'
        when new.status = old.status then 'evidence'
        when new.status = 'submitted' then 'submitted'
        when new.status = 'confirmed' then 'confirmed'
        when old.status = 'confirmed' then 'reopened'
        else 'returned' end;
    insert into inspection_remediation_events (finding_id, revision, kind, actor, reason)
    values (new.finding_id, new.revision, event_kind,
            current_setting('decimus.remediation_actor'),
            case when event_kind in ('returned', 'reopened')
                 then current_setting('decimus.remediation_reason') else '' end);
    return null;
end
$$;
revoke all on function inspection_remediation_history() from public;
create trigger inspection_remediation_history after insert or update on inspection_remediation
    for each row execute function inspection_remediation_history();

create function inspection_followup_item_guard() returns trigger
    language plpgsql security definer
    set search_path = pg_catalog, public, pg_temp
as $$
begin
    if new.finding_id is not null then
        perform inspection_remediation_lock(new.inspection_id, new.finding_id);
        if exists (select 1 from inspection_remediation r
                   where r.finding_id = new.finding_id and r.status = 'confirmed') then
            raise exception 'repair is closed' using errcode = 'check_violation';
        end if;
    end if;
    return new;
end
$$;
revoke all on function inspection_followup_item_guard() from public;
create trigger inspection_followup_item_guard before insert on inspection_followup
    for each row execute function inspection_followup_item_guard();

create function inspection_followup_item_revision() returns trigger
    language plpgsql security definer
    set search_path = pg_catalog, public, pg_temp
as $$
begin
    if new.finding_id is not null then
        perform set_config('decimus.remediation_actor', new.author, true);
        insert into inspection_remediation (finding_id, inspection_id)
        values (new.finding_id, new.inspection_id)
        on conflict (finding_id) do update set revision = inspection_remediation.revision + 1;
    end if;
    return null;
end
$$;
revoke all on function inspection_followup_item_revision() from public;
create trigger inspection_followup_item_revision after insert on inspection_followup
    for each row execute function inspection_followup_item_revision();

alter table inspection_remediation enable row level security;
alter table inspection_remediation force row level security;
create policy inspection_remediation_read on inspection_remediation
    for select to dodo_audit_app, dodo_audit_admin using (
        exists (select 1 from inspections i where i.id = inspection_id));
create policy inspection_remediation_submit on inspection_remediation
    for update to dodo_audit_app using (
        exists (select 1 from inspections i where i.id = inspection_id))
    with check (status = 'submitted' and exists (select 1 from inspections i where i.id = inspection_id));
create policy inspection_remediation_review on inspection_remediation
    for update to dodo_audit_admin using (
        exists (select 1 from inspections i where i.id = inspection_id and decimus_space_writes(i.tenant_code)))
    with check (exists (select 1 from inspections i where i.id = inspection_id and decimus_space_writes(i.tenant_code)));
grant select, update on inspection_remediation to dodo_audit_app, dodo_audit_admin;

alter table inspection_remediation_events enable row level security;
alter table inspection_remediation_events force row level security;
create policy inspection_remediation_events_read on inspection_remediation_events
    for select to dodo_audit_app, dodo_audit_admin using (
        exists (select 1 from inspection_remediation r where r.finding_id = inspection_remediation_events.finding_id));
grant select on inspection_remediation_events to dodo_audit_app, dodo_audit_admin;
