-- 0062_space_isolation.sql
--
-- Изоляция пространств на уровне базы (аудит 12.10, F-037, F-005).
--
-- До этой миграции разделение пространств держалось только на условии охвата в
-- тексте каждого запроса (`src/db/reach.py`): политики роли приложения на данных
-- пространств были `using (true)`, и запрос без условия охвата отдал бы чужое.
-- Теперь вторая линия — сама база.
--
-- КАК УСТРОЕНО. Дверь (веб, бот, мини-апп, MCP, служебная работа) ставит на
-- соединение настройку `decimus.space` (`src/db/space.py`). Политики ниже —
-- ОГРАНИЧИВАЮЩИЕ (`as restrictive`) и только для роли приложения
-- (`dodo_audit_app`): они ложатся поверх уже действующих разрешающих политик,
-- ничего не открывают сами и не меняют ни администратора истории
-- (`dodo_audit_admin` — снятие, приёмка, перенос, учётки, пространства), ни
-- владельца схемы (накат `migrate`, функции `security definer` триггеров).
--
-- Значение настройки:
--   не задано  → ОШИБКА «пространство не задано», а не пустой ответ: забытая
--                дверь видна сразу, а не пустым экраном и не утечкой;
--   'HQ'       → чтение всей сети (D283), запись — только своего;
--   партнёр    → чтение своих проверок и проверок пиццерий своих стран (D289),
--                запись — только своего (D283);
--   '*'        → служебная работа без человека: всё.
--
-- Рейтинги, карты и агрегаторы (F-005) видят все (D327) — чтение открыто
-- осознанно политикой `using (true)`; запись — только УК и служебной работе
-- (загрузки ведут админы УК и контроль, сбор — бот). Неиспользуемые права на
-- запись роли приложения сняты.
--
-- Чем это НЕ является: защитой от захваченного процесса — роль приложения сама
-- может поставить себе любую настройку. Граница — от ошибки в коде.
--
-- Раннер оборачивает файл в одну транзакцию сам.

-- ── Пространство соединения ────────────────────────────────────────────────

create function decimus_space() returns text
    language plpgsql stable
    set search_path = pg_catalog
as $$
declare
    код text := btrim(coalesce(current_setting('decimus.space', true), ''));
begin
    if код = '' then
        raise exception 'decimus.space is not set: the request did not say which space it acts for'
            using errcode = 'insufficient_privilege',
                  hint = 'src/db/space.py: acting_space()';
    end if;
    return код;
end
$$;

comment on function decimus_space() is
    'Пространство, от имени которого идёт обращение (F-037). Не задано — ошибка, '
    'а не пустой ответ. Ставит дверь: src/db/space.py.';

-- Читает ли пространство обращения проверку пространства `чья` в пиццерии `точка`.
create function decimus_space_reads(чья text, точка uuid) returns boolean
    language sql stable
    set search_path = pg_catalog, public
as $$
    select case decimus_space()
        when '*' then true
        when 'HQ' then true
        else чья = decimus_space()
            or exists (
                select 1
                  from units u
                  join space_countries s on s.country = u.country
                 where u.id = точка and s.tenant_code = decimus_space()
            )
    end
$$;

-- Пишет ли пространство обращения в строку пространства `чья`: только своё (D283).
create function decimus_space_writes(чья text) returns boolean
    language sql stable
    set search_path = pg_catalog, public
as $$
    select decimus_space() = '*' or чья = decimus_space()
$$;

-- Видит ли пространство обращения то, что адресовано стране `страна` (предписания).
create function decimus_space_country(страна text) returns boolean
    language sql stable
    set search_path = pg_catalog, public
as $$
    select case decimus_space()
        when '*' then true
        when 'HQ' then true
        else exists (
            select 1 from space_countries s
             where s.tenant_code = decimus_space() and s.country = страна
        )
    end
$$;

-- Записывает ли пространство обращения в проверку `ид` (её строки-дети).
-- Исполнителем, а не владельцем: проверка сама проходит свои политики.
create function decimus_writes_inspection(ид uuid) returns boolean
    language sql stable
    set search_path = pg_catalog, public
as $$
    select exists (
        select 1 from inspections i where i.id = ид and decimus_space_writes(i.tenant_code)
    )
$$;

-- Только для УК и служебной работы: запись рейтингов, карт, агрегаторов (F-005).
create function decimus_space_is_hq() returns boolean
    language sql stable
    set search_path = pg_catalog, public
as $$
    select decimus_space() in ('HQ', '*')
$$;

-- ── Проверки ───────────────────────────────────────────────────────────────

create policy inspections_space_reads on inspections as restrictive
    for select to dodo_audit_app using (decimus_space_reads(tenant_code, unit_id));
