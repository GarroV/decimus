-- Оконный кеш операционных показателей и native LFL для API Swarm: точные периоды,
-- знаменатели средних, валюты, покрытие и происхождение без строк заказов и клиентов.
-- Старые sales:month и unit_sales_month не меняются; чужим токенам права не добавляются.

create table dodois.performance_windows (
    country text not null check (country ~ '^[A-Z]{2}$'),
    subject_id text not null,
    metric text not null check (metric in ('revenue', 'orders', 'delivery_seconds',
        'restaurant_cooking_seconds', 'stops_seconds', 'stops_count', 'certificates_count')),
    period_from date not null,
    period_to date not null check (period_to >= period_from),
    value numeric,
    numerator numeric,
    denominator numeric check (denominator >= 0),
    currency text check (currency ~ '^[A-Z]{3}$'),
    timezone text not null,
    source text not null,
    status text not null check (status in ('complete', 'partial', 'unavailable')),
    covered_units integer check (covered_units >= 0),
    expected_units integer check (expected_units >= 0),
    loaded_at timestamptz not null default now(),
    reason text check (reason is null or reason ~ '^[a-z_]{1,64}$'),
    primary key (country, subject_id, metric, period_from, period_to),
    check (subject_id = country or subject_id ~ '^[0-9a-f]{32}$'),
    check ((numerator is null) = (denominator is null)),
    check (covered_units <= expected_units)
);
create index performance_windows_period_idx
    on dodois.performance_windows (country, period_from, period_to);

create table dodois.performance_lfl (
    country text not null check (country ~ '^[A-Z]{2}$'),
    subject_id text not null,
    query_from date not null,
    query_to date not null check (query_to >= query_from),
    granularity text not null check (granularity in ('Day', 'Week', 'Month')),
    bucket_date date not null,
    revenue_raw numeric,
    orders_raw numeric,
    source text not null,
    loaded_at timestamptz not null default now(),
    primary key (country, subject_id, query_from, query_to, granularity, bucket_date),
    check (subject_id = country or subject_id ~ '^[0-9a-f]{32}$')
);

create table dodois.performance_loads (
    country text not null check (country ~ '^[A-Z]{2}$'),
    kind text not null,
    period_from date not null,
    period_to date not null check (period_to >= period_from),
    attempted_at timestamptz not null default now(),
    last_ok_at timestamptz,
    error_code text check (error_code is null or error_code ~ '^[a-z_]{1,64}$'),
    primary key (country, kind, period_from, period_to)
);

grant select on dodois.performance_windows, dodois.performance_lfl,
    dodois.performance_loads to dodo_audit_app, dodo_audit_admin;
grant insert, update, delete on dodois.performance_windows, dodois.performance_lfl,
    dodois.performance_loads to dodo_audit_app;

alter table api.tokens drop constraint tokens_scopes_check;
alter table api.tokens add constraint tokens_scopes_check
    check (cardinality(scopes) > 0 and scopes <@ array[
        'ratings:scores', 'ratings:checkups', 'ratings:violations', 'maps:ratings',
        'aggregators:ratings', 'inspections:list', 'inspections:detail',
        'inspections:violations', 'sales:month', 'performance:read'
    ]);
