"""Кнопка «Обратная связь» (D761 п.6): права, пределы, «чат не задан — ничего не уходит».

База не поднимается: двери `db.feedback` подменены на границе модуля, как у соседних
экранных наборов. Запись, предел частоты и политики таблиц проверяет
`tests/test_db_feedback.py` на настоящей базе.
"""

from __future__ import annotations

import io
from datetime import UTC, datetime
from typing import Any

import pytest
from PIL import Image
from web_harness import СВОЙ, войти, подменить_двери, собрать

from src.db import feedback as db_feedback
from src.web import feedback as web_feedback
from src.web import feedback_telegram

HEADERS = {"Origin": СВОЙ}
CHAT = "-1001234567890"
ALL_ROLES = [
    ("HQ", "superadmin"),
    ("HQ", "admin"),
    ("HQ", "control"),
    ("HQ", "developer"),
    ("RS", "admin"),
    ("RS", "auditor"),
]


def _image(fmt: str = "JPEG") -> bytes:
    out = io.BytesIO()
    Image.new("RGB", (32, 24), (200, 30, 30)).save(out, format=fmt)
    return out.getvalue()


def _entry(**over: Any) -> db_feedback.Entry:
    base = dict(
        id="11111111-1111-1111-1111-111111111111",
        tenant="RS",
        login="anna",
        role="auditor",
        page="/inspections",
        lang="ru",
        body="Кнопка не нажимается",
        created_at=datetime(2026, 11, 12, 9, 30, tzinfo=UTC),
        reviewed_at=None,
        reviewed_by=None,
        telegram_sent_at=None,
        telegram_error=None,
        photo_ids=("22222222-2222-2222-2222-222222222222",),
    )
    base.update(over)
    return db_feedback.Entry(**base)


class Store:
    """Что бы записала и отправила кнопка: вместо базы и Telegram."""

    def __init__(self) -> None:
        self.saved: list[dict[str, Any]] = []
        self.sent: list[tuple[str, str]] = []
        self.delivery: list[tuple[str, bool, str | None]] = []
        self.reviews: list[tuple[str, bool, str]] = []
        self.chat: str | None = None
        self.chat_writes: list[tuple[str | None, str]] = []
        self.save_error: Exception | None = None
        self.attempts: list[tuple[str, str]] = []
        self.attempt_error: Exception | None = None
        self.send_result: str | None = None


@pytest.fixture
def store(monkeypatch: pytest.MonkeyPatch) -> Store:
    s = Store()

    def save(**kw: Any) -> str:
        if s.save_error is not None:
            raise s.save_error
        s.saved.append(kw)
        return "33333333-3333-3333-3333-333333333333"

    def sender(chat: str, text: str) -> str | None:
        s.sent.append((chat, text))
        return s.send_result

    def take_attempt(**kw: Any) -> None:
        s.attempts.append((kw["tenant"], kw["login"]))
        if s.attempt_error is not None:
            raise s.attempt_error

    monkeypatch.setattr(db_feedback, "take_attempt", take_attempt)
    monkeypatch.setattr(db_feedback, "save", save)
    monkeypatch.setattr(db_feedback, "chat_id", lambda: s.chat)
    monkeypatch.setattr(
        db_feedback,
        "record_delivery",
        lambda i, *, sent, error=None: s.delivery.append((i, sent, error)),
    )
    monkeypatch.setattr(db_feedback, "entries", lambda **_: (_entry(),))
    monkeypatch.setattr(db_feedback, "photo", lambda pid: ("image/jpeg", b"\xff\xd8\xff-jpeg"))
    monkeypatch.setattr(
        db_feedback,
        "mark_reviewed",
        lambda i, *, reviewed, by: s.reviews.append((i, reviewed, by)) or True,
    )
    monkeypatch.setattr(db_feedback, "set_chat_id", lambda v, *, by: s.chat_writes.append((v, by)))
    monkeypatch.setattr(feedback_telegram, "send", sender)
    # `deliver` берёт отправителя по умолчанию при определении функции: подменяем и его.
    monkeypatch.setattr(feedback_telegram.deliver, "__kwdefaults__", {"sender": sender})
    return s