create policy inspections_space_inserts on inspections as restrictive
    for insert to dodo_audit_app with check (decimus_space_writes(tenant_code));
create policy inspections_space_updates on inspections as restrictive
    for update to dodo_audit_app
    using (decimus_space_writes(tenant_code)) with check (decimus_space_writes(tenant_code));
create policy inspections_space_deletes on inspections as restrictive
    for delete to dodo_audit_app using (decimus_space_writes(tenant_code));

-- Строки проверки: читаются вслед за видимой проверкой (это уже держат политики
-- `*_follow_visible_inspection` из `0010`), пишутся — только в свою.

create policy findings_space_inserts on findings as restrictive
    for insert to dodo_audit_app with check (decimus_writes_inspection(inspection_id));
create policy findings_space_updates on findings as restrictive
    for update to dodo_audit_app
    using (decimus_writes_inspection(inspection_id))
    with check (decimus_writes_inspection(inspection_id));
create policy findings_space_deletes on findings as restrictive
    for delete to dodo_audit_app using (decimus_writes_inspection(inspection_id));

create policy inspection_info_space_inserts on inspection_info as restrictive
    for insert to dodo_audit_app with check (decimus_writes_inspection(inspection_id));
create policy inspection_info_space_updates on inspection_info as restrictive
    for update to dodo_audit_app
    using (decimus_writes_inspection(inspection_id))
    with check (decimus_writes_inspection(inspection_id));
create policy inspection_info_space_deletes on inspection_info as restrictive
    for delete to dodo_audit_app using (decimus_writes_inspection(inspection_id));

create policy photos_space_inserts on photos as restrictive
    for insert to dodo_audit_app with check (decimus_writes_inspection(inspection_id));
create policy photos_space_updates on photos as restrictive
    for update to dodo_audit_app
    using (decimus_writes_inspection(inspection_id))
    with check (decimus_writes_inspection(inspection_id));
create policy photos_space_deletes on photos as restrictive
    for delete to dodo_audit_app using (decimus_writes_inspection(inspection_id));

-- Переводы ссылаются на проверку или находку (как `translations_follow_visible_inspection`).
create function decimus_writes_translation(вид text, ид uuid) returns boolean
    language sql stable
    set search_path = pg_catalog, public
as $$
    select case вид
        when 'inspection' then decimus_writes_inspection(ид)
        when 'finding' then exists (
            select 1 from findings f where f.id = ид and decimus_writes_inspection(f.inspection_id)
        )
        else false
    end
$$;

create policy translations_space_inserts on translations as restrictive
    for insert to dodo_audit_app with check (decimus_writes_translation(entity_type, entity_id));
create policy translations_space_updates on translations as restrictive
    for update to dodo_audit_app
    using (decimus_writes_translation(entity_type, entity_id))
    with check (decimus_writes_translation(entity_type, entity_id));
create policy translations_space_deletes on translations as restrictive
    for delete to dodo_audit_app using (decimus_writes_translation(entity_type, entity_id));

-- Отчёт и письмо партнёру: вслед за видимой проверкой (чтение и запись).
create policy reports_space on reports as restrictive
    for all to dodo_audit_app
    using (exists (select 1 from inspections i where i.id = reports.inspection_id))
    with check (exists (select 1 from inspections i where i.id = reports.inspection_id));
create policy partner_letters_space on partner_letters as restrictive
    for all to dodo_audit_app
    using (exists (select 1 from inspections i where i.id = partner_letters.inspection_id))
    with check (exists (select 1 from inspections i where i.id = partner_letters.inspection_id));

-- История переносов: вслед за видимой проверкой. До сих пор без политик вовсе;
-- включается без `force` — пишет её триггер владельца (`0025`), а роль
-- приложения только читает.
alter table inspection_moves enable row level security;
create policy inspection_moves_access on inspection_moves for all using (true) with check (true);
create policy inspection_moves_space on inspection_moves as restrictive
    for all to dodo_audit_app
    using (exists (select 1 from inspections i where i.id = inspection_moves.inspection_id));

-- ── Экшн-планы и предписания ───────────────────────────────────────────────

-- Запрос плана — вслед за видимой проверкой; файл, вердикт и история — за запросом.
-- Партнёр загружает план к проверке УК своей пиццерии (D289), поэтому запись
-- здесь — по видимости, а не «только своё».
create policy action_plan_requests_space on action_plan_requests as restrictive
    for all to dodo_audit_app
    using (exists (select 1 from inspections i where i.id = action_plan_requests.inspection_id))
    with check (exists (select 1 from inspections i where i.id = action_plan_requests.inspection_id));
