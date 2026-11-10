-- 0129_calendar_deadline.sql
--
-- D740, D741 (#1590): срок отчёта по проверке УК — событием в Google Календаре проверяющего.
--
-- `calendar_grants` — доступ человека к СВОЕМУ календарю: один ключ на учётку. Ключ продления
-- лежит зашифрованным (`src/db/secret_crypto.py`, AES-256-GCM; имя записи `calendar:<user_id>`
-- в связанных данных, ключ шифрования — только в окружении). Это отступление от правила
-- черновиков Gmail, где ключ не хранится (D741: ради автоматики, по решению владельца).
-- Отключение стирает строку целиком; ключ у Google отзывается до этого.
--
-- `calendar_events` — что сейчас стоит в календаре по проверке: номер события, дата и название.
-- По расхождению этой строки с проверкой (перенос даты или пиццерии, снятие) фоновая задача
-- бота (`src/bot/calendar_loader.py`) двигает или удаляет событие. Строки удаляются вместе с
-- событием; сама проверка не трогается.
--
-- Раннер оборачивает файл в одну транзакцию сам — begin/commit здесь не нужны.

create table calendar_grants (
    user_id uuid primary key references web_users (id),
    google_email text not null check (length(btrim(google_email)) > 0),
    scope text not null check (length(btrim(scope)) > 0),
    refresh_ciphertext bytea not null,
    connected_at timestamptz not null default now(),
    -- Последний сбой Google: код причины (`invalid_grant`, `calendar_api_disabled`…), не текст
    -- ответа. Пусто — всё в порядке. Экран говорит человеку «переподключите».
    problem text check (problem is null or problem ~ '^[a-z0-9_]{1,64}$'),
    problem_at timestamptz,
    check ((problem is null) = (problem_at is null))
);

comment on table calendar_grants is
    'Доступ человека к своему Google Календарю (D741). Ключ продления — зашифрованный; '
    'отключение стирает строку.';
comment on column calendar_grants.refresh_ciphertext is
    'nonce || шифртекст ключа продления (secret_crypto, AAD = calendar:<user_id>).';
comment on column calendar_grants.problem is
    'Код последнего сбоя Google; пусто — доступ работает.';

create table calendar_events (
    inspection_id uuid primary key references inspections (id),
    user_id uuid not null references web_users (id),
    event_id text not null check (length(btrim(event_id)) > 0),
    due_date date not null,
    title text not null check (length(btrim(title)) > 0),
    synced_at timestamptz not null default now()
);

create index calendar_events_by_user on calendar_events (user_id);

comment on table calendar_events is
    'Событие срока отчёта, как оно стоит в календаре проверяющего (D740): по расхождению с '
    'проверкой задача бота сдвигает, переименовывает или удаляет событие.';

alter table calendar_grants enable row level security;
alter table calendar_grants force row level security;
create policy calendar_grants_app_access on calendar_grants
    for all to dodo_audit_app using (true) with check (true);

alter table calendar_events enable row level security;
alter table calendar_events force row level security;
create policy calendar_events_app_access on calendar_events
    for all to dodo_audit_app using (true) with check (true);

grant select, insert, update, delete on calendar_grants, calendar_events to dodo_audit_app;
