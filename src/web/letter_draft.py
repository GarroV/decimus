"""Письмо уходит в черновики почты вошедшего (T352, D174, D176, D185, #332).

Отправки из системы нет: черновик кладётся в ящик человека, и дальше он
отправляет его сам. Порядок здесь такой, и он не случаен:

1. Письмо **фиксируется** — ровно тот текст, который человек видел на экране
   (D171). Без этого уход за согласием увёл бы со страницы вместе с правками.
2. Человек уходит к Google за почтовым правом. Оно спрашивается отдельно от
   входа (D185) и только при первом уходе: уже выданное Google пропускает
   молча.
3. На возврате черновик собирается из **зафиксированного** письма, а не из
   поля формы, которого после ухода уже нет.

**Токен доступа к почте нигде не сохраняется** — ни в базе, ни в куке. Он
живёт внутри одного возврата и умирает вместе с ним: черновик создаётся тут
же, а долговременный ключ к чужой почте нужен только фоновой отправке,
которой нет.
"""

from __future__ import annotations

import hashlib
import hmac

from flask import Flask, redirect, render_template, request, url_for
from itsdangerous import BadSignature, URLSafeTimedSerializer
from werkzeug.wrappers import Response

from src.db.errors import DbError

from . import auth
from . import inspections as data
from .config import Settings
from .google_auth import GoogleSettings, load_google_settings, new_state
from .google_mail import (
    GOOGLE_MAIL_REDIRECT_URI_VAR,
    GoogleMailError,
    consent_url,
    create_draft,
    draft_subject,
    exchange_code_for_token,
)
from .origin import refuse_foreign_origin
from .sections import section

MAIL_CALLBACK_PATH = "/auth/google/mail"

MAIL_STATE_COOKIE = "dodo_audit_mail_state"
MAIL_STATE_SALT = "google-mail-state"
#: Десять минут на согласие. Больше — окно, в котором чужая страница может
#: подсунуть свой возврат; меньше — человек не успевает прочитать экран Google.
MAIL_STATE_TTL_SECONDS = 600


def _почта_вошедшего(вошедший: object | None) -> str:
    """Логин как почта — или пусто. Выдумывать адрес нельзя ничем."""
    логин = str(getattr(вошедший, "login", "") or "")
    return логин if "@" in логин else ""


