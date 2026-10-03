-- 0029_space_countries.sql
--
-- Волна 1 пространств (#340, D284): одна страна — один партнёр. Пространство
-- партнёра привязано к своим странам; справочник пиццерий один, и партнёр видит
-- пиццерии своих стран. Страна — ключ строки, поэтому второе пространство на ту
-- же страну не заведётся: это отказ схемы, а не договорённость.
--
-- У УК строк нет: её охват — вся сеть (D283). Партнёр без строк не видит
-- ничего — закрыто по умолчанию.
--
-- Роли приложения и администратора истории — только чтение: страны заводит
-- команда (задача 13), а не продукт. Читают таблицу охват чтения
-- (`src/db/reach.py`) и сторож проверки из 0030.

create table space_countries (
    country text primary key check (country ~ '^[A-Z]{2}$'),
    tenant_code text not null references tenants (code) check (tenant_code <> 'HQ'),
    created_at timestamptz not null default now()
);

create index space_countries_tenant_idx on space_countries (tenant_code);

comment on table space_countries is
    'Страны пространства партнёра (D284). Страна — ключ: одна страна, одно пространство.';

grant select on space_countries to dodo_audit_app;
grant select on space_countries to dodo_audit_admin;
