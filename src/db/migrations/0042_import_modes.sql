-- 0042_import_modes.sql
--
-- D332, D334: загрузка проверок через MCP работает в ДВУХ явно разграниченных
-- режимах, и режим — это происхождение проверки.
--
--   field  — обход из бота (как было).
--   import — ТЕКУЩАЯ: недавняя проверка, заведённая задним числом по ДЕЙСТВУЮЩЕЙ
--            версии эталона УК. Записи проверяет и оценку считает движок — как у
--            обхода. `reported_pct`/`reported_grade` — необязательная сверка.
--   legacy — ИСТОРИЧЕСКАЯ: проверка по прежней методике из старого отчёта.
--            Оценка переносится как есть и движком НЕ пересчитывается (D332):
--            `pct = reported_pct`, `grade = reported_grade` (или пусто, если в
--            отчёте буквы не было), вычетов и разбивки по зонам нет, `counts` —
--            простой счёт записей по классам. Это исключение из правила проекта
--            «оценку не считать заново» (CLAUDE.md) — не пересчитывать.
--
-- Смысл значения `import` переопределяется без переноса данных: на проде
-- загруженных проверок нет (09.10.2026 — только `field`).
--
-- Номер 0042, а не 0039: 0039–0041 заняты на соседних ветках (feat/ratings,
-- feat/administration-core, feat/swarm-read-api, feat/swarm-api).
--
-- ПРОИСХОЖДЕНИЕ ПО-ПРЕЖНЕМУ НЕ ПЕРЕПИСЫВАЕТСЯ — триггер
-- `inspections_origin_fixed` (0038) остаётся как есть. Режим черновика задаётся
-- при создании и потом не меняется (D334): перевести текущую в историческую
-- значило бы снять с неё пересчёт движком одной правкой.
--
-- ОЦЕНКА ИСТОРИЧЕСКОЙ ДЕРЖИТСЯ БАЗОЙ. Ограничение `inspections_legacy_score_as_is`
-- требует у `legacy` оценку из отчёта и равенство `pct = reported_pct`: если
-- какой-нибудь путь (правка на приёмке, сверка письма) однажды попробует
-- записать исторической посчитанное движком, запись упадёт, а не разойдётся с
-- отчётом молча.
--
-- ОТКАТ (ручной, миграции вперёд-только):
--   drop index if exists inspections_import_drafts;
--   create index inspections_import_drafts on inspections (tenant_code, pushed_at desc)
--       where origin = 'import' and status = 'draft';
--   alter table inspections
--       drop constraint inspections_legacy_score_as_is,
--       drop constraint inspections_legacy_fields_only_legacy,
--       drop constraint inspections_import_has_no_chat,
--       drop constraint inspections_origin_check,
--       drop column legacy_method, drop column reported_status;
--   alter table inspections
--       add constraint inspections_origin_check check (origin in ('field', 'import')),
--       add constraint inspections_import_has_no_chat check (origin <> 'import' or chat_id = 0);
-- Откат безопасен, пока исторических (`legacy`) проверок нет; с ними — сначала
-- их снять, иначе новое ограничение `origin` не встанет.
--
-- Раннер оборачивает файл в одну транзакцию сам — begin/commit здесь не нужны.

alter table inspections
    drop constraint inspections_origin_check,
    drop constraint inspections_import_has_no_chat;

alter table inspections
    add column reported_status text
        check (reported_status is null or length(btrim(reported_status)) between 1 and 60),
    add column legacy_method text
        check (legacy_method is null or length(btrim(legacy_method)) between 1 and 100),
    add constraint inspections_origin_check
        check (origin in ('field', 'import', 'legacy')),
    add constraint inspections_import_has_no_chat
        check (origin = 'field' or chat_id = 0),
    add constraint inspections_legacy_score_as_is
        check (origin <> 'legacy' or (reported_pct is not null and pct = reported_pct)),
    add constraint inspections_legacy_fields_only_legacy
        check (origin = 'legacy' or (reported_status is null and legacy_method is null));

comment on column inspections.origin is
    'field — обход из бота; import — текущая проверка, заведённая задним числом через MCP по действующей версии эталона УК, оценку считает движок (D334); legacy — историческая из старого отчёта, оценка перенесена как есть и движком не пересчитывается (D332). Подтверждение import и legacy не открывает запрос экшн-плана (D310). Не переписывается (триггер inspections_origin_fixed).';
comment on column inspections.reported_pct is
    'Процент из исходного отчёта. У legacy это и есть оценка проверки (pct = reported_pct, D332). У import — необязательная сверка с оценкой движка (D334).';
comment on column inspections.reported_grade is
    'Буква из исходного отчёта. У legacy — буква проверки как есть (grade = она же или пусто, если в отчёте буквы не было, D332). У import — необязательная сверка.';
comment on column inspections.reported_status is
    'Статус из старого отчёта словами (Passed, Not passed, Issues (D2) …) — только у legacy, показывается как есть (D332).';
comment on column inspections.legacy_method is
    'Метка прежней методики, по которой проведена историческая проверка (например, «Qvalon 133», «старый чек-лист 253») — только у legacy (D332).';
comment on column inspections.source_ref is
    'Ссылка или название исходного документа загруженной проверки (import, legacy).';

-- Очередь черновиков загрузки одного пространства (`import_list_drafts`) —
-- теперь обоих режимов.
drop index if exists inspections_import_drafts;
create index inspections_import_drafts
    on inspections (tenant_code, pushed_at desc)
    where origin in ('import', 'legacy') and status = 'draft';
