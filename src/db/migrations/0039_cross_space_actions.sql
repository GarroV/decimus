-- 0039_cross_space_actions.sql
--
-- Журнал действий человека УК в пространстве партнёра (спека «Администрирование»).
-- Данные принадлежат владельцу пространства (D017): УК в них действует (D304),
-- и каждое такое действие оставляет строку «кто, что, когда, в чьём пространстве».
--
-- Пишется ТЕМ ЖЕ подключением, что и действие, до его коммита
-- (`src/db/cross_space.py: record`): откатилось действие — откатилась строка.
-- Журнал только дописывается: update и delete не выданы никому.
--
-- Раннер оборачивает файл в одну транзакцию сам — begin/commit здесь не нужны.

create table cross_space_actions (
    id bigint generated always as identity primary key,
    at timestamptz not null default now(),
    actor_web_user_id uuid not null references web_users (id),
    actor_tenant text not null references tenants (code) check (actor_tenant = 'HQ'),
    object_tenant text not null references tenants (code) check (object_tenant <> 'HQ'),
    action_code text not null check (action_code ~ '^[a-z]+\.[a-z_]+$'),
    object_ref text not null check (length(btrim(object_ref)) between 1 and 200)
);

create index cross_space_actions_object_idx on cross_space_actions (object_tenant, at desc);

grant select, insert on cross_space_actions to dodo_audit_app, dodo_audit_admin;
