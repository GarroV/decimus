-- 0054_oauth.sql
--
-- Подключение Claude к decimus входом через сайт (D417): OAuth 2.1 с PKCE.
-- claude.ai в браузере, Desktop и телефон подключаются к MCP только так — им
-- нужен сервер авторизации, а не токен из бота. Сервер авторизации — веб-админка
-- (`src/web/oauth.py`), проверка токена — сервер MCP (`src/mcp/config.py`),
-- общее хранилище — `src/db/oauth_store.py`.
--
-- Четыре таблицы:
--   oauth_clients — клиенты, заведённые динамической регистрацией (RFC 7591).
--                   Секретов у них нет: клиент публичный, держит его PKCE.
--   oauth_codes   — коды авторизации: одноразовые, 10 минут, привязаны к
--                   клиенту, адресу возврата и `code_challenge`.
--   oauth_grants  — подключение «учётка × клиент». Его и видит человек на
--                   своей карточке, его и отзывает; токены живут, пока живо оно.
--   oauth_tokens  — access и refresh. Значения нет — только SHA-256, как у
--                   сессий (`0014`) и личных токенов MCP (`0011`).
--
-- Права роли — НЕ здесь: учётка, роль и пространство читаются из `web_users` на
-- каждом запросе, поэтому отключение учётки и смена роли действуют сразу.
--
-- Раннер оборачивает файл в одну транзакцию сам.

create table oauth_clients (
    id bigserial primary key,
    -- Публичный идентификатор клиента (`client_id`). Не секрет: Claude
    -- передаёт его в адресной строке.
    client_id text not null unique check (client_id ~ '^[A-Za-z0-9_-]{16,64}$'),
    client_name text not null check (char_length(client_name) between 1 and 200),
    -- Разрешённые адреса возврата. Какие вообще допустимы, решает продукт
    -- (`oauth_store.redirect_uri_allowed`), схема держит только «не пусто».
    redirect_uris text[] not null check (cardinality(redirect_uris) between 1 and 10),
    -- Адрес, с которого клиента завели: предел регистраций считается по нему
    -- (`src/web/oauth.py`), иначе один перебирающий выбрал бы общий предел за всех.
    registered_from text not null check (char_length(registered_from) between 1 and 100),
    created_at timestamptz not null default now()
);
create index oauth_clients_from_idx on oauth_clients (registered_from, created_at);
comment on table oauth_clients is
    'OAuth-клиенты, заведённые динамической регистрацией (D417). Секретов нет: '
    'клиент публичный, обмен кода держит PKCE.';

create table oauth_grants (
    id uuid primary key default gen_random_uuid(),
    user_id uuid not null references web_users (id),
    client_id bigint not null references oauth_clients (id),
    created_at timestamptz not null default now(),
    -- Когда Claude последний раз ходил в MCP этим подключением. Пишет сервер
    -- MCP, не чаще раза в минуту на подключение.
    last_used_at timestamptz,
    -- Отзыв — пометка со следом, строка остаётся. Причина: `user` — человек
    -- нажал «Отключить», `reuse` — предъявлен уже обменянный refresh или код,
    -- `password` — пароль учётки сменён (с экрана или командой), `email` —
    -- сменена почта входа через Google.
    revoked_at timestamptz,
    revoked_reason text check (revoked_reason in ('user', 'reuse', 'password', 'email'))
);
alter table oauth_grants add constraint oauth_grants_revocation_is_named
    check ((revoked_at is null) = (revoked_reason is null));
create index oauth_grants_user_idx on oauth_grants (user_id);
-- Чистка ищет клиентов без подключений и без кодов (`oauth_purge`).
create index oauth_grants_client_idx on oauth_grants (client_id);
comment on table oauth_grants is
    'Подключения Claude (D417): учётка сайта × OAuth-клиент. Отзыв гасит все '
    'токены подключения на следующем же вызове.';

