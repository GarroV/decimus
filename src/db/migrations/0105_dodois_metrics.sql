-- 0105_dodois_metrics.sql
--
-- Данные Dodo IS для страницы «Качество» по пиццериям и месяцам (D671): продажи
-- по источнику и каналу, заказы агрегаторов, оценки клиентов (КР), оценки РКО и РС по
-- периодам и число проверок. Собирает бот раз в
-- сутки под входом страны (`dodois.logins`, D640): в базе агрегаты «пиццерия × месяц»,
-- ни строки заказа, ни данных клиента здесь нет.
--
-- Ключ везде — (dodo_id, month), где `dodo_id` — 32-значный код пиццерии (тот же, что
-- `ratings.units.dodo_id`), `month` — первое число месяца. Внешнего ключа на
-- `ratings.units` нет намеренно, как у `agg` и `maps`: пиццерия бывает у Dodo IS, но не в
-- рейтингах; страну чтение берёт соединением с `ratings.units`.
--
-- Загрузка месяца — заменой целиком: удалить строки месяца пиццерий, ответивших в этот
-- заход, и вставить новые. Поэтому роли приложения (бот работает ею) нужен и `delete`.
-- Служебная работа без человека идёт от имени служебного пространства (F-037); у этих
-- таблиц построчных политик нет — как у `agg` и `maps`.
--
-- Раннер оборачивает файл в одну транзакцию сам.

create table dodois.unit_sales_month (
    dodo_id text not null check (dodo_id ~ '^[0-9a-f]{32}$'),
    month date not null check (month = date_trunc('month', month)::date),
    -- Источник заказа (CallCenter, Website, Dine-in, MobileApp, Manager, Aggregator,
    -- Kiosk) и канал продажи (Dine-in, Takeaway, Delivery): как отдаёт Dodo IS.
    order_source text not null check (order_source <> ''),
    sales_channel text not null check (sales_channel <> ''),
    orders integer not null check (orders >= 0),
    revenue numeric(16, 2) not null,
    currency text,
    loaded_at timestamptz not null default now(),
    primary key (dodo_id, month, order_source, sales_channel)
);
create index unit_sales_month_month_idx on dodois.unit_sales_month (month);
comment on table dodois.unit_sales_month is
    'Продажи пиццерии за месяц по источнику заказа и каналу (D671): заказы и выручка.';

create table dodois.unit_aggregator_month (
    dodo_id text not null check (dodo_id ~ '^[0-9a-f]{32}$'),
    month date not null check (month = date_trunc('month', month)::date),
    aggregator text not null check (aggregator <> ''),
    orders integer not null check (orders >= 0),
    revenue numeric(16, 2),
    loaded_at timestamptz not null default now(),
    primary key (dodo_id, month, aggregator)
);
create index unit_aggregator_month_month_idx on dodois.unit_aggregator_month (month);
comment on table dodois.unit_aggregator_month is
    'Заказы пиццерии из агрегаторов за месяц (D671): свёртка продаж по `aggregatorName`, '
    'строк заказов не хранится.';

create table dodois.unit_kr_month (
    dodo_id text not null check (dodo_id ~ '^[0-9a-f]{32}$'),
    month date not null check (month = date_trunc('month', month)::date),
    -- Средняя оценка клиентов по шкале 0–5 и число оценок, зал и доставка отдельно.
    dine_in_avg numeric(4, 2) check (dine_in_avg is null or dine_in_avg between 0 and 5),
    dine_in_count integer not null default 0 check (dine_in_count >= 0),
    delivery_avg numeric(4, 2) check (delivery_avg is null or delivery_avg between 0 and 5),
    delivery_count integer not null default 0 check (delivery_count >= 0),
    loaded_at timestamptz not null default now(),
    primary key (dodo_id, month)
);
comment on table dodois.unit_kr_month is
    'Оценки клиентов (КР) пиццерии за месяц (D671): среднее и число оценок, зал и доставка.';

-- Оценки контроля по периодам (РКО и РС, `controlling/ratings/*/history`): неделя за неделей,
-- как отдаёт Dodo IS. `rate` — 0–100. Ключ — начало периода; месяц страницы берёт периоды,
-- чьё начало в нём.
create table dodois.unit_rating_period (
    dodo_id text not null check (dodo_id ~ '^[0-9a-f]{32}$'),
    kind text not null check (kind in ('rko', 'rs')),
    period_from date not null,
    period_to date not null check (period_to >= period_from),
    rate numeric(6, 2) not null,
    publish_status text,
    loaded_at timestamptz not null default now(),
    primary key (dodo_id, kind, period_from)
);
comment on table dodois.unit_rating_period is
    'Оценки РКО и РС пиццерии по периодам из Dodo IS (D671): процент 0–100 и статус публикации.';

-- Сколько проверок (`controlling/checkups`) легло в период оценки: число и разбивка по статусу.
-- Только счёт: ни номеров проверок, ни людей. Вид — как отдал Dodo IS, приведённый к rko / rs.
create table dodois.unit_checkup_period (
    dodo_id text not null check (dodo_id ~ '^[0-9a-f]{32}$'),
    kind text not null check (kind <> ''),
    period_from date not null,
    period_to date not null check (period_to >= period_from),
    checkups integer not null check (checkups >= 0),
    by_status jsonb not null default '{}'::jsonb,
    loaded_at timestamptz not null default now(),
    primary key (dodo_id, kind, period_from)
);
comment on table dodois.unit_checkup_period is
    'Число проверок пиццерии по периодам и статусам из Dodo IS (D671), без номеров и людей.';

-- Журнал загрузки: строка на страну и вид данных за заход. Свежесть и последняя ошибка
-- страны выводятся из него; текст ошибки — вид отказа без значений ответа.
create table dodois.metric_loads (
    id bigint generated always as identity primary key,
    country text not null check (country ~ '^[A-Z]{2}$'),
    kind text not null check (kind in ('sales', 'aggregators', 'kr', 'ratings')),
    started_at timestamptz not null default now(),
    finished_at timestamptz,
    ok boolean not null default false,
    error text check (error is null or char_length(error) <= 500),
    rows integer not null default 0 check (rows >= 0)
);
create index metric_loads_country_idx on dodois.metric_loads (country, kind, started_at desc);
comment on table dodois.metric_loads is
    'Журнал сбора данных Dodo IS для «Качества» (D671): страна, вид, исход, сколько строк.';

grant select on dodois.unit_sales_month, dodois.unit_aggregator_month, dodois.unit_kr_month,
    dodois.unit_rating_period, dodois.unit_checkup_period, dodois.metric_loads to dodo_audit_app, dodo_audit_admin;
grant insert, update, delete on dodois.unit_sales_month, dodois.unit_aggregator_month,
    dodois.unit_kr_month, dodois.unit_rating_period, dodois.unit_checkup_period to dodo_audit_app;
grant insert, update on dodois.metric_loads to dodo_audit_app;
grant usage on sequence dodois.metric_loads_id_seq to dodo_audit_app;
