"""D312: запись из мини-аппа обхода — кадр, нарушение, рекомендация, сведения о визите.

Ядро здесь — доступ и доказательство. Адреса записи открыты без учётки
админки, и отделяет чужого от проверки только подпись Telegram; запись без
кадра или в сданную проверку — та самая ошибка, которую партнёр увидит в
отчёте. Поэтому каждый отказ проверяется отдельно, а успех — по состоянию
проверки, а не по коду ответа.
"""

from __future__ import annotations

import io
import json
from pathlib import Path
from typing import Any

import pytest
from PIL import Image
from test_web_walk import АУДИТОР, ТОКЕН, _приложение, подписать

from src.db.bot_links import NEVER_BOUND, Standing
from src.domain import get_state, start_inspection
from src.domain.handover import HANDED_OVER_KEY, NOTES_FILE_NAME
from src.web import walk, walk_write


def _jpeg(цвет: tuple[int, int, int]) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (32, 24), цвет).save(buffer, format="JPEG")
    return buffer.getvalue()


JPEG = _jpeg((200, 180, 150))
ДРУГОЙ_JPEG = _jpeg((150, 180, 200))


class Клиент:
    """Тестовый клиент, который подписывает каждый запрос, как это делает Telegram."""

    def __init__(self, flask_client: Any, user_id: int = АУДИТОР) -> None:
        self.c = flask_client
        self.init = подписать(user_id)

    def кадр(self, raw: bytes = JPEG) -> Any:
        return self.c.post(
            walk_write.PHOTO_PATH,
            data=raw,
            content_type="image/jpeg",
            headers={"X-Telegram-Init-Data": self.init},
        )

    def ссылка(self, raw: bytes = JPEG) -> str:
        ответ = self.кадр(raw)
        assert ответ.status_code == 201, ответ.get_json()
        return str(ответ.get_json()["ref"])

    def запись(self, **тело: Any) -> Any:
        return self.c.post(
            walk_write.FINDING_PATH,
            data=json.dumps(тело),
            content_type="application/json",
            headers={"X-Telegram-Init-Data": self.init},
        )

    def сведение(self, **тело: Any) -> Any:
        return self.c.post(
            walk_write.INFO_PATH,
            data=json.dumps(тело),
            content_type="application/json",
            headers={"X-Telegram-Init-Data": self.init},
        )

    def показ(self, ref: str) -> Any:
        return self.c.post(
            walk_write.PHOTO_VIEW_PATH,
            data=json.dumps({"ref": ref}),
            content_type="application/json",
            headers={"X-Telegram-Init-Data": self.init},
        )


@pytest.fixture
def клиент(domain_env: Path, monkeypatch: pytest.MonkeyPatch) -> Клиент:
    start_inspection(АУДИТОР, unit="Белград-1", kind="planned", report_lang="ru", ui_lang="ru")
    monkeypatch.setattr(walk.queries, "previous_findings", lambda **_: None)
    monkeypatch.setattr(walk.bot_links, "standing", lambda _: NEVER_BOUND)
    return Клиент(_приложение(monkeypatch, TELEGRAM_BOT_TOKEN=ТОКЕН).test_client())


def _нарушение(ref: str, **сверх: Any) -> dict[str, Any]:
    тело = {"op": "add", "zone": "hot_kitchen", "code": "CLN05", "level": "D1", "photos": [ref]}
    return тело | сверх


# ── запись ──────────────────────────────────────────────────────────────