create table oauth_codes (
    id bigserial primary key,
    fingerprint text not null unique check (fingerprint ~ '^[0-9a-f]{64}$'),
    client_id bigint not null references oauth_clients (id),
    user_id uuid not null references web_users (id),
    redirect_uri text not null,
    -- PKCE S256: base64url(SHA-256(verifier)) без выравнивания — 43 знака.
    code_challenge text not null check (code_challenge ~ '^[A-Za-z0-9_-]{43}$'),
    scope text not null,
    -- Ресурс (RFC 8707), к которому выдан код, — адрес MCP. Без `resource` в
    -- запросе сервер подставляет свой адрес MCP: пустого здесь не бывает.
    resource text not null check (char_length(resource) between 1 and 500),
    expires_at timestamptz not null,
    used_at timestamptz,
    -- Подключение, выпущенное этим кодом: повтор кода отзывает его (RFC 6749 §4.1.2).
    grant_id uuid references oauth_grants (id)
);
alter table oauth_codes add constraint oauth_codes_use_is_complete
    check ((used_at is null) = (grant_id is null));
comment on table oauth_codes is
    'Коды авторизации OAuth (D417): только отпечаток SHA-256, одноразовые, 10 минут.';

create table oauth_tokens (
    id bigserial primary key,
    grant_id uuid not null references oauth_grants (id),
    kind text not null check (kind in ('access', 'refresh')),
    fingerprint text not null unique check (fingerprint ~ '^[0-9a-f]{64}$'),
    -- Ресурс, для которого выдан токен (RFC 8707): наследуется от кода, затем
    -- от refresh. Сервер MCP принимает только токен своего адреса.
    resource text not null check (char_length(resource) between 1 and 500),
    issued_at timestamptz not null default now(),
    expires_at timestamptz not null,
    -- Refresh, уже обменянный на новую пару. Повторное его предъявление — знак
    -- кражи, и отзывается всё подключение.
    used_at timestamptz
);
create index oauth_tokens_grant_idx on oauth_tokens (grant_id);
create index oauth_tokens_expires_idx on oauth_tokens (expires_at);
create index oauth_codes_expires_idx on oauth_codes (expires_at);
create index oauth_codes_client_idx on oauth_codes (client_id);
-- Смена пароля гасит невыменянные коды человека (`change_own_password` ниже).
create index oauth_codes_user_idx on oauth_codes (user_id);
comment on table oauth_tokens is
    'Access- и refresh-токены OAuth (D417): только отпечаток SHA-256. Живы, пока '
    'не истекли и живо подключение (oauth_grants.revoked_at is null).';

-- Чистка (`oauth_store.purge_stale`). Регистрация открыта без входа, и клиенты,
-- заведённые перебором, коды и истёкшие токены копились бы бесконечно. Права
-- DELETE у приложения нет: удаляет только эта функция и только отжившее —
-- коды и токены, истёкшие больше суток назад, и клиентов старше суток без
-- единого подключения и без кода. Сутки запаса держат обнаружение повтора:
-- обменянный refresh удаляется не раньше, чем истёк бы сам.
create function oauth_purge()
    returns integer
    language plpgsql
    security definer
    set search_path = pg_catalog, public, pg_temp
as $$
declare
    коды integer;
    токены integer;
    клиенты integer;
begin
    delete from public.oauth_codes where expires_at < now() - interval '1 day';
    get diagnostics коды = row_count;
    delete from public.oauth_tokens where expires_at < now() - interval '1 day';
    get diagnostics токены = row_count;
    delete from public.oauth_clients c
     where c.created_at < now() - interval '1 day'
       and not exists (select 1 from public.oauth_grants g where g.client_id = c.id)
       and not exists (select 1 from public.oauth_codes k where k.client_id = c.id);
    get diagnostics клиенты = row_count;
    return коды + токены + клиенты;
end;
$$;

comment on function oauth_purge() is
    'Чистка OAuth (D417): коды и токены, истёкшие больше суток назад; клиенты старше суток '
    'без подключений и кодов. Права DELETE у приложения нет — только эта функция.';

revoke all on function oauth_purge() from public;
grant execute on function oauth_purge() to dodo_audit_app;

