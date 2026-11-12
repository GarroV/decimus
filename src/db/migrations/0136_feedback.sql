-- 0136_feedback.sql
--
-- D761 п.6: кнопка «Обратная связь» на всех страницах веба. Любой вошедший пишет текст и
-- прикладывает до пяти фото; отзыв сохраняется здесь и виден в «Администрировании» главному
-- админу и админу УК. Дальше (отдельное «да» владельца на текст и адресатов) он уходит в чат
-- Telegram, id которого задаёт главный админ; пока чат не задан, отправки нет вовсе.
--
-- `feedback` — отзыв: кто (учётка, роль, пространство), откуда (адрес страницы, язык), что
-- написал, когда. Править можно только отметки: «разобрано» и итог отправки в Telegram —
-- колоночными правами, сам текст после записи не меняется.
-- `feedback_photos` — кадры отзыва: сжатая копия лежит в самой строке (до пяти по ~1 МБ),
-- хранилище кадров проверок для них не нужно, и демо работает без него.
-- `feedback_chat` — настройка чата Telegram журналом: текущий чат — последняя строка,
-- пустой `telegram_chat_id` значит «выключено». Миграция ни одной строки не добавляет:
-- чат не задан, значит ничего не отправляется.
--
-- `feedback_attempts` — попытки отправки (любые, и принятые, и отклонённые): предел частоты
-- считается по ней ДО разбора фото, чтобы поток тяжёлых запросов останавливался дёшево.
--
-- Видимость по пространству: пишет каждый в своё; читает УК (вся сеть) и пространство-автор.
-- Строка, добавленная без `returning`, читателя не требует: партнёр свой отзыв пишет, а чужие
-- не видит. Раннер оборачивает файл в одну транзакцию сам — begin/commit здесь не нужны.

create table feedback (
    id uuid primary key default gen_random_uuid(),
    tenant_code text not null references tenants (code),
    login text not null check (length(btrim(login)) > 0),
    role text not null,
    page text not null check (length(page) <= 500),
    lang text not null check (lang ~ '^[a-z]{2}$'),
    body text not null check (length(btrim(body)) > 0 and length(body) <= 4000),
    created_at timestamptz not null default now(),
    reviewed_at timestamptz,
    reviewed_by text,
    telegram_sent_at timestamptz,
    telegram_error text
);

create index feedback_by_time on feedback (created_at desc, id);
create index feedback_by_login on feedback (login, created_at desc);

create table feedback_photos (
    id uuid primary key default gen_random_uuid(),
    feedback_id uuid not null references feedback (id) on delete cascade,
    position smallint not null check (position between 1 and 5),
    content_type text not null check (content_type = 'image/jpeg'),
    size_bytes integer not null check (size_bytes > 0),
    data bytea not null,
    unique (feedback_id, position)
);

create table feedback_chat (
    id bigint generated always as identity primary key,
    telegram_chat_id text check (telegram_chat_id is null or telegram_chat_id ~ '^-?[0-9]{5,20}$'),
    changed_by text not null,
    changed_at timestamptz not null default now()
);

create table feedback_attempts (
    id bigint generated always as identity primary key,
    tenant_code text not null references tenants (code),
    login text not null check (length(btrim(login)) > 0),
    attempted_at timestamptz not null default now()
);

create index feedback_attempts_by_login on feedback_attempts (login, attempted_at desc);

comment on table feedback_attempts is
    'Попытки отправки отзыва (D761): предел частоты на учётку; считаются и отклонённые.';

comment on table feedback is
    'Отзывы из кнопки «Обратная связь» (D761): текст, откуда и от кого. Меняются только '
    'отметки «разобрано» и итог отправки в Telegram.';
comment on column feedback.telegram_error is
    'Почему отправка в Telegram не удалась (код, не текст ответа); пусто — отправка не '
    'пытались или она прошла.';
comment on table feedback_photos is
    'Кадры отзыва: сжатая JPEG-копия в самой строке; до пяти на отзыв.';
comment on table feedback_chat is
    'Чат Telegram для отзывов, журнал: текущий — последняя строка; пустой id — выключено. '
    'Пока строк нет, отзывы только сохраняются.';

alter table feedback enable row level security;
alter table feedback force row level security;
create policy feedback_app_access on feedback
    for all to dodo_audit_app using (true) with check (true);
create policy feedback_space_reads on feedback as restrictive
    for select to dodo_audit_app
    using (decimus_space_is_hq() or tenant_code = decimus_space());
create policy feedback_space_inserts on feedback as restrictive
    for insert to dodo_audit_app with check (decimus_space_writes(tenant_code));
create policy feedback_space_updates on feedback as restrictive
    for update to dodo_audit_app
    using (decimus_space_is_hq() or tenant_code = decimus_space())
    with check (decimus_space_is_hq() or tenant_code = decimus_space());

alter table feedback_photos enable row level security;
alter table feedback_photos force row level security;
create policy feedback_photos_app_access on feedback_photos
    for all to dodo_audit_app using (true) with check (true);
create policy feedback_photos_space_reads on feedback_photos as restrictive
    for select to dodo_audit_app
    using (exists (select 1 from feedback f where f.id = feedback_photos.feedback_id));
create policy feedback_photos_space_inserts on feedback_photos as restrictive
    for insert to dodo_audit_app
    with check (exists (select 1 from feedback f where f.id = feedback_photos.feedback_id));

alter table feedback_chat enable row level security;
alter table feedback_chat force row level security;
create policy feedback_chat_app_access on feedback_chat
    for all to dodo_audit_app using (true) with check (true);

alter table feedback_attempts enable row level security;
alter table feedback_attempts force row level security;
create policy feedback_attempts_app_access on feedback_attempts
    for all to dodo_audit_app using (true) with check (true);
create policy feedback_attempts_space on feedback_attempts as restrictive
    for all to dodo_audit_app
    using (decimus_space_writes(tenant_code)) with check (decimus_space_writes(tenant_code));

grant select, insert on feedback, feedback_photos, feedback_chat, feedback_attempts
    to dodo_audit_app;
grant update (reviewed_at, reviewed_by, telegram_sent_at, telegram_error)
    on feedback to dodo_audit_app;
