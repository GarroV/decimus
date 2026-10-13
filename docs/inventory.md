# Инвентарь кода

> Генерируется `make map`, руками не править: таблицы ниже собираются из кода
> (`tools/gen_map.py`), а `tests/test_docs_map.py` краснеет, если они отстали. Где
> лежит файл и что в нём — [`00-map.md`](00-map.md).
>
> Откуда что берётся. **Маршруты** — из `url_map` настоящих приложений: фабрики
> `create_app` и `create_walk_app` вызываются на чистом окружении с заглушками
> адресов (поэтому маршруты OAuth присутствуют: они включаются, когда заданы
> публичные адреса). **Инструменты MCP** — из объекта `TOOLS` каталога.
> **Переменные окружения** — статический разбор AST: чтение `os.environ`/`getenv`,
> чтение из словаря окружения по имени и константы вида `*_VAR`; чтение с динамически
> собранным именем сюда не попадёт. **Таблицы** — из `create table` в миграциях;
> созданные иначе (динамическим SQL) и переименованные позже здесь не отслеживаются. **Цели
> Makefile** — описание после `##` в строке цели, а без него — комментарий над ней.

## Маршруты веба

<!-- map:begin routes -->
**Админка (`src/web/app.py: create_app`)** — 126 маршрутов

| Путь | Методы | Endpoint | Файл |
|---|---|---|---|
| `/` | GET | `home` | `src/web/app.py` |
| `/.well-known/oauth-authorization-server` | GET | `oauth_metadata` | `src/web/oauth.py` |
| `/actions` | GET | `actions` | `src/web/action_plans.py` |
| `/actions/prescriptions` | GET | `rx_list` | `src/web/prescriptions.py` |
| `/actions/prescriptions` | POST | `rx_create` | `src/web/prescriptions.py` |
| `/actions/prescriptions/<prescription_id>` | GET | `rx_view` | `src/web/prescriptions.py` |
| `/actions/prescriptions/<prescription_id>/close` | POST | `rx_close` | `src/web/prescriptions.py` |
| `/actions/prescriptions/<prescription_id>/edit` | GET | `rx_edit` | `src/web/prescriptions.py` |
| `/actions/prescriptions/<prescription_id>/edit` | POST | `rx_update` | `src/web/prescriptions.py` |
| `/actions/prescriptions/<prescription_id>/send` | POST | `rx_send` | `src/web/prescriptions.py` |
| `/actions/prescriptions/new` | GET | `rx_new` | `src/web/prescriptions.py` |
| `/actions/request` | POST | `actions_new` | `src/web/action_plans.py` |
| `/actions/requests/<request_id>` | GET | `actions_request` | `src/web/action_plans.py` |
| `/actions/requests/<request_id>/due` | POST | `actions_due` | `src/web/action_plans.py` |
| `/actions/requests/<request_id>/review` | POST | `actions_review` | `src/web/action_plans.py` |
| `/admin` | GET | `methodology` | `src/web/app.py` |
| `/admin/bot/<code>` | POST | `methodology_bot` | `src/web/app.py` |
| `/admin/checklists` | GET | `checklists` | `src/web/app.py` |
| `/admin/checklists` | POST | `checklists_create` | `src/web/app.py` |
| `/admin/checklists/<code>/apply` | GET | `checklists_apply_preview` | `src/web/app.py` |
| `/admin/checklists/<code>/apply` | POST | `checklists_apply` | `src/web/app.py` |
| `/admin/checklists/<code>/master` | POST | `checklists_master` | `src/web/app.py` |
| `/admin/checklists/<code>/state` | POST | `checklists_state` | `src/web/app.py` |
| `/admin/items` | POST | `methodology_add` | `src/web/app.py` |
| `/admin/items/<code>` | GET | `methodology_item` | `src/web/app.py` |
| `/admin/items/<code>` | POST | `methodology_edit` | `src/web/app.py` |
| `/admin/items/<code>/disable` | POST | `methodology_disable` | `src/web/app.py` |
| `/admin/items/<code>/restore` | POST | `methodology_restore` | `src/web/app.py` |
| `/admin/publish` | POST | `methodology_publish` | `src/web/app.py` |
| `/admin/route` | POST | `methodology_route` | `src/web/app.py` |
| `/admin/scoring` | POST | `methodology_scoring` | `src/web/app.py` |
| `/admin/zones` | POST | `methodology_zone_add` | `src/web/app.py` |
| `/admin/zones/<code>/remove` | POST | `methodology_zone_remove` | `src/web/app.py` |
| `/admin/zones/<code>/rename` | POST | `methodology_zone_rename` | `src/web/app.py` |
| `/admin/zones/shares` | POST | `methodology_zone_shares` | `src/web/app.py` |
| `/api/v1/aggregators/ratings` | GET | `swarm_api_aggregators` | `src/web/swarm_api.py` |
| `/api/v1/inspections` | GET | `swarm_api_inspections` | `src/web/swarm_api.py` |
| `/api/v1/inspections/<inspection_id>` | GET | `swarm_api_inspection` | `src/web/swarm_api.py` |
| `/api/v1/inspections/violations` | GET | `swarm_api_inspection_violations` | `src/web/swarm_api.py` |
| `/api/v1/maps/ratings` | GET | `swarm_api_maps` | `src/web/swarm_api.py` |
| `/api/v1/ratings/checkups` | GET | `swarm_api_checkups` | `src/web/swarm_api.py` |
| `/api/v1/ratings/scores` | GET | `swarm_api_scores` | `src/web/swarm_api.py` |
| `/api/v1/ratings/violations` | GET | `swarm_api_violations` | `src/web/swarm_api.py` |
| `/auth/google/callback` | GET | `google_callback` | `src/web/auth.py` |
| `/auth/google/mail` | GET | `google_mail_callback` | `src/web/letter_draft.py` |
| `/calendar` | GET | `calendar` | `src/web/app.py` |
| `/country` | GET | `country_index` | `src/web/app.py` |
| `/country/<code>` | GET | `country` | `src/web/app.py` |
| `/country/<code>/units/new` | GET | `unit_new` | `src/web/unit_add.py` |
| `/country/<code>/units/new` | POST | `unit_create` | `src/web/unit_add.py` |
| `/inspections` | GET | `registry` | `src/web/app.py` |
| `/inspections/<inspection_id>` | GET | `card` | `src/web/app.py` |
| `/inspections/<inspection_id>/accept` | POST | `do_accept` | `src/web/app.py` |
| `/inspections/<inspection_id>/findings/<finding_id>/revise` | POST | `do_revise` | `src/web/app.py` |
| `/inspections/<inspection_id>/letter` | GET | `letter` | `src/web/app.py` |
| `/inspections/<inspection_id>/letter/draft` | POST | `letter_draft` | `src/web/letter_draft.py` |
| `/inspections/<inspection_id>/letter/save` | POST | `save_letter` | `src/web/app.py` |
| `/inspections/<inspection_id>/move` | POST | `do_move` | `src/web/app.py` |
| `/inspections/<inspection_id>/photos/<photo_id>` | GET | `photo` | `src/web/app.py` |
| `/inspections/<inspection_id>/report` | GET | `report` | `src/web/app.py` |
| `/inspections/<inspection_id>/retract` | POST | `do_retract` | `src/web/app.py` |
| `/login` | GET, POST | `login` | `src/web/auth.py` |
| `/login/google` | GET | `google_start` | `src/web/auth.py` |
| `/logout` | POST | `logout` | `src/web/auth.py` |
| `/oauth/authorize` | GET, POST | `oauth_authorize` | `src/web/oauth.py` |
| `/oauth/register` | POST | `oauth_register` | `src/web/oauth.py` |
| `/oauth/token` | POST | `oauth_token` | `src/web/oauth.py` |
| `/overview` | GET | `overview` | `src/web/app.py` |
| `/plans` | GET | `plans` | `src/web/action_plans.py` |
| `/plans/<request_id>/upload` | POST | `plans_upload` | `src/web/action_plans.py` |
| `/plans/files/<file_id>` | GET | `plan_file` | `src/web/action_plans.py` |
| `/prescriptions` | GET | `orders` | `src/web/prescriptions.py` |
| `/prescriptions/<prescription_id>` | GET | `order` | `src/web/prescriptions.py` |
| `/prescriptions/<prescription_id>/reply` | POST | `order_reply` | `src/web/prescriptions.py` |
| `/prescriptions/files/<reply_id>` | GET | `order_file` | `src/web/prescriptions.py` |
| `/ratings` | GET | `ratings` | `src/web/ratings.py` |
| `/ratings/aggregators/update` | POST | `ratings_agg_update` | `src/web/ratings.py` |
| `/ratings/countries` | POST | `ratings_developer` | `src/web/ratings.py` |
| `/ratings/coverage` | GET | `ratings_coverage` | `src/web/ratings.py` |
| `/ratings/coverage/link` | POST | `ratings_coverage_link` | `src/web/ratings.py` |
| `/ratings/hard-rules` | POST | `ratings_rule_add` | `src/web/ratings.py` |
| `/ratings/hard-rules/<int:rule_id>/delete` | POST | `ratings_rule_remove` | `src/web/ratings.py` |
| `/ratings/import` | POST | `ratings_upload` | `src/web/ratings.py` |
| `/ratings/imports` | GET | `ratings_imports` | `src/web/ratings.py` |
| `/ratings/layout` | POST | `ratings_layout` | `src/web/ratings.py` |
| `/ratings/settings` | POST | `ratings_settings` | `src/web/ratings.py` |
| `/settings` | GET | `settings_page` | `src/web/settings_screen.py` |
| `/settings/avatar` | GET | `settings_avatar` | `src/web/settings_screen.py` |
| `/settings/bot-link` | POST | `settings_bot_link` | `src/web/settings_screen.py` |
| `/settings/bot-unlink` | POST | `settings_bot_unlink` | `src/web/settings_screen.py` |
| `/settings/claude-revoke` | POST | `settings_claude_revoke` | `src/web/settings_screen.py` |
| `/settings/claude-token` | POST | `settings_claude_token` | `src/web/settings_screen.py` |
| `/settings/claude-token-revoke` | POST | `settings_claude_token_revoke` | `src/web/settings_screen.py` |
| `/settings/confirm` | GET | `reauth_confirm` | `src/web/reauth.py` |
| `/settings/confirm` | POST | `reauth_confirm_password` | `src/web/reauth.py` |
| `/settings/confirm/google` | POST | `reauth_confirm_google` | `src/web/reauth.py` |
| `/settings/continue` | POST | `settings_continue` | `src/web/settings_screen.py` |
| `/settings/google-link` | POST | `settings_google_link` | `src/web/settings_screen.py` |
| `/settings/google-unlink` | POST | `settings_google_unlink` | `src/web/settings_screen.py` |
| `/settings/lang` | POST | `settings_lang` | `src/web/ui_lang.py` |
| `/settings/menu` | GET | `settings_menu` | `src/web/settings_screen.py` |
| `/settings/password` | POST | `settings_own_password` | `src/web/settings_screen.py` |
| `/static/<path:filename>` | GET | `static` | (библиотека) |
| `/tg/walk` | GET | `walk_page` | `src/web/walk_proxy.py` |
| `/tg/walk/app` | POST | `walk_app` | `src/web/walk_proxy.py` |
| `/tg/walk/data` | POST | `walk_data` | `src/web/walk_proxy.py` |
| `/tg/walk/finding` | POST | `walk_finding` | `src/web/walk_proxy.py` |
| `/tg/walk/info` | POST | `walk_info` | `src/web/walk_proxy.py` |
| `/tg/walk/photo` | POST | `walk_photo` | `src/web/walk_proxy.py` |
| `/tg/walk/photo/view` | POST | `walk_photo_view` | `src/web/walk_proxy.py` |
| `/tg/walk/start` | POST | `walk_start` | `src/web/walk_proxy.py` |
| `/tg/walk/suggest` | POST | `walk_suggest` | `src/web/walk_proxy.py` |
| `/tg/walk/translate` | POST | `walk_translate` | `src/web/walk_proxy.py` |
| `/units/<unit_id>` | GET | `unit` | `src/web/app.py` |
| `/users` | GET | `users` | `src/web/users_screen.py` |
| `/users/add` | POST | `add_user` | `src/web/users_screen.py` |
| `/users/bot-unlink` | POST | `bot_unlink` | `src/web/users_screen.py` |
| `/users/connections/<int:token_id>/reissue` | POST | `connections_reissue` | `src/web/connections_screen.py` |
| `/users/connections/<int:token_id>/revoke` | POST | `connections_revoke` | `src/web/connections_screen.py` |
| `/users/connections/<int:token_id>/update` | POST | `connections_update` | `src/web/connections_screen.py` |
| `/users/connections/issue` | POST | `connections_issue` | `src/web/connections_screen.py` |
| `/users/disable` | POST | `disable_user` | `src/web/users_screen.py` |
| `/users/email` | POST | `user_email` | `src/web/users_screen.py` |
| `/users/role` | POST | `user_role` | `src/web/users_screen.py` |
| `/users/spaces/add` | POST | `add_space` | `src/web/users_screen.py` |
| `/users/spaces/countries` | POST | `space_countries` | `src/web/users_screen.py` |