-- Роль приложения: под ней ходят и веб (выдача), и сервер MCP (сверка и отметка
-- последнего вызова). Удаления напрямую нет, правка — только пометок.
grant select, insert on oauth_clients to dodo_audit_app;
grant usage on sequence oauth_clients_id_seq to dodo_audit_app;
grant select, insert on oauth_grants to dodo_audit_app;
grant update (last_used_at, revoked_at, revoked_reason) on oauth_grants to dodo_audit_app;
grant select, insert on oauth_codes to dodo_audit_app;
grant update (used_at, grant_id) on oauth_codes to dodo_audit_app;
grant usage on sequence oauth_codes_id_seq to dodo_audit_app;
grant select, insert on oauth_tokens to dodo_audit_app;
grant update (used_at) on oauth_tokens to dodo_audit_app;
grant usage on sequence oauth_tokens_id_seq to dodo_audit_app;

-- Роль администратора истории: посмотреть, кто и чем подключён, и отозвать
-- подключения учётки, чей пароль она меняет командой (`web_access.change_password`).
grant select on oauth_clients, oauth_grants, oauth_codes, oauth_tokens to dodo_audit_admin;
grant update (revoked_at, revoked_reason) on oauth_grants to dodo_audit_admin;
grant update (expires_at) on oauth_codes to dodo_audit_admin;

-- Смена пароля отзывает и подключения Claude. Пароль меняют в ответ на «его
-- кто-то узнал»; вошедший по старому паролю мог успеть разрешить Claude доступ,
-- и подключение пережило бы смену, как пережила бы её незакрытая сессия.
-- Гаснут и ещё не обменянные коды (срок — сейчас): иначе код, выданный до
-- смены, обменялся бы после неё на новое подключение.
--
-- ПОРЯДОК ВАЖЕН: сперва коды, потом подключения. Обмен кода держит строку кода
-- (`for update`) до конца своей транзакции; гашение кодов ждёт его, и только
-- после — отзыв подключений, который новым снимком видит и подключение,
-- только что выпущенное этим обменом. В обратном порядке оно бы уцелело.
-- Ротация refresh держит строку подключения (`for update of t, g`), отзыв её
-- же: кто второй, тот видит итог первого.
-- Смена с экрана идёт функцией `change_own_password` (`0032`, путь поиска —
-- `0033`); тело то же, добавлен отзыв в той же транзакции. Смена командой —
-- `web_access.change_password`, отзывает сама.
create or replace function change_own_password(p_token text, p_old_hash text, p_new_hash text)
    returns boolean
    language plpgsql
    security definer
    set search_path = pg_catalog, public, pg_temp
as $$
declare
    отпечаток text := encode(sha256(convert_to(p_token, 'UTF8')), 'hex');
    чей uuid;
begin
    select u.id into чей
      from public.web_sessions s
      join public.web_users u on u.id = s.user_id
     where s.fingerprint = отпечаток
       and s.closed_at is null
       and s.expires_at > now()
       and u.disabled_at is null
       and u.password_hash = p_old_hash;
    if чей is null then
        return false;
    end if;

    update public.web_users set password_hash = p_new_hash where id = чей;

    update public.web_sessions
       set closed_at = now()
     where user_id = чей
       and closed_at is null
       and fingerprint <> отпечаток;

    update public.oauth_codes
       set expires_at = now()
     where user_id = чей
       and used_at is null
       and expires_at > now();

    update public.oauth_grants
       set revoked_at = now(), revoked_reason = 'password'
     where user_id = чей
       and revoked_at is null;
    return true;
end;
$$;

comment on function change_own_password(text, text, text) is
    'Смена СВОЕГО пароля с экрана (#324): строку выбирает живая сессия, чей токен предъявлен; '
    'прежний хеш обязан быть на месте; остальные сессии человека закрываются, своя — нет, '
    'подключения Claude отзываются (0054). '
    'Сужает поверхность (у приложения нет прямой записи хеша), но от пробитого приложения '
    'не защищает: оно читает хеши и открывает сессии само (0033).';
