-- 0060_d440_roles.sql
--
-- Роли УК по D440: «бизнес-девелопер» (`developer`) вместо аудитора УК и «гость»
-- (`guest`) — вся сеть на чтение.
--
-- 1. Допустимые роли расширяются: `developer` и `guest`. Обе бывают только в
--    пространстве УК — держит схема, а не только форма (как `control`, `0040`).
-- 2. Нынешние аудиторы УК становятся бизнес-девелоперами: пользовались сервисом
--    полностью, и D440 оставляет им это (плюс приёмка, снятие и перенос).
--    Партнёрские `auditor` не трогаются — сторона партнёра не менялась.
-- 3. Аудитора в УК больше нет: после перевода схема не даёт его завести. Порядок
--    важен — ограничение ставится ПОСЛЕ перевода строк, иначе накат упал бы на
--    них самих.
--
-- Раннер оборачивает файл в одну транзакцию сам.

alter table web_users drop constraint web_users_role_check;
alter table web_users add constraint web_users_role_check
    check (role in ('auditor', 'admin', 'control', 'superadmin', 'developer', 'guest'));
alter table web_users add constraint web_users_developer_guest_only_hq
    check (role not in ('developer', 'guest') or tenant_code = 'HQ');

update web_users set role = 'developer' where role = 'auditor' and tenant_code = 'HQ';

alter table web_users add constraint web_users_no_hq_auditor
    check (role <> 'auditor' or tenant_code <> 'HQ');

comment on column web_users.role is
    'Что человеку можно В АДМИНКЕ (D440). УК: superadmin — всё, включая ключи API; '
    'admin — работает и отвечает за систему (главный чек-лист, методика, веса, '
    'страны, люди, админы кроме главного); developer — бизнес-девелопер, '
    'пользуется сервисом полностью, методику и людей не трогает; control — '
    'рейтинги; guest — вся сеть только на чтение. Партнёр: admin — админ '
    'пространства, auditor — сотрудник. Чью историю видно, решает tenant_code.';