**Мини-апп обхода (`src/web/walk_app.py: create_walk_app`)** — 11 маршрутов

| Путь | Методы | Endpoint | Файл |
|---|---|---|---|
| `/static/<path:filename>` | GET | `static` | (библиотека) |
| `/tg/walk` | GET | `walk_page` | `src/web/walk.py` |
| `/tg/walk/app` | POST | `walk_app` | `src/web/walk_settings.py` |
| `/tg/walk/data` | POST | `walk_data` | `src/web/walk.py` |
| `/tg/walk/finding` | POST | `walk_finding` | `src/web/walk_write.py` |
| `/tg/walk/info` | POST | `walk_info` | `src/web/walk_write.py` |
| `/tg/walk/photo` | POST | `walk_photo` | `src/web/walk_write.py` |
| `/tg/walk/photo/view` | POST | `walk_photo_view` | `src/web/walk_write.py` |
| `/tg/walk/start` | POST | `walk_start` | `src/web/walk_start.py` |
| `/tg/walk/suggest` | POST | `walk_suggest` | `src/web/walk_suggest.py` |
| `/tg/walk/translate` | POST | `walk_translate` | `src/web/walk_translate.py` |
<!-- map:end -->

## Инструменты MCP

<!-- map:begin mcp -->
Всего **56** инструментов (checklist — 33, checklist_source — 2, import — 9, inspections — 6, ratings — 2, ratings_read — 3, retraction — 1).

