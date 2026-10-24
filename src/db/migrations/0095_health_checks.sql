-- 0095_health_checks.sql
--
-- Постоянная проверка подключений (D638, #1251). Фоновая задача бота раз в 15 минут
-- дёргает ключи и службы (OpenAI, Pointer, iSpring, сам бот, хранилище кадров) и кладёт
-- сюда исход последней пробы — одна строка на подключение, следующая проба её заменяет.
-- Вкладка «Администрирование → Подключения» читает её и выводит цвет
-- (`src/domain/health.py`). Сборы (агрегаторы, карты, таблица контроля, iSpring) сюда не
-- пишут: у них свои журналы загрузок, цвет выводится из них.
--
-- Ни значений ключей, ни ответов провайдера здесь нет: только код подключения, цвет,
-- ключ текста причины и время.
--
-- Раннер оборачивает файл в одну транзакцию сам.

create schema health;
grant usage on schema health to dodo_audit_app, dodo_audit_admin;

create table health.checks (
    code text primary key check (code ~ '^[a-z_]{1,40}$'),
    light text not null check (light in ('green', 'yellow', 'red', 'grey')),
    reason text not null check (reason ~ '^health\.reason\.[a-z_]{1,40}$'),
    checked_at timestamptz not null default now()
);

grant select on health.checks to dodo_audit_app, dodo_audit_admin;
grant insert, update on health.checks to dodo_audit_app;
