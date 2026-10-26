"""Тексты входов в Dodo IS по странам (D640, #951): блок «Dodo IS» на «Подключениях» и
публичная страница входа по ссылке.

Сливаются в общий каталог (`texts.TEXTS`). Подстановок со значениями ключей и токеном ссылки
нет и быть не может: подстановки — страна, числа и время.
"""

from __future__ import annotations

DODOIS_TEXTS: dict[str, dict[str, str]] = {
    # ── Блок на «Подключениях» ──
    "dodois.sub": {
        "ru": (
            "Страна подключается по ссылке: откройте страну в списке, сгенерируйте ссылку и "
            "передайте коллеге. Он подтвердит вход на сайте Dodo IS, и здесь появится, кто "
            "подключил страну и в каком состоянии вход."
        ),
        "en": (
            "A country is connected through a link: open the country in the list, generate a "
            "link and pass it to a colleague. They confirm the login on the Dodo IS site, and "
            "this tab then shows who connected the country and the state of the login."
        ),
    },
    "dodois.keys.title": {"ru": "Ключи приложения", "en": "App keys"},
    "dodois.count": {
        "ru": "Стран: {count}, подключено {linked}",
        "en": "Countries: {count}, connected {linked}",
    },
    "dodois.open": {"ru": "Открыть страну: {country}", "en": "Open the country: {country}"},
    "dodois.panel.title": {"ru": "Вход Dodo IS", "en": "Dodo IS login"},
    "dodois.app.title": {
        "ru": "Маркетплейс Dodo IS: ключи приложения Decimus",
        "en": "Dodo IS Marketplace: Decimus app keys",
    },
    "dodois.need_keys": {
        "ru": "Сначала задайте ключи приложения из маркетплейса (блок вверху вкладки).",
        "en": "First set the Marketplace app keys (the block at the top of this tab).",
    },
    "dodois.unknown": {
        "ru": "Не удалось прочитать входы. Повторите чуть позже.",
        "en": "Could not read the logins. Try again shortly.",
    },
    "dodois.empty": {
        "ru": "Стран в справочнике пока нет.",
        "en": "No countries in the registry yet.",
    },
    "dodois.tile.counts": {
        "ru": "Открыто {open} из {total}",
        "en": "{open} of {total} open",
    },
    "dodois.tile.unchecked": {"ru": "Ещё не проверялось", "en": "Not checked yet"},
    "dodois.state.ok": {"ru": "Работает", "en": "Working"},
    "dodois.state.partial": {"ru": "Открыто не всё", "en": "Not everything open"},
    "dodois.state.expired": {"ru": "Вход истёк", "en": "Login expired"},
    "dodois.state.failed": {"ru": "Сбой связи", "en": "Connection failure"},
    "dodois.state.none": {"ru": "Входа нет", "en": "No login"},
    "dodois.reason.refresh_rejected": {
        "ru": "Dodo IS отказал в продлении входа. Нужна новая ссылка.",
        "en": "Dodo IS refused to renew the login. A new link is needed.",
    },
    "dodois.reason.network": {
        "ru": "Dodo IS не ответил или ответил ошибкой.",
        "en": "Dodo IS did not answer or answered with an error.",
    },
    "dodois.reason.rate_limited": {
        "ru": "Dodo IS ограничил частоту запросов; повторим при следующей проверке.",
        "en": "Dodo IS limited the request rate; we will retry on the next check.",
    },
    "dodois.reason.unauthorized": {
        "ru": "Dodo IS не принял ключ доступа; вход продлится ночью или нужна новая ссылка.",
        "en": "Dodo IS did not accept the access key; it renews overnight or a new link is needed.",
    },
    "dodois.reason.no_units": {
        "ru": "В стране не нашлось работающих пиццерий.",
        "en": "No working pizzerias were found in the country.",
    },
    "dodois.reason.write_failed": {
        "ru": (
            "Новый ключ входа выдан, но не записался в базу — запись повторяется каждый час, "
            "пока работает бот. Если бот перезапустится раньше, вход будет потерян: "
            "выдайте новую ссылку."
        ),
        "en": (
            "The new login key was issued but could not be saved — saving is retried every "
            "hour while the bot runs. If the bot restarts first the login is lost: issue a "
            "new link."
        ),
    },
    "dodois.reason.no_keys": {
        "ru": "Не заданы ключи приложения маркетплейса Dodo IS (блок вверху вкладки «Dodo IS»).",
        "en": (
            "The Dodo IS Marketplace app keys are not set (the block at the top of the "
            "'Dodo IS' tab)."
        ),
    },
    "dodois.reason.no_tokens": {
        "ru": "Ключи входа не нашлись или не открылись.",
        "en": "The login keys were not found or could not be opened.",
    },
    "dodois.fact.owner": {"ru": "Владелец (перенесённый вход)", "en": "Owner (transferred login)"},
    "dodois.fact.unknown_account": {
        "ru": "Учётка Dodo IS не назвалась",
        "en": "The Dodo IS account did not identify itself",
    },
    "dodois.check": {"ru": "Проверить сейчас", "en": "Check now"},
    "dodois.country": {"ru": "Страна", "en": "Country"},
    "dodois.col.status": {"ru": "Статус", "en": "Status"},
    "dodois.col.via": {"ru": "Через кого подключено", "en": "Connected via"},
    "dodois.generate": {"ru": "Сгенерировать ссылку", "en": "Generate link"},
    "dodois.issue_hint": {
        "ru": (
            "Ссылка одноразовая, живёт 24 часа и откроет вход только этой страны. "
            "Новый вход заменит прежний, только если откроет хоть одну пиццерию."
        ),
        "en": (
            "The link is single-use, valid for 24 hours and opens a login for this country "
            "only. A new login replaces the old one only if it opens at least one pizzeria."
        ),
    },
    "dodois.replace.warn": {
        "ru": (
            "Подключение заменит текущий вход ({who}, записан {at}), если новая учётка откроет "
            "хотя бы одну пиццерию; иначе прежний вход останется."
        ),
        "en": (
            "The connection will replace the current login ({who}, recorded {at}) if the new "
            "account opens at least one pizzeria; otherwise the current login stays."
        ),
    },
    "dodois.invite.not_applied": {
        "ru": "Новый вход не дал доступа ни к одной пиццерии — не применён. Учётка: {who}",
        "en": "The new login gave access to no pizzeria and was not applied. Account: {who}",
    },
    "dodois.page.not_applied": {
        "ru": (
            "Вход не применён: у этой учётки нет доступа ни к одной пиццерии страны. "
            "Прежний вход остался. Ссылка использована; попросите выдать новую и войдите "
            "учёткой с доступом."
        ),
        "en": (
            "The login was not applied: this account has access to no pizzeria in the country. "
            "The previous login is kept. The link is used; ask for a new one and sign in with "
            "an account that has access."
        ),
    },
    "dodois.link.title": {"ru": "Ссылка для {country}", "en": "Link for {country}"},
    "dodois.link.warn": {
        "ru": (
            "Ссылка показана один раз — потом её не восстановить, только выдать "
            "новую. Отправьте её коллеге страны."
        ),
        "en": (
            "The link is shown once and cannot be recovered, only reissued. "
            "Send it to a colleague in the country."
        ),
    },
    "dodois.link.until": {"ru": "Действует до {at}", "en": "Valid until {at}"},
    "dodois.link.copy": {"ru": "Скопировать", "en": "Copy"},
    "dodois.link.copied": {"ru": "Скопировано", "en": "Copied"},
    "dodois.invite.status.active": {"ru": "Выдана", "en": "Issued"},
    "dodois.invite.status.used": {"ru": "Использована", "en": "Used"},
    "dodois.invite.status.expired": {"ru": "Истекла", "en": "Expired"},
    "dodois.invite.status.revoked": {"ru": "Отозвана", "en": "Revoked"},
    "dodois.invite.revoke": {"ru": "Отозвать", "en": "Revoke"},
    "dodois.ok.revoked": {"ru": "Ссылка отозвана.", "en": "The link was revoked."},
    "dodois.ok.checked": {"ru": "Проверено.", "en": "Checked."},
    "dodois.err.country": {
        "ru": "Выберите страну из списка.",
        "en": "Pick a country from the list.",
    },
    "dodois.err.db": {
        "ru": "База не ответила — действие не выполнено. Повторите чуть позже.",
        "en": "The database did not answer — nothing was done. Try again shortly.",
    },
    "dodois.err.not_revocable": {
        "ru": "Ссылку уже нельзя отозвать: она использована или отозвана.",
        "en": "The link can no longer be revoked: it was used or revoked.",
    },
    "dodois.err.no_login": {
        "ru": "У этой страны нет входа.",
        "en": "This country has no login.",
    },
    # ── Публичная страница по ссылке ──
    "dodois.page.title": {"ru": "Вход в Dodo IS", "en": "Dodo IS login"},
    "dodois.page.lead": {
        "ru": (
            "Decimus просит доступ на чтение данных Dodo IS по стране {country}: "
            "продажи, стопы, доставка."
        ),
        "en": (
            "Decimus asks for read access to Dodo IS data for {country}: "
            "sales, stop lists, delivery."
        ),
    },
    "dodois.page.safe": {
        "ru": (
            "Подтверждайте только на auth.dodois.com. Данные людей не "
            "запрашиваются, изменить в Dodo IS ничего нельзя."
        ),
        "en": (
            "Confirm only on auth.dodois.com. No personal data is requested and "
            "nothing can be changed in Dodo IS."
        ),
    },
    "dodois.page.start": {"ru": "Войти в Dodo IS", "en": "Sign in to Dodo IS"},
    "dodois.page.pending": {
        "ru": (
            "Откройте страницу Dodo IS, проверьте код и подтвердите вход. Эта "
            "страница сама увидит результат."
        ),
        "en": (
            "Open the Dodo IS page, check the code and confirm the login. This "
            "page will notice the result by itself."
        ),
    },
    "dodois.page.code": {"ru": "Код", "en": "Code"},
    "dodois.page.open": {"ru": "Открыть Dodo IS", "en": "Open Dodo IS"},
    "dodois.page.waiting": {"ru": "Ждём подтверждения…", "en": "Waiting for confirmation…"},
    "dodois.page.done": {
        "ru": "Готово, вход записан. Страницу можно закрыть.",
        "en": "Done, the login is recorded. You can close this page.",
    },
    "dodois.page.expired": {
        "ru": "Код устарел (он живёт 5 минут). Начните заново, пока ссылка действует.",
        "en": "The code expired (it lives 5 minutes). Start again while the link is valid.",
    },
    "dodois.page.denied": {
        "ru": "Вход не подтверждён в Dodo IS. Можно начать заново, пока ссылка действует.",
        "en": (
            "The login was not confirmed in Dodo IS. You can start again while the link is valid."
        ),
    },
    "dodois.page.failed": {
        "ru": "Не получилось записать вход. Можно начать заново, пока ссылка действует.",
        "en": "The login could not be recorded. You can start again while the link is valid.",
    },
    "dodois.page.revoked": {
        "ru": "Ссылку отозвали. Попросите новую.",
        "en": "The link was revoked. Ask for a new one.",
    },
    "dodois.page.err.no_keys": {
        "ru": "Сервис ещё не настроен для входа. Сообщите тому, кто прислал ссылку.",
        "en": "The service is not set up for logins yet. Tell the person who sent the link.",
    },
    "dodois.page.err.network": {
        "ru": "Dodo IS сейчас не отвечает. Попробуйте ещё раз через минуту.",
        "en": "Dodo IS is not answering right now. Try again in a minute.",
    },
    "dodois.page.err.rate_limited": {
        "ru": "Слишком много попыток. Попробуйте ещё раз через минуту.",
        "en": "Too many attempts. Try again in a minute.",
    },
    "dodois.page.err.unauthorized": {
        "ru": "Dodo IS не принял ключи приложения. Сообщите тому, кто прислал ссылку.",
        "en": "Dodo IS did not accept the application keys. Tell the person who sent the link.",
    },
}
