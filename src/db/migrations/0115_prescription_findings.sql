-- 0115_prescription_findings.sql
--
-- Сборка предписания из проверки (шаг 3 спеки 2026-10-21-osb-prescriptions-design,
-- D601, D602, D606): вид предписания и нарушения из проверки-основания.
--
-- ЧТО ЗДЕСЬ
--
-- * `prescriptions.kind` — inspection / ratings / other. Выданные и закрытые до
--   миграции остаются как есть: `inspection`, если у них есть основания, иначе `other`.
-- * `prescription_findings` — строки таблицы нарушений документа: запись проверки-
--   основания, объект, формулировка пункта и описание КАК ЛЕГЛИ в документ, срок,
--   порядок, включена ли. Снимок, а не ссылка на живой текст: документ, который
--   согласовали, не должен поменяться от правки справочника.
--
-- Шаблон документа здесь НЕ хранится: он живёт в `mailing_templates` (0104, 0113,
-- вид `document`), версии только добавляются там. Предписание не запоминает номер
-- версии шаблона — документ собирается по действующей на момент сборки.
--
-- ЗАЩИТА (как 0037/0087): строки нарушений правятся только у неотправленного
-- предписания, с подписью (`decimus.prescription_actor`); правка согласованного снимает
-- согласование; отправленное не правится. Запись должна принадлежать проверке-основанию
-- этого же предписания (составной внешний ключ). Предписание с нарушениями не
-- согласуется и не отправляется без единой включённой записи.
--
-- Раннер оборачивает файл в одну транзакцию сам.

-- ── Предписание: вид ────────────────────────────────────────────────────────

alter table prescriptions
    add column kind text not null default 'other'
        check (kind in ('inspection', 'ratings', 'other'));

-- Прежние предписания: вид по наличию оснований. Триггеры на время отключены:
-- отправленное не правится даже мигратором, а это не правка содержимого.
alter table prescriptions disable trigger prescriptions_guarded;
alter table prescriptions disable trigger prescriptions_logged;
update prescriptions p set kind = 'inspection'
where exists (select 1 from prescription_inspections pi where pi.prescription_id = p.id);
alter table prescriptions enable trigger prescriptions_guarded;
alter table prescriptions enable trigger prescriptions_logged;

comment on column prescriptions.kind is
    'Вид предписания: по проверке, по рейтингам, прочее (D601). Права на обновление нет ни у кого: вид ставится при заведении.';

-- ── Нарушения предписания ───────────────────────────────────────────────────

create table prescription_findings (
    id uuid primary key default gen_random_uuid(),
    prescription_id uuid not null references prescriptions (id),
    inspection_id uuid not null,
    finding_id uuid not null references findings (id),
    position integer not null check (position >= 1),
    -- Объект строкой, а не только пиццерией: ПРЦ и цех теста лягут сюда же (D605).
    object_kind text not null default 'pizzeria' check (length(btrim(object_kind)) > 0),
    object_name text not null check (length(btrim(object_name)) between 1 and 200
                                     and object_name !~ '[[:cntrl:]]'),
    level text not null check (level in ('D1', 'D2', 'D3')),
    clause text not null check (length(btrim(clause)) between 1 and 1000),
    description text not null default '' check (length(description) <= 4000),
    -- Описание записи по-английски (или записи нет) — иначе на языке отчёта, «нет перевода».
    description_translated boolean not null,
    due_on date not null,
    -- Срок пункта по движку — подсказка рядом со сроком предписания.
    engine_due_on date,
    suggested boolean not null,
    included boolean not null,
    unique (prescription_id, finding_id),
    foreign key (prescription_id, inspection_id)
        references prescription_inspections (prescription_id, inspection_id)
);

create index prescription_findings_order_idx on prescription_findings (prescription_id, position);

comment on table prescription_findings is
    'Нарушения предписания по проверке (D602, D606): строки таблицы документа — снимок формулировок, срок, порядок, включено ли. Правятся у неотправленного.';

grant select on prescription_findings to dodo_audit_app, dodo_audit_admin;
grant insert, delete on prescription_findings to dodo_audit_admin;
grant update (included, due_on) on prescription_findings to dodo_audit_admin;

alter table prescription_findings enable row level security;
alter table prescription_findings force row level security;
create policy prescription_findings_app_read on prescription_findings
    for select to dodo_audit_app
    using (decimus_space() in ('*', 'HQ'));
create policy prescription_findings_admin on prescription_findings
    for all to dodo_audit_admin
    using (true) with check (true);

create function guard_prescription_finding() returns trigger
    language plpgsql
    set search_path = pg_catalog, public, pg_temp
as $$
declare
    чья uuid := case when tg_op = 'DELETE' then old.prescription_id else new.prescription_id end;
    статус text;
begin
    perform public.lock_prescription(чья);
    select p.status into статус from public.prescriptions p where p.id = чья;
    if статус is null or статус not in ('draft', 'review', 'approved') then
        raise exception 'нарушения меняют только у неотправленного предписания (сейчас %)', coalesce(статус, 'нет предписания')
            using errcode = 'check_violation';
    end if;
    if btrim(coalesce(current_setting('decimus.prescription_actor', true), '')) = '' then
        raise exception 'нарушения предписания % правят с подписью (decimus.prescription_actor)', чья
            using errcode = 'check_violation';
    end if;
    if tg_op = 'DELETE' then
        perform public.drop_prescription_approval(чья, статус);
        return old;
    end if;
    if tg_op = 'INSERT' and not exists (
        select 1 from public.findings f
        where f.id = new.finding_id and f.inspection_id = new.inspection_id
    ) then
        raise exception 'запись % не из проверки %', new.finding_id, new.inspection_id
            using errcode = 'check_violation';
    end if;
    perform public.drop_prescription_approval(чья, статус);
    return new;
end;
$$;

create trigger prescription_findings_guarded
    before insert or update or delete on prescription_findings
    for each row execute function guard_prescription_finding();
create trigger prescription_findings_logged
    after insert or update or delete on prescription_findings
    for each row execute function log_prescription_link();

-- Предписание с нарушениями не согласуется и не отправляется без единой включённой записи.
create function guard_prescription_notice_ready() returns trigger
    language plpgsql
    set search_path = pg_catalog, public, pg_temp
as $$
begin
    if new.status in ('approved', 'issued')
       and old.status is distinct from new.status
       and exists (select 1 from public.prescription_findings pf where pf.prescription_id = new.id)
       and not exists (
           select 1 from public.prescription_findings pf
           where pf.prescription_id = new.id and pf.included
       ) then
        raise exception 'в предписании % нет ни одного нарушения — согласовывать и отправлять нечего', new.id
            using errcode = 'check_violation';
    end if;
    return new;
end;
$$;

create trigger prescriptions_notice_ready
    before update on prescriptions
    for each row execute function guard_prescription_notice_ready();
