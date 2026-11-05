-- 0119_walk_log.sql
--
-- Журнал шагов обхода (D710): что аудитор ввёл и что ответила система на каждом шаге
-- записи нарушения в мини-аппе — подбор пункта, определение класса, уточнение фактов,
-- класс вручную, сохранение, правка, снятие. Повод — проверка 05.11.2026: на шаге класса
-- система ответила «нарушение не установлено», «Сохранить» осталась неактивной, а в
-- журнале контейнера от этого не осталось ничего: восстанавливали по скриншотам.
--
-- 1. Проверки до сдачи в базе ещё нет (она появляется при слиянии), поэтому строка
--    держится за личность проверки чата `run_id` и за привязку «чат + пространство + дата
--    обхода». По ней же экран карточки находит шаги после слияния. Внешних ключей нет
--    намеренно (как у `model_usage`, `0078`): запись журнала не вправе отказать из-за
--    строки справочника, а шаг аудитора уже состоялся.
-- 2. Пишет роль приложения, и только ДОПИСЫВАЕТ (`insert`): ни `select`, ни `update`, ни
--    `delete` — задним числом не поправить, напрямую не прочитать (тот же приём, что
--    у журналов `0067`).
-- 3. Читает функция `walk_log_read(токен, проверка)`: зритель определяется по токену живой
--    сессии, видят главный админ и админ УК (как расход модели, `0078`); остальным —
--    пусто. Учётку аудитора функция подставляет сама по привязке Telegram (`bot_bindings`).
-- 4. Фото сюда не попадают — только их число. Слова аудитора и ответ классификатора
--    усечены; секретов нет: ошибка — тип исключения или код отказа, не текст.
-- 5. Хранить 180 дней: `purge_walk_log()` (роли приложения `delete` не выдан, чистит
--    функция владельца; зовёт та же периодическая уборка, что у журналов, `0067`).
--
-- Раннер оборачивает файл в одну транзакцию сам.

create table walk_log (
    id bigint generated always as identity primary key,
    occurred_at timestamptz not null default now(),
    -- Личность проверки чата (`Inspection.run_id`): пусто у проверки, начатой до D392.
    run_id text check (run_id is null or char_length(run_id) <= 80),
    chat_id bigint not null,
    tenant_code text not null default '',
    -- Пиццерия так, как её видел обход («Brasov-1»), и дата обхода: по ним и по чату
    -- карточка находит шаги после слияния проверки в базу.
    unit_label text not null default '' check (char_length(unit_label) <= 120),
    visit_date date,
    step text not null
        check (step in ('suggest', 'class', 'class_facts', 'class_manual', 'save', 'edit',
                        'remove', 'other')),
    -- ok — шаг прошёл; refused — система отказала (занято, проверка сдана, не принято);
    -- error — сбой (модель недоступна, исключение).
    outcome text not null check (outcome in ('ok', 'refused', 'error')),
    -- Слова аудитора и число кадров (сами кадры не пишутся).
    words text not null default '' check (char_length(words) <= 2000),
    photos integer not null default 0 check (photos >= 0),
    -- Что ответила система.
    item_code text check (item_code is null or char_length(item_code) <= 60),
    zone text check (zone is null or char_length(zone) <= 60),
    level text check (level is null or char_length(level) <= 20),
    -- Вердикт классификатора: ready / needs_fact / not_established / manual; у подбора пусто.
    verdict text check (verdict is null or char_length(verdict) <= 30),
    reason text not null default '' check (char_length(reason) <= 1500),
    -- Каким путём найден пункт (быстрый, выученная фраза, модель) или `fallback` — модель
    -- недоступна и аудитор выбирает вручную.
    via text check (via is null or char_length(via) <= 40),
    -- Остальное по шагу: предложенные пункты, вопрос о факте, текст записи, число уточнений.
    detail jsonb not null default '{}'::jsonb,
    duration_ms integer check (duration_ms is null or duration_ms >= 0),
    -- Код отказа или тип исключения; без текста и секретов.
    error text not null default '' check (char_length(error) <= 300)
);

create index walk_log_time_idx on walk_log (occurred_at);
create index walk_log_chat_visit_idx on walk_log (chat_id, tenant_code, visit_date, occurred_at);

comment on table walk_log is
    'Журнал шагов обхода (D710): одна строка на шаг записи нарушения в мини-аппе. Роль '
    'приложения только дописывает; читает функция walk_log_read (главный админ и админ УК), '
    'срок хранения 180 дней (purge_walk_log).';

grant insert on walk_log to dodo_audit_app;
grant usage on sequence walk_log_id_seq to dodo_audit_app;

-- Шаги обхода проверки из базы: те, что записаны за её чат, пространство и дату обхода.
-- Зритель — по токену живой сессии; не главный админ и не админ УК — пусто.
create function walk_log_read(p_token text, p_inspection uuid)
returns table (
    id bigint, occurred_at timestamptz, run_id text, unit_label text, step text,
    outcome text, words text, photos integer, item_code text, zone text, level text,
    verdict text, reason text, via text, detail jsonb, duration_ms integer, error text,
    login text
)
language plpgsql stable security definer set search_path = pg_catalog, public, pg_temp as $$
declare
    роль text;
    пространство text;
begin
    select u.role, u.tenant_code into роль, пространство
      from public.web_sessions s
      join public.web_users u on u.id = s.user_id
     where s.fingerprint = encode(sha256(convert_to(p_token, 'UTF8')), 'hex')
       and s.closed_at is null
       and s.expires_at > now()
       and u.disabled_at is null;
    if роль is null or not (роль = 'superadmin' or (роль = 'admin' and пространство = 'HQ')) then
        return;
    end if;
    return query
        select w.id, w.occurred_at, w.run_id, w.unit_label, w.step, w.outcome, w.words,
               w.photos, w.item_code, w.zone, w.level, w.verdict, w.reason, w.via, w.detail,
               w.duration_ms, w.error, bound.login
          from public.inspections i
          join public.walk_log w
            on w.chat_id = i.chat_id
           and w.tenant_code = i.tenant_code
           and w.visit_date = i.inspection_date
          left join lateral (
              select u.login
                from public.bot_bindings bb
                join public.web_users u on u.id = bb.user_id
               where bb.telegram_id = w.chat_id
               order by (bb.unbound_at is null) desc, bb.bound_at desc
               limit 1
          ) bound on true
         where i.id = p_inspection
         order by w.occurred_at, w.id
         limit 3000;
end $$;

revoke all on function walk_log_read(text, uuid) from public;
grant execute on function walk_log_read(text, uuid) to dodo_audit_app;

create function purge_walk_log() returns integer
language plpgsql security definer set search_path = pg_catalog, public, pg_temp as $$
declare
    убрано integer;
begin
    delete from public.walk_log where occurred_at < now() - interval '180 days';
    get diagnostics убрано = row_count;
    return убрано;
end $$;

revoke all on function purge_walk_log() from public;
grant execute on function purge_walk_log() to dodo_audit_app;

comment on function purge_walk_log() is
    'Срок хранения журнала шагов обхода (D710): 180 дней. Зовёт периодическая уборка бота '
    '(src/bot/upload_sweeper.py).';
