# 40. Языки: где живут, как добавить новый

> Ручной документ. Канон по теме «язык» — здесь; карта кода (`docs/00-map.md`)
> и инвентарь ссылаются сюда, а не повторяют. Правите код из таблиц ниже —
> правьте документ тем же коммитом.

## Что это и зачем

Проверка ведётся на одном языке, а отчёт и письмо партнёру уходят на другом:
аудитор говорит по-русски, партнёр в Сербии читает по-английски. Поэтому язык в
продукте — не одна настройка, а **четыре разных**, и путать их нельзя:

| Язык | Чей | Где выбирается | Где хранится |
|---|---|---|---|
| Интерфейса | человека | веб: меню учётки, «Настройки», вход; бот: `/lang` | профиль учётки (`web_own_profile`), `bot_ui_langs` (0035) |
| Речи аудитора | проверки | бот и мини-апп на старте | `inspections.speech_lang` |
| Чек-листа | человека | мини-апп на старте (D451) | `checklist_langs` (0057) |
| Отчёта | проверки | конец проверки: бот (`src/bot/report_lang.py`), мини-апп (`walk-finish.js`) | `inspections.report_lang` |

Какие языки отчёта предлагать в стране — данные, не код: сначала перекрытие из
вкладки «Администрирование → Страны» (`country_report_langs`, 0098, D640), затем
`report_langs.json` в каталоге методики (`src/domain/report_langs.py`, D415).

## Что переводится чем

| Что | Откуда текст на нужном языке |
|---|---|
| Формулировки методики: процесс, вопрос, зона, подпись оценки, примечание D3 | файлы версии методики: `checklist.csv` (`process_<яз>`, `question_<яз>`), `zones.csv` (`name_<яз>`), `scoring.json` (`label_<яз>`, `d3_note_<яз>`) |
| Постоянные тексты отчёта и письма | каталоги в коде: `engine/report.py` (`T`, `GRADE_NOTE`, `ITEM_REF`, `LETTER_*`, `LETTER_FEEDBACK`, `LETTER_COUNTS`, `LETTER_CRITICAL`, `TIME_UNITS`, `FILE_WORDS`), `src/report/batch_letter_texts.py`, `src/domain/mailing_content.py` (`DEFAULTS`), `src/domain/item_label.py` (`SPECIAL_TITLES`), `src/web/google_mail.py` (`SUBJECT_TITLES`), `src/domain/kinds.py` и `engine/audit.py` (`INSPECTION_KINDS` — две копии). Полноту по `REPORT_LANGS` держит `tests/test_lang_catalogs_complete.py` |
| Названия городов в письме | `src/domain/geo.py` (`CITIES`) |
| Шаблоны писем, правленные в админке | таблица `mailing_templates` (0104; язык — код из двух букв с 0131) |
| Свободный текст аудитора (комментарий, ответ) | переводит модель: `src/recognize/translate.py` (названия языков — `_LANG_NAMES`, есть и турецкий); в конце проверки — `src/bot/finish_translate.py`, в мини-аппе — `src/web/walk_translate.py` |
| Тексты интерфейса | веб — `src/web/texts*.py`, бот — `src/bot/texts.py`; полноту по языкам держат `tests/test_web_texts.py` и тест бота |

Таблица `translations` (0001) и колонки `lang` в 0019/0057/0098/0128/0131 от числа
языков не зависят.

## Какие списки языков есть в коде

