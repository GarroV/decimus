-- 0089_prescription_notice.sql
--
-- Сборка предписания из проверки (шаг 3 спеки 2026-10-21-osb-prescriptions-design,
-- D601, D602, D606, D607): вид предписания, нарушения из проверки-основания,
-- версии шаблона документа.
--
-- ЧТО ЗДЕСЬ
--
-- * `mail_templates` — версии шаблонов писем и документов по виду и языку. Версия
--   только добавляется: прежняя не правится и не удаляется, предписание помнит, по
--   какой версии собрано (`prescriptions.template_version_id`). Шаблон может
--   содержать реальные реквизиты франчайзора — читает его только пространство УК.
-- * `prescriptions.kind` — inspection / ratings / other. Выданные и закрытые до
--   миграции остаются как есть: `inspection`, если у них есть основания, иначе `other`.
-- * `prescriptions.template_version_id` — версия шаблона, по которой собран документ.
--   Пусто у предписаний с текстом, вписанным руками (до миграции и «прочее»).
-- * `prescription_findings` — строки таблицы нарушений документа: запись проверки-
--   основания, объект, формулировка пункта и описание КАК ЛЕГЛИ в документ, срок,
--   порядок, включена ли. Снимок, а не ссылка на живой текст: документ, который
--   согласовали, не должен поменяться от правки справочника.
--
-- ЗАЩИТА (как 0037/0087): строки нарушений правятся только у неотправленного
-- предписания, с подписью (`decimus.prescription_actor`); правка согласованного снимает
-- согласование; отправленное не правится. Запись должна принадлежать проверке-основанию
-- этого же предписания (составной внешний ключ). Предписание с шаблоном не
-- согласуется и не отправляется без единой включённой записи.
--
-- Раннер оборачивает файл в одну транзакцию сам.

-- ── Версии шаблонов ─────────────────────────────────────────────────────────

create table mail_templates (
    id uuid primary key default gen_random_uuid(),
    kind text not null check (kind in ('inspection_letter', 'prescription_inspection',
                                        'prescription_ratings', 'prescription_other',
                                        'action_plan')),
    lang text not null check (lang ~ '^[a-z]{2}$'),
    version integer not null check (version >= 1),
    body text not null check (length(btrim(body)) between 1 and 100000),
    created_by text not null check (length(btrim(created_by)) > 0),
    created_at timestamptz not null default now(),
    unique (kind, lang, version)
);

create function guard_mail_template() returns trigger
    language plpgsql
    set search_path = pg_catalog, public, pg_temp
as $$
begin
    raise exception 'версия шаблона письма не правится и не удаляется: добавьте новую версию'
        using errcode = 'check_violation';
end;
$$;

create trigger mail_templates_frozen
    before update or delete on mail_templates
    for each row execute function guard_mail_template();

comment on table mail_templates is
    'Версии шаблонов писем и документов (D601, D608): вид, язык, версия, текст, кто и когда. Версия только добавляется.';

grant select on mail_templates to dodo_audit_app;
grant select, insert on mail_templates to dodo_audit_admin;

alter table mail_templates enable row level security;
alter table mail_templates force row level security;
create policy mail_templates_app_read on mail_templates
    for select to dodo_audit_app
    using (decimus_space() in ('*', 'HQ'));
create policy mail_templates_admin on mail_templates
    for all to dodo_audit_admin
    using (true) with check (true);

-- ── Предписание: вид и версия шаблона ───────────────────────────────────────

alter table prescriptions
    add column kind text not null default 'other'
        check (kind in ('inspection', 'ratings', 'other')),
    add column template_version_id uuid references mail_templates (id);

-- Прежние предписания: вид по наличию оснований. Триггеры на время отключены:
-- отправленное не правится даже мигратором, а это не правка содержимого.
alter table prescriptions disable trigger prescriptions_guarded;
alter table prescriptions disable trigger prescriptions_logged;
update prescriptions p set kind = 'inspection'
where exists (select 1 from prescription_inspections pi where pi.prescription_id = p.id);
alter table prescriptions enable trigger prescriptions_guarded;
alter table prescriptions enable trigger prescriptions_logged;

comment on column prescriptions.kind is
    'Вид предписания: по проверке, по рейтингам, прочее (D601). Не меняется.';
comment on column prescriptions.template_version_id is
    'Версия шаблона документа, по которой собрано предписание. Пусто — текст вписан руками. Не меняется.';

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
    шаблон uuid;
begin
    perform public.lock_prescription(чья);
    select p.status, p.template_version_id into статус, шаблон
    from public.prescriptions p where p.id = чья;
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
    if tg_op = 'INSERT' then
        if шаблон is null then
            raise exception 'у предписания % нет шаблона — нарушения в нём не ведутся', чья
                using errcode = 'check_violation';
        end if;
        if not exists (
            select 1 from public.findings f
            where f.id = new.finding_id and f.inspection_id = new.inspection_id
        ) then
            raise exception 'запись % не из проверки %', new.finding_id, new.inspection_id
                using errcode = 'check_violation';
        end if;
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

-- Предписание с шаблоном не согласуется и не отправляется без единой записи.
create function guard_prescription_notice_ready() returns trigger
    language plpgsql
    set search_path = pg_catalog, public, pg_temp
as $$
begin
    if new.template_version_id is not null and new.status in ('approved', 'issued')
       and old.status is distinct from new.status
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

-- Версия шаблона и вид ставятся при заведении предписания и дальше не правятся:
-- права на их обновление администратор не получает (0037, 0087).

create function guard_prescription_template() returns trigger
    language plpgsql
    set search_path = pg_catalog, public, pg_temp
as $$
begin
    if new.template_version_id is not null and not exists (
        select 1 from public.mail_templates t
        where t.id = new.template_version_id
          and t.kind = case new.kind when 'inspection' then 'prescription_inspection'
                                     when 'ratings' then 'prescription_ratings'
                                     else 'prescription_other' end
    ) then
        raise exception 'версия шаблона не от того вида предписания: %', new.kind
            using errcode = 'check_violation';
    end if;
    return new;
end;
$$;

create trigger prescriptions_template_guarded
    before insert on prescriptions
    for each row execute function guard_prescription_template();
