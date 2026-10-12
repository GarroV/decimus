-- 0038_inspection_import.sql
--
-- D305–D310: исторические проверки загружаются через MCP поштучно. Коллега с
-- Claude разбирает старый отчёт (Битрикс, PDF, таблица), заводит черновик,
-- вносит записи с пересчётом движком, сверяет с оценкой в старом отчёте и
-- подтверждает сам (D308).
--
-- ЗАГРУЖЕННАЯ — ОБЫЧНАЯ ПРОВЕРКА СВОЕЙ ВЕРСИИ (D306). Отдельной таблицы и
-- отдельного режима чтения нет: строка лежит в `inspections` рядом с
-- обойдёнными, читается теми же запросами и после подтверждения входит в
-- историю точки и аналитику наравне с ними. Отличие одно — происхождение
-- (`origin`), и решает оно ровно две вещи: подтверждение загруженной не
-- открывает запрос экшн-плана (D310, `src/db/accept.py`), а инструменты
-- загрузки правят и удаляют только загруженные черновики.
--
-- ПРОИСХОЖДЕНИЕ НЕ ПЕРЕПИСЫВАЕТСЯ. Иначе роль приложения перевела бы обойдённую
-- проверку с D2 в «загруженные» одной правкой — и подтверждение прошло бы мимо
-- запроса экшн-плана, которого партнёр обязан дождаться (D272). Держит это
-- триггер, а не память кода: колонка выдана приложению вместе с таблицей
-- (`0004`, права на таблицу целиком).
--
-- ОЦЕНКА ИЗ СТАРОГО ОТЧЁТА — ТОЛЬКО ДЛЯ СВЕРКИ. `reported_pct`/`reported_grade`
-- — то, что напечатано в исходном документе. В аналитику они не идут никогда:
-- оценка проверки — `pct`/`grade`, посчитанные движком по её версии методики
-- (CLAUDE.md, «оценку не считать заново»). Расхождение показывается коллеге
-- до подтверждения — по нему видно пропущенную или лишнюю запись.
--
-- ЧАТА У ЗАГРУЗКИ НЕТ: `chat_id = 0`. Колонка `not null` с `0001`, и её читает
-- общий слой чтения (`src/db/queries.py`, `int(row[3])`) — сделать её
-- nullable значило бы менять тип в модели и у всех читателей ради строки,
-- которой никто не пользуется. Телеграм нулевых чатов не выдаёт, поэтому ноль
-- однозначно значит «не из бота», и ограничение ниже держит это равенство в обе
-- стороны для загрузок.
--
-- ОТПЕЧАТОК У ЗАГРУЗКИ — `import:<uuid>`, по одному на черновик. Отпечаток
-- обойдённой — sha256 содержимого (`src/db/fingerprint.py`), и у него другая
-- задача: не дать повторному сливу лечь второй строкой. У загрузки повторного
-- слива нет, а содержимое черновика меняется после создания — отпечаток по
-- содержимому врал бы с первой же записи. Пространство имён `import:` не
-- пересекается с шестнадцатеричным sha256.
--
-- ОТКАТ (ручной, миграции вперёд-только):
--   drop trigger inspections_origin_fixed on inspections;
--   drop function guard_inspection_origin();
--   alter table inspections drop constraint inspections_import_has_no_chat,
--       drop column source_ref, drop column reported_grade,
--       drop column reported_pct, drop column origin;
--   drop index if exists inspections_import_drafts;
-- Откат безопасен, пока загруженных проверок нет; с ними — теряется признак,
-- по которому их подтверждение не открывает запрос экшн-плана.
--
-- Раннер оборачивает файл в одну транзакцию сам — begin/commit здесь не нужны.

alter table inspections
    add column origin text not null default 'field'
        check (origin in ('field', 'import')),
    add column reported_pct numeric(5, 2)
        check (reported_pct is null or (reported_pct >= 0 and reported_pct <= 100)),
    add column reported_grade text
        check (reported_grade is null or length(btrim(reported_grade)) between 1 and 8),
    add column source_ref text
        check (source_ref is null or length(btrim(source_ref)) between 1 and 1000),
    add constraint inspections_import_has_no_chat
        check (origin <> 'import' or chat_id = 0);

comment on column inspections.origin is
    'field — проверка обхода из бота; import — историческая, загруженная через MCP поштучно (D305). Загруженная читается как обычная своей версии методики (D306); её подтверждение не открывает запрос экшн-плана (D310). Не переписывается (триггер inspections_origin_fixed).';
comment on column inspections.reported_pct is
    'Процент, напечатанный в исходном старом отчёте (D305). Только для сверки при загрузке, в аналитику не идёт: оценка проверки — pct, посчитанный движком.';
comment on column inspections.reported_grade is
    'Буква, напечатанная в исходном старом отчёте (D305). Только для сверки, как reported_pct.';
comment on column inspections.source_ref is
    'Ссылка или название исходного документа загруженной проверки (Битрикс, PDF, таблица).';

create function guard_inspection_origin() returns trigger
    language plpgsql
    set search_path = pg_catalog, public, pg_temp
as $$
begin
    if new.origin is distinct from old.origin then
        raise exception 'происхождение проверки % не переписывается (0038, D310)', old.id
            using errcode = 'check_violation';
    end if;
    return new;
end;
$$;

create trigger inspections_origin_fixed
    before update of origin on inspections
    for each row execute function guard_inspection_origin();

-- Очередь черновиков загрузки одного пространства (`import_list_drafts`).
create index inspections_import_drafts
    on inspections (tenant_code, pushed_at desc)
    where origin = 'import' and status = 'draft';