def _client(monkeypatch: pytest.MonkeyPatch, tenant: str, role: str, **app_kw: Any):
    подменить_двери(monkeypatch, tenant=tenant, role=role)
    client = собрать(tenant="HQ", **app_kw).test_client()
    assert войти(client).status_code == 302
    return client


def _post(client, text="Не работает кнопка", photos=(), page="/inspections?x=1", **extra):
    data: dict[str, Any] = {"text": text, "page": f"https://evil.example{page}", **extra}
    data["photos"] = [(io.BytesIO(raw), name) for name, raw in photos] or [(io.BytesIO(b""), "")]
    return client.post(
        "/feedback?lang=ru", data=data, headers=HEADERS, content_type="multipart/form-data"
    )


# ── Отправка: любой вошедший ────────────────────────────────────────────


@pytest.mark.parametrize(("tenant", "role"), ALL_ROLES)
def test_any_signed_in_role_can_send(monkeypatch, store, tenant, role):
    client = _client(monkeypatch, tenant, role)
    response = _post(client, photos=[("a.jpg", _image())])
    assert response.status_code == 200, response.get_data(as_text=True)
    assert response.get_json()["ok"] is True
    [saved] = store.saved
    assert saved["tenant"] == tenant
    assert saved["role"] == role
    assert saved["login"] == "director"
    assert saved["lang"] == "ru"
    assert saved["body"] == "Не работает кнопка"
    assert len(saved["photos"]) == 1
    # Страница — только путь: ни хоста, ни запроса (в нём бывают имена и поиск).
    assert saved["page"] == "/inspections"


def test_signed_out_cannot_send(store):
    client = собрать(tenant="HQ").test_client()
    response = client.post("/feedback", data={"text": "x"}, headers=HEADERS)
    assert response.status_code in {302, 401, 403}
    assert store.saved == []


def test_foreign_origin_refused(monkeypatch, store):
    client = _client(monkeypatch, "HQ", "admin")
    response = client.post("/feedback", data={"text": "привет"})
    assert response.status_code == 403
    assert store.saved == []


# ── Пределы ─────────────────────────────────────────────────────────────


def test_empty_and_blank_text_refused(monkeypatch, store):
    client = _client(monkeypatch, "RS", "auditor")
    assert _post(client, text="   ").status_code == 400
    assert store.saved == []


def test_too_long_text_refused(monkeypatch, store):
    client = _client(monkeypatch, "RS", "auditor")
    assert _post(client, text="я" * (web_feedback.MAX_TEXT + 1)).status_code == 400
    assert _post(client, text="я" * web_feedback.MAX_TEXT).status_code == 200


def test_photo_limit(monkeypatch, store):
    client = _client(monkeypatch, "RS", "auditor")
    photos = [(f"{n}.jpg", _image()) for n in range(web_feedback.MAX_PHOTOS)]
    assert _post(client, photos=photos).status_code == 200
    response = _post(client, photos=[*photos, ("6.jpg", _image())])
    assert response.status_code == 400
    assert len(store.saved) == 1


def test_photo_size_limit(monkeypatch, store):
    monkeypatch.setattr(web_feedback, "MAX_UPLOAD_BYTES", 2000)
    client = _client(monkeypatch, "RS", "auditor")
    big = _image("PNG") + b"\0" * 5000
    response = _post(client, photos=[("big.png", big)])
    assert response.status_code == 413
    assert store.saved == []


@pytest.mark.parametrize("fmt", ["JPEG", "PNG", "WEBP"])
def test_allowed_types_are_compressed_to_jpeg(monkeypatch, store, fmt):
    client = _client(monkeypatch, "RS", "auditor")
    assert _post(client, photos=[("x.bin", _image(fmt))]).status_code == 200
    assert store.saved[0]["photos"][0][:3] == b"\xff\xd8\xff"


