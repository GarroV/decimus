-- 0067_journals.sql
--
-- Два журнала на случай взлома учётки (D462, шаг 2): «кто и откуда входил» и «что
-- делали админы». Сообщений в Telegram здесь нет — это отдельный шаг, ему нужно «да»
-- владельца.
--
-- 1. `web_sessions.ip` и `web_sessions.user_agent` — откуда открыта сессия. Адрес
--    приходит от приложения по цепочке доверенных звеньев (`src/web/remote.py`), а
--    не из сырого `X-Forwarded-For`; браузер усечён до 200 знаков.
-- 2. `login_journal` — каждая попытка входа и её исход: учётка (пусто, если логин
--    неизвестен), время, адрес, браузер, способ, результат и номер сессии, если она
--    выдана. Хранить 180 дней.
-- 3. `action_journal` — каждое изменяющее действие админа и главного админа: кто (учётка
--    и роль на тот момент), чем (сессия / токен), откуда, что (код действия и сводка
--    цели без секретов) и чем кончилось. Хранить 365 дней.
-- 4. Права. Роль приложения только ДОПИСЫВАЕТ (`insert`): ни `update`, ни `delete`, ни
--    `select`. Правки задним числом нет, прочитать таблицу напрямую нельзя — читать
--    можно только функциями ниже, и кому чьи записи видны, решает ЭТА схема, а не
--    экран: человек видит свои записи входов, главный админ — все; журнал действий
--    видит только главный админ. Зритель определяется по токену живой сессии (тот же
--    приём, что `sign_out_everywhere`, `0063`), а не по параметру, который назвал вызов.
-- 5. `purge_journals()` — удаление записей старше срока хранения; роли приложения
--    `delete` не выдан, поэтому чистит функция владельца.
--
-- Раннер оборачивает файл в одну транзакцию сам.

alter table web_sessions add column ip text;
alter table web_sessions add column user_agent text
    check (user_agent is null or char_length(user_agent) <= 200);

comment on column web_sessions.ip is
    'Адрес клиента при входе (D462): по цепочке доверенных звеньев, null — не определён.';
comment on column web_sessions.user_agent is
    'Браузер при входе (D462), усечён до 200 знаков.';

create table login_journal (
    id bigint generated always as identity primary key,
    occurred_at timestamptz not null default now(),
    -- Учётка, в которую пытались войти; null — логин неизвестен.
    user_id uuid references web_users (id),
    ip text,
    user_agent text check (user_agent is null or char_length(user_agent) <= 200),
    method text not null
        check (method in ('password', 'google', 'oauth-claude', 'personal-mcp-token', 'bot-link')),
    -- `refused` — сверка пароля прошла, но учётке этот способ закрыт (привязана почта Google).
    result text not null
        check (result in ('ok', 'bad-password', 'frozen', 'unknown', 'rate-limited', 'refused')),
    session_id uuid references web_sessions (id)
);

create index login_journal_time_idx on login_journal (occurred_at desc);
create index login_journal_user_time_idx on login_journal (user_id, occurred_at desc);

comment on table login_journal is
    'Журнал входов (D462): каждая попытка и исход. Роль приложения только дописывает; '
    'читать — функцией login_journal_read, срок хранения 180 дней (purge_journals).';

create table action_journal (
    id bigint generated always as identity primary key,
    occurred_at timestamptz not null default now(),
    user_id uuid not null references web_users (id),
    -- Роль и пространство на момент действия: роль потом сменится, запись нет.
    role text not null,
    tenant_code text not null,
    door text not null check (door in ('web', 'mcp', 'bot')),
    -- Чем вошёл: номер сессии, отпечаток-метка токена или подключения Claude.
    credential text check (credential is null or char_length(credential) <= 80),
    ip text,
    -- Имя маршрута веба или инструмента MCP; читаемую подпись даёт экран.
    action text not null check (char_length(action) <= 120),
    -- Сводка цели: номера и коды из адреса и формы, без паролей, токенов и свободного текста.
    target text not null default '' check (char_length(target) <= 500),
    -- Код ответа веба или `ok` / `failed` / `rejected` у MCP.
    outcome text not null check (char_length(outcome) <= 40)
);

create index action_journal_time_idx on action_journal (occurred_at desc);
create index action_journal_user_time_idx on action_journal (user_id, occurred_at desc);

comment on table action_journal is
    'Журнал действий админов (D462): одна строка на изменяющий запрос веба или вызов '
    'инструмента MCP. Роль приложения только дописывает; читает только главный админ '
    '(action_journal_read), срок хранения 365 дней (purge_journals).';

grant insert on login_journal to dodo_audit_app;
grant insert on action_journal to dodo_audit_app;
grant usage on sequence login_journal_id_seq to dodo_audit_app;
grant usage on sequence action_journal_id_seq to dodo_audit_app;

