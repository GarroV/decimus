-- 0070 — ключ модели, который главный админ вставляет на экране «Подключения» (D491).
--
-- Раньше ключ жил только в окружении процессов (`OPENAI_API_KEY`), и сменить его значило
-- править `.env` на площадке. Теперь ключ можно вставить на экране: он лежит ЗАШИФРОВАННЫМ
-- (AES-GCM, ключ шифрования — переменная окружения `SECRETS_KEY`, в базу не попадает),
-- от него на виду только последние четыре знака. Открытого значения в базе нет нигде.
--
-- Читает роль приложения (бот, веб и обход расшифровывают ключ у себя), пишет и удаляет
-- роль администратора истории — та же, что выдаёт ключи API (`api_access._managing`):
-- получив базу продукта, чужой не подменит ключ модели.
--
-- Раннер оборачивает файл в одну транзакцию сам.

create schema vault;
grant usage on schema vault to dodo_audit_app, dodo_audit_admin;

create table vault.secrets (
    -- Что за секрет: пока только `model_key`.
    name text primary key check (name in ('model_key')),
    provider text not null check (provider <> ''),
    -- nonce (12 байт) || шифртекст с тегом подлинности AES-GCM.
    ciphertext bytea not null check (octet_length(ciphertext) > 28),
    last4 text not null check (char_length(last4) between 1 and 4),
    set_by text not null check (set_by <> ''),
    set_at timestamptz not null default now()
);
comment on table vault.secrets is
    'Секреты, вставленные с экрана (D491): шифртекст AES-GCM, ключ шифрования — SECRETS_KEY '
    'вне базы. Читает роль приложения, пишет администратор истории.';

grant select on vault.secrets to dodo_audit_app;
grant select, insert, update, delete on vault.secrets to dodo_audit_admin;
