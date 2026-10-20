-- 0085_learning.sql
--
-- Обучение пиццерий из iSpring (D574, D575, D578, #906). Раз в сутки загрузчик забирает
-- результаты прохождения курсов, сворачивает их в счётчики по пиццерии и кладёт сюда
-- снимок дня: экран «Обучение» читает нашу базу, а не iSpring.
--
-- **D575 — данных о сотрудниках нет.** Ни одной колонки с идентификатором, именем, почтой,
-- STAFF_ID или строкой «человек × курс»: в таблицах только счётчики подразделения
-- (`src/domain/training_metrics.py: Counters`). Люди считаются в памяти загрузчика, а в базу
-- уходят числа «сколько всего» и «сколько полностью обучены». Тест
-- `tests/test_db_learning_schema.py` перечисляет колонки и падает на любой новой не-числовой,
-- кроме названий подразделений и курсов.
--
-- Подразделение iSpring — пиццерия, страна или офис (`kind`); пиццерия сопоставляется с
-- пиццерией рейтингов (`unit_dodo_id`), несопоставленная остаётся с пустой связью и выходит
-- на экран отдельным списком.
--
-- Раннер оборачивает файл в одну транзакцию сам.

create schema learning;
grant usage on schema learning to dodo_audit_app, dodo_audit_admin;

create table learning.departments (
    ispring_id text primary key,
    title text not null check (length(btrim(title)) between 1 and 200),
    kind text not null check (kind in ('country', 'pizzeria', 'office')),
    country_code text check (country_code ~ '^[A-Z]{2}$'),
    parent_id text,
    unit_dodo_id text references ratings.units (dodo_id) on delete set null,
    seen_at timestamptz not null default now()
);
create index departments_country_idx on learning.departments (country_code, kind);

create table learning.courses (
    course_id text primary key,
    title text not null check (length(btrim(title)) between 1 and 500),
    seen_at timestamptz not null default now()
);

-- Итог подразделения на дату загрузки. Повторная загрузка того же дня заменяет снимок.
create table learning.unit_totals (
    sync_date date not null,
    department_id text not null references learning.departments (ispring_id) on delete cascade,
    assigned integer not null check (assigned >= 0),
    completed integer not null check (completed between 0 and assigned),
    in_progress integer not null check (in_progress >= 0),
    not_started integer not null check (not_started >= 0),
    failed integer not null check (failed >= 0),
    passed integer not null check (passed >= 0),
    overdue integer not null check (overdue >= 0),
    people_total integer not null check (people_total >= 0),
    people_trained integer not null check (people_trained between 0 and people_total),
    time_sum bigint not null check (time_sum >= 0),
    time_n integer not null check (time_n >= 0),
    score_sum double precision not null check (score_sum >= 0),
    score_n integer not null check (score_n >= 0),
    days_sum double precision not null check (days_sum >= 0),
    days_n integer not null check (days_n >= 0),
    primary key (sync_date, department_id)
);

-- То же по курсам; «людей» по курсу не храним — по курсу это и есть назначения.
create table learning.unit_courses (
    sync_date date not null,
    department_id text not null references learning.departments (ispring_id) on delete cascade,
    course_id text not null references learning.courses (course_id) on delete cascade,
    assigned integer not null check (assigned >= 0),
    completed integer not null check (completed between 0 and assigned),
    in_progress integer not null check (in_progress >= 0),
    not_started integer not null check (not_started >= 0),
    failed integer not null check (failed >= 0),
    passed integer not null check (passed >= 0),
    overdue integer not null check (overdue >= 0),
    time_sum bigint not null check (time_sum >= 0),
    time_n integer not null check (time_n >= 0),
    score_sum double precision not null check (score_sum >= 0),
    score_n integer not null check (score_n >= 0),
    days_sum double precision not null check (days_sum >= 0),
    days_n integer not null check (days_n >= 0),
    primary key (sync_date, department_id, course_id)
);

-- Журнал загрузок: когда, чем кончилась, сколько легло. Текст ошибки — без ключей и данных.
create table learning.loads (
    id bigserial primary key,
    at timestamptz not null default now(),
    outcome text not null check (outcome in ('ok', 'failed')),
    departments integer not null default 0,
    results integer not null default 0,
    error text
);

grant select on all tables in schema learning to dodo_audit_app, dodo_audit_admin;
grant insert, update, delete on
    learning.departments, learning.courses, learning.unit_totals, learning.unit_courses
    to dodo_audit_app;
grant insert on learning.loads to dodo_audit_app;
grant usage on sequence learning.loads_id_seq to dodo_audit_app;
