-- 0068_second_factor.sql
--
-- Вторая ступень входа (D463): ключ доступа (passkey, Touch ID), код из приложения-
-- аутентификатора (TOTP, RFC 6238) и одноразовые резервные коды. Ступень стоит ПОВЕРХ
-- первой (Google или пароль): угнанная почта или пароль сами по себе сессию не дают.
-- Обязательна админу и главному админу; остальным — по желанию из «Настроек».
--
-- 1. `web_passkeys` — ключи доступа: номер ключа (credential id), открытый ключ,
--    счётчик подписей (откат счётчика отвергается — признак клона ключа), способы
--    связи, имя и времена. Несколько на человека. Закрытого ключа здесь нет и быть не
--    может — он не покидает устройство.
-- 2. `web_totp` — приложение-аутентификатор, одно на человека. `secret` лежит только
--    на стороне сервера и после подтверждения человеку не показывается. `confirmed_at`
--    пуст, пока человек не ввёл первый код: недоподтверждённое приложение вторым
--    фактором не считается. `last_step` — последний принятый шаг времени: тот же код в
--    пределах своего окна повторно не принимается (повтор).
-- 3. `web_backup_codes` — резервные коды. Хранится только отпечаток (sha256), код
--    показывается человеку один раз при выпуске. Погашение — пометка `used_at`, а не
--    удаление: «использован» читается, а код — одноразовый.
-- 4. `web_second_steps` — «наполовину вошёл»: первая ступень пройдена, вторая нет.
--    Это НЕ сессия: строка ничего не открывает, потому что опознаёт сессию только
--    `web_sessions`, а эту строку знает лишь страница «Подтвердите вход». Живёт
--    5 минут, гасится одним переходом (`consumed_at`), после пяти неудач мертва.
--    Токен — в куке браузера, в базе только отпечаток (браузер привязан этим).
-- 5. `web_webauthn_challenges` — вызов, выданный браузеру для ключа доступа:
--    на пару «привязка + назначение» один, срок 2 минуты, снимается при первом же
--    предъявлении (одноразовый, повторить нельзя).
-- 6. `login_journal` принимает способ `second-step` и исходы `bad-code`,
--    `passkey-fail`, `backup-used` (резервный код погашен).
-- 7. `web_sessions.second_step_at` — сессия выдана ПОСЛЕ второй ступени. Снимать способы
--    входа можно только такой сессией: первая ступень, пусть и свежая, этого не даёт.
-- 8. Права. Роль приложения читает и пишет ровно то, что нужно её двери; снимает
--    ключи и сбрасывает ВТОРУЮ СТУПЕНЬ другому человеку — только администратор истории
--    (`delete`): тот же заслон, что у заморозки (`0063`).
--
-- Раннер оборачивает файл в одну транзакцию сам.

create table web_passkeys (
    id uuid primary key default gen_random_uuid(),
    user_id uuid not null references web_users (id),
    credential_id bytea not null unique check (octet_length(credential_id) between 1 and 1023),
    public_key bytea not null,
    sign_count bigint not null default 0 check (sign_count >= 0),
    transports text[] not null default '{}',
    name text not null check (char_length(name) between 1 and 60),
    created_at timestamptz not null default now(),
    last_used_at timestamptz
);

create index web_passkeys_user_idx on web_passkeys (user_id);

comment on table web_passkeys is
    'Ключи доступа (passkey, D463): открытый ключ и счётчик подписей. Закрытый ключ '
    'остаётся на устройстве человека. Откат счётчика — признак клона, вход отклоняется.';

create table web_totp (
    user_id uuid primary key references web_users (id),
    secret text not null check (secret ~ '^[A-Z2-7]{32}$'),
    created_at timestamptz not null default now(),
    confirmed_at timestamptz,
    last_step bigint
);

