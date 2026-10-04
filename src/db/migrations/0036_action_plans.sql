-- 0036_action_plans.sql
--
-- Экшн-планы, волна 2 спеки «Страна, предписания и экшн-планы» (D263–D265,
-- D267–D269, D272, D274). Партнёр отвечает на проверку УК файлом плана; УК
-- принимает план или возвращает с комментарием.
--
-- ЖИЗНЕННЫЙ ЦИКЛ ЗАПРОСА
--
--   requested ──(партнёр загрузил версию)──► on_review ──(УК принял)──► accepted
--       ▲                                         │
--       └──────────(УК вернул, комментарий)───────┘
--
-- «Просрочен» не хранится, а считается (`src/db/action_plans.py`).
--
-- КТО ЧТО ПИШЕТ. Партнёр ходит ролью приложения и может ровно одно: положить
-- новую версию файла и перевести запрос из `requested` в `on_review`. Завести
-- запрос, поправить срок, принять и вернуть — только администратор истории
-- (роль, которой веб делает действия УК). Урок #490: защищена и ВСТАВКА, а не
-- только правка — запрос ложится в базу только `requested` у ЛЮБОЙ роли, а
-- `accepted` достижим лишь переходом из `on_review`, при котором у последней
-- версии уже лежит вердикт «принят», а вердикт вставляет только администратор.
-- Бот (та же роль приложения) поэтому не может положить «принятый» план мимо
-- УК ни вставкой, ни правкой.
--
-- ИСТОРИЯ. `action_plan_events` пишут только триггеры (security definer,
-- search_path как в 0033); прямой записи не выдано никому. Действие нельзя
-- совершить, не оставив следа, и след нельзя дописать задним числом.
--
-- ЧЬЯ СТРАНА. Копии страны в запросе нет: страна — у точки проверки
-- (`inspections.unit_id → units.country`, D284: одна страна — один партнёр).
-- Перенесли проверку в точку другой страны (D195) — запрос уехал вместе с ней,
-- и охват чтения (`reach.py`) и триггер загрузки читают одно и то же. Загрузить
-- версию может только пространство, за которым страна точки закреплена
-- (`space_countries`), — это держит триггер, а не только запрос веба.
--
-- ПО КАКОЙ ПРОВЕРКЕ. Запрос заводится только по принятой и не отклонённой
-- проверке УК, у точки которой есть страна, — держит триггер вставки (урок
-- #490: не только Python). Отклонённая проверка запрос не снимает, но
-- загрузить версию к ней нельзя, и из очереди он уходит (`action_plans.py`).
--
-- СРОК С ПОДПИСЬЮ. Кто назначил срок, пишет триггер из `decimus.plan_actor`
-- (настройка транзакции, как `decimus.move_actor` у переноса, 0025): правка
-- срока без подписи — отказ, а подпись без правки срока не переписывается.
--
-- Раннер оборачивает файл в одну транзакцию сам — begin/commit здесь не нужны.

create table action_plan_requests (
    id uuid primary key default gen_random_uuid(),
    -- Один запрос на проверку: автозапрос при подтверждении и кнопка УК не
    -- заводят двух.
    inspection_id uuid not null unique references inspections (id),
    due_on date not null,
    status text not null default 'requested'
        check (status in ('requested', 'on_review', 'accepted')),
    -- auto — появился сам при подтверждении проверки с D2/D3 (D272);
    -- manual — кнопкой УК.
    origin text not null check (origin in ('auto', 'manual')),
    requested_by text not null check (length(btrim(requested_by)) > 0),
    requested_at timestamptz not null default now(),
    -- Кто последним назначил срок: при заведении — тот, кто запросил; дальше
    -- пишет триггер из подписи транзакции.
    due_set_by text not null check (length(btrim(due_set_by)) > 0)
);

-- Очередь УК (`action_plans._OPEN_SQL`): открытых — единицы, принятые копятся
-- годами. Частичный индекс держит открытые в порядке выдачи и не растёт вместе
-- с историей.
create index action_plan_requests_open_idx on action_plan_requests (due_on, requested_at)
    where status <> 'accepted';

create table action_plan_files (
    id uuid primary key,
    request_id uuid not null references action_plan_requests (id),
    version integer not null check (version > 0),
    storage_path text not null check (length(btrim(storage_path)) > 0),
    file_name text not null check (length(btrim(file_name)) between 1 and 255),
    size_bytes bigint not null check (size_bytes > 0),
    content_type text not null check (length(btrim(content_type)) > 0),
    uploaded_by text not null check (length(btrim(uploaded_by)) > 0),
    uploaded_tenant text not null references tenants (code),
    uploaded_at timestamptz not null default now(),
    unique (request_id, version)
);

create table action_plan_reviews (
    id uuid primary key default gen_random_uuid(),
    -- Вердикт один на версию: вернули — партнёр кладёт новую.
    file_id uuid not null unique references action_plan_files (id),
    verdict text not null check (verdict in ('accepted', 'returned')),
    comment text,
    reviewed_by text not null check (length(btrim(reviewed_by)) > 0),
    reviewed_at timestamptz not null default now(),
    -- Возврат без комментария партнёру ничего не говорит (спека).
    check (verdict = 'accepted' or length(btrim(coalesce(comment, ''))) > 0)
);

create table action_plan_events (
    id bigint generated always as identity primary key,
    request_id uuid not null references action_plan_requests (id),
    action text not null
        check (action in ('requested', 'due_changed', 'uploaded', 'accepted', 'returned')),
    actor text not null check (length(btrim(actor)) > 0),
    detail text,
    at timestamptz not null default now()
);

create index action_plan_events_request_idx on action_plan_events (request_id, at);

comment on table action_plan_requests is
    'Запросы экшн-плана по проверке (D272, D274). Статус: requested → on_review → accepted; возврат — on_review → requested. Просрочка считается, не хранится.';
comment on table action_plan_files is
    'Версии файла экшн-плана (D265, D267). Каждая загрузка — новая версия, старые не стираются.';
comment on table action_plan_reviews is
    'Вердикт УК по версии плана: принят или возвращён с комментарием.';
comment on table action_plan_events is
    'История действий по запросу экшн-плана: кто, что, когда. Пишут только триггеры 0036.';

-- ── Переходы запроса ────────────────────────────────────────────────────────

create function guard_action_plan_request() returns trigger
    language plpgsql
    set search_path = pg_catalog, public, pg_temp
as $$
declare
    последняя uuid;
    вердикт text;
    автор text;
    чья text;
    стадия text;
    отклонена timestamptz;
    страна text;
begin
    if tg_op = 'INSERT' then
        if new.status <> 'requested' then
            raise exception 'запрос экшн-плана заводится только запрошенным, а не %', new.status
                using errcode = 'insufficient_privilege';
        end if;
        select i.tenant_code, i.status, i.retracted_at, u.country
          into чья, стадия, отклонена, страна
        from public.inspections i
        join public.units u on u.id = i.unit_id
        where i.id = new.inspection_id;
        if чья is distinct from 'HQ' then
            raise exception 'экшн-план запрашивают по проверке УК, а проверка % не её', new.inspection_id
                using errcode = 'check_violation';
        end if;
        if стадия is distinct from 'finalized' or отклонена is not null then
            raise exception 'экшн-план запрашивают по принятой и не отклонённой проверке'
                using errcode = 'check_violation';
        end if;
        if страна is null then
            raise exception 'у точки проверки % нет страны — запрос некому показать', new.inspection_id
                using errcode = 'check_violation';
        end if;
        new.due_set_by := new.requested_by;
        return new;
    end if;

    if old.status = 'accepted' then
        raise exception 'принятый экшн-план % не меняется', old.id
            using errcode = 'check_violation';
    end if;
    if new.due_on is not distinct from old.due_on then
        if new.due_set_by is distinct from old.due_set_by then
            raise exception 'кто назначил срок, не меняется без правки срока'
                using errcode = 'check_violation';
        end if;
    else
        автор := btrim(coalesce(current_setting('decimus.plan_actor', true), ''));
        if автор = '' then
            raise exception 'срок запроса % правят с подписью (decimus.plan_actor)', old.id
                using errcode = 'check_violation';
        end if;
        new.due_set_by := автор;
    end if;
    if new.status = old.status then
        return new;
    end if;

    select f.id into последняя
    from public.action_plan_files f
    where f.request_id = old.id
    order by f.version desc
    limit 1;
    select r.verdict into вердикт from public.action_plan_reviews r where r.file_id = последняя;

    if old.status = 'requested' and new.status = 'on_review' then
        if последняя is null or вердикт is not null then
            raise exception 'на приёмку запрос % уходит только с новой версией файла', old.id
                using errcode = 'check_violation';
        end if;
        return new;
    end if;

    if old.status = 'on_review' and new.status in ('accepted', 'requested') then
        if not pg_has_role(current_user, 'dodo_audit_admin', 'member') then
            raise exception 'принять или вернуть экшн-план % может только УК', old.id
                using errcode = 'insufficient_privilege';
        end if;
        if вердикт is distinct from (case new.status when 'accepted' then 'accepted' else 'returned' end) then
            raise exception 'у последней версии запроса % нет вердикта под этот переход', old.id
                using errcode = 'check_violation';
        end if;
        return new;
    end if;

    raise exception 'переход запроса % из % в % не предусмотрен', old.id, old.status, new.status
        using errcode = 'check_violation';
end;
$$;

create trigger action_plan_requests_guarded
    before insert or update on action_plan_requests
    for each row execute function guard_action_plan_request();

-- ── Загрузка версии ─────────────────────────────────────────────────────────

create function guard_action_plan_file() returns trigger
    language plpgsql
    set search_path = pg_catalog, public, pg_temp
as $$
declare
    статус text;
    страна text;
    отклонена timestamptz;
    следующая integer;
begin
    -- Страна — у точки проверки, а не копией в запросе. Отклонённую проверку
    -- роль приложения не видит вовсе (0010): строки нет — отказ.
    select r.status, u.country, i.retracted_at into статус, страна, отклонена
    from public.action_plan_requests r
    join public.inspections i on i.id = r.inspection_id
    join public.units u on u.id = i.unit_id
    where r.id = new.request_id;
    if статус is distinct from 'requested' then
        raise exception 'версию плана кладут только в запрошенный запрос (сейчас %)', coalesce(статус, 'нет запроса')
            using errcode = 'check_violation';
    end if;
    if отклонена is not null then
        raise exception 'проверка отклонена — план к ней не кладут'
            using errcode = 'check_violation';
    end if;
    if not exists (
        select 1 from public.space_countries s
        where s.tenant_code = new.uploaded_tenant and s.country = страна
    ) then
        raise exception 'пространство % не отвечает за страну % — план кладёт её партнёр', new.uploaded_tenant, страна
            using errcode = 'insufficient_privilege';
    end if;
    select coalesce(max(f.version), 0) + 1 into следующая
    from public.action_plan_files f
    where f.request_id = new.request_id;
    if new.version <> следующая then
        raise exception 'версия % не следующая (ожидалась %)', new.version, следующая
            using errcode = 'check_violation';
    end if;
    return new;
end;
$$;

create trigger action_plan_files_guarded
    before insert on action_plan_files
    for each row execute function guard_action_plan_file();

-- ── Вердикт ─────────────────────────────────────────────────────────────────

create function guard_action_plan_review() returns trigger
    language plpgsql
    set search_path = pg_catalog, public, pg_temp
as $$
declare
    запрос uuid;
    статус text;
    последняя uuid;
begin
    select f.request_id into запрос from public.action_plan_files f where f.id = new.file_id;
    select r.status into статус from public.action_plan_requests r where r.id = запрос;
    if статус is distinct from 'on_review' then
        raise exception 'вердикт выносят только плану на приёмке (сейчас %)', coalesce(статус, 'нет запроса')
            using errcode = 'check_violation';
    end if;
    select f.id into последняя
    from public.action_plan_files f
    where f.request_id = запрос
    order by f.version desc
    limit 1;
    if последняя is distinct from new.file_id then
        raise exception 'вердикт выносят последней версии плана'
            using errcode = 'check_violation';
    end if;
    return new;
end;
$$;

create trigger action_plan_reviews_guarded
    before insert on action_plan_reviews
    for each row execute function guard_action_plan_review();

-- ── История ─────────────────────────────────────────────────────────────────

create function log_action_plan_request() returns trigger
    language plpgsql
    security definer
    set search_path = pg_catalog, public, pg_temp
as $$
begin
    if tg_op = 'INSERT' then
        insert into public.action_plan_events (request_id, action, actor, detail)
        values (new.id, 'requested', new.requested_by, new.origin || ' ' || new.due_on::text);
    elsif new.due_on is distinct from old.due_on then
        insert into public.action_plan_events (request_id, action, actor, detail)
        values (new.id, 'due_changed', new.due_set_by, old.due_on::text || ' ' || new.due_on::text);
    end if;
    return null;
end;
$$;

create function log_action_plan_file() returns trigger
    language plpgsql
    security definer
    set search_path = pg_catalog, public, pg_temp
as $$
begin
    insert into public.action_plan_events (request_id, action, actor, detail)
    values (new.request_id, 'uploaded', new.uploaded_by, new.version::text);
    return null;
end;
$$;

create function log_action_plan_review() returns trigger
    language plpgsql
    security definer
    set search_path = pg_catalog, public, pg_temp
as $$
begin
    insert into public.action_plan_events (request_id, action, actor, detail)
    select f.request_id, new.verdict, new.reviewed_by, new.comment
    from public.action_plan_files f
    where f.id = new.file_id;
    return null;
end;
$$;

revoke all on function log_action_plan_request() from public;
revoke all on function log_action_plan_file() from public;
revoke all on function log_action_plan_review() from public;

create trigger action_plan_requests_logged
    after insert or update of due_on on action_plan_requests
    for each row execute function log_action_plan_request();
create trigger action_plan_files_logged
    after insert on action_plan_files
    for each row execute function log_action_plan_file();
create trigger action_plan_reviews_logged
    after insert on action_plan_reviews
    for each row execute function log_action_plan_review();

-- ── Права ───────────────────────────────────────────────────────────────────

grant select on action_plan_requests, action_plan_files, action_plan_reviews, action_plan_events
    to dodo_audit_app, dodo_audit_admin;

-- Партнёр (роль приложения): только загрузка версии и перевод на приёмку.
grant insert on action_plan_files to dodo_audit_app;
grant update (status) on action_plan_requests to dodo_audit_app;

-- УК (администратор истории): запрос, срок, вердикт.
grant insert on action_plan_requests to dodo_audit_admin;
grant update (status, due_on) on action_plan_requests to dodo_audit_admin;
grant insert on action_plan_reviews to dodo_audit_admin;

alter table action_plan_requests enable row level security;
alter table action_plan_requests force row level security;
create policy action_plan_requests_access on action_plan_requests
    for all using (true) with check (true);

alter table action_plan_files enable row level security;
alter table action_plan_files force row level security;
create policy action_plan_files_access on action_plan_files
    for all using (true) with check (true);

alter table action_plan_reviews enable row level security;
alter table action_plan_reviews force row level security;
create policy action_plan_reviews_access on action_plan_reviews
    for all using (true) with check (true);

alter table action_plan_events enable row level security;
alter table action_plan_events force row level security;
create policy action_plan_events_access on action_plan_events
    for all using (true) with check (true);
