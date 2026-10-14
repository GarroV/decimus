-- 0071_finding_reading.sql
--
-- #855 (D495): показание термометра, которое аудитор подтвердил или исправил
-- (#836), — факт проверки и обязано пережить сдачу. До этой миграции число жило
-- только в файле проверки (блок `domain.readings`) и терялось при сливе.
--
-- NULL — замера у записи нет. Пределы те же, что у домена
-- (`READING_MIN_C`/`READING_MAX_C`, `src/domain/models.py`): вне них число —
-- мусор распознавания или опечатка, а не измерение.
--
-- Колонка дописывается в конец списков выборки (позиционный разбор, см. 0024).
-- Права на таблицу выданы целиком (0004), отдельный грант не нужен.

alter table findings
    add column if not exists reading_c numeric(5, 1);

alter table findings
    add constraint findings_reading_c_is_a_temperature
    check (reading_c is null or reading_c between -60 and 500);

comment on column findings.reading_c is
    'Показание термометра, °C, подтверждённое или исправленное аудитором (#836, D495). NULL — замера нет.';
