-- Материалы проведённой работы и обсуждение принятой проверки (#2405).
-- Дополнения хранятся отдельно от замороженного отчёта. Только добавление:
-- новый файл не заменяет предыдущий; прав на update/delete у приложения нет.
create table inspection_followup (
    id uuid primary key,
    inspection_id uuid not null references inspections (id),
    author_tenant text not null references tenants (code),
    author text not null check (length(btrim(author)) between 1 and 200),
    created_at timestamptz not null default clock_timestamp(),
    body text not null default '' check (length(body) <= 5000),
    storage_path text,
    file_name text,
    size_bytes bigint,
    sha256 text,
    check (length(btrim(body)) > 0 or storage_path is not null),
    check ((storage_path is null and file_name is null and size_bytes is null and sha256 is null)
        or (storage_path is not null and file_name is not null and size_bytes is not null
            and sha256 is not null and length(file_name) between 1 and 200
            and size_bytes > 0 and sha256 ~ '^[0-9a-f]{64}$'))
);
create index inspection_followup_history
    on inspection_followup (inspection_id, created_at desc, id desc);
comment on table inspection_followup is
    'История файлов проведённой работы и комментариев к проверке. Не запрос плана и не согласование.';

-- Обычной роли замороженная проверка недоступна для SELECT FOR SHARE
-- (он требует UPDATE-политики). Узкий триггер блокирует только родителя
-- вставляемой строки и не даёт гонке со снятием сохранить материал после снятия.
create function inspection_followup_parent() returns trigger
    language plpgsql security definer
    set search_path = pg_catalog, public, pg_temp
as $$
declare
    parent inspections%rowtype;
begin
    select * into parent from inspections where id = new.inspection_id for share;
    if not found or parent.status <> 'finalized' or parent.retracted_at is not null then
        raise exception 'inspection is not accepted or is retracted' using errcode = 'check_violation';
    end if;
    return new;
end
$$;
revoke all on function inspection_followup_parent() from public;
create trigger inspection_followup_parent_guard before insert on inspection_followup
    for each row execute function inspection_followup_parent();

alter table inspection_followup enable row level security;
alter table inspection_followup force row level security;
create policy inspection_followup_read on inspection_followup
    for select to dodo_audit_app, dodo_audit_admin
    using (exists (select 1 from inspections i where i.id = inspection_id));
create policy inspection_followup_add on inspection_followup
    for insert to dodo_audit_app
    with check (
        (author_tenant = decimus_space() or decimus_space() = '*')
        and exists (select 1 from inspections i where i.id = inspection_id
            and i.status = 'finalized' and i.retracted_at is null)
    );
grant select, insert on inspection_followup to dodo_audit_app;
grant select on inspection_followup to dodo_audit_admin;
