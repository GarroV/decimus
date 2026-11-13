-- Переводы свободного текста находок сданной проверки (#1619, D744).
--
-- Исходник аудитора лежит строкой `translations` на языке речи проверки и после сдачи
-- заморожен (0004). Перевод на другой язык — производное: отчёт или письмо на языке, которого
-- ещё не было, переводит текст в момент сборки и кладёт рядом (`src/report/finding_text.py`).
-- Запрет вставки на сданной проверке этого не пускал. Снимаем его только для находки и только
-- для языка, отличного от языка речи: исходник сданной проверки по-прежнему не добавить, а
-- правка и удаление остаются под заморозкой (перетереть лежащий перевод нельзя).

drop policy translations_not_added_to_finalized on translations;

create policy translations_not_added_to_finalized on translations
    as restrictive for insert
    with check (not exists (
        select 1 from inspections i
        where i.status = 'finalized'
          and (
              (translations.entity_type = 'inspection' and i.id = translations.entity_id)
              or (translations.entity_type = 'finding'
                  and translations.lang = i.speech_lang
                  and exists (
                      select 1 from findings f
                      where f.id = translations.entity_id and f.inspection_id = i.id))
          )));
