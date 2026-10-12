-- 0049_api_tokens.sql
--
-- Сервисные токены внешнего API и журнал обращений (D356, D388, #568).
-- Первый потребитель — API чтения для Swarm (`/api/v1/*`, #567, D387). До этой
-- миграции токен лежал в окружении веба открытым текстом (`SWARM_API_TOKEN`):
-- один на всех, без прав, без отзыва и без следа, кто и когда им ходил.
--
-- Значение токена здесь не хранится — только SHA-256 (64 знака hex), как у
-- личных токенов MCP (`0011`). Права — список строк из закрытого перечня;
-- маршрут API пускает только токен с нужным правом. Отзыв — пометка со следом,
-- строка остаётся.
--
-- Журнал — каждое обращение к API, включая отказы (токен неизвестен — пустой
-- `token_id`). По нему же считается лимит частоты на токен, поэтому индекс
-- (token_id, at). Старые строки удаляет попутно сам веб (`src/db/api_access.py`).
--
-- Раннер оборачивает файл в одну транзакцию сам.

create schema api;
grant usage on schema api to dodo_audit_app, dodo_audit_admin;

create table api.tokens (
    id bigserial primary key,
    -- Кто ходит этим токеном: `swarm` и т. п. Не учётка и не человек.
    consumer text not null check (consumer ~ '^[a-z][a-z0-9_-]{1,39}$'),
    fingerprint text not null unique check (fingerprint ~ '^[0-9a-f]{64}$'),
    scopes text[] not null
        check (cardinality(scopes) > 0 and scopes <@ array['ratings:read', 'inspections:read']),
    issued_at timestamptz not null default now(),
    -- Кто выпустил: имя из окружения того, кто запускал команду выдачи.
    issued_by text not null check (issued_by <> ''),
    revoked_at timestamptz,
    revoked_by text
);
alter table api.tokens add constraint tokens_revocation_is_named
    check ((revoked_at is null) = (revoked_by is null));
comment on table api.tokens is
    'Сервисные токены внешнего API (D356, D388): только отпечаток SHA-256, права, '
    'отзыв пометкой. Выдача и отзыв — tools/api_token.py.';

create table api.access_log (
    id bigserial primary key,
    token_id bigint references api.tokens (id),
    at timestamptz not null default now(),
    path text not null,
    status smallint not null check (status between 100 and 599),
    client text
);
create index access_log_token_at_idx on api.access_log (token_id, at);
create index access_log_at_idx on api.access_log (at);
comment on table api.access_log is
    'Журнал обращений к внешнему API (D356): и пропущенные, и отказы. '
    'По нему считается лимит частоты на токен.';

-- Роль приложения: сверить токен и вести журнал. Выпускать и отзывать токены
-- она не может — получив базу продукта, чужой не выдаст себе доступ.
grant select on api.tokens to dodo_audit_app;
grant select, insert, delete on api.access_log to dodo_audit_app;
grant usage on sequence api.access_log_id_seq to dodo_audit_app;

-- Роль администратора истории (та же, что заводит учётки): выдача и отзыв.
grant select, insert on api.tokens to dodo_audit_admin;
grant update (revoked_at, revoked_by) on api.tokens to dodo_audit_admin;
grant usage on sequence api.tokens_id_seq to dodo_audit_admin;
grant select on api.access_log to dodo_audit_admin;