Список языков в коде — два, с разными ролями (#541, `src/domain/models.py`):

| Список | Что значит | Кто его читает |
|---|---|---|
| `REPORT_LANGS` | на каком языке можно напечатать отчёт, письмо, методику | движок (`LANGS`), отчёт, письма (одиночное и общее), страны, MCP, шаблоны писем, подпись оценки в базе |
| `SPEECH_LANGS` | на каком языке говорит аудитор | бот и мини-апп (`LANG_LABELS`), перевод в мини-аппе (`walk_translate`), словарь зон (`zone_words`) |

Сейчас оба — `("ru", "en")`. Поле на языке берётся по имени `<поле>_<язык>`
(`pick_lang`, `localized` в `models.py`; в движке — `lang_fields` и f-строки по
`LANGS`): языка нет в списке — отказ, а не откат на русский. Откат остаётся только
там, где он и был: подпись пункта без перевода показывается на другом языке методики
(`item_label.py`, `methodology_view.py`, `import_draft.py`).

Движок — отдельный подпроцесс и `src` не импортирует: его копии `LANGS` и `BASE_LANG`
(`engine/audit.py`), а также `INSPECTION_KINDS` держатся равными списку продукта
тестом (`tests/test_lang_catalogs_complete.py`, `tests/test_engine_kind_code.py`).

Что ещё зашито парой `ru`/`en` и останется до этапа 2 (#1619):

* **Поля в моделях.** `ChecklistItem`, `Zone`, `ZoneScore`, `ProcessScore`, `Score`
  (`src/domain/models.py`) хранят `process_ru`/`process_en`, `title_*`, `name_*`,
  `label_*` полями; их читают по имени, но завести третье поле они сами не умеют, как и
  загрузчики `src/domain/checklist.py`, `scoring.py`, `ItemTexts` (`item_label.py`).
* **База.** Рейтинги (0039) и план действий (0092, `src/report/plan_terms.py`,
  `src/mcp/plans.py: PLAN_LANGS`, `src/db/plan_rows.py`) — колонки `name_ru`/`name_en`
  и `title_*`; названия чек-листов (`name_ru`/`name_en` в `src/mcp/checklists.py`).
* **Движок.** `plan_due_date` ищет «план действий» / «action plan» по тексту вопроса;
  `engine/manage.py`: `backfill-processes` (справочник `PROCESS_NAMES_EN`) и
  `import-xlsx` (колонки `(en)`) знают только английский как второй язык.
* **Прочее.** `FALLBACK_LANGS` в `src/domain/report_langs.py` (перечень, когда файла
  нет совсем) и описание документа предписания по-английски
  (`src/web/prescription_notice.py`, D601) — парой; страны (`COUNTRIES` в `geo.py`)
  в тест полноты не входят.

## Выгрузка готовой проверки на другом языке

* **Письмо** — можно: выпадающий список языка в `_letter_form.html` (одиночное) и
  `country/_batch.html` (общее, D739); язык проверяется по `REPORT_LANGS`, по
  умолчанию — `report_lang` проверки (`src/report/letters.py`, `src/report/batch_letter.py`).
* **PDF** — нельзя: `/…/<id>/report` печатает на `report_lang`, хранится один PDF
  на проверку (`inspection_reports`, 0018, без `lang`), пересборка — только при
  смене содержимого (`src/report/current_pdf.py`).
* **Свободный текст.** `finish_translate.py` переводит комментарий на язык отчёта
  и **затирает** исходник — второй перевод делается уже с перевода.
* **Исторические проверки** (`origin = 'legacy'`, D332) не пересобираются ни на
  каком языке: их отчёт перенесён как есть (`docs/14-history-import.md`, D743).

## Переключатели языка в интерфейсе

| Где | Сейчас |
|---|---|
| Язык сайта: шапка, меню учётки, лендинг, «Настройки» — `templates/_langpick.html` | пилюля сегментами (`.langpill`) |
| Вход — `templates/_login_lang.html` | пилюля; при > 2 языках — меню `<details>` |
| Язык письма — `_letter_form.html`, `country/_batch.html` | `<select class="pickselect">` |
| Языки отчёта страны — `country/_settings.html` | флажки |
| Мини-апп: язык интерфейса, язык отчёта, подсказки — `walk-app.js`, `walk-finish.js`, `walk-hints.js` | пилюля |

D743: переключатели языка — выпадающим списком в дизайне forma, языки кодами
(`RU`, `EN`, `TR`).

## Как добавить язык

1. Строка в `REPORT_LANGS` (`src/domain/models.py`) и в `LANGS` движка
   (`engine/audit.py`) — тест `tests/test_lang_catalogs_complete.py` сверяет их и сразу
   покажет, в каком каталоге нет перевода: ключ и язык названы в сообщении.
2. Перевести постоянные тексты (раздел «Что переводится чем»), пока тест полноты не
   позеленеет.
3. Колонки `*_<яз>` во все версии методики, по которым будут выгружать проверки
   (`checklist.csv`, `zones.csv`, `scoring.json`); инструменты правки методики
   (`engine/manage.py`, MCP `add_checklist_item` и др.) выводят поля из списка сами.
4. Поля в моделях и загрузчиках — см. «Что ещё зашито парой» выше (этап 2, #1619).
5. Язык интерфейса и речи — отдельно: `UI_LANGS` и `SPEECH_LANGS`, только если он там
   нужен; язык отчётов страны — вкладка «Страны».
6. Проверить эталоны: `examples/belgrade-1` — 97.5%, A; `belgrade-2` — 97.0%, A.
