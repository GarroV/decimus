-- 0086_osb_role.sql
--
-- Роль ОСБ (отдел сопровождения бизнеса) — D599, спека 2026-10-21-osb-prescriptions-design.
-- Сторона УК, рядом с `developer` и `guest` (0060): права гостя на чтение плюс
-- ведение предписаний на странице «ОСБ». Бывает только в пространстве УК —
-- держит схема, а не только форма. К странам не привязана (D606).
--
-- Раннер оборачивает файл в одну транзакцию сам.

alter table web_users drop constraint web_users_role_check;
alter table web_users add constraint web_users_role_check
    check (role in ('auditor', 'admin', 'control', 'superadmin', 'developer', 'guest', 'osb'));
alter table web_users add constraint web_users_osb_only_hq
    check (role <> 'osb' or tenant_code = 'HQ');

comment on column web_users.role is
    'Что человеку можно В АДМИНКЕ (D440). УК: superadmin — всё, включая ключи API; '
    'admin — работает и отвечает за систему (главный чек-лист, методика, веса, '
    'страны, люди, админы кроме главного); developer — бизнес-девелопер, '
    'пользуется сервисом полностью, методику и людей не трогает; control — '
    'рейтинги; guest — вся сеть только на чтение; osb — гость плюс ведение '
    'предписаний (D599). Партнёр: admin — админ '
    'пространства, auditor — сотрудник. Чью историю видно, решает tenant_code.';
