-- 0050_aggregators.sql
--
-- Оценки пиццерий в агрегаторах доставки — Wolt, Glovo, Bolt Food, Яндекс Еда,
-- Yemeksepeti и другие (#638, D389, docs/17-aggregators.md). Бот раз в сутки
-- собирает оценки и кладёт снимок дня сюда: агрегаторы отдают только «сейчас»,
-- история копится у нас.
--
-- Агрегатор — поле данных (`aggregator`, код латиницей): новый агрегатор
-- добавляется сборщиком в коде, без миграции. Шкала у каждого своя (Wolt — из
-- 10, Glovo — % положительных, остальные — из 5) и хранится при оценке: в
-- общую шкалу не пересчитываем, это исказило бы то, что видит гость.
--
-- Раннер оборачивает файл в одну транзакцию сам.

create schema agg;
grant usage on schema agg to dodo_audit_app, dodo_audit_admin;

-- Точка агрегатора: заведение на его витрине. `point_key` — его собственный
-- ключ (slug, id), уникальный внутри агрегатора. `dodo_id` — пиццерия Dodo
-- (`UUId` из publicapi, тот же код, что `ratings.units.dodo_id`); внешнего ключа
-- нет намеренно, как у карт: пиццерия бывает на витрине, но не в рейтингах.
-- `extra` — то, что нужно сборщику, чтобы снять оценку завтра (город, id
-- магазина, координаты доставки).
create table agg.points (
    aggregator text not null check (aggregator ~ '^[a-z][a-z0-9_]*$'),
    point_key text not null,
    country_code text not null check (country_code ~ '^[A-Z]{2}$'),
    name text,
    url text,
    lat double precision,
    lng double precision,
    dodo_id text check (dodo_id ~ '^[0-9a-f]{32}$'),
    dodo_name text,
    link_distance_m integer check (link_distance_m >= 0),
    extra jsonb not null default '{}'::jsonb,
    excluded_reason text,
    seen_at timestamptz not null default now(),
    primary key (aggregator, point_key)
);
create index points_dodo_idx on agg.points (dodo_id);
create index points_country_idx on agg.points (country_code);

-- Снимок оценки на дату сбора. `scale` — во сколько баллов оценка (5, 10, 100);
-- `votes` — число оценок, если агрегатор его отдаёт; `votes_exact = false` —
-- агрегатор показывает ступень («500+»).
create table agg.ratings (
    aggregator text not null,
    point_key text not null,
    on_date date not null,
    score numeric(5, 2) not null check (score >= 0),
    scale smallint not null check (scale in (5, 10, 100)),
    votes integer check (votes >= 0),
    votes_exact boolean not null default true,
    is_open boolean,
    loaded_at timestamptz not null default now(),
    primary key (aggregator, point_key, on_date),
    foreign key (aggregator, point_key) references agg.points (aggregator, point_key),
    check (score <= scale)
);

-- Журнал сбора — строка на агрегатор за заход: удался ли, сколько точек и
-- оценок. Пустой ответ при прошлых непустых — `failed`, а не «Додо пропал».
create table agg.loads (
    id bigserial primary key,
    at timestamptz not null default now(),
    aggregator text not null,
    outcome text not null check (outcome in ('ok', 'failed')),
    points integer not null default 0,
    ratings integer not null default 0,
    error text
);
create index loads_aggregator_idx on agg.loads (aggregator, at desc);

grant select on all tables in schema agg to dodo_audit_app, dodo_audit_admin;
grant insert, update on agg.points, agg.ratings to dodo_audit_app;
grant insert on agg.loads to dodo_audit_app;
grant usage on sequence agg.loads_id_seq to dodo_audit_app;

-- Новый блок страницы рейтингов (D368): компоновка покажет его в конце.
alter table ratings.layout drop constraint layout_block_check;
alter table ratings.layout add constraint layout_block_check
    check (block in ('scores', 'violations', 'top', 'hard', 'risk', 'maps', 'aggregators'));
insert into ratings.layout (block, position, updated_by) values ('aggregators', 6, 'migration 0050');