comment on table web_totp is
    'Приложение-аутентификатор (TOTP, D463), одно на человека. secret — только на стороне '
    'сервера и после подтверждения не показывается; last_step — защита от повтора кода.';

create table web_backup_codes (
    id bigint generated always as identity primary key,
    user_id uuid not null references web_users (id),
    code_hash text not null check (code_hash ~ '^[0-9a-f]{64}$'),
    created_at timestamptz not null default now(),
    used_at timestamptz,
    unique (user_id, code_hash)
);

comment on table web_backup_codes is
    'Резервные коды (D463): хранится отпечаток, а не код; погашение — used_at, код одноразовый.';

create table web_second_steps (
    id uuid primary key default gen_random_uuid(),
    user_id uuid not null references web_users (id),
    fingerprint text not null unique check (fingerprint ~ '^[0-9a-f]{64}$'),
    -- Чем пройдена первая ступень: `password` или `google`.
    method text not null check (method in ('password', 'google')),
    -- Куда вернуть после входа: только путь внутри приложения (проверяет `safe_next`).
    next_path text check (next_path is null or char_length(next_path) <= 500),
    issued_at timestamptz not null default now(),
    expires_at timestamptz not null,
    consumed_at timestamptz,
    failures integer not null default 0 check (failures >= 0)
);

comment on table web_second_steps is
    'Полупройденный вход (D463): первая ступень есть, второй нет. НЕ сессия: ничего не '
    'открывает. Живёт 5 минут, одноразовый (consumed_at), после 5 неудач мёртв.';

create table web_webauthn_challenges (
    -- Отпечаток токена того, к чему привязан вызов: полупройденного входа или сессии.
    bound_fp text not null check (bound_fp ~ '^[0-9a-f]{64}$'),
    purpose text not null check (purpose in ('register', 'authenticate')),
    user_id uuid not null references web_users (id),
    challenge bytea not null,
    expires_at timestamptz not null,
    primary key (bound_fp, purpose)
);

comment on table web_webauthn_challenges is
    'Вызовы для ключей доступа (D463): один на привязку и назначение, 2 минуты, снимается '
    'при первом предъявлении.';

alter table web_sessions add column second_step_at timestamptz;

-- Журнал входов: вторая ступень.
alter table login_journal drop constraint login_journal_method_check;
alter table login_journal add constraint login_journal_method_check
    check (method in ('password', 'google', 'oauth-claude', 'personal-mcp-token', 'bot-link',
                      'second-step'));
alter table login_journal drop constraint login_journal_result_check;
alter table login_journal add constraint login_journal_result_check
    check (result in ('ok', 'bad-password', 'frozen', 'unknown', 'rate-limited', 'refused',
                      'bad-code', 'passkey-fail', 'backup-used'));

-- --- права -------------------------------------------------------------------

grant select, insert, delete on web_passkeys to dodo_audit_app;
grant update (sign_count, last_used_at) on web_passkeys to dodo_audit_app;

grant select, insert, delete on web_totp to dodo_audit_app;
grant update (secret, created_at, confirmed_at, last_step) on web_totp to dodo_audit_app;

grant select, insert, delete on web_backup_codes to dodo_audit_app;
grant update (used_at) on web_backup_codes to dodo_audit_app;

grant select, insert, delete on web_second_steps to dodo_audit_app;
grant update (consumed_at, failures) on web_second_steps to dodo_audit_app;

grant select, insert, delete on web_webauthn_challenges to dodo_audit_app;

-- Сброс второй ступени ДРУГОМУ человеку (главный админ, команда с машины) — рукой
-- администратора истории, а не роли приложения: тот же заслон, что у заморозки.
grant select, delete on web_passkeys to dodo_audit_admin;
grant select, delete on web_totp to dodo_audit_admin;
grant select, delete on web_backup_codes to dodo_audit_admin;
grant select, delete on web_second_steps to dodo_audit_admin;
grant select, delete on web_webauthn_challenges to dodo_audit_admin;