def test_нарушение_с_кадром_и_рекомендацией_ложится_в_проверку(клиент: Клиент) -> None:
    ref = клиент.ссылка()

    ответ = клиент.запись(**_нарушение(ref, text="нагар на поду", comment="почистить до открытия"))

    assert ответ.status_code == 200, ответ.get_json()
    запись = get_state(АУДИТОР).findings[0]  # type: ignore[union-attr]
    assert (запись.code, запись.level, запись.zone) == ("CLN05", "D1", "hot_kitchen")
    assert запись.photos == [ref], "кадр должен лечь в запись тем же вызовом"
    assert запись.text == "нагар на поду"
    assert запись.comment == "почистить до открытия", "рекомендация печатается партнёру"
    assert запись.source == "comment" and запись.repeat is False
    экран = ответ.get_json()
    горячий = next(z for z in экран["zones"] if z["code"] == "hot_kitchen")
    assert горячий["recorded"][0]["photos"] == [{"ref": ref, "own": True}]


def test_без_своих_слов_формулировка_пункта_без_классов(клиент: Клиент) -> None:
    клиент.запись(**_нарушение(клиент.ссылка()))

    текст = get_state(АУДИТОР).findings[0].text  # type: ignore[union-attr]

    assert текст and not текст.startswith("("), "служебный префикс класса ушёл бы партнёру"


@pytest.mark.parametrize(
    "фото",
    [
        pytest.param([], id="без-кадра"),
        pytest.param(["walk:" + "0" * 32], id="кадр-не-загружен"),
        pytest.param(["AgACAgIAAxkBAAI"], id="кадр-телеграма"),
        pytest.param(["walk:../../inspection"], id="путь-вместо-ссылки"),
    ],
)
def test_запись_без_настоящего_кадра_не_заводится(клиент: Клиент, фото: list[str]) -> None:
    ответ = клиент.запись(op="add", zone="hot_kitchen", code="CLN05", level="D1", photos=фото)

    assert ответ.status_code == 422
    assert get_state(АУДИТОР).findings == [], "D078: записи без фотофиксации быть не может"  # type: ignore[union-attr]


def test_отказ_движка_приходит_его_словами(клиент: Клиент) -> None:
    ответ = клиент.запись(**_нарушение(клиент.ссылка(), level="D3"))

    assert ответ.status_code == 422
    assert ответ.get_json()["message"], "аудитор должен увидеть, что не так"
    assert get_state(АУДИТОР).findings == []  # type: ignore[union-attr]


def test_повтор_только_по_нажатию_и_не_у_замера(клиент: Клиент) -> None:
    клиент.запись(**_нарушение(клиент.ссылка(), repeat=True))
    клиент.запись(
        op="add",
        zone="fridge",
        code="INF10",
        level="D0",
        text="-18",
        repeat=True,
        photos=[клиент.ссылка(ДРУГОЙ_JPEG)],
    )

    записи = {f.code: f for f in get_state(АУДИТОР).findings}  # type: ignore[union-attr]

    assert записи["CLN05"].repeat is True
    assert записи["INF10"].repeat is False, "D0 повтором не удваивается"


def test_правка_добавление_и_снятие_кадра(клиент: Клиент) -> None:
    первый = клиент.ссылка()
    клиент.запись(**_нарушение(первый))
    второй = клиент.ссылка(ДРУГОЙ_JPEG)

    assert клиент.запись(op="attach", n=1, ref=второй).status_code == 200
    assert клиент.запись(op="edit", n=1, comment="заменить уплотнитель").status_code == 200
    assert клиент.запись(op="detach", n=1, ref=первый).status_code == 200

    запись = get_state(АУДИТОР).findings[0]  # type: ignore[union-attr]
    assert запись.photos == [второй] and запись.comment == "заменить уплотнитель"


def test_последний_кадр_не_снимается(клиент: Клиент) -> None:
    ref = клиент.ссылка()
    клиент.запись(**_нарушение(ref))

    ответ = клиент.запись(op="detach", n=1, ref=ref)

    assert ответ.status_code == 422
    assert get_state(АУДИТОР).findings[0].photos == [ref]  # type: ignore[union-attr]


def test_удаление_записи(клиент: Клиент) -> None:
    клиент.запись(**_нарушение(клиент.ссылка()))

    assert клиент.запись(op="drop", n=1).status_code == 200
    assert get_state(АУДИТОР).findings == []  # type: ignore[union-attr]