def install(app: Flask, conf: Settings) -> None:
    """Повесить маршрут ухода за согласием и возврата с ним."""
    подписант = URLSafeTimedSerializer(
        conf.secret_key, salt=MAIL_STATE_SALT, signer_kwargs={"digest_method": hashlib.sha256}
    )
    реестр = section("registry").path

    def к_письму(inspection_id: str, *, lang: str, исход: str) -> Response:
        return redirect(
            # Параметр СВОЙ, а не `draft`: тем уже помечен возврат к
            # заготовке движка на этом же экране, и один параметр с двумя
            # смыслами разошёлся бы молча.
            url_for("letter", inspection_id=inspection_id, letter_lang=lang, gmail=исход),
            code=303,
        )

    def почтовые_реквизиты() -> GoogleSettings | None:
        """Те же клиент и секрет, что у входа, но СВОЙ адрес возврата.

        Адрес возврата у Google сверяется точно, и он свой у каждого пути:
        вход возвращается на `/auth/google/callback`, почта — сюда. Общий
        адрес заставил бы один маршрут угадывать, за чем именно ходили.
        """
        вход = load_google_settings()
        if вход is None:
            return None
        import os

        адрес = (os.environ.get(GOOGLE_MAIL_REDIRECT_URI_VAR) or "").strip()
        if not адрес:
            return None
        return GoogleSettings(
            client_id=вход.client_id, client_secret=вход.client_secret, redirect_uri=адрес
        )

    @app.post(f"{реестр}/<inspection_id>/letter/draft", endpoint="letter_draft")
    def letter_draft(inspection_id: str) -> Response | tuple[str, int]:
        refuse_foreign_origin()
        detail = data.load_card(inspection_id, tenant=conf.tenant)
        if detail is None:
            return render_template("inspections/not_found.html"), 404

        письмо_на = request.form.get("letter_lang") or detail.inspection.report_lang
        текст = request.form.get("text") or ""
        вошедший = auth.current_account()

        # Фиксация ПЕРВЫМ делом: уход к Google уводит со страницы, и текст из
        # поля формы после возврата не существует нигде (D185).
        try:
            data.remember_letter(
                inspection_id,
                body=текст,
                lang=письмо_на,
                saved_by="—" if вошедший is None else вошедший.login,
            )
        except (DbError, ValueError):
            # Пустое письмо и потерянная база чинятся по-разному, но для этого
            # экрана исход один: черновика нет, и человек должен это прочитать
            # словами, а не догадаться по молчащей кнопке.
            return к_письму(inspection_id, lang=письмо_на, исход="failed")

        реквизиты = почтовые_реквизиты()
        if реквизиты is None:
            # Законная настройка стенда, а не поломка: без реквизитов админка
            # работает как работала, просто без черновиков.
            return к_письму(inspection_id, lang=письмо_на, исход="unavailable")

        метка = new_state()
        ответ = redirect(
            consent_url(
                реквизиты,
                state=метка,
                # Подсказка, в какой аккаунт вести: своей почты у учётки
                # админки пока нет (D173, #334 — человек ещё не одна
                # сущность), поэтому годится логин, если он и есть почта.
                # Пустая подсказка — не поломка: Google просто спросит, каким
                # аккаунтом входить.
                login_hint=_почта_вошедшего(вошедший),
            )
        )
        # В куке едет и метка, и то, за чем ходили: возврат придёт голым GET, и
        # без этого маршрут не знал бы, какое письмо класть в черновики. Кука
        # подписана — подменить в ней номер проверки значит подделать подпись.
        ответ.set_cookie(
            MAIL_STATE_COOKIE,
            подписант.dumps({"state": метка, "id": inspection_id, "lang": письмо_на}),
            max_age=MAIL_STATE_TTL_SECONDS,
            httponly=True,
            samesite="Lax",
            secure=request.is_secure,
            path="/",
        )
        return ответ

    @app.get(MAIL_CALLBACK_PATH, endpoint="google_mail_callback")
    def google_mail_callback() -> Response | tuple[str, int]:
        """Возврат от Google: сверить метку, обменять код, положить черновик."""
        подписанная = request.cookies.get(MAIL_STATE_COOKIE)
        if not подписанная:
            return redirect(url_for("registry"), code=303)
        try:
            поход = подписант.loads(подписанная, max_age=MAIL_STATE_TTL_SECONDS)
        except BadSignature:
            return redirect(url_for("registry"), code=303)

        inspection_id = str(поход.get("id") or "")
        письмо_на = str(поход.get("lang") or "")
        if not inspection_id:
            return redirect(url_for("registry"), code=303)

        пришедшая = request.args.get("state") or ""
        # В БАЙТАХ, а не в строках: `compare_digest` на не-ASCII падает
        # TypeError, и подделанная метка с кириллицей давала бы 500 вместо
        # отказа. Эта же грабля уже ловилась на входе.
        if not hmac.compare_digest(str(поход.get("state") or "").encode(), пришедшая.encode()):
            return к_письму(inspection_id, lang=письмо_на, исход="failed")

        # Человек сам отказался в окне согласия — это не поломка.
        if request.args.get("error"):
            return к_письму(inspection_id, lang=письмо_на, исход="denied")

        код = request.args.get("code") or ""
        реквизиты = почтовые_реквизиты()
        if not код or реквизиты is None:
            return к_письму(inspection_id, lang=письмо_на, исход="failed")

        detail = data.load_card(inspection_id, tenant=conf.tenant)
        if detail is None:
            return render_template("inspections/not_found.html"), 404

        # Из ЗАФИКСИРОВАННОГО письма, а не из заготовки: заготовка
        # пересобирается и к этому моменту могла бы дать другой текст, чем
        # видел человек, нажимая кнопку.
        try:
            записанное = data.saved_letter(inspection_id, lang=письмо_на)
        except DbError:
            return к_письму(inspection_id, lang=письмо_на, исход="failed")
        if записанное is None:
            return к_письму(inspection_id, lang=письмо_на, исход="failed")

        try:
            токен = exchange_code_for_token(реквизиты, code=код)
            create_draft(
                токен,
                to=detail.inspection.contact,
                subject=draft_subject(
                    city=detail.inspection.city,
                    date=str(detail.inspection.inspection_date),
                    lang=письмо_на,
                ),
                body=записанное.body,
            )
        except GoogleMailError:
            return к_письму(inspection_id, lang=письмо_на, исход="failed")

        ответ = к_письму(inspection_id, lang=письмо_на, исход="ok")
        # Метка одноразовая: оставленная в браузере, она отвечала бы «да» на
        # чужой возврат следующие десять минут.
        ответ.delete_cookie(MAIL_STATE_COOKIE, path="/")
        return ответ
