-- 0037_prescriptions.sql
--
-- Предписания, волна 3 спеки «Страна, предписания и экшн-планы» (D266, D268–D270,
-- D275). Предписание — официальное письмо УК партнёру страны: сотрудник УК
-- вставляет текст сам, письмо ложится черновиком в его Gmail, отправляет он сам.
-- Копия текста и адресатов остаётся здесь.
--
-- ЖИЗНЕННЫЙ ЦИКЛ
--
--   draft ──(черновик лёг в Gmail сотрудника)──► issued ──(УК закрыл, комментарий)──► closed
--
-- «Просрочено» не хранится, а считается (`src/db/prescriptions.py`).
--
-- ОТПРАВЛЕННОЕ НЕ ПРАВИТСЯ. У `issued` меняется только переход в `closed`, у
-- `closed` — ничего; пиццерии и проверки-основания правятся только у черновика.
-- Исправление — закрытие с комментарием и новое предписание (спека).
--
-- КТО ЧТО ПИШЕТ. Предписание, его связи и закрытие — только администратор
-- истории (роль, которой веб делает действия УК). Роль приложения (партнёр в
-- вебе, бот) может ровно одно: положить ответ в действующее предписание своей
-- страны. Урок #490: защищена и ВСТАВКА — предписание ложится только
-- черновиком у ЛЮБОЙ роли, а `issued` и `closed` достижимы лишь переходом.
--
-- ЧЬЯ СТРАНА. Страна — поле самого предписания: оно адресовано стране. Партнёр —
-- по `space_countries` (D284: одна страна — один партнёр), копии тенанта нет.
-- Пиццерии и точки проверок-оснований сверяются по ТЕКУЩЕЙ стране на отправке:
-- проверку перенесли в точку другой страны (D195) или отклонили — отправка
-- отказывает, а не уносит партнёру чужое.
--
-- ИСТОРИЯ. `prescription_events` пишут только триггеры (security definer,
-- search_path как в 0033); прямой записи не выдано никому. Правка черновика
-- подписывается настройкой транзакции `decimus.prescription_actor` (как
-- `decimus.plan_actor`, 0036): без подписи — отказ.
--
-- АДРЕСАТЫ СТРАНЫ (D275). На отправке триггер запоминает адресатов для страны
-- в `country_recipients` — следующее предписание стране их подставит.
--
-- Раннер оборачивает файл в одну транзакцию сам — begin/commit здесь не нужны.

create table prescriptions (
    id uuid primary key default gen_random_uuid(),
    country text not null check (country ~ '^[A-Z]{2}$'),
    due_on date not null,
    -- Адреса через запятую, как их вписал сотрудник; на отправке не пусто.
    recipients text not null default '' check (length(recipients) <= 2000),
    subject text not null check (length(btrim(subject)) between 1 and 300),
    body text not null check (length(btrim(body)) between 1 and 20000),
    status text not null default 'draft' check (status in ('draft', 'issued', 'closed')),
    created_by text not null check (length(btrim(created_by)) > 0),
    created_at timestamptz not null default now(),
    issued_by text,
    issued_at timestamptz,
    closed_by text,
    closed_at timestamptz,
    close_comment text,
    -- Поля шага заполнены ровно тогда, когда шаг пройден.
    check (
        (status = 'draft' and issued_by is null and issued_at is null
            and closed_by is null and closed_at is null and close_comment is null)
        or (status = 'issued' and length(btrim(coalesce(issued_by, ''))) > 0
            and issued_at is not null
            and closed_by is null and closed_at is null and close_comment is null)
        or (status = 'closed' and length(btrim(coalesce(issued_by, ''))) > 0
            and issued_at is not null
            and length(btrim(coalesce(closed_by, ''))) > 0 and closed_at is not null
            and length(btrim(coalesce(close_comment, ''))) > 0)
    )
);

-- Очередь УК (`prescriptions._OPEN_SQL`): закрытые копятся годами, открытых —
-- единицы. Частичный индекс держит открытые в порядке срока.
create index prescriptions_open_idx on prescriptions (due_on, created_at)
    where status <> 'closed';
create index prescriptions_country_idx on prescriptions (country, created_at);

-- Пиццерии предписания. Пусто — вся страна.
create table prescription_units (
    prescription_id uuid not null references prescriptions (id),
    unit_id uuid not null references units (id),
    primary key (prescription_id, unit_id)
);

-- Проверки-основания.
create table prescription_inspections (
    prescription_id uuid not null references prescriptions (id),
    inspection_id uuid not null references inspections (id),
    primary key (prescription_id, inspection_id)
);

