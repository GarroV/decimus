-- 0041_api_tokens.sql
--
-- #567, #568, решение D336: токены сервисов для API чтения `/api/v1`.
--
-- ЧТО ПОЯВЛЯЕТСЯ. Таблица токенов ПОТРЕБИТЕЛЕЙ — сервисов вроде Swarm, а не
-- людей. Устроена тем же приёмом, что личные токены MCP в `0011`: хранится
-- отпечаток SHA-256, отзыв — пометка со следом, строка не удаляется.
--
-- ОТЛИЧИЕ ОТ `0011` — ПРАВА ТОКЕНА. MCP-токен открывает всё, что умеет сервер
-- MCP, в пределах пространства. Токен API открывает ровно перечисленные права
-- (`scopes`): маршрут сверяет своё право с набором токена, и токен рейтингов не
-- читает проверки. Набор допустимых прав держит схема, а не код: опечатка в
-- праве — отказ записи, а не токен, у которого молча нет нужного права.
--
-- ЗНАЧЕНИЯ ТОКЕНА ЗДЕСЬ НЕТ — ограничение схемы, как в `0011`: колонка
-- принимает только 64 знака шестнадцатеричной записи. Сырой токен
-- (`dcm_` + 43 знака `token_urlsafe`) в неё физически не запишется.
--
-- Раннер оборачивает файл в одну транзакцию сам — begin/commit здесь не нужны.

create table api_tokens (
    id uuid primary key default gen_random_uuid(),
    -- Кто пользуется: короткое имя сервиса латиницей (`swarm`). Не уникально:
    -- ротация — это новый токен того же потребителя и отзыв старого, и на время
    -- переключения живыми бывают оба.
    consumer text not null check (consumer ~ '^[a-z][a-z0-9_-]{1,39}$'),
    -- Права токена. Пустой набор не принимается: токен без прав — ошибка выпуска,
    -- а не законное состояние. Список допустимых — здесь, новое право — новая
    -- миграция вместе с маршрутом, который его спрашивает.
    scopes text[] not null check (
        cardinality(scopes) > 0
        and scopes <@ array['ratings:read', 'inspections:read']::text[]
    ),
    fingerprint text not null unique check (fingerprint ~ '^[0-9a-f]{64}$'),
    -- Кто выпустил: имя человека из команды, запустившего `tools/api_token.py`.
    issued_by text not null check (length(btrim(issued_by)) between 1 and 120),
    issued_at timestamptz not null default now(),
    revoked_at timestamptz,
    revoked_by text check (revoked_by is null or length(btrim(revoked_by)) between 1 and 120),
    -- Когда токен последний раз открыл маршрут. Отвечает на вопрос «этим ещё
    -- пользуются?» перед отзывом. Пишется не чаще раза в минуту (`src/db/api_tokens.py`).
    last_used_at timestamptz,
    constraint api_tokens_revocation_is_named
        check ((revoked_at is null) = (revoked_by is null))
);

comment on table api_tokens is
    'Токены сервисов для API чтения /api/v1 (#567, #568, D336). Хранится ОТПЕЧАТОК '
    'SHA-256; значение показывается один раз при выпуске. Права — scopes. '
    'Отзыв — пометка, строка остаётся следом.';
comment on column api_tokens.fingerprint is
    'SHA-256 токена шестнадцатеричной записью. Сырой токен в колонку не запишется.';
comment on column api_tokens.scopes is
    'Права токена: ratings:read — /api/v1/ratings/*, inspections:read — /api/v1/inspections.';

-- --- права ------------------------------------------------------------------
--
-- Роль приложения ТОЛЬКО сверяет токен и отмечает использование. Выпускать и
-- отзывать она не может вовсе: получив базу продукта или веб-процесс, токен
-- себе не выпустить. Значений колонок «кто выпустил/отозвал» ей не нужно.
grant select (id, consumer, scopes, fingerprint, revoked_at, last_used_at)
    on api_tokens to dodo_audit_app;
grant update (last_used_at) on api_tokens to dodo_audit_app;

-- Выпуск и отзыв — администратор истории (`DATABASE_RETRACTION_URL`), как
-- учётки админки (`0020`): узкая роль повышенных полномочий, а не владелец
-- схемы. Править можно ровно пометку отзыва: подмена отпечатка или прав у
-- живой строки — это выдача доступа мимо следа.
grant select, insert (consumer, scopes, fingerprint, issued_by) on api_tokens to dodo_audit_admin;
grant update (revoked_at, revoked_by) on api_tokens to dodo_audit_admin;

alter table api_tokens enable row level security;
alter table api_tokens force row level security;

-- Без `to <роль>`, как у сессий в `0014`: кого и к каким колонкам пускать,
-- решают привилегии выше, а политики говорят про переходы.
create policy api_tokens_access on api_tokens
    for all using (true) with check (true);

-- Отозванную строку не правит никто: ни снять пометку, ни подвинуть её, ни
-- отметить использование отозванным токеном. `with check (true)` обязателен:
-- без него проверка новой строки повторяет `using`, и отзыв не прошёл бы сам.
create policy api_tokens_revoked_are_final on api_tokens
    as restrictive for update
    using (revoked_at is null)
    with check (true);
