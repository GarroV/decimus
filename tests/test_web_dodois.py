"""Блок «Dodo IS» на «Подключениях» и публичная страница входа по ссылке (D640).

База, сеть и вход Dodo IS подменены на границе модулей (`dodois_logins`, `dodois.flow`).
Здесь поверхность: кто пройдёт (404 всем, кроме главного админа, на чтение и каждую запись),
заслоны выдачи, ссылка видна один раз и нигде не остаётся, одинаковый 404 на любой плохой
токен, GET ничего не начинает, предел попыток по адресу, закрыто в демо. Настоящая база и
шифрование — `tests/test_db_dodois_logins.py`. Каждая проверка прогонялась на сломанной
копии (что ломали — в комментарии теста).
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from flask.testing import FlaskClient
from web_harness import СВОЙ, войти, подменить_двери, собрать

from src.db import dodois_logins as store
from src.db import health_store, ratings_read
from src.dodois import client, flow, service
from src.dodois.client import Credentials
from src.domain import dodois as rules
from src.domain.dodois import Invite
from src.web import auth, dodois_connect

ЗАГОЛОВКИ = {"Origin": СВОЙ}
ВКЛАДКА = "/administration?tab=dodois"
ВЫДАЧА = "/administration/dodois/invite"
РОЛИ = [("HQ", "admin"), ("HQ", "control"), ("HQ", "auditor"), ("GE", "admin"), ("GE", "auditor")]
СТРАНЫ = (
    ratings_read.CountryRow("SI", "Словения", "Slovenia", None, True),
    ratings_read.CountryRow("BG", "Болгария", "Bulgaria", None, True),
)


class Ссылки:
    """Двойник дверей базы для ссылок и входов: что записано и кого звали."""

    def __init__(self) -> None:
        self.ссылки: dict[int, Invite] = {}
        self.зовы: list[str] = []

    def create_invite(self, **поля: Any) -> int:
        self.зовы.append("create")
        номер = len(self.ссылки) + 1
        self.ссылки[номер] = Invite(
            id=номер,
            country=поля["country"],
            issued_by=поля["issued_by"],
            issued_at=поля["now"],
            expires_at=поля["expires_at"],
            used_at=None,
            revoked_at=None,
            token_hash=поля["token_hash"],
            issued_by_id=поля["issued_by_id"],
            issued_by_role=поля["issued_by_role"],
            issued_by_tenant=поля["issued_by_tenant"],
        )
        return номер

    def find_invite(self, token_hash: str) -> Invite | None:
        return next(
            (i for i in self.ссылки.values() if rules.hashes_equal(i.token_hash, token_hash)), None
        )

    def list_invites(self, limit: int = 30) -> tuple[Invite, ...]:
        return tuple(sorted(self.ссылки.values(), key=lambda i: -i.id))[:limit]

    def revoke_invite(self, invite_id: int, now: datetime) -> bool:
        self.зовы.append("revoke")
        ссылка = self.ссылки.get(invite_id)
        if ссылка is None or ссылка.used_at or ссылка.revoked_at:
            return False
        self.ссылки[invite_id] = replace(ссылка, revoked_at=now)
        return True

    def изменить(self, invite_id: int, **поля: Any) -> None:
        self.ссылки[invite_id] = replace(self.ссылки[invite_id], **поля)


class Вход:
    """Двойник `flow.start`: записывает, с какой ссылкой начали вход."""

    def __init__(self) -> None:
        self.начато: list[Invite] = []
        self.ошибка: Exception | None = None

    def start(self, invite: Invite, *, creds: Credentials, ip: str | None) -> flow.Flow:
        self.начато.append(invite)
        if self.ошибка is not None:
            raise self.ошибка
        вход = flow.Flow(invite=invite, ip=ip, started=0.0, user_code="ABCD-1234")
        вход.link = "https://auth.dodois.com/device?user_code=ABCD-1234"
        вход.state = flow.PENDING
        flow._flows[invite.id] = вход
        return вход


@pytest.fixture(autouse=True)
def _чисто() -> Iterator[None]:
    flow.forget_all()
    yield
    flow.forget_all()


@pytest.fixture
def ссылки(monkeypatch: pytest.MonkeyPatch) -> Ссылки:
    двойник = Ссылки()
    for имя in ("create_invite", "find_invite", "list_invites", "revoke_invite"):
        monkeypatch.setattr(store, имя, getattr(двойник, имя))
    monkeypatch.setattr(store, "list_logins", lambda: ())
    monkeypatch.setattr(store, "get_login", lambda _c: None)
    monkeypatch.setattr(ratings_read, "countries", lambda: СТРАНЫ)
    monkeypatch.setattr(health_store, "probes", lambda: {})
    monkeypatch.setattr(health_store, "loads", lambda: {})
    return двойник


@pytest.fixture
def вход(monkeypatch: pytest.MonkeyPatch, ссылки: Ссылки) -> Вход:
    двойник = Вход()
    monkeypatch.setattr(flow, "start", двойник.start)
    monkeypatch.setattr(store, "check_secrets_key", lambda: None)
    monkeypatch.setattr(service, "credentials", lambda: Credentials("id", "secret"))
    return двойник


def _стенд(
    monkeypatch: pytest.MonkeyPatch, *, tenant: str, role: str
) -> Iterator[tuple[FlaskClient, dict[str, list[Any]]]]:
    двери = подменить_двери(monkeypatch, tenant=tenant, role=role)
    with собрать(tenant="HQ").test_client() as клиент:
        assert войти(клиент).status_code == 302
        yield клиент, двери


@pytest.fixture
def стенд(
    monkeypatch: pytest.MonkeyPatch, ссылки: Ссылки
) -> Iterator[tuple[FlaskClient, dict[str, list[Any]]]]:
    yield from _стенд(monkeypatch, tenant="HQ", role="superadmin")


@pytest.fixture
def главный(стенд: tuple[FlaskClient, dict[str, list[Any]]]) -> FlaskClient:
    return стенд[0]


@pytest.fixture
def чужой(monkeypatch: pytest.MonkeyPatch, вход: Вход) -> Iterator[FlaskClient]:
    """Посетитель без входа в decimus — коллега по ссылке."""
    подменить_двери(monkeypatch, tenant="HQ", role="superadmin")
    with собрать(tenant="HQ").test_client() as клиент:
        yield клиент


def _выдать(клиент: FlaskClient, страна: str = "SI") -> tuple[Any, str]:
    ответ = клиент.post(ВЫДАЧА, data={"country": страна}, headers=ЗАГОЛОВКИ)
    найдено = re.search(r"/dodois/connect/([A-Za-z0-9_-]{43})", ответ.get_data(as_text=True))
    return ответ, найдено.group(1) if найдено else ""


# --- кто пройдёт ---------------------------------------------------------------------------


@pytest.mark.parametrize(("tenant", "role"), РОЛИ)
def test_остальным_блока_нет_ни_на_чтение_ни_на_запись(
    monkeypatch: pytest.MonkeyPatch, ссылки: Ссылки, tenant: str, role: str
) -> None:
    # Сломанная копия: в маршрутах заменить `keys.manage` на `view.users` — тест падает на 200.
    for клиент, _ in _стенд(monkeypatch, tenant=tenant, role=role):
        читать = клиент.get(ВКЛАДКА)
        assert читать.status_code == 404 and "Dodo IS" not in читать.get_data(as_text=True)
        for адрес in (
            ВЫДАЧА,
            "/administration/dodois/invite/1/revoke",
            "/administration/dodois/SI/check",
        ):
            ответ = клиент.post(адрес, data={"country": "SI"}, headers=ЗАГОЛОВКИ)
            assert ответ.status_code == 404, f"{role}@{tenant} достучался до {адрес}"
    assert ссылки.зовы == [], "чужая роль дошла до базы"


def test_главный_админ_видит_блок(главный: FlaskClient) -> None:
    html = главный.get(ВКЛАДКА).get_data(as_text=True)
    assert 'id="dodois"' in html and 'id="dodois-countries"' in html
    # Вкладка своя (D641): блока нет в «Подключениях», страны сети видны и без входов.
    assert "Словения" in html and "Болгария" in html
    assert "Входа нет" in html
    # D651: одна таблица, у каждой страны своя кнопка выдачи; карточек и выбора страны нет.
    assert html.count("Сгенерировать ссылку") >= 2 and 'class="stile' not in html
    for колонка in ("Страна", "Статус", "Через кого подключено"):
        assert колонка in html


def test_блок_не_остался_во_вкладке_подключения(главный: FlaskClient) -> None:
    html = главный.get("/administration?tab=connections").get_data(as_text=True)
    assert 'id="dodois"' not in html and "dodois-countries" not in html


def test_вкладка_стоит_после_подключений_и_ключей(главный: FlaskClient) -> None:
    html = главный.get(ВКЛАДКА).get_data(as_text=True)
    assert 'aria-current="page"' in html
    вкладки = re.findall(r'class="sadmin__tab[^"]*" href="[^"]*\?tab=(\w+)', html)
    assert вкладки[-3:] == ["connections", "keys", "dodois"]


@pytest.mark.parametrize(
    "адрес",
    [
        ВЫДАЧА,
        "/administration/dodois/invite/1/revoke",
        "/administration/dodois/SI/check",
    ],
)
def test_чужое_происхождение_отказ_и_без_действия(
    главный: FlaskClient, ссылки: Ссылки, адрес: str
) -> None:
    без = главный.post(адрес, data={"country": "SI"})
    чужое = главный.post(
        адрес,
        data={"country": "SI"},
        headers={"Origin": "https://evil.example"},
    )
    assert (без.status_code, чужое.status_code) == (403, 403)
    assert ссылки.зовы == []


def test_неизвестная_страна_в_проверке_404(главный: FlaskClient) -> None:
    assert главный.post("/administration/dodois/si/check", headers=ЗАГОЛОВКИ).status_code == 404


# --- заслоны выдачи (как у ключей сервисов) -------------------------------------------------


def _сессия_с(monkeypatch: pytest.MonkeyPatch, **признаки: Any) -> None:
    прежняя = auth.resolve_session

    def _resolve(token: str) -> Any:
        учётка = прежняя(token)
        for имя, значение in признаки.items():
            setattr(учётка, имя, значение)
        return учётка

    monkeypatch.setattr(auth, "resolve_session", _resolve)


def test_без_второго_шага_входа_ссылку_не_выдают(
    стенд: tuple[FlaskClient, dict[str, list[Any]]],
    ссылки: Ссылки,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Сломанная копия: убрать `_key_gate` из `dodois_invite_issue` — падает на 200.
    _сессия_с(monkeypatch, has_second_factor=False)
    ответ, токен = _выдать(стенд[0])
    assert ответ.status_code == 403 and токен == "" and ссылки.зовы == []


def test_несвежее_подтверждение_уводит_на_подтверждение(
    стенд: tuple[FlaskClient, dict[str, list[Any]]],
    ссылки: Ссылки,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _сессия_с(monkeypatch, signed_in_at=datetime.now(UTC) - timedelta(minutes=11))
    ответ, _ = _выдать(стенд[0])
    assert ответ.status_code == 302 and ссылки.зовы == []


def test_второй_шаг_не_пройден_в_этой_сессии_отказ(
    стенд: tuple[FlaskClient, dict[str, list[Any]]],
    ссылки: Ссылки,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _сессия_с(monkeypatch, passed_second_step=False)
    assert _выдать(стенд[0])[0].status_code == 403 and ссылки.зовы == []


# --- выдача: ссылка видна один раз, токена нигде нет ---------------------------------------


def test_ссылка_привязана_к_стране_живёт_сутки_и_в_базе_только_хэш(
    стенд: tuple[FlaskClient, dict[str, list[Any]]], ссылки: Ссылки
) -> None:
    ответ, токен = _выдать(стенд[0], "BG")
    assert ответ.status_code == 200 and токен
    (ссылка,) = ссылки.ссылки.values()
    assert ссылка.country == "BG" and ссылка.issued_by == "director"
    assert ссылка.expires_at - ссылка.issued_at == rules.INVITE_TTL
    assert ссылка.token_hash == rules.hash_token(токен) and токен not in ссылка.token_hash
    assert "no-store" in ответ.headers["Cache-Control"]


def test_ссылка_показана_один_раз_и_не_попадает_в_журнал_и_страницы(
    стенд: tuple[FlaskClient, dict[str, list[Any]]], ссылки: Ссылки
) -> None:
    # Сломанная копия: класть ссылку в `flash` или цель журнала — токен найдётся ниже.
    клиент, двери = стенд
    ответ, токен = _выдать(клиент)
    assert токен and "Ссылка показана один раз" in ответ.get_data(as_text=True)
    повтор = клиент.get(ВКЛАДКА).get_data(as_text=True)
    assert токен not in повтор and "Выдана" in повтор, "дальше только статус"
    for запись in двери["action_journal"]:
        assert токен not in str(запись), "токен ссылки попал в журнал действий"
    выдача = next(з for з in двери["action_journal"] if з["action"] == "dodois_invite_issue")
    assert выдача["target"] == "country=SI; invite=1"


def test_страна_только_из_реестра(
    стенд: tuple[FlaskClient, dict[str, list[Any]]], ссылки: Ссылки
) -> None:
    for плохая in ("ZZ", "si", "", "SLO", "'; drop table"):
        ответ, токен = _выдать(стенд[0], плохая)
        assert ответ.status_code == 400 and токен == "", плохая
    assert ссылки.ссылки == {}


def test_отзыв_гасит_ссылку_и_второй_раз_отказ(
    стенд: tuple[FlaskClient, dict[str, list[Any]]], ссылки: Ссылки, чужой: FlaskClient
) -> None:
    клиент, _ = стенд
    _, токен = _выдать(клиент)
    адрес = "/administration/dodois/invite/1/revoke"
    assert клиент.post(адрес, headers=ЗАГОЛОВКИ).status_code == 200
    assert "Отозвана" in клиент.get(ВКЛАДКА).get_data(as_text=True)
    assert клиент.post(адрес, headers=ЗАГОЛОВКИ).status_code == 409
    assert чужой.get(f"/dodois/connect/{токен}").status_code == 404


# --- публичная страница --------------------------------------------------------------------


def _ссылка_живая(ссылки: Ссылки, страна: str = "SI") -> str:
    токен = rules.new_token()
    сейчас = datetime.now(UTC)
    ссылки.create_invite(
        country=страна,
        token_hash=rules.hash_token(токен),
        issued_by="director",
        issued_by_id="22222222-2222-2222-2222-222222222222",
        issued_by_role="superadmin",
        issued_by_tenant="HQ",
        now=сейчас,
        expires_at=сейчас + rules.INVITE_TTL,
    )
    return токен


def test_открытие_ссылки_ничего_не_начинает(чужой: FlaskClient, ссылки: Ссылки, вход: Вход) -> None:
    # Сломанная копия: звать `flow.start` из GET-маршрута — боты-превью мессенджеров тратили бы код.
    токен = _ссылка_живая(ссылки)
    for _ in range(3):
        ответ = чужой.get(
            f"/dodois/connect/{токен}", headers={"User-Agent": "Slackbot-LinkExpanding"}
        )
        assert ответ.status_code == 200
    assert вход.начато == [], "GET начал вход"
    assert flow.current(1) is None


def test_страница_объясняет_и_ведёт_на_кнопку(чужой: FlaskClient, ссылки: Ссылки) -> None:
    html = чужой.get(f"/dodois/connect/{_ссылка_живая(ссылки)}").get_data(as_text=True)
    assert "Decimus просит доступ на чтение данных Dodo IS" in html
    assert "Подтверждайте только на auth.dodois.com" in html
    assert "Войти в Dodo IS" in html and "Словения" in html


def test_заголовки_без_реферера_без_кэша_и_без_сторонних_ресурсов(
    чужой: FlaskClient, ссылки: Ссылки
) -> None:
    # Сломанная копия: убрать `_public_headers` — Referer унесёт токен на сайт Dodo IS.
    токен = _ссылка_живая(ссылки)
    for адрес in (f"/dodois/connect/{токен}", f"/dodois/connect/{токен}/status"):
        ответ = чужой.get(адрес)
        assert ответ.headers["Referrer-Policy"] == "no-referrer"
        assert "no-store" in ответ.headers["Cache-Control"]
    html = чужой.get(f"/dodois/connect/{токен}").get_data(as_text=True)
    внешние = re.findall(r'(?:src|href|action)="(https?://[^"]+)"', html)
    assert внешние == [], f"сторонние ресурсы на странице: {внешние}"
    неверный = чужой.get("/dodois/connect/" + "a" * 43)
    assert неверный.headers["Referrer-Policy"] == "no-referrer"
    assert "no-store" in неверный.headers["Cache-Control"]


def _плохие(ссылки: Ссылки) -> dict[str, str]:
    """Пять разных «нет»: чужой токен, кривая форма, погашена, истекла, отозвана."""
    погашена, истекла, отозвана = (_ссылка_живая(ссылки) for _ in range(3))
    сейчас = datetime.now(UTC)
    ссылки.изменить(1, used_at=сейчас)
    ссылки.изменить(
        2, expires_at=сейчас - timedelta(seconds=1), issued_at=сейчас - timedelta(days=2)
    )
    ссылки.изменить(3, revoked_at=сейчас)
    return {
        "чужой": rules.new_token(),
        "форма": "короткий",
        "погашена": погашена,
        "истекла": истекла,
        "отозвана": отозвана,
    }


def test_любой_плохой_токен_даёт_один_и_тот_же_404(
    чужой: FlaskClient, ссылки: Ссылки, вход: Вход
) -> None:
    # Сломанная копия: отвечать 410 на погашенную или 403 на истёкшую — ответы разойдутся.
    ответы = {}
    for название, токен in _плохие(ссылки).items():
        for метод, суффикс in (("get", ""), ("post", "/start"), ("get", "/status")):
            ответ = getattr(чужой, метод)(f"/dodois/connect/{токен}{суффикс}", headers=ЗАГОЛОВКИ)
            # Страница отказа повторяет адрес запроса в форме выбора языка — это не причина.
            тело = ответ.get_data().replace(токен.encode(), b"TOKEN")
            ответы[(название, метод, суффикс)] = (ответ.status_code, тело)
    assert {код for код, _ in ответы.values()} == {404}
    for метод, суффикс in (("get", ""), ("post", "/start"), ("get", "/status")):
        тела = {
            ответы[(н, метод, суффикс)][1]
            for н in ("чужой", "форма", "погашена", "истекла", "отозвана")
        }
        assert len(тела) == 1, f"{метод} {суффикс}: тела ответов различаются — по ним видна причина"
    assert вход.начато == []


def test_ссылка_одноразова_после_погашения_вход_не_начинается(
    чужой: FlaskClient, ссылки: Ссылки, вход: Вход
) -> None:
    токен = _ссылка_живая(ссылки)
    ссылки.изменить(1, used_at=datetime.now(UTC))
    assert чужой.post(f"/dodois/connect/{токен}/start", headers=ЗАГОЛОВКИ).status_code == 404
    assert вход.начато == []


def test_кнопка_начинает_вход_по_этой_ссылке_и_страна_из_ссылки(
    чужой: FlaskClient, ссылки: Ссылки, вход: Вход
) -> None:
    токен = _ссылка_живая(ссылки, "BG")
    ответ = чужой.post(f"/dodois/connect/{токен}/start", headers=ЗАГОЛОВКИ)
    html = ответ.get_data(as_text=True)
    assert ответ.status_code == 200 and "ABCD-1234" in html
    assert [(и.id, и.country) for и in вход.начато] == [(1, "BG")]
    assert "https://auth.dodois.com/device?user_code=ABCD-1234" in html
    assert "device_code" not in html and "data-status-url" in html


def test_чужое_происхождение_кнопки_отказ(чужой: FlaskClient, ссылки: Ссылки, вход: Вход) -> None:
    токен = _ссылка_живая(ссылки)
    for заголовки in ({}, {"Origin": "https://evil.example"}):
        ответ = чужой.post(f"/dodois/connect/{токен}/start", headers=заголовки)
        assert ответ.status_code == 403
    assert вход.начато == []


def test_нет_ключей_приложения_или_сбой_связи_говорят_человеку_и_ничего_не_портят(
    чужой: FlaskClient, ссылки: Ссылки, вход: Вход, monkeypatch: pytest.MonkeyPatch
) -> None:
    токен = _ссылка_живая(ссылки)
    вход.ошибка = client.DodoisError(client.NETWORK)
    ответ = чужой.post(f"/dodois/connect/{токен}/start", headers=ЗАГОЛОВКИ)
    assert ответ.status_code == 503 and "Dodo IS сейчас не отвечает" in ответ.get_data(as_text=True)
    monkeypatch.setattr(service, "credentials", lambda: None)
    ответ = чужой.post(f"/dodois/connect/{токен}/start", headers=ЗАГОЛОВКИ)
    assert ответ.status_code == 503 and "ещё не настроен" in ответ.get_data(as_text=True)
    assert ссылки.ссылки[1].used_at is None, "сбой не гасит ссылку"


def test_статус_отдаёт_только_состояние(чужой: FlaskClient, ссылки: Ссылки, вход: Вход) -> None:
    токен = _ссылка_живая(ссылки)
    assert чужой.get(f"/dodois/connect/{токен}/status").get_json() == {"state": "idle"}
    чужой.post(f"/dodois/connect/{токен}/start", headers=ЗАГОЛОВКИ)
    assert чужой.get(f"/dodois/connect/{токен}/status").get_json() == {"state": "pending"}


def test_только_что_законченный_вход_виден_как_готово_хотя_ссылка_погашена(
    чужой: FlaskClient, ссылки: Ссылки, вход: Вход
) -> None:
    токен = _ссылка_живая(ссылки)
    чужой.post(f"/dodois/connect/{токен}/start", headers=ЗАГОЛОВКИ)
    ссылки.изменить(1, used_at=datetime.now(UTC))
    flow._flows[1].state = flow.DONE
    assert чужой.get(f"/dodois/connect/{токен}/status").get_json() == {"state": "done"}
    assert "Готово, вход записан" in чужой.get(f"/dodois/connect/{токен}").get_data(as_text=True)
    # но начать заново по погашенной ссылке нельзя
    assert чужой.post(f"/dodois/connect/{токен}/start", headers=ЗАГОЛОВКИ).status_code == 404


def test_перебор_токенов_запирает_адрес_даже_для_верного_токена(
    чужой: FlaskClient, ссылки: Ссылки
) -> None:
    # Сломанная копия: не звать `note_address_failure` в `_resolve` — верный токен откроется.
    верный = _ссылка_живая(ссылки)
    for _n in range(25):
        чужой.get(f"/dodois/connect/{rules.new_token()}")
    ответ = чужой.get(f"/dodois/connect/{верный}")
    assert ответ.status_code == 404, "запертый адрес пустили"


def test_верный_токен_неудач_не_копит(чужой: FlaskClient, ссылки: Ссылки) -> None:
    верный = _ссылка_живая(ссылки)
    for _ in range(12):
        assert чужой.get(f"/dodois/connect/{верный}").status_code == 200


def test_в_демо_страница_и_кнопки_закрыты(monkeypatch: pytest.MonkeyPatch, ссылки: Ссылки) -> None:
    токен = _ссылка_живая(ссылки)
    подменить_двери(monkeypatch, tenant="HQ", role="superadmin")
    with собрать(tenant="HQ", demo=True).test_client() as клиент:
        for метод, суффикс in (("get", ""), ("post", "/start"), ("get", "/status")):
            ответ = getattr(клиент, метод)(f"/dodois/connect/{токен}{суффикс}", headers=ЗАГОЛОВКИ)
            assert ответ.status_code == 403, f"{метод} {суффикс} открыт в демо"


def test_адреса_страницы_открыты_заслону_входа() -> None:
    assert dodois_connect.ENDPOINTS <= auth.OPEN_ENDPOINTS


def test_без_ключа_шифрования_вход_не_начинается_до_похода_к_dodois(
    чужой: FlaskClient, ссылки: Ссылки, вход: Вход, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Сломанная копия: убрать `check_secrets_key` из маршрута — код устройства сожжён зря.
    from src.db.secret_crypto import SecretCryptoError

    def нет_ключа() -> None:
        raise SecretCryptoError("нет SECRETS_KEY")

    monkeypatch.setattr(store, "check_secrets_key", нет_ключа)
    токен = _ссылка_живая(ссылки)
    ответ = чужой.post(f"/dodois/connect/{токен}/start", headers=ЗАГОЛОВКИ)
    assert ответ.status_code == 503 and "ещё не настроен" in ответ.get_data(as_text=True)
    assert вход.начато == [], "до проверки ключа дошли до Dodo IS"


def test_страница_ссылки_не_трогает_общий_счёт_адреса(
    чужой: FlaskClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Сломанная копия: вернуть в `_resolve` общие `address_verdict`/`note_address_failure`.
    from src.db import web_throttle

    def нельзя(**_п: Any) -> Any:
        raise AssertionError("страница ссылки пошла в общий счёт адреса (пароль и API)")

    monkeypatch.setattr(web_throttle, "address_verdict", нельзя)
    monkeypatch.setattr(web_throttle, "note_address_failure", нельзя)
    assert чужой.get(f"/dodois/connect/{rules.new_token()}").status_code == 404


# --- плитка «Состояние подключений» ведёт во вкладку; оповещения (D641) ----------------------


def _вход_страны(country: str, state: str) -> rules.Login:
    сейчас = datetime.now(UTC)
    return rules.Login(
        country=country,
        contour="intl",
        source="invite",
        issued_by="boss",
        account_name=None,
        account_email=None,
        linked_at=сейчас,
        scope="shared",
        units_total=5,
        units_open=0,
        refreshed_at=сейчас,
        access_expires_at=None,
        checked_at=сейчас,
        state=state,
        reason=None,
    )


def test_плитка_страны_ведёт_во_вкладку_и_сбой_входа_красный(
    главный: FlaskClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(store, "list_logins", lambda: (_вход_страны("SI", rules.FAILED),))
    html = главный.get("/administration?tab=connections").get_data(as_text=True)
    assert re.search(r'href="[^"]*\?tab=dodois[^"]*country=SI[^"]*">Dodo IS — Словения', html)
    assert "shealth__dot--red" in html


def test_строка_оповещений_видна_во_вкладке_подключения(
    главный: FlaskClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from src.domain.health import ProbeRow

    строка = ProbeRow("grey", "health.reason.alerts_off", datetime.now(UTC))
    monkeypatch.setattr(health_store, "probes", lambda: {"alerts_channel": строка})
    html = главный.get("/administration?tab=connections").get_data(as_text=True)
    assert "Оповещения выключены" in html


def test_ответ_действия_это_вкладка_dodois_а_не_подключения(
    главный: FlaskClient,
) -> None:
    ответ = главный.post("/administration/dodois/SI/check", headers=ЗАГОЛОВКИ)
    html = ответ.get_data(as_text=True)
    assert 'id="dodois"' in html
    assert re.search(r'aria-current="page">\s*Dodo IS', html)
