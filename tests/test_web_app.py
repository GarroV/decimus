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

import re
from collections.abc import Iterator
from datetime import date
from typing import Any

import pytest
from flask.testing import FlaskClient
from web_harness import ЛОГИН, войти, подменить_двери, собрать

from src.db.errors import DbError, MoveError, RetractionError
from src.db.models import FindingRow, InspectionDetail, InspectionRow
from src.db.move import MoveRecord
from src.db.retract import Retraction
from src.web import inspections as data
from src.web import overview as overview_data
from src.web.assets import FONT_MAX_AGE, IMMUTABLE_MAX_AGE
from src.web.sections import SECTIONS

ТЕНАНТ = "default"


#: Сеть без единой записи: экран «Обзор» ходит в базу, а этот стенд
#: проверяет не данные, а то, что каждый раздел открывается.
ПУСТАЯ_СЕТЬ = overview_data.Overview(
    units_total=0,
    inspections=(),
    grades=(),
    average=None,
    comparable=True,
    comparability_note="",
    zone_losses=(),
    systemic=(),
    attention=(),
    problem_units=(),
)


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
def стенд(monkeypatch: pytest.MonkeyPatch, request: pytest.FixtureRequest) -> Iterator[FlaskClient]:
    """Приложение с подменёнными дверями блока `db` и УЖЕ ВОШЕДШИМ человеком.

    Вход настоящий — отправкой формы (`tests/web_harness.py`). После T323 без
    него не открывается ни один экран, и подставлять сюда обход заслона
    значило бы проверять экраны в положении, которого у живого приложения не
    бывает.
    """
    monkeypatch.setattr(data, "retraction_available", lambda: True)
    monkeypatch.setattr(data, "load_registry", lambda **_: data.Registry((), True))
    monkeypatch.setattr(overview_data, "load", lambda **_: ПУСТАЯ_СЕТЬ)
    monkeypatch.setattr(data, "load_card", lambda *_a, **_k: None)
    роль = getattr(request, "param", "auditor")
    подменить_двери(monkeypatch, tenant=ТЕНАНТ, role=роль)
    with собрать(tenant=ТЕНАНТ).test_client() as client:
        assert войти(client).status_code == 302
        yield client


#: Тот же стенд, но вошёл администратор: отклонение и перенос — только его.
админ = pytest.mark.parametrize("стенд", ["admin"], indirect=True)


# --- каркас: девять разделов и честная лента (D138) ------------------------


def test_все_девять_разделов_открываются(стенд: FlaskClient) -> None:
    # Act / Assert — раздел, которого нет в карте продукта, спрятан, а прятать
    # непостроенное решением запрещено.
    # Раздел с ограничением по роли (T338) из этого правила выведен: он и
    # должен отказывать, и отказывает вслух — 403 с объяснением, а не пустой
    # страницей.
    for раздел in SECTIONS:
        ожидаемый = 403 if раздел.admin_only else 200
        assert стенд.get(раздел.path).status_code == ожидаемый, раздел.key


def test_непостроенный_раздел_говорит_что_он_в_разработке(стенд: FlaskClient) -> None:
    # Arrange
    непостроенные = [раздел for раздел in SECTIONS if not раздел.built]

    # Act / Assert — не на том разделе, куда посмотрели, а на всех сразу.
    assert len(непостроенные) == 6
    for раздел in непостроенные:
        страница = стенд.get(раздел.path).get_data(as_text=True)
        assert "ещё в разработке" in страница, раздел.key
        assert "tape tape--screen" in страница, раздел.key


def test_построенный_раздел_ленты_не_несёт(стенд: FlaskClient) -> None:
    # Act
    страница = стенд.get("/inspections").get_data(as_text=True)

    # Assert — ни ленты на экране, ни приглушения у своего пункта навигации.
    # Смотрим ВНУТРЬ навигации, а не во всю страницу: адреса разделов есть и
    # в отборе выборки, и проверка по всей странице ловила их вместо пунктов
    # меню — то есть проверяла не то, что написано в её имени.
    assert "tape tape--screen" not in страница
    навигация = re.search(r'<nav class="sidenav.*?</nav>', страница, re.S)
    assert навигация, "на странице построенного раздела обязана быть навигация"
    свой = re.search(r'<span class="sidenav__current"[^>]*>', навигация.group(0))
    assert свой, "свой раздел в навигации обязан быть помечен как текущий"
    assert "is-wip" not in свой.group(0), "построенный раздел не приглушается"