@pytest.mark.parametrize(
    ("name", "raw"),
    [
        ("fake.jpg", b"<html>not an image</html>"),  # расширение врёт
        ("pic.gif", _image("GIF")),  # настоящая картинка, но тип не из списка
        ("doc.pdf", b"%PDF-1.4 ..."),
        ("empty.jpg", b""),
    ],
)
def test_type_is_checked_by_content_not_name(monkeypatch, store, name, raw):
    client = _client(monkeypatch, "RS", "auditor")
    response = _post(client, photos=[(name, raw)])
    assert response.status_code == 400
    assert store.saved == []


def test_rate_limit_answers_429_before_any_photo_is_parsed(monkeypatch, store):
    store.attempt_error = db_feedback.FeedbackRateLimited("limit")
    parsed: list[int] = []
    real = web_feedback.read_photos
    monkeypatch.setattr(web_feedback, "read_photos", lambda files: parsed.append(1) or real(files))
    client = _client(monkeypatch, "RS", "auditor")
    response = _post(client, photos=[("a.jpg", _image())])
    assert response.status_code == 429
    assert response.get_json()["ok"] is False
    assert parsed == [], "предел частоты проверен ПОСЛЕ разбора фото"
    assert store.saved == [] and store.sent == []


def test_every_attempt_is_counted_even_a_refused_one(monkeypatch, store):
    client = _client(monkeypatch, "RS", "auditor")
    assert _post(client, text="  ").status_code == 400  # отклонена — но в счёте
    assert _post(client, photos=[("x.jpg", b"not an image")]).status_code == 400
    assert _post(client).status_code == 200
    assert store.attempts == [("RS", "director")] * 3


@pytest.mark.parametrize("side", [9000, 30000])
def test_huge_png_that_is_tiny_in_bytes_is_refused_not_a_500(monkeypatch, store, side):
    # 81 и 900 Мпикс: в пару килобайт сжатого PNG, а в памяти — сотни МБ и гигабайты.
    # Первый проходит порог бомбы Pillow, но не наш предел; второй — сама бомба.
    out = io.BytesIO()
    Image.new("1", (side, side)).save(out, format="PNG")
    assert len(out.getvalue()) < 200_000
    client = _client(monkeypatch, "RS", "auditor")
    response = _post(client, photos=[("bomb.png", out.getvalue())])
    assert response.status_code == 400, response.get_data(as_text=True)
    if side == 9000:
        assert "пикселях" in response.get_json()["message"]
    assert store.saved == []


def test_decompression_bomb_error_is_a_refusal(monkeypatch, store):
    from PIL import Image as PilImage

    def boom(*_a, **_k):
        raise PilImage.DecompressionBombError("too big")

    monkeypatch.setattr(web_feedback, "_check_pixels", lambda data: None)
    monkeypatch.setattr(web_feedback, "make_preview", boom)
    client = _client(monkeypatch, "RS", "auditor")
    assert _post(client, photos=[("a.jpg", _image())]).status_code == 400
    assert store.saved == []


def test_pixel_limit_is_the_shared_one():
    from src.domain.uploads import MAX_PIXELS

    assert web_feedback.MAX_PIXELS == MAX_PIXELS


def test_partner_gets_no_photo_by_id(monkeypatch, store):
    """IDOR: фото отзыва по угаданному номеру — только админу УК; партнёру не отдаётся."""
    called: list[str] = []
    monkeypatch.setattr(
        db_feedback,
        "photo",
        lambda pid: called.append(pid) or ("image/jpeg", b"\xff\xd8\xff-secret"),
    )
    for role in ("admin", "auditor"):
        client = _client(monkeypatch, "RS", role)
        response = client.get("/administration/feedback/photo/22222222-2222-2222-2222-222222222222")
        assert response.status_code in {403, 404}
        assert b"secret" not in response.get_data()
    assert called == [], "база опрошена до проверки прав"


