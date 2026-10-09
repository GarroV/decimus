-- 0043_ratings_layout.sql
--
-- Компоновка страницы «Рейтинги» (D368, D370): какие блоки показывать и в
-- каком порядке. Собирает контролинг; действует на всех, кто смотрит рейтинги,
-- в том числе на партнёров. Новые блоки — код, их здесь не заводят: список
-- кодов закрыт проверкой.
--
-- Раннер оборачивает файл в одну транзакцию сам.

create table ratings.layout (
    block text primary key
        check (block in ('scores', 'violations', 'top', 'hard', 'risk')),
    position integer not null check (position >= 0),
    visible boolean not null default true,
    updated_by text not null,
    updated_at timestamptz not null default now()
);

insert into ratings.layout (block, position, updated_by) values
    ('scores', 0, 'migration 0043'),
    ('violations', 1, 'migration 0043'),
    ('top', 2, 'migration 0043'),
    ('hard', 3, 'migration 0043'),
    ('risk', 4, 'migration 0043');

grant select on ratings.layout to dodo_audit_app, dodo_audit_admin;
grant update (position, visible, updated_by, updated_at) on ratings.layout to dodo_audit_app;