def test_навигация_показывает_карту_продукта_целиком(стенд: FlaskClient) -> None:
    # Act — карту видно с любого экрана, а не только с главного.
    страница = стенд.get("/calendar").get_data(as_text=True)

    # Assert — непостроенный раздел в карте есть и помечен, но ПРИГЛУШЕНИЕМ,
    # а не цветной лентой: лент было семь на один экран, и бриф на визуал
    # оставляет сильный цвет букве оценки и классу нарушения, больше нигде
    # (D190). Пометка обязана остаться какой-то: раздел без неё выглядит
    # готовым, и человек идёт в него за работой, которой там нет.
    assert "sidenav__item is-wip" in страница
    for раздел in SECTIONS:
        if раздел.admin_only:
            # Ссылка, ведущая в отказ, выглядит как поломка продукта: раздел
            # с ограничением по роли не зовёт того, кого не пустят.
            assert раздел.path not in страница, раздел.key
            continue
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


def test_без_администратора_истории_плашки_о_снятых_нет(
    стенд: FlaskClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Arrange
    monkeypatch.setattr(data, "retraction_available", lambda: False)
    monkeypatch.setattr(data, "load_registry", lambda **_: data.Registry((шапка(),), False))

    # Act
    страница = стенд.get("/inspections").get_data(as_text=True)

    # Assert — без роли администратора истории снять проверку не может никто,
    # снятых нет, и предупреждать о них — шум (D193). Имя переменной окружения
    # человеку на экране тем более не нужно.
    assert "Снятые проверки не видны" not in страница
    assert "DATABASE_RETRACTION_URL" not in страница


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
    assert "Снятые проверки не видны" not in страница


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


@админ
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


@админ
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


@админ
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


@админ
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


@админ
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


def test_ссылки_страницы_собираются_с_путём_общего_входа(
    стенд: FlaskClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Под чужим корнем кнопки ведут к админке, а не в корень площадки.

    Снаружи админка живёт под путём общего входа (`WEB_URL_PREFIX`, T324), и
    путь этот приходит в `SCRIPT_NAME`. Ссылка, собранная без него, открывает
    корень площадки — то есть соседний продукт: страница при этом выглядит
    рабочей, и промах виден только по нажатию.

    Проверено на живой поломке: до этой правки шаблоны писали `/inspections`
    строкой, и снаружи первая же кнопка реестра уводила с админки.
    """
    monkeypatch.setattr(data, "load_registry", lambda **_: data.Registry((шапка(),), True))

    ответ = стенд.get("/inspections", base_url="http://localhost/audit/")

    разметка = ответ.get_data(as_text=True)
    assert 'href="/audit/inspections' in разметка
    assert 'href="/inspections' not in разметка


# --- статика: отпечаток в адресе и долгий кеш (src/web/assets.py) ---------
# Замер 24.09.2026: без кеша каждый переход между разделами переспрашивал три
# таблицы стилей и шрифты, по 0,3 с на запрос через Funnel, и страница стояла
# белой до ответа — владелец видел это как моргание экрана.


def test_стили_адресуются_с_отпечатком_и_кешируются_на_год(стенд: FlaskClient) -> None:
    # Arrange
    страница = стенд.get("/inspections").get_data(as_text=True)
    адреса = re.findall(r'href="([^"]*decimus-web\.css[^"]*)"', страница)
    assert адреса, "страница обязана подключать decimus-web.css"

    # Act
    ответ = стенд.get(адреса[0])

    # Assert
    assert re.search(r"\?v=[0-9a-f]{12}$", адреса[0]), адреса[0]
    assert ответ.status_code == 200
    assert f"max-age={IMMUTABLE_MAX_AGE}" in ответ.headers["Cache-Control"]


def test_адрес_без_отпечатка_перепроверяется(стенд: FlaskClient) -> None:
    # Act — старый адрес без `?v=` на год кешировать нельзя: он не меняется
    # вместе с файлом, и человек застрял бы на прошлых стилях.
    ответ = стенд.get("/static/decimus-web.css")

    # Assert
    assert "max-age=31536000" not in ответ.headers.get("Cache-Control", "")


def test_шрифт_кешируется_на_неделю_без_отпечатка(стенд: FlaskClient) -> None:
    # Act
    ответ = стенд.get("/static/fonts/manrope-cyrillic.woff2")

    # Assert
    assert ответ.status_code == 200
    assert f"max-age={FONT_MAX_AGE}" in ответ.headers["Cache-Control"]


# --- сбой подключения администратора истории не роняет экран (#307) --------


def _сломанный_админ(ответ: Any) -> Any:
    """Чтение, которое падает под администратором и отвечает обычной ролью."""

    def прочитать(*_a: Any, include_retracted: bool = False, **_k: Any) -> Any:
        if include_retracted:
            raise DbError("password authentication failed for user dodo_audit_admin")
        return ответ

    return прочитать


def test_реестр_без_снятых_если_администратор_не_подключился(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Arrange — 21.09.2026 неверный адрес этого подключения давал 503 на всём
    # реестре при живой базе.
    строка = шапка()
    monkeypatch.setattr(data, "retraction_available", lambda: True)
    monkeypatch.setattr(data.queries, "list_inspections", _сломанный_админ([строка]))

    # Act
    реестр = data.load_registry(tenant=ТЕНАНТ, limit=10)

    # Assert
    assert реестр.rows == (строка,)
    assert реестр.retracted_visible is False


def test_карточка_открывается_если_администратор_не_подключился(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Arrange
    деталь = карточка(шапка())
    monkeypatch.setattr(data, "retraction_available", lambda: True)
    monkeypatch.setattr(data.queries, "get_inspection", _сломанный_админ(деталь))

    # Act / Assert
    assert data.load_card(деталь.inspection.id, tenant=ТЕНАНТ) is деталь


def test_лежащая_база_по_прежнему_отказ(monkeypatch: pytest.MonkeyPatch) -> None:
    # Arrange — откат на обычную роль не должен превращать «база лежит» в
    # пустой реестр: обычное чтение падает следом и отказ доходит до экрана.
    def лежит(*_a: Any, **_k: Any) -> Any:
        raise DbError("connection refused")

    monkeypatch.setattr(data, "retraction_available", lambda: True)
    monkeypatch.setattr(data.queries, "list_inspections", лежит)

    # Act / Assert
    with pytest.raises(DbError):
        data.load_registry(tenant=ТЕНАНТ, limit=10)


def test_аудитор_не_отклоняет_проверку(стенд: FlaskClient, monkeypatch: pytest.MonkeyPatch) -> None:
    # Arrange — до 24.09.2026 маршрут проверял только вход, и отклонить
    # проверку с выносом кадров мог любой вошедший.
    def отклонить(*_a: Any, **_k: Any) -> Retraction:
        raise AssertionError("до базы дойти не должно")

    monkeypatch.setattr(data, "retract_card", отклонить)
    monkeypatch.setattr(data, "load_card", lambda *_a, **_k: карточка(шапка()))

    # Act
    ответ = стенд.post(
        "/inspections/x/retract", data={"reason": "дубль"}, headers={"Origin": "http://localhost"}
    )
    карточка_аудитора = стенд.get("/inspections/x").get_data(as_text=True)

    # Assert — отказ, и формы ему не показывают.
    assert ответ.status_code == 403
    assert "/retract" not in карточка_аудитора


# --- перенос по дате и пиццерии (D195) ---------------------------------------


def _перенос(
    monkeypatch: pytest.MonkeyPatch, *, история: tuple[Any, ...] = ()
) -> list[dict[str, Any]]:
    вызовы: list[dict[str, Any]] = []

    def перенести(inspection_id: str, **kw: Any) -> bool:
        вызовы.append({"id": inspection_id, **kw})
        return True

    monkeypatch.setattr(data, "move_card", перенести)
    monkeypatch.setattr(data, "load_moves", lambda *_a, **_k: история)
    monkeypatch.setattr(data, "load_units", lambda **_: (("u-1", "Тбилиси-1"), ("u-2", "Батуми-1")))
    monkeypatch.setattr(data, "load_card", lambda *_a, **_k: карточка(шапка()))
    return вызовы


@админ
def test_администратор_переносит_и_автор_берётся_из_сессии(
    стенд: FlaskClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Arrange
    вызовы = _перенос(monkeypatch)

    # Act — автор в форме не передаётся: его подставляет вход, а не человек.
    ответ = стенд.post(
        "/inspections/x/move",
        data={"date": "2026-09-01", "unit": "u-2", "reason": "не та точка", "actor": "подлог"},
        headers={"Origin": "http://localhost"},
    )

    # Assert
    assert ответ.status_code == 200
    assert вызовы == [
        {
            "id": "x",
            "tenant": ТЕНАНТ,
            "new_date": "2026-09-01",
            "new_unit_id": "u-2",
            "reason": "не та точка",
            "actor": ЛОГИН,
        }
    ]
    assert "Исправлено." in ответ.get_data(as_text=True)


def test_аудитор_не_переносит(стенд: FlaskClient, monkeypatch: pytest.MonkeyPatch) -> None:
    # Arrange
    вызовы = _перенос(monkeypatch)

    # Act
    ответ = стенд.post(
        "/inspections/x/move",
        data={"date": "2026-09-01", "unit": "u-2", "reason": "не та точка"},
        headers={"Origin": "http://localhost"},
    )
    страница = стенд.get("/inspections/x").get_data(as_text=True)

    # Assert
    assert ответ.status_code == 403
    assert вызовы == []
    assert "/move" not in страница


@админ
def test_форма_переноса_и_история_на_карточке(
    стенд: FlaskClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Arrange
    след = MoveRecord(
        moved_at="2026-09-24T15:00+00:00",
        moved_by="admin",
        reason="опечатка в названии",
        old_date="2026-09-21",
        new_date="2026-09-21",
        old_unit="Тбилиси -1",
        new_unit="Тбилиси-1",
    )
    _перенос(monkeypatch, история=(след,))

    # Act
    страница = стенд.get("/inspections/x").get_data(as_text=True)

    # Assert
    assert "/move?lang=" in страница
    assert "Тбилиси -1, 2026-09-21 → Тбилиси-1, 2026-09-21" in страница
    assert "опечатка в названии" in страница


@админ
def test_без_истории_формы_переноса_нет(
    стенд: FlaskClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Arrange — схема без 0025: история не читается, и перенос без следа
    # показывать нельзя.
    _перенос(monkeypatch)

    def нет_истории(*_a: Any, **_k: Any) -> Any:
        raise DbError("relation inspection_moves does not exist")

    monkeypatch.setattr(data, "load_moves", нет_истории)

    # Act
    страница = стенд.get("/inspections/x").get_data(as_text=True)

    # Assert
    assert "/move" not in страница
    assert "История исправлений сейчас недоступна" in страница


@админ
def test_отказ_переноса_показан_текстом(
    стенд: FlaskClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Arrange
    _перенос(monkeypatch)

    def отказать(*_a: Any, **_k: Any) -> bool:
        raise MoveError("Не назван повод исправления")

    monkeypatch.setattr(data, "move_card", отказать)

    # Act
    ответ = стенд.post(
        "/inspections/x/move",
        data={"date": "2026-09-01", "unit": "u-2", "reason": ""},
        headers={"Origin": "http://localhost"},
    )

    # Assert
    assert "Исправить не удалось: Не назван повод исправления" in ответ.get_data(as_text=True)
