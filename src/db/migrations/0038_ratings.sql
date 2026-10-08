-- 0038_ratings.sql
--
-- Рейтинги РС и РКО (спека docs/superpowers/specs/2026-10-08-ratings-design.md,
-- D317–D329). Своя схема: данные рейтингов не смешиваются с проверками Decimus
-- (D321). Политик пространств нет — рейтинги видят все (D327, «рейтинги видят
-- все»). Пишет только роль приложения: дверью загрузки
-- (`src/ratings/importer.py`) и экраном «Загрузки» (`src/web/ratings.py`).
--
-- КЛЮЧИ. Пиццерия — id Dodo IS (32 hex строчными), проверка — тип + id
-- проверки, период — тип + дата начала (у периода из снимка ещё и id Dodo IS),
-- оценка — пиццерия + период, нарушение — `row_key`, который строит импортёр.
-- Повтор строки по ключу обновляет её, а не множит.
--
-- ЖУРНАЛ. Строка `loaded` с данным sha256 одна (частичный уникальный индекс):
-- тот же файл дважды не ложится. Повтор пишется строкой `duplicate` со
-- ссылкой на первую, неразобранный файл — `failed` с причиной.
--
-- Раннер оборачивает файл в одну транзакцию сам — begin/commit здесь не нужны.

create schema ratings;
grant usage on schema ratings to dodo_audit_app, dodo_audit_admin;

create table ratings.countries (
    code text primary key check (code ~ '^[A-Z]{2}$'),
    name_ru text not null check (length(btrim(name_ru)) > 0),
    name_en text not null check (length(btrim(name_en)) > 0),
    dodo_id integer unique,
    developer text check (developer is null or length(btrim(developer)) between 1 and 120),
    is_imf boolean not null default true,
    updated_by text,
    updated_at timestamptz not null default now()
);

create table ratings.imports (
    id bigint generated always as identity primary key,
    at timestamptz not null default now(),
    actor text not null check (length(btrim(actor)) > 0),
    channel text not null check (channel in ('web', 'mcp', 'seed')),
    format text check (
        format in ('rko-violations', 'rko-evaluations', 'rs-checkups', 'snapshot', 'sheet-scores')
    ),
    file_name text check (file_name is null or length(file_name) <= 255),
    sha256 text not null check (sha256 ~ '^[0-9a-f]{64}$'),
    outcome text not null check (outcome in ('loaded', 'duplicate', 'failed')),
    duplicate_of bigint references ratings.imports (id),
    accepted integer not null default 0 check (accepted >= 0),
    updated integer not null default 0 check (updated >= 0),
    skipped integer not null default 0 check (skipped >= 0),
    unmatched integer not null default 0 check (unmatched >= 0),
    -- Для `loaded` — «часть 2 из 3» у снимка, для `failed` — причина отказа.
    note text check (note is null or length(note) <= 2000),
    check (outcome <> 'loaded' or format is not null),
    check ((outcome = 'duplicate') = (duplicate_of is not null)),
    check (outcome <> 'failed' or note is not null)
);
create unique index imports_loaded_once on ratings.imports (sha256) where outcome = 'loaded';
create index imports_at_idx on ratings.imports (at desc);

create table ratings.import_issues (
    import_id bigint not null references ratings.imports (id),
    row_no integer not null check (row_no > 0),
    reason text not null check (reason in ('unit_unmatched', 'country_unknown', 'bad_row')),
    detail jsonb not null default '{}'::jsonb,
    primary key (import_id, row_no, reason)
);

create table ratings.units (
    dodo_id text primary key check (dodo_id ~ '^[0-9a-f]{32}$'),
    name text not null check (length(btrim(name)) between 1 and 120),
    name_normalized text not null,
    country_code text references ratings.countries (code),
    -- Связь со справочником Decimus — отдельная задача вместе с #312.
    decimus_unit_id uuid references public.units (id),
    updated_at timestamptz not null default now()
);
create index units_name_idx on ratings.units (name_normalized);

create table ratings.periods (
    id bigint generated always as identity primary key,
    rating_type text not null check (rating_type in ('rs', 'rko')),
    dodo_id text unique check (dodo_id is null or dodo_id ~ '^[0-9a-f]{32}$'),
    begin_on date not null,
    end_on date not null,
    title_ru text not null check (length(btrim(title_ru)) > 0),
    title_en text not null check (length(btrim(title_en)) > 0),
    check (end_on >= begin_on),
    unique (rating_type, begin_on)
);

create table ratings.scores (
    unit_dodo_id text not null references ratings.units (dodo_id),
    period_id bigint not null references ratings.periods (id),
    score numeric(5, 2) not null check (score between 0 and 100),
    status text,
    checkups_count integer check (checkups_count is null or checkups_count >= 0),
    source text not null check (source in ('snapshot', 'sheet', 'demo')),
    import_id bigint not null references ratings.imports (id),
    updated_at timestamptz not null default now(),
    primary key (unit_dodo_id, period_id)
);
create index scores_period_idx on ratings.scores (period_id);

