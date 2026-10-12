-- 0051_oauth.sql
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
    created_at timestamptz not null default now()
);
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
    -- нажал «Отключить», `reuse` — предъявлен уже обменянный refresh или код.
    revoked_at timestamptz,
    revoked_reason text check (revoked_reason in ('user', 'reuse'))
);
alter table oauth_grants add constraint oauth_grants_revocation_is_named
    check ((revoked_at is null) = (revoked_reason is null));
create index oauth_grants_user_idx on oauth_grants (user_id);
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
    resource text,
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
    issued_at timestamptz not null default now(),
    expires_at timestamptz not null,
    -- Refresh, уже обменянный на новую пару. Повторное его предъявление — знак
    -- кражи, и отзывается всё подключение.
    used_at timestamptz
);
create index oauth_tokens_grant_idx on oauth_tokens (grant_id);
comment on table oauth_tokens is
    'Access- и refresh-токены OAuth (D417): только отпечаток SHA-256. Живы, пока '
    'не истекли и живо подключение (oauth_grants.revoked_at is null).';

-- Роль приложения: под ней ходят и веб (выдача), и сервер MCP (сверка и отметка
-- последнего вызова). Удаления нет вовсе, правка — только пометок.
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

-- Роль администратора истории: посмотреть, кто и чем подключён.
grant select on oauth_clients, oauth_grants, oauth_codes, oauth_tokens to dodo_audit_admin;