def test_failed_save_is_told_and_nothing_is_sent(monkeypatch, store):
    store.chat = CHAT
    store.save_error = db_feedback.DbError("down")
    client = _client(monkeypatch, "RS", "auditor")
    assert _post(client).status_code == 503
    assert store.sent == []


# ── Telegram: выключено, пока чат не задан ──────────────────────────────


def test_no_chat_means_nothing_is_sent(monkeypatch, store):
    store.chat = None
    client = _client(monkeypatch, "RS", "auditor")
    assert _post(client).status_code == 200
    assert len(store.saved) == 1
    assert store.sent == []
    assert store.delivery == []


def test_chat_set_sends_after_save_and_records_result(monkeypatch, store):
    store.chat = CHAT
    client = _client(
        monkeypatch,
        "RS",
        "auditor",
    )
    assert _post(client, photos=[("a.jpg", _image())]).status_code == 200
    [(chat, text)] = store.sent
    assert chat == CHAT
    assert "director" in text and "RS" in text and "Страница: /inspections" in text
    assert "Не работает кнопка" in text and "Фото: 1" in text
    assert store.delivery == [("33333333-3333-3333-3333-333333333333", True, None)]


def test_failed_send_does_not_break_saving(monkeypatch, store):
    store.chat = CHAT
    store.send_result = "http_403"
    client = _client(monkeypatch, "RS", "auditor")
    response = _post(client)
    assert response.status_code == 200 and response.get_json()["ok"] is True
    assert store.delivery == [("33333333-3333-3333-3333-333333333333", False, "http_403")]


def test_crash_in_delivery_does_not_break_saving(monkeypatch, store):
    store.chat = CHAT

    def boom(chat: str, text: str) -> str | None:
        raise RuntimeError("network exploded")

    monkeypatch.setattr(feedback_telegram.deliver, "__kwdefaults__", {"sender": boom})
    client = _client(monkeypatch, "RS", "auditor")
    assert _post(client).status_code == 200


def test_send_without_token_is_a_code_not_a_call(monkeypatch):
    monkeypatch.delenv(feedback_telegram.TOKEN_VAR, raising=False)
    assert feedback_telegram.send(CHAT, "x") == feedback_telegram.NO_TOKEN


def test_message_template_is_stable():
    text = feedback_telegram.message(
        login="anna",
        role="auditor",
        space="RS",
        page="/inspections",
        body="Текст",
        photos=2,
        moment=datetime(2026, 11, 12, 9, 30, tzinfo=UTC),
    )
    assert text.splitlines()[0] == "💬 Обратная связь · Decimus"
    assert "anna · auditor · RS · 12.11.2026 09:30 UTC" in text
    assert "Страница: /inspections" in text and text.endswith(
        "в «Администрирование → Обратная связь»"
    )


# ── Кнопка на страницах ─────────────────────────────────────────────────


@pytest.mark.parametrize(("tenant", "role"), ALL_ROLES)
def test_button_is_on_every_page_of_any_role(monkeypatch, store, tenant, role):
    client = _client(monkeypatch, tenant, role)
    html = client.get("/no-such-page?lang=ru").get_data(as_text=True)
    assert "data-feedback-open" in html and 'id="feedback-dialog"' in html
    assert "Обратная связь" in html


def test_button_is_not_on_the_login_page():
    html = собрать(tenant="HQ").test_client().get("/login").get_data(as_text=True)
    assert "feedback-dialog" not in html


def test_demo_has_button_but_sending_is_locked(monkeypatch, store):
    client = _client(monkeypatch, "HQ", "admin", demo=True)
    html = client.get("/no-such-page?lang=en").get_data(as_text=True)
    assert "feedback-dialog" in html and "Sending is turned off in the demo" in html
    assert _post(client).status_code == 403
    assert store.saved == []


# ── Вкладка администрирования ───────────────────────────────────────────


