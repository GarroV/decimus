"""Экраны админки: что на них попадает и чего на них не бывает.

Разметку и тексты тестами не сторожим — их проверяют глазами и сверкой с
эталоном (конституция, слой «Поверхность»). Здесь проверяется ровно то, чья
ошибка молчит:

* **оценка не пересчитывается** — экран печатает то, что записано, даже когда
  записанное выглядит неправдоподобно;
* **«снятых нет» и «вам их не видно» — разные ответы**, и второй сказан вслух;
* **снятие зовёт существующую дверь** `src/db/retract.py`, а не заводит второе
  понятие удаления;
* **непостроенное выглядит непостроенным** на всех восьми разделах сразу, а не
  на том, куда посмотрели.

База здесь не поднимается: двери блока `db` подменяются на границе модуля
`src/web/inspections.py`. Живой путь до Postgres проверяется смоуком на стенде,
а не набором — он громкий и падает на первом же вызове.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import date
from typing import Any

import pytest
from flask.testing import FlaskClient
from web_harness import войти, подменить_двери, собрать

from src.db.errors import DbError, RetractionError
from src.db.models import FindingRow, InspectionDetail, InspectionRow
from src.db.retract import Retraction
from src.web import inspections as data
from src.web.sections import SECTIONS

ТЕНАНТ = "default"


def шапка(**поля: Any) -> InspectionRow:
    """Строка проверки с правдоподобной шапкой; числа задаёт вызывающий."""
    основа: dict[str, Any] = {
        "id": "11111111-1111-1111-1111-111111111111",
        "tenant_code": ТЕНАНТ,
        "unit_name": "Demo Pizzeria #1",
        "chat_id": 1,
        "kind": "planned",
        "inspection_date": date(2026, 9, 18),
        "report_lang": "en",
        "checklist_version": "2026.09",
        "pct": 92.0,
        "grade": "B",
        "findings_count": 4,
        "pushed_at": "2026-09-18T10:00:00+00:00",
        "auditor": "Demo Auditor",
        "city": "Demo City",
    }
    основа.update(поля)
    return InspectionRow(**основа)


def карточка(row: InspectionRow, **поля: Any) -> InspectionDetail:
    основа: dict[str, Any] = {
        "inspection": row,
        "deductions": 8.0,
        "counts": {"D1": 4},
        "by_zone": {
            "KITCHEN": {
                "code": "KITCHEN",
                "name_ru": "Кухня",
                "name_en": "Kitchen",
                "share": 20.0,
                "counts": {"D1": 2},
                "loss": 1.0,
                "left": 19.0,
                "zeroed": False,
            }
        },
        "findings": (
            FindingRow(
                id="f1",
                inspection_id=row.id,
                unit_name=row.unit_name,
                inspection_date=row.inspection_date,
                n=1,
                code="CLN02",
                level="D1",
                zone="KITCHEN",
                zone_unusual=False,
                source="comment",
                lang="en",
                text="Crumbs on the prep table",
                comment=None,
            ),
        ),
    }
    основа.update(поля)
    return InspectionDetail(**основа)


@pytest.fixture
def стенд(monkeypatch: pytest.MonkeyPatch) -> Iterator[FlaskClient]:
    """Приложение с подменёнными дверями блока `db` и УЖЕ ВОШЕДШИМ человеком.

    Вход настоящий — отправкой формы (`tests/web_harness.py`). После T323 без
    него не открывается ни один экран, и подставлять сюда обход заслона
    значило бы проверять экраны в положении, которого у живого приложения не
    бывает.
    """
    monkeypatch.setattr(data, "retraction_available", lambda: True)
    monkeypatch.setattr(data, "load_registry", lambda **_: data.Registry((), True))
    monkeypatch.setattr(data, "load_card", lambda *_a, **_k: None)
    подменить_двери(monkeypatch, tenant=ТЕНАНТ)
    with собрать(tenant=ТЕНАНТ).test_client() as client:
        assert войти(client).status_code == 302
        yield client


# --- каркас: девять разделов и честная лента (D138) ------------------------


def test_все_девять_разделов_открываются(стенд: FlaskClient) -> None:
    # Act / Assert — раздел, которого нет в карте продукта, спрятан, а прятать
    # непостроенное решением запрещено.
    for раздел in SECTIONS:
        assert стенд.get(раздел.path).status_code == 200, раздел.key


def test_непостроенный_раздел_говорит_что_он_в_разработке(стенд: FlaskClient) -> None:
    # Arrange
    непостроенные = [раздел for раздел in SECTIONS if not раздел.built]

    # Act / Assert — не на том разделе, куда посмотрели, а на всех восьми.
    assert len(непостроенные) == 8
    for раздел in непостроенные:
        страница = стенд.get(раздел.path).get_data(as_text=True)
        assert "ещё в разработке" in страница, раздел.key
        assert "tape tape--screen" in страница, раздел.key


def test_построенный_раздел_ленты_не_несёт(стенд: FlaskClient) -> None:
    # Act
    страница = стенд.get("/inspections").get_data(as_text=True)

    # Assert
    assert "tape tape--screen" not in страница


def test_навигация_показывает_карту_продукта_целиком(стенд: FlaskClient) -> None:
    # Act — карту видно с любого экрана, а не только с главного.
    страница = стенд.get("/calendar").get_data(as_text=True)

    # Assert
    assert 'class="tape tape--nav"' in страница
    for раздел in SECTIONS:
        assert раздел.path in страница, раздел.key


def test_корень_ведёт_в_единственный_построенный_раздел(стенд: FlaskClient) -> None:
    # Act
    ответ = стенд.get("/")

    # Assert
    assert ответ.status_code == 302
    assert ответ.headers["Location"].endswith("/inspections")


# --- оценка не пересчитывается --------------------------------------------


def test_реестр_печатает_записанное_даже_когда_оно_неправдоподобно(
    стенд: FlaskClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Arrange — записано 42,0 % и буква D при нуле находок. Пересчитывающий
    # экран «поправил» бы это на 100 % и A; читающий покажет как есть.
    строка = шапка(pct=42.0, grade="D", findings_count=0)
    monkeypatch.setattr(data, "load_registry", lambda **_: data.Registry((строка,), True))

    # Act
    страница = стенд.get("/inspections").get_data(as_text=True)

    # Assert
    assert "42.0" in страница
    assert ">D<" in страница


def test_карточка_печатает_разбивку_записанной_а_не_сведённой(
    стенд: FlaskClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Arrange — записанное намеренно НЕ сходится само с собой: 42 % при вычете
    # 8 и доле зоны 20. Любой пересчёт по дороге к экрану даст другое число
    # (100 − 8 = 92), и тогда этот тест покажет чужую арифметику. Сходящийся
    # набор её не поймал бы: пересчёт совпал бы с записанным.
    деталь = карточка(шапка(pct=42.0, grade="D"))
    monkeypatch.setattr(data, "load_card", lambda *_a, **_k: деталь)

    # Act
    страница = стенд.get(f"/inspections/{деталь.inspection.id}").get_data(as_text=True)

    # Assert — каждое число из базы стоит на экране как есть.
    for число in ("42.0", "8.0", "20.0", "1.0", "19.0"):
        assert число in страница, число
    assert "92" not in страница


# --- «снятых нет» против «вам их не видно» --------------------------------


def test_без_администратора_истории_страница_говорит_об_этом_вслух(
    стенд: FlaskClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Arrange
    monkeypatch.setattr(data, "retraction_available", lambda: False)
    monkeypatch.setattr(data, "load_registry", lambda **_: data.Registry((шапка(),), False))

    # Act
    страница = стенд.get("/inspections").get_data(as_text=True)

    # Assert — молчаливо укороченный список выглядел бы полным.
    assert "Снятые проверки не видны" in страница
    assert "DATABASE_RETRACTION_URL" in страница


def test_без_администратора_истории_снятие_не_предлагается(
    стенд: FlaskClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Arrange
    деталь = карточка(шапка())
    monkeypatch.setattr(data, "retraction_available", lambda: False)
    monkeypatch.setattr(data, "load_card", lambda *_a, **_k: деталь)

    # Act
    страница = стенд.get(f"/inspections/{деталь.inspection.id}").get_data(as_text=True)

    # Assert — ищется именно форма снятия: выход в шапке есть на каждой
    # странице, и «форм на странице нет вовсе» с ним больше не проверка.
    assert "/retract" not in страница
    assert "Снятые проверки не видны" in страница


def test_снятая_проверка_видна_снятой_и_с_причиной(
    стенд: FlaskClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Arrange
    строка = шапка(retracted=True, retraction_reason="проверка проведена не по той методике")
    monkeypatch.setattr(data, "load_card", lambda *_a, **_k: карточка(строка))

    # Act
    страница = стенд.get(f"/inspections/{строка.id}").get_data(as_text=True)

    # Assert — снятой проверке действий не предлагают.
    assert "проверка проведена не по той методике" in страница
    assert "/retract" not in страница


# --- снятие идёт существующей дверью ---------------------------------------


def test_снятие_зовёт_дверь_блока_db_с_причиной_из_формы(
    стенд: FlaskClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Arrange
    строка = шапка()
    вызовы: list[dict[str, Any]] = []

    def снять(inspection_id: str, *, tenant: str, reason: str) -> Retraction:
        вызовы.append({"id": inspection_id, "tenant": tenant, "reason": reason})
        return Retraction(
            inspection_id=inspection_id, reason=reason, retracted_at="2026-09-18", photos_purged=2
        )

    monkeypatch.setattr(data, "retract_card", снять)
    monkeypatch.setattr(data, "load_card", lambda *_a, **_k: карточка(строка))

    # Act — запрос со своей же страницы: браузер ставит `Origin` сам.
    ответ = стенд.post(
        f"/inspections/{строка.id}/retract",
        data={"reason": "дубль обхода"},
        headers={"Origin": "http://localhost"},
    )

    # Assert — ровно один вызов, тенант стенда, причина как введена.
    assert ответ.status_code == 200
    assert вызовы == [{"id": строка.id, "tenant": ТЕНАНТ, "reason": "дубль обхода"}]
    assert "Кадров убрано: 2" in ответ.get_data(as_text=True)


def test_отказ_снятия_показан_текстом_а_не_трассировкой(
    стенд: FlaskClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Arrange — причина обязательна, и правило это живёт в блоке `db`.
    def снять(*_a: Any, **_k: Any) -> Retraction:
        raise RetractionError("Причина снятия не названа")

    monkeypatch.setattr(data, "retract_card", снять)
    monkeypatch.setattr(data, "load_card", lambda *_a, **_k: карточка(шапка()))

    # Act
    ответ = стенд.post(
        "/inspections/x/retract", data={"reason": ""}, headers={"Origin": "http://localhost"}
    )

    # Assert
    assert ответ.status_code == 200
    assert "Причина снятия не названа" in ответ.get_data(as_text=True)


def test_снятие_с_чужой_страницы_отклонено_и_не_доходит_до_базы(
    стенд: FlaskClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Arrange — снятие необратимо убирает кадры, а сессионная кука уехала бы
    # с чужой страницы сама: браузер прикладывает её независимо от затейщика.
    вызвано = False

    def снять(*_a: Any, **_k: Any) -> Retraction:
        nonlocal вызвано
        вызвано = True
        raise AssertionError("до базы дойти не должно")

    monkeypatch.setattr(data, "retract_card", снять)

    # Act / Assert — три способа прийти не со своей страницы, и все три отказ.
    # Пустой заголовок стоит первым намеренно: проверка, которая на пустом
    # входе разрешает, обходится тем, что заголовок просто не присылают.
    случаи: list[dict[str, str]] = [
        {},
        {"Origin": "http://зло.example"},
        {"Referer": "http://зло.example/страница"},
        # Понижение схемы: хост тот же, происхождение другое.
        {"Origin": "https://localhost"},
    ]
    for заголовки in случаи:
        ответ = стенд.post(
            "/inspections/x/retract", data={"reason": "чужой запрос"}, headers=заголовки
        )
        assert ответ.status_code == 403, заголовки
    assert вызвано is False


def test_снятие_со_своей_страницы_проходит_и_по_одному_referer(
    стенд: FlaskClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Arrange — `Origin` ставит не всякий браузер и не во всяком случае;
    # заслон обязан пропускать настоящую форму, иначе он ломает продукт.
    monkeypatch.setattr(
        data,
        "retract_card",
        lambda inspection_id, *, tenant, reason: Retraction(
            inspection_id=inspection_id, reason=reason, retracted_at="2026-09-18", photos_purged=0
        ),
    )
    monkeypatch.setattr(data, "load_card", lambda *_a, **_k: карточка(шапка()))

    # Act
    ответ = стенд.post(
        "/inspections/x/retract",
        data={"reason": "своя страница"},
        headers={"Referer": "http://localhost/inspections/x"},
    )

    # Assert
    assert ответ.status_code == 200
    assert "Кадров убрано: 0" in ответ.get_data(as_text=True)


# --- язык, отказы, ненайденное ---------------------------------------------


def test_язык_интерфейса_это_параметр_а_не_константа(стенд: FlaskClient) -> None:
    # Act
    русский = стенд.get("/inspections").get_data(as_text=True)
    английский = стенд.get("/inspections?lang=en").get_data(as_text=True)

    # Assert
    assert "Проверки" in русский
    assert "Inspections" in английский
    assert "Проверки" not in английский


def test_непонятный_язык_в_адресе_страницу_не_роняет(стенд: FlaskClient) -> None:
    # Ввод снаружи приводится к допустимому на границе, а не роняет экран.
    ответ = стенд.get("/inspections?lang=de")
    assert ответ.status_code == 200
    assert "Проверки" in ответ.get_data(as_text=True)


def test_ненайденная_проверка_отвечает_404_с_объяснением(стенд: FlaskClient) -> None:
    # Act
    ответ = стенд.get("/inspections/нет-такой")

    # Assert
    assert ответ.status_code == 404
    assert "Проверка не найдена" in ответ.get_data(as_text=True)


def test_недоступная_база_показана_страницей_а_не_пятисотой(
    стенд: FlaskClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Arrange — админка читает чужой стенд, и он бывает выключен.
    def падать(**_: Any) -> data.Registry:
        raise DbError("связь с базой не установлена")

    monkeypatch.setattr(data, "load_registry", падать)

    # Act
    ответ = стенд.get("/inspections")

    # Assert
    assert ответ.status_code == 503
    assert "связь с базой не установлена" in ответ.get_data(as_text=True)


def test_страницы_не_встраиваются_в_чужой_документ(стенд: FlaskClient) -> None:
    # Arrange — заслон происхождения закрывает запрос С чужой страницы, но не
    # случай, когда чужая страница показывает НАШУ в рамке: происхождение
    # тогда честно совпадает, и форму снятия можно нажать чужими руками.
    # Проверяем и построенный раздел, и заглушку, и страницу отказа: рамка не
    # выбирает, какую страницу встраивать.
    for адрес in ("/inspections", "/calendar", "/нет-такой-страницы"):
        # Act
        ответ = стенд.get(адрес)

        # Assert
        assert ответ.headers.get("X-Frame-Options") == "DENY", адрес
        assert "frame-ancestors 'none'" in ответ.headers.get("Content-Security-Policy", ""), адрес


def test_отказ_снятия_показан_на_карточке_а_не_потерян(
    стенд: FlaskClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Arrange — отказ снятия обязан дойти до человека словами. Что в самом
    # отказе не окажется адреса базы, проверяет не этот тест, а
    # `test_db_retraction_error_text.py`: здесь источник подменён, и порча
    # настоящего текста отсюда не видна — проверено порчей.
    def снять(*_a: Any, **_k: Any) -> Retraction:
        raise RetractionError("Снятие проверки x не удалось (OperationalError). Повторить можно")

    monkeypatch.setattr(data, "retract_card", снять)
    monkeypatch.setattr(data, "load_card", lambda *_a, **_k: карточка(шапка()))

    # Act
    ответ = стенд.post(
        "/inspections/x/retract",
        data={"reason": "проверка отказа"},
        headers={"Origin": "http://localhost"},
    )

    # Assert — причина отказа на экране есть, адреса базы в ней нет.
    страница = ответ.get_data(as_text=True)
    assert "OperationalError" in страница
    for след in ("host=", "port=", "dbname=", "user=", "postgresql://"):
        assert след not in страница, след
