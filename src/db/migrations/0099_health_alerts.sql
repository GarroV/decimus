-- 0099_health_alerts.sql
--
-- Оповещения владельцу о смене состояния подключений (D641). Бот после каждой проверки
-- сверяет цвет подключения (Dodo IS по странам, сборы, ключи и службы) с последним
-- ОПОВЕЩЁННЫМ состоянием и пишет владельцу только при смене: сломалось или починилось.
-- Эта таблица помнит последнее оповещённое состояние каждого кода (`dodo_is:RS`,
-- `aggregators`, …), чтобы перезапуск бота не повторял тревоги. Пустая таблица — первый заход
-- после выкатки: он лишь фиксирует текущее, ничего не отправляя.
--
-- Ни текстов сообщений, ни ключей здесь нет: код, уровень и время.
--
-- Раннер оборачивает файл в одну транзакцию сам.

create table health.alerts (
    code text primary key check (code ~ '^[a-z_]{1,40}(:[A-Z]{2})?$'),
    level text not null check (level in ('ok', 'yellow', 'red')),
    notified_at timestamptz not null default now()
);

grant select on health.alerts to dodo_audit_app, dodo_audit_admin;
grant insert, update on health.alerts to dodo_audit_app;