-- Ответ партнёра: комментарий обязателен, файл — по желанию.
create table prescription_replies (
    id uuid primary key,
    prescription_id uuid not null references prescriptions (id),
    comment text not null check (length(btrim(comment)) between 1 and 4000),
    storage_path text check (storage_path is null or length(btrim(storage_path)) > 0),
    file_name text check (file_name is null or length(btrim(file_name)) between 1 and 255),
    size_bytes bigint check (size_bytes is null or size_bytes > 0),
    content_type text check (content_type is null or length(btrim(content_type)) > 0),
    replied_by text not null check (length(btrim(replied_by)) > 0),
    replied_tenant text not null references tenants (code),
    replied_at timestamptz not null default now(),
    -- Файл — целиком или никак.
    check (
        (storage_path is null and file_name is null and size_bytes is null and content_type is null)
        or (storage_path is not null and file_name is not null and size_bytes is not null
            and content_type is not null)
    )
);

create index prescription_replies_prescription_idx on prescription_replies (prescription_id, replied_at);

create table prescription_events (
    id bigint generated always as identity primary key,
    prescription_id uuid not null references prescriptions (id),
    action text not null check (action in ('created', 'edited', 'issued', 'replied', 'closed')),
    actor text not null check (length(btrim(actor)) > 0),
    detail text,
    at timestamptz not null default now()
);

create index prescription_events_prescription_idx on prescription_events (prescription_id, at);