create policy action_plan_files_space on action_plan_files as restrictive
    for all to dodo_audit_app
    using (exists (select 1 from action_plan_requests r where r.id = action_plan_files.request_id))
    with check (exists (select 1 from action_plan_requests r where r.id = action_plan_files.request_id));
create policy action_plan_reviews_space on action_plan_reviews as restrictive
    for all to dodo_audit_app
    using (exists (
        select 1 from action_plan_files f where f.id = action_plan_reviews.file_id
    ));
create policy action_plan_events_space on action_plan_events as restrictive
    for all to dodo_audit_app
    using (exists (select 1 from action_plan_requests r where r.id = action_plan_events.request_id));

-- Предписание адресовано стране: видно УК и партнёру этой страны.
create policy prescriptions_space on prescriptions as restrictive
    for all to dodo_audit_app using (decimus_space_country(country));
create policy prescription_units_space on prescription_units as restrictive
    for all to dodo_audit_app
    using (exists (select 1 from prescriptions p where p.id = prescription_units.prescription_id));
create policy prescription_inspections_space on prescription_inspections as restrictive
    for all to dodo_audit_app
    using (exists (
        select 1 from prescriptions p where p.id = prescription_inspections.prescription_id
    ));
create policy prescription_replies_space on prescription_replies as restrictive
    for all to dodo_audit_app
    using (exists (select 1 from prescriptions p where p.id = prescription_replies.prescription_id))
    with check (
        exists (select 1 from prescriptions p where p.id = prescription_replies.prescription_id)
        and decimus_space_writes(replied_tenant)
    );
create policy prescription_events_space on prescription_events as restrictive
    for all to dodo_audit_app
    using (exists (select 1 from prescriptions p where p.id = prescription_events.prescription_id));
create policy country_recipients_space on country_recipients as restrictive
    for all to dodo_audit_app using (decimus_space_country(country));

-- ── Синонимы ───────────────────────────────────────────────────────────────

-- Словарь у каждого пространства свой; УК читает чужие (D283), пишет каждый своё.
create policy phrase_aliases_space_reads on phrase_aliases as restrictive
    for select to dodo_audit_app
    using (decimus_space() in ('HQ', '*') or tenant_code = decimus_space());
create policy phrase_aliases_space_inserts on phrase_aliases as restrictive
    for insert to dodo_audit_app with check (decimus_space_writes(tenant_code));

-- ── Рейтинги, карты, агрегаторы (F-005) ────────────────────────────────────

-- Права на запись, которыми роль приложения не пользуется ни в одном запросе.
revoke delete on ratings.countries, ratings.settings from dodo_audit_app;
revoke update on ratings.violations, ratings.hard_rules, ratings.import_issues from dodo_audit_app;

-- Чтение — всем осознанно (D327); запись роли приложения — только УК и служебной
-- работе. Без `force`: накат владельца схемы заводит справочные строки сам.
do $$
declare
    т record;
begin
    for т in
        select n.nspname as схема, c.relname as таблица
          from pg_class c
          join pg_namespace n on n.oid = c.relnamespace
         where c.relkind = 'r' and n.nspname in ('ratings', 'maps', 'agg')
            or (c.relkind = 'r' and n.nspname = 'public' and c.relname = 'unit_profiles')
    loop
        execute format('alter table %I.%I enable row level security', т.схема, т.таблица);
        execute format(
            'create policy %I on %I.%I for select using (true)',
            т.таблица || '_seen_by_all', т.схема, т.таблица);
        execute format(
            'create policy %I on %I.%I for insert to dodo_audit_app with check (decimus_space_is_hq())',
            т.таблица || '_hq_inserts', т.схема, т.таблица);
        execute format(
            'create policy %I on %I.%I for update to dodo_audit_app '
            'using (decimus_space_is_hq()) with check (decimus_space_is_hq())',
            т.таблица || '_hq_updates', т.схема, т.таблица);
        execute format(
            'create policy %I on %I.%I for delete to dodo_audit_app using (decimus_space_is_hq())',
            т.таблица || '_hq_deletes', т.схема, т.таблица);
    end loop;
end
$$;

-- Журнал API: пишет и чистит только служебная дверь API (`src/web/swarm_api.py`),
-- читает ещё и экран «Подключения» администратором. Ключи (`api.tokens`)
-- сверяются до того, как известно, чей запрос, — им политика не нужна.
alter table api.access_log enable row level security;
create policy access_log_admin_reads on api.access_log for select to dodo_audit_admin using (true);
create policy access_log_system on api.access_log for all to dodo_audit_app
    using (decimus_space() = '*') with check (decimus_space() = '*');