| Инструмент | Вид | Что делает (описание для агента) | Обработчик |
|---|---|---|---|
| `add_checklist_item` | checklist | Add a checklist item | `src/mcp/checklist_tools.py` |
| `add_photo_cue` | checklist | Add one cue row to the word map, storing a new methodology version beside the one in force — the version in force does… | `src/mcp/checklist_tools.py` |
| `add_zone` | checklist | Add a physical zone (e.g | `src/mcp/checklist_tools.py` |
| `apply_checklist` | checklist | Apply a checklist to production: inspections are scored against it from now on | `src/mcp/checklists_tools.py` |
| `checklist_item` | checklist | Read one checklist item together with its D1/D2/D3 criteria — the only source of what makes a finding D1 versus D2… | `src/mcp/checklist_tools.py` |
| `checklist_items` | checklist | List the checklist items of one methodology version, in file order, together with the version's zones | `src/mcp/checklist_tools.py` |
| `checklist_meta` | checklist | Read one checklist's card: code, both names, state, whether it is applied to production and which edition it publishes | `src/mcp/checklists_tools.py` |
| `checklist_versions` | checklist | List every stored checklist version, newest first | `src/mcp/checklist_tools.py` |
| `checklists` | checklist | List the checklists visible to this tenant: code, names, state (draft / active / retired) and which one is applied to… | `src/mcp/checklists_tools.py` |
| `create_checklist` | checklist | Create a new checklist from the blank: an empty item list, one zone at 100 per cent and blank scoring rates | `src/mcp/checklists_tools.py` |
| `edit_checklist_item` | checklist | Edit fields of an existing checklist item | `src/mcp/checklist_tools.py` |
| `edit_photo_cue` | checklist | Change one cue row of the word map — its codes, its phrase, or both — storing a new methodology version beside the one… | `src/mcp/checklist_tools.py` |
| `learned_phrases` | checklist | Show the synonym map: the wordings auditors actually used on site that the product has learned, and the checklist item… | `src/mcp/phrases.py` |
| `photo_cue_suggestions` | checklist | Report where the model has been systematically wrong, and propose what to add to the word map because of it | `src/mcp/checklist_tools.py` |
| `photo_cues` | checklist | Read the word map of one methodology version: the sections and the cue rows inside them, each a phrase an auditor might… | `src/mcp/checklist_tools.py` |
| `publish_checklist_version` | checklist | Make a stored checklist version the one the audit engine scores inspections by | `src/mcp/checklist_tools.py` |
| `remove_checklist_item` | checklist | Disable a checklist item | `src/mcp/checklist_tools.py` |
| `remove_photo_cue` | checklist | Remove one cue row from the word map, storing a new methodology version beside the one in force | `src/mcp/checklist_tools.py` |
| `remove_zone` | checklist | Remove a physical zone | `src/mcp/checklist_tools.py` |
| `rename_checklist` | checklist | Change a checklist's names | `src/mcp/checklists_tools.py` |
| `rename_zone` | checklist | Rename a zone: change the Russian and/or English name the auditor sees on site and the partner reads in the report | `src/mcp/checklist_tools.py` |
| `repoint_learned_phrase` | checklist | Point a learned wording at a different checklist item — and bring a retracted one back into work | `src/mcp/phrases.py` |
| `restore_checklist_item` | checklist | Re-enable a checklist item previously disabled by remove_checklist_item | `src/mcp/checklist_tools.py` |
| `retract_learned_phrase` | checklist | Retract a learned wording from the synonym map, so that it stops matching and stops proposing a record | `src/mcp/phrases.py` |
| `route` | checklist | Read the walking route of one methodology version: the order in which the auditor physically walks the pizzeria … | `src/mcp/checklist_tools.py` |
| `scoring` | checklist | Read the deduction rates of a checklist edition: the starting percentage, the price of each violation class and the… | `src/mcp/checklist_tools.py` |
| `set_checklist_bot_access` | checklist | Open a checklist to auditors in the Telegram bot, or close it | `src/mcp/checklists_tools.py` |
| `set_checklist_state` | checklist | Set a checklist's state: draft, active or retired | `src/mcp/checklists_tools.py` |
| `set_photo_cue_zone` | checklist | Set the object's zone on one cue row of the word map, storing a new methodology version beside the one in force | `src/mcp/checklist_tools.py` |
| `set_route` | checklist | Set the walking route: the order in which the auditor goes through the pizzeria | `src/mcp/checklist_tools.py` |
| `set_scoring` | checklist | Set the deduction rates of the checklist: starting percentage, the price of a D1 and of a D2 violation, and how much… | `src/mcp/checklist_tools.py` |
| `set_zone_shares` | checklist | Set the share (weight in the score) of zones that already exist | `src/mcp/checklist_tools.py` |
| `uncovered_phrases` | checklist | List the words auditors say on site that still produce no record, most frequent first, with the zone each was said in… | `src/mcp/checklist_tools.py` |
| `checklist_source` | checklist_source | Read the checklist the caller is audited against: its items (what is checked), the violation classes each item can… | `src/mcp/checklist_source.py` |
| `checklist_source_item` | checklist_source | Read one item of the checklist the caller is audited against, together with the D1/D2/D3 criteria that decide which… | `src/mcp/checklist_source.py` |
| `import_accept_inspection` | import | Accept an imported draft after the person has checked it (the person who imported it accepts it) | `src/mcp/imports.py` |
| `import_add_finding` | import | Add one finding from the report to an imported draft | `src/mcp/imports.py` |
| `import_add_photo` | import | Attach a photo from the old report to one finding of an imported draft | `src/mcp/imports.py` |
| `import_create_inspection` | import | Start entering ONE inspection after the fact: creates a DRAFT with no findings | `src/mcp/imports.py` |
| `import_discard_draft` | import | Delete an imported DRAFT entirely, with its findings and photos — e.g | `src/mcp/imports.py` |
| `import_edit_finding` | import | Correct one finding of an imported draft by its number n | `src/mcp/imports.py` |
| `import_get_inspection` | import | Read an imported inspection (draft or accepted): its mode, header and findings with their numbers | `src/mcp/imports.py` |
| `import_list_drafts` | import | List this space's imported drafts that are not accepted yet: mode (history/current), unit, date, checklist version… | `src/mcp/imports.py` |
| `import_remove_finding` | import | Remove one finding (with its photos) from an imported draft by its number n | `src/mcp/imports.py` |
| `findings_by_unit` | inspections | List the recorded findings of one unit (pizzeria) across all its inspections, most recent inspection first, exactly as… | `src/mcp/tools.py` |
| `get_inspection` | inspections | Read one recorded inspection of the caller's tenant in full: its header, the score breakdown (percentage, letter grade… | `src/mcp/tools.py` |
| `inspection_letter` | inspections | Rebuild the partner letter for one recorded inspection of the caller's tenant and return its text, ready for a human to… | `src/mcp/tools.py` |
| `list_inspections` | inspections | List recorded inspections for the caller's tenant, most recent first | `src/mcp/tools.py` |
| `network_summary` | inspections | Summarize the caller's tenant network over a date range: how many inspections and units, total findings, the… | `src/mcp/tools.py` |
| `unit_history` | inspections | Read the recorded score history of one unit (pizzeria), most recent inspection first — a series of percentages and… | `src/mcp/tools.py` |
| `import_ratings` | ratings | Upload a ratings file into Decimus (standards and customer-experience ratings, IMF only) | `src/mcp/ratings_tools.py` |
| `request_aggregators_update` | ratings | Запросить внеочередное обновление оценок пиццерий в агрегаторах доставки (Wolt, Glovo, Bolt Food, Yemeksepeti, Trendyol… | `src/mcp/ratings_tools.py` |
| `aggregators_status` | ratings_read | Состояние сбора оценок в агрегаторах доставки: по каждому — когда был последний сбор, чем кончился (ok, failed или… | `src/mcp/ratings_read.py` |
| `ratings_summary` | ratings_read | Сводка рейтингов РС (рейтинг стандартов) и РКО (рейтинг клиентского опыта) по группам стран за период: средняя оценка… | `src/mcp/ratings_read.py` |
| `ratings_units` | ratings_read | Оценки отдельных пиццерий за период: РС и РКО (среднее по периодам рейтинга), оценка на картах Google (из 5, число… | `src/mcp/ratings_read.py` |
| `retract_inspection` | retraction | Retract a finalized inspection from the history | `src/mcp/retraction.py` |
<!-- map:end -->

## Переменные окружения

Читаются кодом в `src/`, `tools/`, `scripts/`, `engine/`. «Нет» в последней колонке
допустимо только для переменных, которые задаёт сам код подпроцессу или рычаг
сборки, и причина тут же; остальные обязаны быть в `.env.example`.

<!-- map:begin env -->
| Переменная | Где читается | В `.env.example` |
|---|---|---|
| `ACTION_PLAN_DUE_DAYS` | `src/db/config.py` | да |
| `ADMIN_PUBLIC_URL` | `src/domain/public_urls.py`, `tools/oauth_smoke.py` | да |
| `ALLOWED_TELEGRAM_IDS` | `src/bot/config.py` | да |
| `API_TOKEN_BY` | `tools/api_token.py` | да |
| `ATTACHMENT_MAX_MB` | `src/db/config.py` | да |
| `AUDITOR_NAMES` | `src/bot/config.py` | да |
| `AUDIT_DATA_DIR` | `src/domain/config.py`, `src/mcp/config.py`, `src/report/letters.py` и ещё 6 | да |
| `BACKUP_DIR` | `tools/state_backup.py` | да |
| `BACKUP_KEEP_DAYS` | `tools/state_backup.py` | да |
| `BOT_MCP_URL` | `src/bot/mcp_setup.py`, `tools/mcp_outside.py` | да |
| `BOT_MODE` | `src/bot/config.py` | да |
| `BOT_UI_LANG` | `src/bot/texts.py` | да |
| `BOT_WALK_URL` | `src/bot/config.py` | да |
| `BUILD_SHA` | `src/bot/version.py` | да |
| `CHECKLIST_DIR` | `engine/audit.py` | нет — подставляется кодом в окружение подпроцесса движка (src/domain/engine.py) |
| `COMPOSE_PROFILES` | `tools/mcp_healthcheck.py` | да |
| `DATABASE_ADMIN_URL` | `src/db/migrate.py`, `tools/seed_web_demo.py` | да |
| `DATABASE_APP_PASSWORD` | `src/db/migrate.py` | да |
| `DATABASE_RETRACTION_PASSWORD` | `src/db/migrate.py` | да |
| `DATABASE_RETRACTION_URL` | `src/db/config.py`, `tools/seed_web_demo.py` | да |
| `DATABASE_URL` | `src/db/config.py`, `src/mcp/config.py` | да |
| `DB_POOL_MAX` | `src/db/pool.py` | да |
| `DB_POOL_TIMEOUT_S` | `src/db/pool.py` | да |
| `DEMO_STATE_DIR` | `tools/seed_demo.py` | да |
| `DODO_MCP_TOKEN` | `tools/mcp_outside.py` | да |
| `DODO_MCP_URL` | `tools/mcp_outside.py` | да |
| `FFMPEG_BIN` | `src/recognize/config.py` | да |
| `FRAMES_DIR` | `src/bot/frame_copies.py` | да |
| `FURCA_NOTIFY_URL` | `src/ratings/aggregators/alert.py` | да |
| `FURCA_SECRET` | `src/ratings/aggregators/alert.py` | да |
| `GOOGLE_CLIENT_ID` | `src/web/google_auth.py` | да |
| `GOOGLE_CLIENT_SECRET` | `src/web/google_auth.py` | да |
| `GOOGLE_FRONT_REDIRECT_URI` | `src/web/google_auth.py` | да |
| `GOOGLE_HQ_DOMAINS` | `src/web/google_auth.py` | да |
| `GOOGLE_MAIL_REDIRECT_URI` | `src/web/google_mail.py` | да |
| `GOOGLE_REDIRECT_URI` | `src/web/google_auth.py` | да |
| `INSPECTION_FILE` | `engine/audit.py` | нет — подставляется кодом в окружение подпроцесса движка (src/domain/engine.py) |
| `LOG_ID_SALT` | `src/domain/log_ids.py` | да |
| `MCP_CHECKLIST_STORE` | `src/domain/config.py`, `src/mcp/config.py`, `src/report/letters.py` и ещё 1 | да |
| `MCP_CHECKLIST_TENANTS` | `src/mcp/config.py` | да |
| `MCP_HOST` | `src/mcp/config.py` | да |
| `MCP_IMPORT_TENANTS` | `src/mcp/config.py` | да |
| `MCP_LINK_PORT` | `tools/mcp_healthcheck.py` | да |
| `MCP_LISTEN_NETWORK` | `src/mcp/config.py` | да |
| `MCP_PORT` | `src/mcp/config.py` | да |
| `MCP_PUBLIC_URL` | `src/domain/public_urls.py`, `tools/mcp_watch.py`, `tools/oauth_smoke.py` | да |
| `MCP_RETRACTION_TOKENS` | `src/mcp/config.py` | да |
| `MCP_TOKENS` | `src/mcp/config.py` | да |
| `MCP_TOKEN_TTL_DAYS` | `src/db/mcp_access.py` | да |
| `MIGROS_RELAY_URL` | `src/ratings/aggregators/migros.py` | да |
| `OAUTH_SMOKE_PASSWORD` | `tools/oauth_smoke.py` | да |
| `OPENAI_API_KEY` | `src/recognize/config.py` | да |
| `POINTER_API_KEY` | `src/ratings/maps.py` | да |
| `PRESCRIPTION_MAX_REPLIES` | `src/db/config.py` | да |
| `RECOGNIZE_MAX_CANDIDATES` | `src/recognize/config.py` | да |
| `RECOGNIZE_MERGE_MODEL` | `src/recognize/config.py` | да |
| `RECOGNIZE_MIN_CONFIDENCE` | `src/recognize/config.py` | да |
| `RECOGNIZE_MODEL` | `src/recognize/config.py` | да |
| `RECOGNIZE_TIMEOUT` | `src/recognize/config.py` | да |
| `RECOGNIZE_TRANSCRIBE_MODEL` | `src/recognize/config.py` | да |
| `S3_ACCESS_KEY_ID` | `src/db/config.py` | да |
| `S3_BUCKET` | `src/db/config.py` | да |
| `S3_ENDPOINT_URL` | `src/db/config.py` | да |
| `S3_REGION` | `src/db/config.py` | да |
| `S3_SECRET_ACCESS_KEY` | `src/db/config.py` | да |
| `SEED_WEB_DEMO_FORCE` | `tools/seed_web_demo.py` | да |
| `STATE_DIR` | `src/domain/config.py`, `src/report/letters.py`, `tools/state_backup.py` | да |
| `TELEGRAM_BOT_TOKEN` | `src/bot/config.py`, `src/web/walk_auth.py` | да |
| `WALK_MOCKUP_ZONES` | `tools/walk_mockup/build.py` | нет — ручной рычаг сборки макета (tools/walk_mockup/build.py), не настройка |
| `WALK_USERS` | `src/domain/walk_users.py` | да |
| `WEB_BOT_USERNAME` | `src/web/config.py` | да |
| `WEB_HOST` | `src/web/config.py` | да |
| `WEB_HSTS` | `src/web/config.py` | да |
| `WEB_LISTEN_NETWORK` | `src/web/config.py` | да |
| `WEB_PORT` | `src/web/config.py`, `tools/walk_healthcheck.py` | да |
| `WEB_SECRET_KEY` | `src/web/config.py` | да |
| `WEB_TENANT` | `src/web/config.py` | да |
| `WEB_TRUSTED_PROXIES` | `src/web/config.py` | да |
| `WEB_TRUSTED_PROXY_ADDR` | `src/web/config.py` | да |
| `WEB_UI_LANG` | `src/web/texts.py` | да |
| `WEB_URL_PREFIX` | `src/web/config.py`, `tools/walk_healthcheck.py` | да |
| `WEB_USER_PASSWORD` | `tools/web_user.py` | да |
| `WEB_WALK_PREVIEW_CHAT` | `src/web/walk_auth.py` | да |
| `WEB_WALK_UPSTREAM` | `src/web/config.py` | да |
<!-- map:end -->

## Таблицы по миграциям

<!-- map:begin tables -->
| Миграция | Новые таблицы |
|---|---|
| `0001_initial_schema.sql` | `tenants`, `units`, `inspections`, `findings`, `photos`, `translations` |
| `0002_unit_directory.sql` | `unit_aliases` |
| `0003_tenant_scoped_reads.sql` | — |
| `0004_finalized_write_protection.sql` | — |
| `0005_reads_by_period.sql` | — |
| `0006_kind_is_a_code.sql` | — |
| `0007_model_suggestion.sql` | — |
| `0008_auditor_words.sql` | — |
| `0009_inspection_info.sql` | `inspection_info` |
| `0010_retracted_inspections.sql` | — |
| `0011_mcp_personal_access.sql` | `mcp_admins`, `mcp_tokens` |
| `0012_phrase_aliases.sql` | `phrase_aliases` |
| `0013_phrase_alias_curation.sql` | — |
| `0014_web_accounts.sql` | `web_users`, `web_sessions` |
| `0015_web_login_attempts.sql` | `web_login_attempts` |
| `0016_web_unlock.sql` | — |
| `0017_unit_geography.sql` | — |
| `0018_inspection_reports.sql` | `reports` |
| `0019_partner_letters.sql` | `partner_letters` |
| `0020_web_user_roles.sql` | — |
| `0021_web_user_email.sql` | — |
| `0022_web_password_change.sql` | — |
| `0023_inspection_checklist_code.sql` | — |
| `0024_finding_repeat.sql` | — |
| `0025_inspection_moves.sql` | `inspection_moves` |
| `0026_photo_previews.sql` | — |
| `0027_tenant_hq.sql` | — |
| `0028_login_across_spaces.sql` | — |
| `0029_space_countries.sql` | `space_countries` |
| `0030_inspection_unit_of_space.sql` | — |
| `0031_bot_bindings.sql` | `bot_link_tokens`, `bot_bindings` |
| `0032_web_own_password.sql` | — |
| `0033_definer_search_path.sql` | — |
| `0034_inspection_acceptance.sql` | — |
| `0035_bot_ui_langs.sql` | `bot_ui_langs` |
| `0036_action_plans.sql` | `action_plan_requests`, `action_plan_files`, `action_plan_reviews`, `action_plan_events` |
| `0037_prescriptions.sql` | `prescriptions`, `prescription_units`, `prescription_inspections`, `prescription_replies`, `prescription_events`, `country_recipients` |
| `0038_inspection_import.sql` | — |
| `0039_ratings.sql` | `ratings.countries`, `ratings.imports`, `ratings.import_issues`, `ratings.units`, `ratings.periods`, `ratings.scores`, `ratings.checkups`, `ratings.violations`, `ratings.hard_rules`, `ratings.settings` |
| `0040_control_role.sql` | — |
| `0041_superadmin.sql` | — |
| `0042_import_modes.sql` | — |
| `0043_ratings_layout.sql` | `ratings.layout` |
| `0044_maps.sql` | `maps.companies`, `maps.ratings`, `maps.loads` |
| `0045_maps_link.sql` | — |
| `0046_unit_profiles.sql` | `unit_profiles` |
| `0047_maps_excluded.sql` | — |
| `0048_ratings_clusters.sql` | — |
| `0049_api_tokens.sql` | `api.tokens`, `api.access_log` |
| `0050_aggregators.sql` | `agg.points`, `agg.ratings`, `agg.loads` |
| `0051_units_registry.sql` | `agg.units` |
| `0052_api_methods.sql` | — |
| `0053_agg_requests.sql` | `agg.requests` |
| `0054_oauth.sql` | `oauth_clients`, `oauth_grants`, `oauth_codes`, `oauth_tokens` |
| `0055_maps_ratings_index.sql` | — |
| `0056_finish_modes.sql` | `finish_modes` |
| `0057_checklist_langs.sql` | `checklist_langs` |
| `0058_translate_modes.sql` | `translate_modes` |
| `0059_mcp_token_identity.sql` | — |
| `0060_d440_roles.sql` | — |
| `0061_web_own_google_lang.sql` | `web_google_link_states` |
| `0062_space_isolation.sql` | — |
| `0063_web_own_google_profile.sql` | — |
<!-- map:end -->

## Makefile

<!-- map:begin make -->
| Цель | Что делает (по комментарию в Makefile) |
|---|---|
| `make bootstrap` | окружение прогона с нуля: `.venv` и зависимости (нужен Python 3.12) |
| `make bounds` | границы модулей: обратный импорт между блоками запрещён (`lint-imports`) |
| `make check` | все гейты качества разом: формат, линт, типы, тесты, мёртвый код, границы модулей; требует базы |
| `make cov` | тесты с покрытием и обязательным наличием данных (`AUDIT_REQUIRE_DATA=1`) |
| `make cov-engine` | покрытие движка, который вызывается подпроцессом |
| `make db-down` | снести стенд базы |
| `make db-up` | поднять Postgres рядом с ботом, дождаться готовности и накатить схему |
| `make dead` | мёртвый код и неиспользуемые зависимости (`vulture`, `deptry`) |
| `make demo` | наполнить синтетический англоязычный демо-набор, боевых данных не касается |
| `make demo-down` | снести только демо-стенд (не боевой бот и не том состояния) |
| `make fastpath` | замер быстрого пути разбора: доля фиксаций без вызова модели; расход нулевой |
| `make fmt` | проверка формата (`ruff format --check`) |
| `make image` | сборка образов бота и MCP-сервера с номером сборки внутри |
| `make lint` | линт (`ruff check`) |
| `make loadcheck` | замер потолка нагрузки: параллельные проверки и альбом одновременных записей |
| `make loadcheck-live` | тот же замер с настоящими вызовами модели; платный, без `--yes` показывает только план |
| `make map` | перегенерировать таблицы карты кода и инвентаря в docs/ (tools/gen_map.py) |
| `make mcp` | поднять MCP-сервер рядом с собой, вне стенда |
| `make mcp-outside` | смоук доступа к MCP с чужой машины |
| `make migrate` | накат SQL-миграций; на накатанной базе ничего не делает |
| `make porcha-permissions` | порча матрицы прав: каждая сломанная защита обязана уронить свой тест (без базы) |
| `make processhint` | замер признака «<описание>, это <процесс>»: сколько раз он срабатывает зря |
| `make recipe-check` | можно ли снять совместимость с прежним рецептом отпечатка проверки на этой базе |
| `make regress` | движок на эталонных данных: цифры не должны разойтись |
| `make space` | пространства и их страны: завести, привязать, перечислить |
| `make state-backup` | выгрузка тома состояния проверок в каталог бэкапа |
| `make storage-down` | снести локальное хранилище кадров |
| `make storage-up` | локальное S3-хранилище кадров для смоука |
| `make test` | тесты с покрытием и сторожем полноты прогона; часть `check` |
| `make test-honest` | прогон тестов без кеша байткода — для проверки тестов порчей (`ARGS=tests/<файл>.py`) |
| `make types` | типы (`mypy`, строгий режим) |
| `make units` | справочник пиццерий: загрузка с сайтов стран и заведение руками |
| `make walk` | сервис мини-аппа обхода на этой машине (пара к `make web`) |
| `make web` | веб-админка на этой машине |
| `make web-demo` | демо-история и демо-рейтинги в базе — то, что показывает админка |
| `make web-stand-user` | учётка стенда для входа в админку |
| `make web-unlock` | запрет на вход после перебора: посмотреть запертых и снять |
| `make web-up` | одной командой: база, схема, демо-история, учётка стенда, адрес админки |
| `make web-user` | учётки веб-админки: завести, перечислить, отключить |
| `make zonecov` | замер покрытия словаря зон: что доходит до зоны и что дописать в карту слов |
| `make zonewords` | замер узнавания зоны, названной не в именительном падеже |
<!-- map:end -->
