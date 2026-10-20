-- 0082_rate_windows.sql
--
-- Общее скользящее окно частоты запросов (аудит F-110, #1006). Предел частоты MCP
-- (`src/mcp/ratelimit.py`) и мини-аппа обхода (`src/web/walk_rate.py`) считался в памяти
-- процесса, поэтому второй контейнер или перекрытие при выкатке удваивали предел: каждый
-- процесс видел только свою половину запросов. Теперь окно лежит здесь и общее на всех.
--
-- 1. Одна строка на ключ (`scope` — какой предел, `key_fingerprint` — отпечаток ключа:
--    токена, адреса, чата). В строке — отметки времени запросов, учтённых за окно:
--    ровно то, что раньше лежало в `deque` процесса, поэтому семантика окна та же.
-- 2. Строку правит только код под advisory-замком на ключ (`src/db/rate_window.py`,
--    образец — `web_throttle`): прочитал, отсёк просроченное, дописал. Без замка два
--    процесса прочли бы одно и то же число и оба пропустили запрос.
-- 3. Хранятся ОТПЕЧАТКИ ключей, не сами ключи: адрес клиента и токен в базе не лежат.
-- 4. Строки, в которых ничего не осталось от окна, удаляются попутно при следующем
--    обращении к тому же пределу — отдельного расписания чистки нет.
-- 5. `tenant_code` нет намеренно: предел считается ДО того, как известно, чей запрос.
--
-- Раннер оборачивает файл в одну транзакцию сам.

create table rate_windows (
    scope text not null check (scope ~ '^[a-z][a-z0-9_.]{0,39}$'),
    key_fingerprint text not null check (key_fingerprint ~ '^[0-9a-f]{64}$'),
    stamps timestamptz[] not null check (cardinality(stamps) between 1 and 5000),
    updated_at timestamptz not null,
    primary key (scope, key_fingerprint)
);

create index rate_windows_stale_idx on rate_windows (scope, updated_at);

comment on table rate_windows is
    'Общее скользящее окно частоты запросов (F-110): отметки учтённых запросов по ключу '
    'предела. Хранятся отпечатки ключей. Правится под advisory-замком на ключ '
    '(src/db/rate_window.py); просроченные строки удаляются попутно.';
comment on column rate_windows.stamps is
    'Моменты запросов, учтённых за окно. Просроченные отсекаются при каждом обращении.';

grant select, insert, delete on rate_windows to dodo_audit_app;

grant update (stamps, updated_at) on rate_windows to dodo_audit_app;