create table ratings.checkups (
    rating_type text not null check (rating_type in ('rs', 'rko')),
    dodo_id text not null check (dodo_id ~ '^[0-9a-f]{32}$'),
    -- Пусто, пока проверку знает только приёмка (`rko-evaluations`).
    unit_dodo_id text references ratings.units (dodo_id),
    country_code text references ratings.countries (code),
    occurred_at timestamptz,
    channel text check (channel in ('delivery', 'restaurant', 'inspection', 'online')),
    acceptance text check (acceptance in ('accepted', 'rejected')),
    evaluated_at timestamptz,
    duration_min integer check (duration_min is null or duration_min >= 0),
    period_dodo_id text check (period_dodo_id is null or period_dodo_id ~ '^[0-9a-f]{32}$'),
    backoffice_url text,
    rating_url text,
    import_id bigint not null references ratings.imports (id),
    primary key (rating_type, dodo_id)
);
create index checkups_when_idx on ratings.checkups (rating_type, occurred_at);

create table ratings.violations (
    id bigint generated always as identity primary key,
    row_key text not null unique,
    rating_type text not null check (rating_type in ('rs', 'rko')),
    checkup_dodo_id text,
    unit_dodo_id text not null references ratings.units (dodo_id),
    period_id bigint references ratings.periods (id),
    text text not null check (length(btrim(text)) between 1 and 500),
    category text not null check (category in ('violation', 'other', 'remark')),
    criterion_id text,
    parent_name text,
    auto_detected boolean not null default false,
    deduction numeric(7, 2),
    amount integer not null default 1 check (amount > 0),
    import_id bigint not null references ratings.imports (id),
    foreign key (rating_type, checkup_dodo_id)
        references ratings.checkups (rating_type, dodo_id) on delete cascade,
    -- Нарушение проверки — с проверкой; замечание периода (снимок) — с периодом.
    check ((checkup_dodo_id is null) = (category = 'remark')),
    check (category <> 'remark' or period_id is not null)
);
create index violations_checkup_idx on ratings.violations (rating_type, checkup_dodo_id);
create index violations_period_idx on ratings.violations (period_id) where period_id is not null;

create table ratings.hard_rules (
    id bigint generated always as identity primary key,
    rating_type text not null check (rating_type in ('rs', 'rko')),
    -- text — совпадение текста целиком без учёта регистра; contains — подстрока
    -- в тексте нарушения или в его родителе (`parent_name`).
    match text not null check (match in ('text', 'contains')),
    pattern text not null check (length(btrim(pattern)) between 1 and 200),
    created_by text not null,
    created_at timestamptz not null default now(),
    unique (rating_type, match, pattern)
);

create table ratings.settings (
    key text primary key check (key in ('top_threshold', 'risk_threshold', 'risk_periods')),
    value numeric not null,
    updated_by text not null,
    updated_at timestamptz not null default now(),
    check (key <> 'risk_periods' or (value between 2 and 12 and value = trunc(value))),
    check (key = 'risk_periods' or value between 0 and 100)
);

-- Стартовые значения из сводки скрипта (D324); правит контроль (D328).
insert into ratings.settings (key, value, updated_by) values
    ('top_threshold', 85, 'migration 0038'),
    ('risk_threshold', 85, 'migration 0038'),
    ('risk_periods', 3, 'migration 0038');

insert into ratings.hard_rules (rating_type, match, pattern, created_by) values
    ('rko', 'text', 'Критично белое дно', 'migration 0038'),
    ('rko', 'text', 'Пиццу привезли холодной', 'migration 0038'),
    ('rko', 'text', 'Нарушен рецепт', 'migration 0038'),
    ('rko', 'text', 'Сильно деформирована', 'migration 0038'),
    ('rko', 'text', 'Все борты белые', 'migration 0038'),
    ('rko', 'text', 'Дисквалифицировать пиццу', 'migration 0038'),
    ('rs', 'contains', 'D3', 'migration 0038'),
    ('rs', 'contains', 'критич', 'migration 0038'),
    ('rs', 'contains', 'обнул', 'migration 0038');

grant select on all tables in schema ratings to dodo_audit_app, dodo_audit_admin;
grant insert, update, delete on
    ratings.countries, ratings.units, ratings.periods, ratings.scores, ratings.checkups,
    ratings.violations, ratings.hard_rules, ratings.settings, ratings.import_issues
    to dodo_audit_app;
-- Журнал не удаляется никем, кроме владельца схемы: след загрузки остаётся.
-- Роль приложения дописывает счётчики разбора, но не переписывает, кто, когда,
-- каким файлом и с каким исходом загружал: actor, sha256, at, outcome — только вставка.
grant insert on ratings.imports to dodo_audit_app;
grant update (accepted, updated, skipped, unmatched) on ratings.imports to dodo_audit_app;
