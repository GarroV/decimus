-- 0096_dodois_logins.sql
--
-- Входы в Dodo IS по странам (D640, #951). Данные Dodo IS по странам берутся через вход
-- учёткой каждой страны (OAuth2, device flow). Главный админ выдаёт коллеге одноразовую
-- ссылку; коллега подтверждает вход на auth.dodois.com, и вход страны записывается.
--
-- Три вещи:
--   1. `dodois.logins` — по строке на страну: кто выдал ссылку, кто подтвердил (имя и
--      почта учётки Dodo IS), когда, права, сколько пиццерий открыто, когда продлён и
--      проверен вход, в каком он состоянии. САМИХ КЛЮЧЕЙ здесь нет.
--   2. `dodois.invites` — приглашения (ссылки): в базе только SHA-256 токена; ссылка
--      показывается один раз при выдаче. Погашается и отзывается, не удаляется.
--   3. Ключи входа (доступ и продление) — в `vault.secrets`, зашифрованными (D491), имена
--      `dodois.access.<cc>` и `dodois.refresh.<cc>` (cc — две строчные латинские буквы);
--      пара ключей приложения — `dodois.client_id` и `dodois.client_secret` (реестр
--      `src/domain/service_keys.py`). Имя по-прежнему не свободное: закрытый список плюс
--      строгий шаблон имени входа страны.
--
-- Права: читает роль приложения (бот, веб), пишет роль администратора истории (она же
-- меняет ключи сервисов): получив базу продукта, чужой не подменит чужой вход.
--
-- Раннер оборачивает файл в одну транзакцию сам.

create schema dodois;
grant usage on schema dodois to dodo_audit_app, dodo_audit_admin;

create table dodois.logins (
    country text primary key check (country ~ '^[A-Z]{2}$'),
    -- Контур: международный (`auth.dodois.com`) или СНГ (`.io`, пока не подключается).
    contour text not null default 'intl' check (contour in ('intl', 'cis')),
    -- Откуда вход: по ссылке или перенесён инструментом `tools/dodois_import.py`.
    source text not null check (source in ('invite', 'import')),
    -- Учётка decimus, выдавшая ссылку (у перенесённых — владелец, переносивший вход).
    issued_by text not null check (issued_by <> ''),
    -- Учётка Dodo IS, подтвердившая вход (`connect/userinfo`); может быть пуста.
    account_name text check (account_name is null or char_length(account_name) <= 200),
    account_email text check (account_email is null or char_length(account_email) <= 200),
    linked_at timestamptz not null default now(),
    scope text not null check (scope <> ''),
    units_total integer check (units_total >= 0),
    units_open integer check (units_open >= 0),
    refreshed_at timestamptz,
    access_expires_at timestamptz,
    checked_at timestamptz,
    state text not null check (state in ('ok', 'partial', 'expired', 'failed')),
    reason text check (reason is null or reason ~ '^[a-z_]{1,40}$')
);
comment on table dodois.logins is
    'Входы в Dodo IS по странам (D640): состояние и след, без ключей. Ключи — vault.secrets.';

create table dodois.invites (
    id bigint generated always as identity primary key,
    country text not null check (country ~ '^[A-Z]{2}$'),
    -- SHA-256 токена ссылки в hex; самого токена в базе нет.
    token_hash text not null unique check (token_hash ~ '^[0-9a-f]{64}$'),
    issued_by text not null check (issued_by <> ''),
    -- Учётка выдавшего: от её имени в журнал действий пишется погашение ссылки.
    issued_by_id uuid not null references web_users (id),
    issued_by_role text not null,
    issued_by_tenant text not null,
    issued_at timestamptz not null default now(),
    expires_at timestamptz not null,
    used_at timestamptz,
    revoked_at timestamptz,
    check (expires_at > issued_at),
    check (used_at is null or revoked_at is null)
);
create index dodois_invites_country_idx on dodois.invites (country, issued_at desc);
comment on table dodois.invites is
    'Приглашения по ссылке (D640): одноразовые, на 24 часа, привязаны к стране. В базе только '
    'хэш токена.';

grant select on dodois.logins, dodois.invites to dodo_audit_app;
grant select, insert, update on dodois.logins to dodo_audit_admin;
grant select, insert, update on dodois.invites to dodo_audit_admin;
grant usage on sequence dodois.invites_id_seq to dodo_audit_admin;

-- Имена записей `vault.secrets`: пара ключей приложения Dodo IS и ключи входа каждой страны.
alter table vault.secrets drop constraint secrets_name_check;
alter table vault.secrets add constraint secrets_name_check check (
    name in (
        'model_key', 'pointer.api_key', 'ispring.client_id', 'ispring.client_secret',
        'dodois.client_id', 'dodois.client_secret'
    )
    or name ~ '^dodois\.(access|refresh)\.[a-z]{2}$'
);