-- Адресаты страны (D275) — первое поле профиля страны (#463).
create table country_recipients (
    country text primary key check (country ~ '^[A-Z]{2}$'),
    recipients text not null check (length(btrim(recipients)) between 1 and 2000),
    updated_by text not null check (length(btrim(updated_by)) > 0),
    updated_at timestamptz not null default now()
);

comment on table prescriptions is
    'Предписания УК партнёру страны (D266, D270). draft → issued (черновик лёг в Gmail) → closed (с комментарием). Отправленное не правится; просрочка считается.';
comment on table prescription_units is 'Пиццерии предписания; пусто — вся страна.';
comment on table prescription_inspections is 'Проверки-основания предписания.';
comment on table prescription_replies is
    'Ответы партнёра на действующее предписание: комментарий и, по желанию, файл (D268, D269).';
comment on table prescription_events is
    'История предписания: кто, что, когда. Пишут только триггеры 0037.';
comment on table country_recipients is
    'Адресаты предписаний страны, запомненные на последней отправке (D275).';

-- ── Переходы предписания ────────────────────────────────────────────────────

create function guard_prescription() returns trigger
    language plpgsql
    set search_path = pg_catalog, public, pg_temp
as $$
declare
    чужая text;
begin
    if tg_op = 'INSERT' then
        if new.status <> 'draft' or new.issued_by is not null or new.issued_at is not null
           or new.closed_by is not null or new.closed_at is not null
           or new.close_comment is not null then
            raise exception 'предписание заводится только черновиком, а не %', new.status
                using errcode = 'insufficient_privilege';
        end if;
        if not exists (
            select 1 from public.units u where u.tenant_code = 'HQ' and u.country = new.country
        ) then
            raise exception 'в справочнике нет пиццерий страны % — предписание некому адресовать', new.country
                using errcode = 'check_violation';
        end if;
        return new;
    end if;

    if new.id is distinct from old.id or new.country is distinct from old.country
       or new.created_by is distinct from old.created_by
       or new.created_at is distinct from old.created_at then
        raise exception 'страна и авторство предписания % не меняются', old.id
            using errcode = 'check_violation';
    end if;
    if old.status = 'closed' then
        raise exception 'закрытое предписание % не меняется', old.id
            using errcode = 'check_violation';
    end if;

    if old.status = 'issued' then
        if new.status <> 'closed'
           or new.subject is distinct from old.subject or new.body is distinct from old.body
           or new.recipients is distinct from old.recipients
           or new.due_on is distinct from old.due_on
           or new.issued_by is distinct from old.issued_by
           or new.issued_at is distinct from old.issued_at then
            raise exception 'отправленное предписание % не правится: закройте его и составьте новое', old.id
                using errcode = 'check_violation';
        end if;
        if length(btrim(coalesce(new.close_comment, ''))) = 0
           or length(btrim(coalesce(new.closed_by, ''))) = 0 then
            raise exception 'предписание % закрывают с подписью и комментарием', old.id
                using errcode = 'check_violation';
        end if;
        new.closed_at := now();
        return new;
    end if;

    -- old.status = 'draft'
    if new.status = 'closed' then
        raise exception 'черновик % не закрывают: он ещё не отправлен', old.id
            using errcode = 'check_violation';
    end if;
    if new.closed_by is not null or new.close_comment is not null then
        raise exception 'у черновика % нет закрытия', old.id
            using errcode = 'check_violation';
    end if;

    if new.status = 'draft' then
        if new.issued_by is not null then
            raise exception 'у черновика % нет отправителя', old.id
                using errcode = 'check_violation';
        end if;
        if btrim(coalesce(current_setting('decimus.prescription_actor', true), '')) = '' then
            raise exception 'черновик % правят с подписью (decimus.prescription_actor)', old.id
                using errcode = 'check_violation';
        end if;
        return new;
    end if;

    -- draft → issued: содержимое то же, что было в черновике.
    if new.subject is distinct from old.subject or new.body is distinct from old.body
       or new.recipients is distinct from old.recipients
       or new.due_on is distinct from old.due_on then
        raise exception 'предписание % отправляют тем, что лежит в черновике, без правки', old.id
            using errcode = 'check_violation';
    end if;
    if length(btrim(coalesce(new.issued_by, ''))) = 0 then
        raise exception 'отправка предписания % подписывается', old.id
            using errcode = 'check_violation';
    end if;
    if length(btrim(new.recipients)) = 0 then
        raise exception 'у предписания % нет адресатов', old.id
            using errcode = 'check_violation';
    end if;
    if new.due_on < current_date then
        raise exception 'срок предписания % уже прошёл', old.id
            using errcode = 'check_violation';
    end if;
    select u.name into чужая
    from public.prescription_units pu
    join public.units u on u.id = pu.unit_id
    where pu.prescription_id = old.id and u.country is distinct from old.country
    limit 1;
    if чужая is not null then
        raise exception 'пиццерия % уже не в стране %', чужая, old.country
            using errcode = 'check_violation';
    end if;
    if exists (
        select 1
        from public.prescription_inspections pi
        join public.inspections i on i.id = pi.inspection_id
        join public.units u on u.id = i.unit_id
        where pi.prescription_id = old.id
          and (i.tenant_code <> 'HQ' or i.status <> 'finalized' or i.retracted_at is not null
               or u.country is distinct from old.country)
    ) then
        raise exception 'проверка-основание предписания % отклонена или уже не в стране %', old.id, old.country
            using errcode = 'check_violation';
    end if;
    new.issued_at := now();
    return new;
end;
$$;

create trigger prescriptions_guarded
    before insert or update on prescriptions
    for each row execute function guard_prescription();

-- ── Связи: только у черновика ───────────────────────────────────────────────

create function guard_prescription_unit() returns trigger
    language plpgsql
    set search_path = pg_catalog, public, pg_temp
as $$
declare
    чья uuid := case when tg_op = 'DELETE' then old.prescription_id else new.prescription_id end;
    статус text;
    страна text;
begin
    select p.status, p.country into статус, страна from public.prescriptions p where p.id = чья;
    if статус is distinct from 'draft' then
        raise exception 'пиццерии меняют только у черновика (сейчас %)', coalesce(статус, 'нет предписания')
            using errcode = 'check_violation';
    end if;
    if tg_op = 'DELETE' then
        return old;
    end if;
    if not exists (
        select 1 from public.units u
        where u.id = new.unit_id and u.tenant_code = 'HQ' and u.country = страна
    ) then
        raise exception 'пиццерия % не из страны %', new.unit_id, страна
            using errcode = 'check_violation';
    end if;
    return new;
end;
$$;

create trigger prescription_units_guarded
    before insert or delete on prescription_units
    for each row execute function guard_prescription_unit();

create function guard_prescription_inspection() returns trigger
    language plpgsql
    set search_path = pg_catalog, public, pg_temp
as $$
declare
    чья uuid := case when tg_op = 'DELETE' then old.prescription_id else new.prescription_id end;
    статус text;
    страна text;
begin
    select p.status, p.country into статус, страна from public.prescriptions p where p.id = чья;
    if статус is distinct from 'draft' then
        raise exception 'основания меняют только у черновика (сейчас %)', coalesce(статус, 'нет предписания')
            using errcode = 'check_violation';
    end if;
    if tg_op = 'DELETE' then
        return old;
    end if;
    if not exists (
        select 1
        from public.inspections i
        join public.units u on u.id = i.unit_id
        where i.id = new.inspection_id and i.tenant_code = 'HQ' and i.status = 'finalized'
          and i.retracted_at is null and u.country = страна
    ) then
        raise exception 'основанием служит принятая и не отклонённая проверка УК страны %', страна
            using errcode = 'check_violation';
    end if;
    return new;
end;
$$;

create trigger prescription_inspections_guarded
    before insert or delete on prescription_inspections
    for each row execute function guard_prescription_inspection();

-- ── Ответ партнёра ──────────────────────────────────────────────────────────

create function guard_prescription_reply() returns trigger
    language plpgsql
    set search_path = pg_catalog, public, pg_temp
as $$
declare
    статус text;
    страна text;
begin
    select p.status, p.country into статус, страна
    from public.prescriptions p where p.id = new.prescription_id;
    if статус is distinct from 'issued' then
        raise exception 'отвечают только на действующее предписание (сейчас %)', coalesce(статус, 'нет предписания')
            using errcode = 'check_violation';
    end if;
    if not exists (
        select 1 from public.space_countries s
        where s.tenant_code = new.replied_tenant and s.country = страна
    ) then
        raise exception 'пространство % не отвечает за страну % — отвечает её партнёр', new.replied_tenant, страна
            using errcode = 'insufficient_privilege';
    end if;
    return new;
end;
$$;

create trigger prescription_replies_guarded
    before insert on prescription_replies
    for each row execute function guard_prescription_reply();

-- ── История и адресаты страны ───────────────────────────────────────────────

create function log_prescription() returns trigger
    language plpgsql
    security definer
    set search_path = pg_catalog, public, pg_temp
as $$
begin
    if tg_op = 'INSERT' then
        insert into public.prescription_events (prescription_id, action, actor, detail)
        values (new.id, 'created', new.created_by, new.country || ' ' || new.due_on::text);
    elsif new.status = 'issued' and old.status = 'draft' then
        insert into public.prescription_events (prescription_id, action, actor, detail)
        values (new.id, 'issued', new.issued_by, new.recipients);
        insert into public.country_recipients (country, recipients, updated_by)
        values (new.country, new.recipients, new.issued_by)
        on conflict (country) do update
            set recipients = excluded.recipients,
                updated_by = excluded.updated_by,
                updated_at = now();
    elsif new.status = 'closed' and old.status = 'issued' then
        insert into public.prescription_events (prescription_id, action, actor, detail)
        values (new.id, 'closed', new.closed_by, new.close_comment);
    else
        insert into public.prescription_events (prescription_id, action, actor, detail)
        values (new.id, 'edited',
                btrim(current_setting('decimus.prescription_actor', true)), null);
    end if;
    return null;
end;
$$;

create function log_prescription_reply() returns trigger
    language plpgsql
    security definer
    set search_path = pg_catalog, public, pg_temp
as $$
begin
    insert into public.prescription_events (prescription_id, action, actor, detail)
    values (new.prescription_id, 'replied', new.replied_by, new.file_name);
    return null;
end;
$$;

revoke all on function log_prescription() from public;
revoke all on function log_prescription_reply() from public;

create trigger prescriptions_logged
    after insert or update on prescriptions
    for each row execute function log_prescription();
create trigger prescription_replies_logged
    after insert on prescription_replies
    for each row execute function log_prescription_reply();

-- ── Права ───────────────────────────────────────────────────────────────────

grant select on prescriptions, prescription_units, prescription_inspections,
    prescription_replies, prescription_events, country_recipients
    to dodo_audit_app, dodo_audit_admin;

-- Партнёр (роль приложения): только ответ.
grant insert on prescription_replies to dodo_audit_app;

-- УК (администратор истории): черновик, его связи, отправка и закрытие.
grant insert on prescriptions to dodo_audit_admin;
grant update (subject, body, recipients, due_on, status, issued_by, closed_by, close_comment)
    on prescriptions to dodo_audit_admin;
grant insert, delete on prescription_units, prescription_inspections to dodo_audit_admin;

alter table prescriptions enable row level security;
alter table prescriptions force row level security;
create policy prescriptions_access on prescriptions
    for all using (true) with check (true);

alter table prescription_units enable row level security;
alter table prescription_units force row level security;
create policy prescription_units_access on prescription_units
    for all using (true) with check (true);

alter table prescription_inspections enable row level security;
alter table prescription_inspections force row level security;
create policy prescription_inspections_access on prescription_inspections
    for all using (true) with check (true);

alter table prescription_replies enable row level security;
alter table prescription_replies force row level security;
create policy prescription_replies_access on prescription_replies
    for all using (true) with check (true);

alter table prescription_events enable row level security;
alter table prescription_events force row level security;
create policy prescription_events_access on prescription_events
    for all using (true) with check (true);

alter table country_recipients enable row level security;
alter table country_recipients force row level security;
create policy country_recipients_access on country_recipients
    for all using (true) with check (true);
