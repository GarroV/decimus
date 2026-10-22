-- 0090_notifications.sql
--
-- Уведомления в приложении (#1129, D604, D614): колокольчик в левой панели и красная
-- точка на пункте меню, где есть новое. Одна общая таблица: на ней сидят события
-- предписаний (спека 2026-10-21-osb-prescriptions-design) и, позже, экшн-плана
-- (спека 2026-10-22-electronic-action-plan-design). Наружу из приложения не уходит
-- ничего — ни почты, ни Telegram (§7 глобальных правил: сообщение человеку только по
-- «да» владельца).
--
-- Что хранится. Кому (`user_id` — учётка веба), вид (`kind` — код, по нему экран берёт
-- текст на своём языке), адрес внутри приложения (`link`, относительный путь) и
-- параметры текста (`params`). ТЕКСТ НЕ ХРАНИТСЯ: формулировки переводятся и
-- правятся, коды нет (принцип 5), а сохранённая фраза осталась бы на старом языке.
--
-- Права. Читать и отмечать прочитанным приложение может, переписывать суть — нет:
-- `update` только на `read_at`. Удаления нет. Кому какие строки видны, решает запрос
-- веба (`user_id = своя учётка` в каждом чтении, `src/db/notifications.py`): чья учётка —
-- определяет сессия, а не параметр запроса. Построчной политики нет намеренно:
-- пространство обращения тут ничего не решает, а у соединения администратора истории
-- (им пишутся события предписаний, в той же транзакции, что и сам переход) его нет.
--
-- Раннер оборачивает файл в одну транзакцию сам.

create table notifications (
    id bigint generated always as identity primary key,
    user_id uuid not null references web_users (id),
    kind text not null check (kind ~ '^[a-z][a-z0-9_.]{0,63}$'),
    -- Относительный путь внутри приложения, без адреса сайта и без префикса площадки.
    link text not null check (link ~ '^/[^[:space:]]{0,500}$' and link !~ '^//'),
    params jsonb not null default '{}'::jsonb check (jsonb_typeof(params) = 'object'),
    created_at timestamptz not null default now(),
    read_at timestamptz
);

-- Главный вопрос экрана: «есть ли у меня непрочитанное» — по человеку и признаку.
create index notifications_user_read_idx on notifications (user_id, read_at, created_at desc);

comment on table notifications is
    'Уведомления в приложении (D604, D614): кому, какого вида, куда вести, параметры текста. Текст не хранится — по kind его берёт экран. Наружу ничего не отправляется.';
comment on column notifications.kind is
    'Код события (rx_requested, rx_returned, ...): по нему экран берёт текст из словаря на языке человека.';
comment on column notifications.link is
    'Адрес внутри приложения (путь и запрос, без префикса площадки). Открытие страницы с этим адресом отмечает строку прочитанной.';

grant select, insert on notifications to dodo_audit_app;
grant update (read_at) on notifications to dodo_audit_app;
-- Администратор истории пишет события предписаний в той же транзакции, что и переход.
grant insert on notifications to dodo_audit_admin;
grant usage on sequence notifications_id_seq to dodo_audit_app, dodo_audit_admin;