-- Зритель по токену живой сессии: учётка и роль. Пусто — сессия не живая.
create function journal_viewer(p_token text, out viewer uuid, out viewer_role text)
language sql stable security definer set search_path = pg_catalog, public, pg_temp as $$
    select u.id, u.role
      from public.web_sessions s
      join public.web_users u on u.id = s.user_id
     where s.fingerprint = encode(sha256(convert_to(p_token, 'UTF8')), 'hex')
       and s.closed_at is null
       and s.expires_at > now()
       and u.disabled_at is null
$$;

revoke all on function journal_viewer(text) from public;

-- Журнал входов. Не главный админ получает ТОЛЬКО свои записи, что бы ни назвал вызов
-- в `p_user`; чужой номер даёт пустой ответ, а не отказ — по нему не узнать, чьи там записи.
create function login_journal_read(
    p_token text, p_user uuid, p_from timestamptz, p_to timestamptz, p_limit integer
) returns table (
    id bigint, occurred_at timestamptz, user_id uuid, login text, ip text,
    user_agent text, method text, result text, session_id uuid
)
language plpgsql stable security definer set search_path = pg_catalog, public, pg_temp as $$
declare
    кто uuid;
    роль text;
begin
    select v.viewer, v.viewer_role into кто, роль from public.journal_viewer(p_token) v;
    if кто is null then
        return;
    end if;
    return query
        select j.id, j.occurred_at, j.user_id, u.login, j.ip, j.user_agent, j.method,
               j.result, j.session_id
          from public.login_journal j
          left join public.web_users u on u.id = j.user_id
         where (роль = 'superadmin' or j.user_id = кто)
           and (p_user is null or j.user_id = p_user)
           and (p_from is null or j.occurred_at >= p_from)
           and (p_to is null or j.occurred_at < p_to)
         order by j.occurred_at desc, j.id desc
         limit least(greatest(coalesce(p_limit, 200), 1), 1000);
end $$;

revoke all on function login_journal_read(text, uuid, timestamptz, timestamptz, integer)
    from public;
grant execute on function login_journal_read(text, uuid, timestamptz, timestamptz, integer)
    to dodo_audit_app;

-- Журнал действий: только главный админ. Всем остальным — пусто.
create function action_journal_read(
    p_token text, p_user uuid, p_from timestamptz, p_to timestamptz, p_limit integer
) returns table (
    id bigint, occurred_at timestamptz, user_id uuid, login text, role text,
    door text, credential text, ip text, action text, target text, outcome text
)
language plpgsql stable security definer set search_path = pg_catalog, public, pg_temp as $$
declare
    кто uuid;
    роль text;
begin
    select v.viewer, v.viewer_role into кто, роль from public.journal_viewer(p_token) v;
    if кто is null or роль <> 'superadmin' then
        return;
    end if;
    return query
        select a.id, a.occurred_at, a.user_id, u.login, a.role, a.door, a.credential,
               a.ip, a.action, a.target, a.outcome
          from public.action_journal a
          join public.web_users u on u.id = a.user_id
         where (p_user is null or a.user_id = p_user)
           and (p_from is null or a.occurred_at >= p_from)
           and (p_to is null or a.occurred_at < p_to)
         order by a.occurred_at desc, a.id desc
         limit least(greatest(coalesce(p_limit, 200), 1), 1000);
end $$;

revoke all on function action_journal_read(text, uuid, timestamptz, timestamptz, integer)
    from public;
grant execute on function action_journal_read(text, uuid, timestamptz, timestamptz, integer)
    to dodo_audit_app;

-- Люди для фильтра «кто»: логины, у которых есть записи. Тот же заслон по зрителю: главный
-- админ — все, остальные — пусто (фильтра по людям у них нет, у них только свои записи).
create function journal_people(p_token text)
returns table (user_id uuid, login text)
language plpgsql stable security definer set search_path = pg_catalog, public, pg_temp as $$
declare
    роль text;
begin
    select v.viewer_role into роль from public.journal_viewer(p_token) v;
    if роль is distinct from 'superadmin' then
        return;
    end if;
    return query
        select u.id, u.login from public.web_users u
         where u.role in ('admin', 'superadmin') or exists (
             select 1 from public.login_journal j where j.user_id = u.id)
         order by u.login;
end $$;

revoke all on function journal_people(text) from public;
grant execute on function journal_people(text) to dodo_audit_app;

create function purge_journals() returns integer
language plpgsql security definer set search_path = pg_catalog, public, pg_temp as $$
declare
    входов integer;
    действий integer;
begin
    delete from public.login_journal where occurred_at < now() - interval '180 days';
    get diagnostics входов = row_count;
    delete from public.action_journal where occurred_at < now() - interval '365 days';
    get diagnostics действий = row_count;
    return входов + действий;
end $$;

revoke all on function purge_journals() from public;
grant execute on function purge_journals() to dodo_audit_app;

comment on function purge_journals() is
    'Срок хранения журналов (D462): входы 180 дней, действия 365. Зовёт периодическая '
    'уборка бота (src/bot/upload_sweeper.py).';