# ── сведения о визите ───────────────────────────────────────────────────


def test_сведения_словами_отчёта(клиент: Клиент) -> None:
    assert клиент.сведение(code="INF03", value="yes").status_code == 200
    assert клиент.сведение(code="INF07", value="2026-10-17").status_code == 200
    assert клиент.сведение(code="INF06", value="Перевесить график уборки").status_code == 200

    info = get_state(АУДИТОР).info  # type: ignore[union-attr]
    assert info["INF03"].text == "Да", "партнёр читает «Да» на языке отчёта, а не yes"
    assert info["INF07"].text == "17.10.2026", "дата — как её печатает движок"
    assert info["INF06"].text == "Перевесить график уборки"


@pytest.mark.parametrize(
    ("код", "значение"),
    [("INF03", "maybe"), ("INF07", "завтра"), ("INF06", "  "), ("INF02", "planned")],
)
def test_сведение_с_мусором_не_пишется(клиент: Клиент, код: str, значение: str) -> None:
    assert клиент.сведение(code=код, value=значение).status_code == 422
    assert код not in get_state(АУДИТОР).info  # type: ignore[union-attr]


# ── доступ ──────────────────────────────────────────────────────────────


def test_без_подписи_запись_не_принимается(клиент: Клиент) -> None:
    чужой = клиент.c.post(
        walk_write.FINDING_PATH,
        data=json.dumps(_нарушение("walk:" + "0" * 32)),
        content_type="application/json",
        headers={"X-Telegram-Init-Data": "hash=0"},
    )
    кадр = клиент.c.post(walk_write.PHOTO_PATH, data=JPEG, content_type="image/jpeg")

    assert чужой.status_code == 401 and кадр.status_code == 401


def test_снятый_доступ_не_пишет(клиент: Клиент, monkeypatch: pytest.MonkeyPatch) -> None:
    ref = клиент.ссылка()
    monkeypatch.setattr(
        walk.bot_links, "standing", lambda _: Standing(binding=None, ever_bound=True)
    )

    assert клиент.запись(**_нарушение(ref)).status_code == 401
    assert get_state(АУДИТОР).findings == []  # type: ignore[union-attr]


def test_сданная_проверка_не_правится(клиент: Клиент, domain_env: Path) -> None:
    ref = клиент.ссылка()
    заметки = domain_env / f"chat_{АУДИТОР}" / NOTES_FILE_NAME
    заметки.write_text(json.dumps({HANDED_OVER_KEY: 0}), encoding="utf-8")

    запись = клиент.запись(**_нарушение(ref))
    кадр = клиент.кадр(ДРУГОЙ_JPEG)
    сведение = клиент.сведение(code="INF06", value="что-то")

    assert (запись.status_code, кадр.status_code, сведение.status_code) == (409, 409, 409)
    assert get_state(АУДИТОР).findings == [], "D080: дописанное легло бы в историю второй строкой"  # type: ignore[union-attr]
    экран = клиент.c.post(walk.DATA_PATH, data=клиент.init, content_type="text/plain")
    assert экран.get_json()["sealed"] is True


def test_без_проверки_записи_некуда(domain_env: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(walk.bot_links, "standing", lambda _: NEVER_BOUND)
    клиент = Клиент(_приложение(monkeypatch, TELEGRAM_BOT_TOKEN=ТОКЕН).test_client())

    assert клиент.кадр().status_code == 409
    assert клиент.запись(**_нарушение("walk:" + "0" * 32)).status_code == 409


# ── кадры ───────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "raw",
    [b"<svg onload=alert(1)>", b"\xff\xd8\xff" + b"\x00" * 64],
    ids=["svg", "только-заголовок-jpeg"],
)
def test_не_jpeg_не_принимается(клиент: Клиент, raw: bytes) -> None:
    ответ = клиент.кадр(raw)
    assert ответ.status_code == 422


