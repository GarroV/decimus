-- 0031_bot_bindings.sql
--
-- D286: бот привязывается через веб. Человек входит в своё пространство, жмёт
-- «привязать бота», получает одноразовую ссылку t.me/<бот>?start=link-<токен>, и
-- бот связывает его Telegram ID с учёткой — а значит, с её пространством.
--
-- Приёмы те же, что у сессий (0014) и токенов MCP (0011): в базе отпечаток
-- SHA-256, а не токен; погашение и отвязка односторонние и держатся сужающими
-- политиками, а не кодом.
--
-- Пишет и читает роль приложения: ссылку выпускает веб, гасит и опознаёт бот —
-- оба ходят ролью приложения. Удалять строки не может никто: след привязок —
-- ответ на вопрос «кто и когда ходил ботом от этой учётки».

create table bot_link_tokens (
    fingerprint text primary key check (fingerprint ~ '^[0-9a-f]{64}$'),
    user_id uuid not null references web_users (id),
    issued_at timestamptz not null default now(),
    expires_at timestamptz not null,
    used_at timestamptz,
    used_by bigint
);

create index bot_link_tokens_user_idx on bot_link_tokens (user_id) where used_at is null;

create table bot_bindings (
    id uuid primary key default gen_random_uuid(),
    telegram_id bigint not null,
    user_id uuid not null references web_users (id),
    bound_at timestamptz not null default now(),
    unbound_at timestamptz
);

-- Одна живая привязка на Telegram ID и одна на учётку (D291: новая привязка
-- заменяет прежнюю, чужой Telegram к учётке не привязывается).
create unique index bot_bindings_live_telegram_uq on bot_bindings (telegram_id)
    where unbound_at is null;
create unique index bot_bindings_live_user_uq on bot_bindings (user_id)
    where unbound_at is null;

grant select, insert on bot_link_tokens to dodo_audit_app;
grant update (used_at, used_by) on bot_link_tokens to dodo_audit_app;
grant select, insert on bot_bindings to dodo_audit_app;
grant update (unbound_at) on bot_bindings to dodo_audit_app;

alter table bot_link_tokens enable row level security;
alter table bot_link_tokens force row level security;
create policy bot_link_tokens_access on bot_link_tokens
    for all using (true) with check (true);
-- Погашение одностороннее: погашенную ссылку не воскресить.
create policy bot_link_tokens_used_once on bot_link_tokens as restrictive
    for update using (used_at is null) with check (used_at is not null);

alter table bot_bindings enable row level security;
alter table bot_bindings force row level security;
create policy bot_bindings_access on bot_bindings
    for all using (true) with check (true);
-- Отвязка односторонняя: снятую привязку не вернуть правкой строки.
create policy bot_bindings_unbound_once on bot_bindings as restrictive
    for update using (unbound_at is null) with check (unbound_at is not null);

comment on table bot_link_tokens is
    'Одноразовые ссылки привязки бота (D286). Хранится отпечаток; ссылка живёт LINK_TTL.';
comment on table bot_bindings is
    'Привязки Telegram ID к учётке (D286). Отвязка — пометкой; живая — одна на ID и одна на учётку.';
