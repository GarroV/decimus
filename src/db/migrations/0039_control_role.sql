-- 0039_control_role.sql
--
-- Роль веб-учётки «контроль» (D319, спека «Рейтинги»): загружает рейтинги и
-- правит их справочники; чек-листы, методику, веса и людей не трогает. Бывает
-- только в пространстве УК — держит схема, а не только форма.
--
-- Имя прежнего ограничения — то, что Postgres дал безымянному check из `0020`
-- (`web_users_role_check`). Перед накатом проверить: `\d web_users`.
--
-- Раннер оборачивает файл в одну транзакцию сам.

alter table web_users drop constraint web_users_role_check;
alter table web_users add constraint web_users_role_check
    check (role in ('auditor', 'admin', 'control'));
alter table web_users add constraint web_users_control_only_hq
    check (role <> 'control' or tenant_code = 'HQ');

comment on column web_users.role is
    'Что человеку можно В АДМИНКЕ: auditor — работать со своей историей, '
    'admin — вдобавок заводить и отключать учётки, control — загружать рейтинги '
    'и править их справочники (только HQ). Чью историю видно, решает tenant_code.';