def test_запись_без_подписи_в_заголовке_не_читает_тело(клиент: Клиент) -> None:
    """Подпись в теле годится только чтению: кадр до 10 МБ не читается до опознания."""
    ответ = клиент.c.post(walk_write.PHOTO_PATH, data=клиент.init, content_type="text/plain")
    assert ответ.status_code == 401


@pytest.mark.parametrize("текст", ["нагар\x00", "\x1b[31mкрасный"])
def test_управляющие_символы_не_доходят_до_движка(клиент: Клиент, текст: str) -> None:
    ответ = клиент.запись(**_нарушение(клиент.ссылка(), text=текст))
    assert ответ.status_code == 422
    assert get_state(АУДИТОР).findings == []  # type: ignore[union-attr]


def test_повтор_у_замера_правкой_не_ставится(клиент: Клиент) -> None:
    клиент.запись(
        op="add", zone="fridge", code="INF10", level="D0", text="-18", photos=[клиент.ссылка()]
    )

    ответ = клиент.запись(op="edit", n=1, repeat=True)

    assert ответ.status_code == 422
    assert get_state(АУДИТОР).findings[0].repeat is False  # type: ignore[union-attr]


def test_кадр_показывается_только_хозяину_записи(
    клиент: Клиент, domain_env: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ref = клиент.ссылка()
    assert клиент.показ(ref).status_code == 404, "кадр не из записи — не показывать"
    клиент.запись(**_нарушение(ref))

    свой = клиент.показ(ref)
    assert свой.status_code == 200 and свой.data == JPEG and свой.mimetype == "image/jpeg"

    start_inspection(777, unit="Белград-2", kind="planned", report_lang="ru", ui_lang="ru")
    чужой = Клиент(клиент.c, user_id=777)
    assert чужой.показ(ref).status_code == 404, "отпечаток кадра не пропуск к чужой проверке"


# ── рекомендация и общая заметка (D201, D314) ───────────────────────────


def _совет(**сверх: Any) -> dict[str, Any]:
    тело = {"op": "add", "zone": "hot_kitchen", "code": "CLN05", "level": "R"}
    return тело | сверх


def test_рекомендация_без_кадра_ложится_в_проверку(клиент: Клиент) -> None:
    ответ = клиент.запись(**_совет(text="Смазать петли крышки линии."))

    assert ответ.status_code == 200, ответ.get_json()
    запись = get_state(АУДИТОР).findings[0]  # type: ignore[union-attr]
    assert (запись.code, запись.level, запись.photos) == ("CLN05", "R", [])
    assert запись.text == "Смазать петли крышки линии."


def test_рекомендация_без_слов_не_пишется(клиент: Клиент) -> None:
    ответ = клиент.запись(**_совет())

    assert ответ.status_code == 422, "пустой совет подменился бы вопросом пункта"
    assert get_state(АУДИТОР).findings == []  # type: ignore[union-attr]


def test_общая_заметка_пишется_без_пункта(клиент: Клиент) -> None:
    ответ = клиент.запись(**_совет(code="NOTE", zone="dining", text="Очередь у кассы."))

    assert ответ.status_code == 200, ответ.get_json()
    запись = get_state(АУДИТОР).findings[0]  # type: ignore[union-attr]
    assert (запись.code, запись.level) == ("NOTE", "R")


def test_рекомендация_не_занимает_пару_нарушения(клиент: Клиент) -> None:
    клиент.запись(**_совет(text="совет"))

    ответ = клиент.запись(**_нарушение(клиент.ссылка()))

    assert ответ.status_code == 200, ответ.get_json()


def test_у_рекомендации_последний_кадр_снимается(клиент: Клиент) -> None:
    ref = клиент.ссылка()
    клиент.запись(**_совет(text="совет", photos=[ref]))

    ответ = клиент.запись(op="detach", n=1, ref=ref)

    assert ответ.status_code == 200, ответ.get_json()
    assert get_state(АУДИТОР).findings[0].photos == []  # type: ignore[union-attr]
