"""Аудитория каждого маршрута веба: по умолчанию партнёру закрыто (аудит 12.10, F-004).

До этой правки заслон «только УК» решал по ПРЕФИКСУ пути (`sections.refused_for`)
и по умолчанию разрешал: маршрут вне префикса закрытого раздела был открыт
партнёрскому пространству молча. Здесь умолчание перевёрнуто: у КАЖДОГО эндпоинта
Flask — явная отметка аудитории, по имени эндпоинта, а не по пути. Партнёра
заслон `app._install_hq_gate` пускает только к отмеченному «все пространства» или
«своя дверь»; без отметки и «только УК» — 404, как несуществующий адрес.

Отметка живёт данными в одном месте, и `check_audiences` сверяет её с приложением
при сборке (как `sections.check_registry`): новый маршрут без отметки — приложение
не соберётся, а не откроется партнёру. Отметка «все пространства» значит лишь
«партнёр сюда ходит»; что именно он увидит и изменит, решает сам маршрут охватом
и ролью (`access_policy`, `db.reach`) — отметка их не заменяет.
"""

from __future__ import annotations

from enum import Enum

from flask import Flask

from . import auth
from .errors import SectionRegistryError
from .sections import current_section, section


class Audience(Enum):
    """Кого пускает маршрут."""

    ALL_SPACES = "все пространства"
    HQ_ONLY = "только УК"
    OWN_DOOR = "своя дверь"


#: Партнёр сюда ходит, и маршрут сам отбирает своё охватом и ролью. Только
#: то, что нужно партнёру по факту: разделы без `hq_only` и дела самого человека.
ALL_SPACES: frozenset[str] = frozenset(
    {
        # Вход и выход, согласие OAuth и обратный вызов Gmail — вошедшему, любому.
        "home",
        "logout",
        "oauth_authorize",
        "google_mail_callback",
        # «Главная» и «Обзор».
        "overview",
        # «Календарь» — заглушка «в разработке», без данных.
        "wip_calendar",
        # «Проверки»: список, карточка, отчёт, снимки, письмо, правки приёмки.
        # Охват — `auth.current_reach()`; запись, снятие и приёмку решает
        # `app._hq_worker_only` на самом маршруте.
        "registry",
        "card",
        "do_accept",
        "do_revise",
        "letter",
        "letter_draft",
        "save_letter",
        "do_move",
        "photo",
        "report",
        "do_retract",
        # Карточка пиццерии: охват — на маршруте.
        "unit",
        # Экшн-планы и предписания партнёра (разделы `partner_only`, не `hq_only`).
        "plans",
        "plans_upload",
        "plan_file",
        "orders",
        "order",
        "order_reply",
        "order_file",
        # «Рейтинги» видят все (D327); загрузки и справочники — заслон на маршрутах.
        "ratings",
        "ratings_agg_update",
        "ratings_developer",
        "ratings_coverage",
        "ratings_coverage_link",
        "ratings_rule_add",
        "ratings_rule_remove",
        "ratings_upload",
        "ratings_imports",
        "ratings_layout",
        "ratings_settings",
        # «Пользователи»: свои дела (пароль, бот, токен Claude, подключения) и люди
        # своего пространства — кого вести, решает `access_policy`.
        "users",
        "add_user",
        "bot_unlink",
        # «Настройки» (D447, D448): свой профиль — пароль, бот, токен Claude.
        "settings_page",
        "settings_own_password",
        "settings_bot_link",
        "settings_bot_unlink",
        "settings_claude_token",
        "settings_claude_token_revoke",
        "settings_claude_revoke",
        "settings_google_link",
        "settings_google_unlink",
        "settings_lang",
        # Повторное подтверждение себя перед чувствительным делом своей учётки.
        "reauth_confirm",
        "reauth_confirm_google",
        "reauth_confirm_password",
        "claude_revoke",
        "connections_issue",
        "connections_reissue",
        "connections_revoke",
        "connections_update",
        "disable_user",
        "user_email",
        "user_role",
        "add_space",
        "space_countries",
        # «Методика»: раздел не `hq_only` — админ партнёра её читает; запись
        # закрывает `app._install_methodology_gate`.
        "methodology",
        "methodology_bot",
        "checklists",
        "checklists_create",
        "checklists_apply_preview",
        "checklists_apply",
        "checklists_master",
        "checklists_state",
        "methodology_add",
        "methodology_item",
        "methodology_edit",
        "methodology_disable",
        "methodology_restore",
        "methodology_publish",
        "methodology_route",
        "methodology_scoring",
        "methodology_zone_add",
        "methodology_zone_remove",
        "methodology_zone_rename",
        "methodology_zone_shares",
    }
)