@pytest.mark.parametrize(("tenant", "role"), [("HQ", "superadmin"), ("HQ", "admin")])
def test_hq_admins_see_the_tab_with_entries(monkeypatch, store, tenant, role):
    client = _client(monkeypatch, tenant, role)
    response = client.get("/administration?tab=feedback&lang=ru")
    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert "Кнопка не нажимается" in html and "anna" in html
    assert "/administration/feedback/photo/22222222" in html
    assert "Отметить разобранным" in html


@pytest.mark.parametrize(
    ("tenant", "role"), [("HQ", "control"), ("HQ", "developer"), ("RS", "admin"), ("RS", "auditor")]
)
def test_others_do_not_see_tab_photos_or_review(monkeypatch, store, tenant, role):
    client = _client(monkeypatch, tenant, role)
    assert client.get("/administration?tab=feedback").status_code == 404
    photo = client.get("/administration/feedback/photo/22222222-2222-2222-2222-222222222222")
    assert photo.status_code in {403, 404}
    review = client.post(
        "/administration/feedback/11111111-1111-1111-1111-111111111111/review",
        data={"reviewed": "1"},
        headers=HEADERS,
    )
    assert review.status_code in {403, 404}
    chat = client.post("/administration/feedback/chat", data={"chat_id": CHAT}, headers=HEADERS)
    assert chat.status_code in {403, 404}
    assert store.reviews == [] and store.chat_writes == []


def test_tab_is_not_in_partner_tabs(monkeypatch, store):
    client = _client(monkeypatch, "RS", "admin")
    html = client.get("/administration?lang=ru").get_data(as_text=True)
    assert "tab=feedback" not in html


def test_admin_serves_photo_and_marks_reviewed(monkeypatch, store):
    client = _client(monkeypatch, "HQ", "admin")
    photo = client.get("/administration/feedback/photo/22222222-2222-2222-2222-222222222222")
    assert photo.status_code == 200 and photo.mimetype == "image/jpeg"
    assert photo.headers["X-Content-Type-Options"] == "nosniff"
    review = client.post(
        "/administration/feedback/11111111-1111-1111-1111-111111111111/review",
        data={"reviewed": "1"},
        headers=HEADERS,
    )
    assert review.status_code == 303
    assert store.reviews == [("11111111-1111-1111-1111-111111111111", True, "director")]


def test_only_super_admin_sets_chat(monkeypatch, store):
    admin = _client(monkeypatch, "HQ", "admin")
    html = admin.get("/administration?tab=feedback&lang=ru").get_data(as_text=True)
    assert "Чат Telegram для команды" not in html
    denied = admin.post("/administration/feedback/chat", data={"chat_id": CHAT}, headers=HEADERS)
    assert denied.status_code in {403, 404}
    assert store.chat_writes == []

    boss = _client(monkeypatch, "HQ", "superadmin")
    html = boss.get("/administration?tab=feedback&lang=ru").get_data(as_text=True)
    assert "Чат Telegram для команды" in html and "Сейчас: не задан" in html
    assert (
        boss.post(
            "/administration/feedback/chat", data={"chat_id": CHAT}, headers=HEADERS
        ).status_code
        == 303
    )
    assert (
        boss.post(
            "/administration/feedback/chat", data={"disable": "1"}, headers=HEADERS
        ).status_code
        == 303
    )
    assert store.chat_writes == [(CHAT, "director"), (None, "director")]


@pytest.mark.parametrize("bad", ["", "abc", "12", "--1001234", "1001234; drop"])
def test_bad_chat_id_is_refused(monkeypatch, store, bad):
    boss = _client(monkeypatch, "HQ", "superadmin")
    response = boss.post("/administration/feedback/chat", data={"chat_id": bad}, headers=HEADERS)
    assert response.status_code == 400
    assert store.chat_writes == []


def test_review_value_is_validated_and_origin_checked(monkeypatch, store):
    client = _client(monkeypatch, "HQ", "admin")
    path = "/administration/feedback/11111111-1111-1111-1111-111111111111/review"
    assert client.post(path, data={"reviewed": "x"}, headers=HEADERS).status_code == 400
    assert client.post(path, data={"reviewed": "1"}).status_code == 403
    assert store.reviews == []