#: Партнёру закрыто: разделы `hq_only` («Страна», «Действия УК») и всё, что в них
#: вложено, включая заведение пиццерии в стране.
HQ_ONLY: frozenset[str] = frozenset(
    {
        "actions",
        "actions_new",
        "actions_request",
        "actions_due",
        "actions_review",
        "rx_list",
        "rx_create",
        "rx_view",
        "rx_close",
        "rx_edit",
        "rx_update",
        "rx_send",
        "rx_new",
        "country_index",
        "country",
        "unit_new",
        "unit_create",
    }
)

#: Своя дверь — без входа админки или с собственным опознанием: вход и статика,
#: мини-апп обхода (подпись Telegram), API для сервисов (ключ), машинные адреса
#: OAuth. Список один с заслоном входа — `auth.OPEN_ENDPOINTS`, здесь он не
#: дублируется. Часть этих адресов вешается только при настройках (OAuth, обход),
#: поэтому «такого эндпоинта нет» для них не ошибка.
OWN_DOOR: frozenset[str] = frozenset(auth.OPEN_ENDPOINTS)


#: Отмеченные, но вешаемые только при публичных адресах (подключение Claude,
#: D417): на стенде без них эндпоинта нет, и это не мусор в реестре.
WHEN_CONFIGURED: frozenset[str] = frozenset(
    {"claude_revoke", "oauth_authorize", "settings_claude_revoke"}
)


def audience_of(endpoint: str | None) -> Audience | None:
    """Аудитория эндпоинта; `None` — отметки нет, и заслон считает его закрытым."""
    if endpoint in OWN_DOOR:
        return Audience.OWN_DOOR
    if endpoint in ALL_SPACES:
        return Audience.ALL_SPACES
    if endpoint in HQ_ONLY:
        return Audience.HQ_ONLY
    return None


def partner_may_reach(endpoint: str | None) -> bool:
    """Пускать ли партнёрское пространство: только по явной отметке (умолчание — закрыто)."""
    return audience_of(endpoint) in (Audience.ALL_SPACES, Audience.OWN_DOOR)


def check_audiences(app: Flask) -> None:
    """Сверить отметки с приложением. Любое расхождение — отказ при сборке.

    * эндпоинт без отметки — маршрут открылся бы никому или, хуже, забыли решить;
    * отметка несуществующего эндпоинта — мусор в реестре, который однажды
      закроет или откроет чужой маршрут с тем же именем;
    * одно имя в двух списках — аудитория неоднозначна;
    * «все пространства» под путём раздела `hq_only` — отметка спорит с заслоном
      по префиксу: что из двух правда, решает человек, а не порядок проверок.
    """
    имена = {rule.endpoint for rule in app.url_map.iter_rules()}
    без_отметки = sorted(имена - ALL_SPACES - HQ_ONLY - OWN_DOOR)
    if без_отметки:
        raise SectionRegistryError(
            "У маршрутов нет отметки аудитории: "
            f"{', '.join(без_отметки)}. Отметьте их в src/web/route_audience.py "
            "(«все пространства» / «только УК» / «своя дверь»): без отметки партнёру "
            "маршрут закрыт (аудит 12.10, F-004)"
        )
    мусор = sorted((ALL_SPACES | HQ_ONLY) - WHEN_CONFIGURED - имена)
    if мусор:
        raise SectionRegistryError(
            f"Отмечены эндпоинты, которых в приложении нет: {', '.join(мусор)}. "
            "Уберите их из src/web/route_audience.py"
        )
    двойные = sorted((ALL_SPACES & HQ_ONLY) | (ALL_SPACES & OWN_DOOR) | (HQ_ONLY & OWN_DOOR))
    if двойные:
        raise SectionRegistryError(
            f"Эндпоинт отмечен в двух аудиториях сразу: {', '.join(двойные)} "
            "(src/web/route_audience.py)"
        )
    спорные = sorted(
        {
            rule.endpoint
            for rule in app.url_map.iter_rules()
            if rule.endpoint in ALL_SPACES and _under_hq_only_section(rule.rule)
        }
    )
    if спорные:
        raise SectionRegistryError(
            f"Маршруты отмечены «все пространства», но лежат под разделом только для УК: "
            f"{', '.join(спорные)}. Либо отметка «только УК», либо маршрут вне раздела "
            "(src/web/route_audience.py, src/web/sections.py)"
        )


def _under_hq_only_section(path: str) -> bool:
    ключ = current_section(path)
    return ключ is not None and section(ключ).hq_only
